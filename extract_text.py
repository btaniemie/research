import os
import re
import json
import pandas as pd
import pymupdf
import pymupdf.pro
import sys
from collections import defaultdict

PILOT_MODE = False      
DPI = 300
OCR_LANGUAGE = "spa"
INPUT_FOLDER = "pdfs"
OUTPUT_DIR = "extracted_files"
CACHE_DIR = "cache"
CSV_INDEX_PATH = "INDEX FEB 2026(Contents).csv"

VOL_STARTS = {
    "vol1": 379,
    "vol2": 463,
    "vol3": 927
}

os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"
os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"
pymupdf.pro.unlock()

for d in [OUTPUT_DIR, CACHE_DIR]:
    if not os.path.exists(d): os.makedirs(d)

def fix_page_range(raw_str):
    """Fixes 622-28 -> 622-628 and 375-1377 -> 1375-1377"""
    nums = re.findall(r'\d+', str(raw_str))
    if not nums: return []
    if len(nums) == 1: return [int(nums[0]), int(nums[0])]
    
    start, end = nums[0], nums[1]
    
    # 375-1377 (start is shorter than end)
    if len(start) < len(end) and end.startswith(start[1:]):
         # If it looks like a typo where the first digit was dropped
         pass # We will use them as is since 1377 is clearly the end
    
    # 622-28 (end is shorter than start)
    if len(end) < len(start):
        prefix = start[:len(start)-len(end)]
        end = prefix + end
        
    return [int(start), int(end)]

def get_split_page_text(page):
    rect = page.rect
    mid_x = rect.width / 2
    left_rect = pymupdf.Rect(0, 0, mid_x - 5, rect.height)
    right_rect = pymupdf.Rect(mid_x + 5, 0, rect.width, rect.height)
    mat = pymupdf.Matrix(DPI / 72, DPI / 72)
    full_text = []

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(sys.stderr.fileno())

    for r in [left_rect, right_rect]:
        if r.width < 20: continue 
        try:
            os.dup2(devnull, sys.stderr.fileno())
            pix = page.get_pixmap(matrix=mat, clip=r)
            ocr_pdf = pymupdf.open("pdf", pix.pdfocr_tobytes(language=OCR_LANGUAGE))
            full_text.append(ocr_pdf[0].get_text())
        except: continue
        finally: os.dup2(old_stderr, sys.stderr.fileno())
            
    os.close(devnull); os.close(old_stderr)
    return "\n".join(full_text)

def get_marker_map(doc, vol_name):
    cache_path = os.path.join(CACHE_DIR, f"{vol_name}_markers.json")
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f: return {int(k): v for k, v in json.load(f).items()}

    marker_map = {}
    pattern = re.compile(r'^\s*(\d+)\s*$', re.MULTILINE)
    for i in range(len(doc)):
        print(f"  Scanning {vol_name}: {i+1}/{len(doc)}...", end="\r")
        page_text = get_split_page_text(doc[i])
        for match in pattern.finditer(page_text):
            phys_num = int(match.group(1))
            if phys_num not in marker_map:
                marker_map[phys_num] = (i, match.start(), match.end())
    
    with open(cache_path, 'w') as f: json.dump(marker_map, f)
    return marker_map

def extract_content_v2(doc, marker_map, start_p, end_p, vol_name):
    """
    Handles ghost pages by looking backwards for the nearest valid marker 
    if the ideal N-1 marker is missing.
    """
    actual_end_marker = end_p
    is_first_page = (start_p == VOL_STARTS.get(vol_name))
    
    actual_start_marker = None
    if is_first_page:
        actual_start_marker = "START" 
    else:
        # Try to find the N-1 marker. If missing, look for N-2, N-3...
        for lookback in range(1, 10): # Look back up to 10 pages
            candidate = start_p - lookback
            if candidate in marker_map:
                actual_start_marker = candidate
                break
    
    if actual_start_marker is None:
        return None
    
    if actual_end_marker not in marker_map:
        return None

    pdf_start = 0 if is_first_page else marker_map[actual_start_marker][0]
    pdf_end = marker_map[actual_end_marker][0]
    
    pages_text = []
    for i in range(pdf_start, pdf_end + 1):
        pages_text.append(get_split_page_text(doc[i]))
    
    full_text = "\n".join(pages_text)
    
    try:
        if is_first_page:
            idx_start = 0
        else:
            marker_str = str(actual_start_marker)
            idx_start = full_text.find(marker_str) + len(marker_str)
            
        idx_end = full_text.find(str(actual_end_marker), idx_start)
        
        # If slicing fails, return the whole text found in those pages
        if idx_end == -1: return full_text.strip()
        
        return full_text[idx_start:idx_end].strip()
    except:
        return full_text.strip()

def main():
    df = pd.read_csv(CSV_INDEX_PATH, encoding='latin1')
    current_vol = None
    tasks = []
    missing_log = [] # Store missing entries here

    for _, row in df.iterrows():
        first_val = str(row.iloc[0]).strip().upper()
        if "VOL" in first_val:
            current_vol = "vol" + "".join(filter(str.isdigit, first_val))
            continue
        if not current_vol: continue
        
        p_range = fix_page_range(row.get('PAGES', ''))
        if p_range:
            tasks.append({
                'vol': current_vol, 'start': p_range[0], 'end': p_range[1],
                'content': str(row.get('CONTENT', 'Unknown')).strip(),
                'date': str(row.get('DATES', 'Unknown'))
            })

    vol_grouped = defaultdict(list)
    for t in tasks: vol_grouped[t['vol']].append(t)

    for vol_name, vol_tasks in vol_grouped.items():
        pdf_path = os.path.join(INPUT_FOLDER, f"{vol_name}.pdf")
        if not os.path.exists(pdf_path): continue

        doc = pymupdf.open(pdf_path)
        marker_map = get_marker_map(doc, vol_name)
        vol_dir = os.path.join(OUTPUT_DIR, vol_name)
        if not os.path.exists(vol_dir): os.makedirs(vol_dir)

        for task in vol_tasks:
            safe_name = re.sub(r'[\\/*?:"<>|]', "", task['content'])[:50]
            out_file = os.path.join(vol_dir, f"{task['start']}_{safe_name}.txt")
            
            if os.path.exists(out_file): continue 

            text = extract_content_v2(doc, marker_map, task['start'], task['end'], vol_name)
            
            if text:
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(f"DATE: {task['date']}\n" + "-"*20 + "\n" + text)
                print(f"✅ Saved {task['start']}-{task['end']}")
            else:
                # Log why it failed
                missing_log.append({
                    'Volume': vol_name,
                    'Start_Page': task['start'],
                    'End_Page': task['end'],
                    'Content': task['content']
                })
        doc.close()

    # Save the missing log to a CSV
    if missing_log:
        log_df = pd.DataFrame(missing_log)
        log_df.to_csv("missing_extractions_report.csv", index=False)
        print(f"\n⚠️ Extraction complete. {len(missing_log)} files could not be generated. Check missing_extractions_report.csv")
    else:
        print("\n✅ All files generated successfully!")

if __name__ == "__main__":
    main()

import os
import re
import json
import pandas as pd
import pymupdf
import pymupdf.pro
import sys
from collections import defaultdict

DPI = 300
OCR_LANGUAGE = "spa"
INPUT_FOLDER = "pdfs"
OUTPUT_DIR = "extracted_html" 
CACHE_DIR = "cache"
CSV_INDEX_PATH = "INDEX FEB 2026(Contents).csv"

VOL_STARTS = {"vol1": 379, "vol2": 463, "vol3": 927}

os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"
os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"
pymupdf.pro.unlock()

if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

def fix_page_range(raw_str):
    nums = re.findall(r'\d+', str(raw_str))
    if not nums: return []
    if len(nums) == 1: return [int(nums[0]), int(nums[0])]
    start, end = nums[0], nums[1]
    if len(end) < len(start):
        end = start[:len(start)-len(end)] + end
    return [int(start), int(end)]

def get_split_page_xhtml(page):
    """Captures XHTML to preserve italics <i> tags."""
    rect = page.rect
    mid_x = rect.width / 2
    left_rect = pymupdf.Rect(0, 0, mid_x - 5, rect.height)
    right_rect = pymupdf.Rect(mid_x + 5, 0, rect.width, rect.height)
    mat = pymupdf.Matrix(DPI / 72, DPI / 72)
    full_html = ""
    
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(sys.stderr.fileno())
    for r in [left_rect, right_rect]:
        try:
            os.dup2(devnull, sys.stderr.fileno())
            pix = page.get_pixmap(matrix=mat, clip=r)
            ocr_pdf_bytes = pix.pdfocr_tobytes(language=OCR_LANGUAGE)
            ocr_doc = pymupdf.open("pdf", ocr_pdf_bytes)
            full_html += ocr_doc[0].get_text("xhtml")
        except: continue
        finally: os.dup2(old_stderr, sys.stderr.fileno())
    os.close(devnull); os.close(old_stderr)
    return full_html

def main():
    df = pd.read_csv(CSV_INDEX_PATH, encoding='latin1')
    current_vol = None
    tasks = []

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
        cache_path = os.path.join(CACHE_DIR, f"{vol_name}_markers.json")
        if not os.path.exists(pdf_path) or not os.path.exists(cache_path): continue

        doc = pymupdf.open(pdf_path)
        with open(cache_path, 'r') as f:
            marker_map = {int(k): v for k, v in json.load(f).items()}
        
        vol_dir = os.path.join(OUTPUT_DIR, vol_name)
        if not os.path.exists(vol_dir): os.makedirs(vol_dir)

        print(f"--- Generating HTML Mirror for {vol_name} ---")

        for task in vol_tasks:
            safe_name = re.sub(r'[\\/*?:"<>|]', "", task['content'])[:50]
            out_file = os.path.join(vol_dir, f"{task['start']}_{safe_name}.html")

            if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                continue
            
            # Use the N-1 ghost logic implicitly by looking at marker_map
            # (We find the nearest valid marker for the start boundary)
            actual_start_marker = None
            if task['start'] == VOL_STARTS.get(vol_name):
                pdf_start = 0
            else:
                for lookback in range(1, 10):
                    cand = task['start'] - lookback
                    if cand in marker_map:
                        pdf_start = marker_map[cand][0]
                        break
                else: continue # Skip if no boundary found

            if task['end'] not in marker_map: continue
            pdf_end = marker_map[task['end']][0]

            html_body = ""
            for i in range(pdf_start, pdf_end + 1):
                html_body += get_split_page_xhtml(doc[i])

            with open(out_file, "w", encoding="utf-8") as f:
                f.write("<html><head><meta charset='utf-8'></head><body>")
                # Add headers at the top
                f.write(f"<div style='background:#eee; padding:10px;'>")
                f.write(f"<b>DATE:</b> {task['date']}<br>")
                f.write(f"<b>CONTENT:</b> {task['content']}<br>")
                f.write(f"<b>PAGES:</b> {task['start']}-{task['end']}</div><hr>")
                f.write(html_body)
                f.write("</body></html>")
            
            print(f"  Mirror Saved: {task['start']}_{safe_name}.html")

        doc.close()

if __name__ == "__main__":
    main()
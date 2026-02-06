import os
import re
import json
import pandas as pd

# --- CONFIG ---
OUTPUT_DIR = "extracted_files"
CACHE_DIR = "cache"
CSV_INDEX_PATH = "INDEX FEB 2026(Contents).csv"

def fix_page_range(raw_str):
    nums = re.findall(r'\d+', str(raw_str))
    if not nums: return []
    if len(nums) == 1: return [int(nums[0]), int(nums[0])]
    start, end = nums[0], nums[1]
    if len(end) < len(start):
        end = start[:len(start)-len(end)] + end
    return [int(start), int(end)]

def main():
    print("--- STARTING POST-PROCESSOR ---")
    df = pd.read_csv(CSV_INDEX_PATH, encoding='latin1')
    
    current_vol = None
    tasks = []
    
    # Load all markers from cache to check for misses
    all_markers = {}
    for v in ["vol1", "vol2", "vol3"]:
        cache_p = os.path.join(CACHE_DIR, f"{v}_markers.json")
        if os.path.exists(cache_p):
            with open(cache_p, 'r') as f:
                all_markers[v] = {int(k) for k in json.load(f).keys()}
        else:
            all_markers[v] = set()

    missing_report = []

    for _, row in df.iterrows():
        first_val = str(row.iloc[0]).strip().upper()
        if "VOL" in first_val:
            current_vol = "vol" + "".join(filter(str.isdigit, first_val))
            continue
        if not current_vol: continue
        
        p_range = fix_page_range(row.get('PAGES', ''))
        if p_range:
            start_p, end_p = p_range[0], p_range[1]
            date_val = str(row.get('DATES', 'Unknown')).strip()
            content_val = str(row.get('CONTENT', 'Unknown')).strip()
            
            # 1. Check for missing markers (N-1 logic)
            # Check for marker N-1 and N
            for m in [start_p - 1, end_p]:
                # We skip checking the start exception if it matches your known starts
                if m == 378 and current_vol == "vol1": continue # (379-1)
                if m == 462 and current_vol == "vol2": continue # (463-1)
                if m == 926 and current_vol == "vol3": continue # (927-1)
                
                if m not in all_markers.get(current_vol, set()):
                    missing_report.append(f"{current_vol} | Missing Marker: {m}")

            # 2. Find the file and inject the date
            safe_name = re.sub(r'[\\/*?:"<>|]', "", content_val)[:50]
            file_path = os.path.join(OUTPUT_DIR, current_vol, f"{start_p}_{safe_name}.txt")
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Only inject if we haven't already
                if not content.startswith("DATE:"):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(f"DATE: {date_val}\n" + "-"*20 + "\n" + content)
                    print(f"Updated: {start_p}_{safe_name}.txt")

    # Save missing report
    if missing_report:
        with open("MISSING_MARKERS_REPORT.txt", "w") as f:
            f.write("OCR MISSED THESE MARKERS. ADD THEM MANUALLY TO CACHE JSONS:\n\n")
            f.write("\n".join(sorted(list(set(missing_report)))))
        print(f"\n⚠️ Done! Check MISSING_MARKERS_REPORT.txt")
    else:
        print("\n✅ Done! Dates injected and all markers accounted for.")

if __name__ == "__main__":
    main()
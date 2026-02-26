import os
import re
import json
import math
import io
import base64
import sys
import numpy as np
import cv2
import pandas as pd
import pymupdf
import pymupdf.pro
import pytesseract
from PIL import Image
from bs4 import BeautifulSoup
from collections import defaultdict

DPI = 300
OCR_LANGUAGE = "spa"
INPUT_FOLDER = "pdfs"
OUTPUT_DIR = "extracted_html"
CACHE_DIR = "cache"
CSV_INDEX_PATH = "INDEX FEB 2026(Contents).csv"

VOL_STARTS = {"vol1": 379, "vol2": 463, "vol3": 927}

# --- ITALIC DETECTION TUNING ---
ITALIC_ANGLE_THRESHOLD = 3.0

# Shear sweep range and resolution
SHEAR_MIN   = -3.0
SHEAR_MAX   = 20.0
SHEAR_STEPS = 48

MIN_WORD_WIDTH = 20

os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"
os.environ["TESSDATA_PREFIX"] = "/opt/homebrew/share/tessdata"
pymupdf.pro.unlock()

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def projection_sharpness(binary_img, angle_deg):
    """Shear image horizontally and return variance of vertical projection profile."""
    h, w = binary_img.shape
    shear = math.tan(math.radians(angle_deg))
    M = np.float32([[1, shear, 0], [0, 1, 0]])
    new_w = int(w + abs(shear) * h)
    sheared = cv2.warpAffine(binary_img, M, (new_w, h),
                             flags=cv2.INTER_LINEAR, borderValue=0)
    proj = sheared.sum(axis=0).astype(float)
    return float(np.var(proj))


def best_shear_angle(word_img_gray):
    """Returns the shear angle that best aligns word strokes (italic = high angle)."""
    h, w = word_img_gray.shape
    if w < MIN_WORD_WIDTH or h < 4:
        return 0.0
    _, bw = cv2.threshold(word_img_gray, 0, 255,
                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if bw.sum() == 0:
        return 0.0
    angles = np.linspace(SHEAR_MIN, SHEAR_MAX, SHEAR_STEPS)
    scores = [projection_sharpness(bw, a) for a in angles]
    return float(angles[int(np.argmax(scores))])

def parse_hocr_bbox(title_str):
    m = re.search(r"bbox\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", title_str)
    return tuple(int(x) for x in m.groups()) if m else None


def ocr_column(pil_image):
    hocr = pytesseract.image_to_pdf_or_hocr(
        pil_image, lang=OCR_LANGUAGE, extension="hocr", config="--psm 6"
    )
    return hocr.decode("utf-8", errors="replace")

def get_italics_aware_html(page):
    """
    Splits page into two columns, OCRs each with Tesseract hOCR,
    measures italic slant via projection shear, returns HTML with <i> tags.
    """
    mat   = pymupdf.Matrix(DPI / 72, DPI / 72)
    rect  = page.rect
    mid_x = rect.width / 2

    columns = [
        (pymupdf.Rect(0,        0, mid_x - 5,   rect.height), "LEFT"),
        (pymupdf.Rect(mid_x + 5, 0, rect.width, rect.height), "RIGHT"),
    ]

    full_html = ""

    for clip_rect, label in columns:
        try:
            pix     = page.get_pixmap(matrix=mat, clip=clip_rect, colorspace=pymupdf.csGRAY)
            pil_img = Image.open(io.BytesIO(pix.tobytes("png")))
            np_img  = np.array(pil_img)

            hocr_str = ocr_column(pil_img)
            soup     = BeautifulSoup(hocr_str, "html.parser")

            col_html = ""
            for para in soup.find_all(class_="ocr_par"):
                col_html += "<p>"
                for line in para.find_all(class_="ocr_line"):
                    for word_el in line.find_all(class_="ocrx_word"):
                        text = word_el.get_text(strip=True)
                        if not text:
                            continue

                        bbox      = parse_hocr_bbox(word_el.get("title", ""))
                        is_italic = False

                        if bbox:
                            x0, y0, x1, y1 = bbox
                            x0c = max(0, x0); x1c = min(np_img.shape[1], x1)
                            y0c = max(0, y0); y1c = min(np_img.shape[0], y1)
                            crop = np_img[y0c:y1c, x0c:x1c]

                            if crop.size > 0 and (x1c - x0c) >= MIN_WORD_WIDTH:
                                angle     = best_shear_angle(crop)
                                is_italic = angle >= ITALIC_ANGLE_THRESHOLD

                        col_html += f"<i>{text}</i> " if is_italic else f"{text} "

                    col_html += " "  
                col_html += "</p>\n"

            full_html += f"\n<!-- ===== {label} COLUMN ===== -->\n" + col_html

        except Exception as e:
            full_html += f"<p><em>[Error processing {label} column: {e}]</em></p>\n"
            print(f"    [WARNING] {label} column error: {e}")

    return full_html

def fix_page_range(raw_str):
    nums = re.findall(r'\d+', str(raw_str))
    if not nums:
        return []
    if len(nums) == 1:
        return [int(nums[0]), int(nums[0])]
    start, end = nums[0], nums[1]
    if len(end) < len(start):
        end = start[:len(start) - len(end)] + end
    return [int(start), int(end)]

def main():
    df = pd.read_csv(CSV_INDEX_PATH, encoding='latin1')
    current_vol = None
    tasks = []

    for _, row in df.iterrows():
        first_val = str(row.iloc[0]).strip().upper()
        if "VOL" in first_val:
            current_vol = "vol" + "".join(filter(str.isdigit, first_val))
            continue
        if not current_vol:
            continue

        p_range = fix_page_range(row.get('PAGES', ''))
        if p_range:
            tasks.append({
                'vol':     current_vol,
                'start':   p_range[0],
                'end':     p_range[1],
                'content': str(row.get('CONTENT', 'Unknown')).strip(),
                'date':    str(row.get('DATES',   'Unknown')),
            })

    vol_grouped = defaultdict(list)
    for t in tasks:
        vol_grouped[t['vol']].append(t)

    for vol_name in sorted(vol_grouped.keys()):
        pdf_path   = os.path.join(INPUT_FOLDER, f"{vol_name}.pdf")
        cache_path = os.path.join(CACHE_DIR,    f"{vol_name}_markers.json")

        if not os.path.exists(pdf_path) or not os.path.exists(cache_path):
            print(f"Skipping {vol_name}: Missing PDF or cache file")
            continue

        doc = pymupdf.open(pdf_path)
        with open(cache_path, 'r') as f:
            marker_map = {int(k): v for k, v in json.load(f).items()}

        vol_dir = os.path.join(OUTPUT_DIR, vol_name)
        if not os.path.exists(vol_dir):
            os.makedirs(vol_dir)

        print(f"\n--- Processing {vol_name} ({len(vol_grouped[vol_name])} entries) ---")

        for task in vol_grouped[vol_name]:
            safe_name = re.sub(r'[\\/*?:"<>|]', "", task['content'])[:50]
            out_file  = os.path.join(vol_dir, f"{task['start']}_{safe_name}.html")

            # skip already completed files
            if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
                continue

            print(f"  Exporting: {task['start']}_{safe_name}.html")

            if task['start'] == VOL_STARTS.get(vol_name):
                pdf_start = 0
            else:
                for lookback in range(1, 15):
                    cand = task['start'] - lookback
                    if cand in marker_map:
                        pdf_start = marker_map[cand][0]
                        break
                else:
                    print(f"    [SKIP] No marker found before page {task['start']}")
                    continue

            if task['end'] not in marker_map:
                print(f"    [SKIP] End page {task['end']} not in marker map")
                continue

            pdf_end = marker_map[task['end']][0]

            html_content = ""
            for i in range(pdf_start, pdf_end + 1):
                html_content += get_italics_aware_html(doc[i])

            with open(out_file, "w", encoding="utf-8") as f:
                f.write("<html><head><meta charset='utf-8'><style>"
                        "body{font-family:serif; line-height:1.6; padding:40px;} "
                        "i{color:#d9534f;}"
                        "</style></head><body>")
                f.write("<div style='background:#f9f9f9; padding:20px; border:1px solid #ddd;'>")
                f.write("<h3>Metadata</h3>")
                f.write(f"<b>DATE:</b> {task['date']}<br>")
                f.write(f"<b>CONTENT:</b> {task['content']}<br>")
                f.write(f"<b>PAGES:</b> {task['start']}-{task['end']}</div><hr>")
                f.write(html_content)
                f.write("</body></html>")

        doc.close()

    print("\n All volumes processed")


if __name__ == "__main__":
    main()
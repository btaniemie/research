import pandas as pd
import re
import os
from bs4 import BeautifulSoup

INPUT_CSV    = "INDEX FEB 2026(Contents).csv"
OUTPUT_CSV   = "EliseFeed_converted.tsv"
HTML_ROOT    = "extracted_html"  

df = pd.read_csv(INPUT_CSV, encoding="cp1252", header=0)

df.columns = [
    "year", "ms_pg", "content", "dates", "pages",
    "kind_of_document", "tag", "topic", "_col8",
    "indios",
    *[f"_extra_{i}" for i in range(len(df.columns) - 10)]
]

CATEGORY_MAP = {
    "court preceeding":   "court proceeding",
    "court proceding":    "court proceeding",
    "expert testimony":   "doctor testimony",  
}

ALLOWED_CATEGORIES = {
    "court proceeding", "misc", "oral testimony",
    "written testimony", "doctor testimony", "witness testimony",
}

def resolve_category(content_val, kind_val):
    for raw in [content_val, kind_val]:
        v = str(raw).strip().lower().strip()
        if v in ALLOWED_CATEGORIES:
            return v
        if v in CATEGORY_MAP:
            return CATEGORY_MAP[v]
    return str(content_val).strip()

def clean_ms_pg(val):
    val = str(val).strip()
    if not val or val.lower() == "nan":
        return "", ""
    val = re.sub(r"^[Xx]\s*", "", val).strip().rstrip("-").strip()
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", val)
    if m:
        return int(m.group(1)), int(m.group(2))
    try:
        return int(val), int(val)
    except ValueError:
        return val, val

def split_pages(val):
    val = str(val).strip()
    if not val or val.lower() == "nan":
        return "", ""
    val = re.sub(r"^[IVX]+:", "", val).strip()  # strip volume prefix e.g. "II:"
    val = re.sub(r"\[.*?\]", "", val).strip()
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", val)
    if m:
        return int(m.group(1)), int(m.group(2))
    try:
        return int(val), int(val)
    except ValueError:
        return val, val

def split_dates(val):
    val = str(val).strip().strip("[]")
    if not val or val.lower() == "nan":
        return "", ""
    m = re.match(
        r"(\d{1,2}\s+\w+\.?\s+\d{4})\s*[-–]\s*(\d{1,2}\s+\w+\.?\s+\d{4})", val
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(\w+\.?\s+\d{4})", val)
    if m:
        return f"{m.group(1)} {m.group(3)}", f"{m.group(2)} {m.group(3)}"
    return val, val

def resolve_indios(val):
    v = str(val).strip()
    return "TRUE" if v and v.lower() != "nan" else "FALSE"

def get_html_content(volume_num, page_start, category):
    """
    Look up extracted_html/vol{N}/{page_start}_{category}.html
    Returns (html_body, raw_text) or ("", "") if not found.
    """
    if not page_start:
        return "", ""
    folder = os.path.join(HTML_ROOT, f"vol{volume_num}")

    # try the name first, then known typos
    filename_candidates = [f"{page_start}_{category}.html"]
    if category == "court proceeding":
        filename_candidates += [
            f"{page_start}_court preceeding.html",
            f"{page_start}_court proceding.html",
        ]
    elif category == "doctor testimony":
        filename_candidates.append(f"{page_start}_expert testimony.html")

    filepath = None
    for candidate in filename_candidates:
        candidate_path = os.path.join(folder, candidate)
        if os.path.exists(candidate_path):
            filepath = candidate_path
            break

    if not filepath:
        print(f"  [MISSING] {os.path.join(folder, filename_candidates[0])}")
        return "", ""
    with open(filepath, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, "html.parser")

    # remove metadata div
    meta_div = soup.find("div", style=lambda s: s and "background:#f9f9f9" in s)
    if meta_div:
        next_sib = meta_div.find_next_sibling()
        if next_sib and next_sib.name == "hr":
            next_sib.decompose()
        meta_div.decompose()

    # extract inner body content, strip outer html/head/body tags
    body_tag = soup.find("body")
    inner_html = body_tag.decode_contents().strip() if body_tag else str(soup)

    # strip HTML comments including leftover ===== COLUMN ===== text
    inner_html_no_comments = re.sub(r"<!--.*?-->", "", inner_html, flags=re.DOTALL)
    raw_text = BeautifulSoup(inner_html_no_comments, "html.parser").get_text(separator=" ", strip=True)
    raw_text = re.sub(r"=====.*?=====", "", raw_text).strip()
    raw_text = re.sub(r"\s+", " ", raw_text).strip()

    return inner_html, raw_text

# ── Process rows ──────────────────────────────────────────────────────────────
rows = []
uid = 1000
current_volume = 1
current_year = ""

for _, row in df.iterrows():
    year_val    = str(row["year"]).strip()
    ms_val      = str(row["ms_pg"]).strip()
    content_val = str(row["content"]).strip()

    for check in [year_val, ms_val]:
        vm = re.match(r"VOL\s*(\d)", check, re.IGNORECASE)
        if vm:
            current_volume = int(vm.group(1))
            break
    else:
        y = re.sub(r"[\[\]]", "", year_val).strip()
        if re.match(r"\d{4}", y):
            current_year = y

    # skip volume header rows and fully blank rows
    if re.match(r"VOL\s*\d", year_val, re.IGNORECASE) or \
       re.match(r"VOL\s*\d", ms_val, re.IGNORECASE):
        continue
    if (not content_val or content_val.lower() == "nan") and \
       (not ms_val or ms_val.lower() in ("nan", "x", "")):
        continue

    ms_start, ms_end   = clean_ms_pg(row["ms_pg"])
    pg_start, pg_end   = split_pages(row["pages"])
    date_start, date_end = split_dates(row["dates"])
    category           = resolve_category(row["content"], row["kind_of_document"])
    indios             = resolve_indios(row["indios"])

    # title from kind_of_document
    title = str(row["kind_of_document"]).strip()
    if not title or title.lower() == "nan":
        title = category
    title = f"{title}"

    # HTML body and raw text
    body_html, body_raw = get_html_content(current_volume, pg_start, category)

    rows.append({
        "UniqueID":                       uid,
        "Title":                          title,
        "Volume":                         f"volume_{current_volume}",
        "Manuscript page number start":   ms_start,
        "Manuscript page number end":     ms_end,
        "Date  start":                    date_start,
        "Date end":                       date_end,
        "Page start":                     pg_start,
        "Page end":                       pg_end,
        "Content category":               category,
        "Indios":                         indios,
        "Body":                           body_html,
        "Body raw text":                  body_raw,
        "PDF attachment":                 "",
    })
    uid += 1

out = pd.DataFrame(rows)
out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8", sep="\t")
print(f"Done! {len(out)} rows written to {OUTPUT_CSV}")
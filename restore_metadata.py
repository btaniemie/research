"""
Restores missing metadata divs to HTML files that had them stripped by fix_page_offset.py.

The metadata is reconstructed from the INDEX CSV using:
  - Volume: from the subfolder name (vol1, vol2, vol3)
  - Start page: from the filename prefix (e.g. 937_oral testimony.html -> 937)
  - DATE, CONTENT, PAGES: looked up from the INDEX CSV

Usage:
    python restore_metadata.py              # apply to extracted_html/
    python restore_metadata.py --dry-run    # preview only
    python restore_metadata.py --dir path/to/extracted_html
"""

import os
import re
import argparse
import pandas as pd
from pathlib import Path


CSV_PATH = "INDEX FEB 2026(Contents).csv"
HTML_ROOT = "extracted_html"

METADATA_DIV = (
    "<div style='background:#f9f9f9; padding:20px; border:1px solid #ddd;'>"
    "<h3>Metadata</h3>"
    "<b>DATE:</b> {date}<br>"
    "<b>CONTENT:</b> {content}<br>"
    "<b>PAGES:</b> {pages}</div><hr>"
)


def build_lookup(csv_path: str) -> dict:
    """
    Build a dict: (volume_num, start_page) -> {date, content, pages}
    from the INDEX CSV.
    """
    df = pd.read_csv(csv_path, encoding="cp1252", header=0)
    df.columns = [
        "year", "ms_pg", "content", "dates", "pages",
        "kind_of_document", "tag", "topic", "_col8",
        "indios",
        *[f"_extra_{i}" for i in range(len(df.columns) - 10)]
    ]

    lookup = {}
    current_vol = None

    for _, row in df.iterrows():
        year_val = str(row["year"]).strip()
        ms_val   = str(row["ms_pg"]).strip()

        for check in [year_val, ms_val]:
            vm = re.match(r"VOL\s*(\d)", check, re.IGNORECASE)
            if vm:
                current_vol = int(vm.group(1))
                break

        if not current_vol:
            continue
        if re.match(r"VOL\s*\d", year_val, re.IGNORECASE) or \
           re.match(r"VOL\s*\d", ms_val, re.IGNORECASE):
            continue

        pages_raw = str(row["pages"]).strip()
        pages_clean = re.sub(r"^[IVX]+:", "", pages_raw).strip()
        nums = re.findall(r'\d+', pages_clean)
        if not nums:
            continue
        start_page = int(nums[0])
        end_page   = int(nums[1]) if len(nums) > 1 else start_page
        pages_str  = f"{start_page}-{end_page}" if start_page != end_page else str(start_page)

        key = (current_vol, start_page)
        lookup[key] = {
            "date":    str(row["dates"]).strip().strip("[]"),
            "content": str(row["content"]).strip(),
            "pages":   pages_str,
        }

    return lookup


def has_metadata(html: str) -> bool:
    return "background:#f9f9f9" in html


def process_file(path: Path, vol_num: int, lookup: dict, dry_run: bool) -> bool:
    html = path.read_text(encoding="utf-8", errors="replace")

    if has_metadata(html):
        return False  # already has metadata, skip

    m = re.match(r'^(\d+)_', path.name)
    if not m:
        return False
    start_page = int(m.group(1))

    key = (vol_num, start_page)
    if key not in lookup:
        print(f"  [MISSING IN CSV] {path.name} (vol {vol_num}, page {start_page})")
        return False

    info = lookup[key]
    meta_block = METADATA_DIV.format(
        date=info["date"],
        content=info["content"],
        pages=info["pages"],
    )

    # Insert after <body> tag
    new_html = re.sub(
        r'(<body>)',
        r'\1' + meta_block,
        html,
        count=1,
        flags=re.IGNORECASE,
    )

    if new_html == html:
        # No <body> tag found — prepend directly
        new_html = meta_block + html

    if not dry_run:
        path.write_text(new_html, encoding="utf-8")

    return True


def process_folder(root_dir: str, dry_run: bool):
    root = Path(root_dir)
    lookup = build_lookup(CSV_PATH)
    print(f"Loaded {len(lookup)} entries from CSV.\n")

    fixed = 0
    skipped = 0

    for vol_dir in sorted(root.iterdir()):
        if not vol_dir.is_dir():
            continue
        m = re.match(r'vol(\d+)', vol_dir.name, re.IGNORECASE)
        if not m:
            continue
        vol_num = int(m.group(1))

        for path in sorted(vol_dir.glob("*.html")):
            changed = process_file(path, vol_num, lookup, dry_run)
            if changed:
                fixed += 1
                prefix = "[DRY RUN] " if dry_run else ""
                print(f"  {prefix}Restored: {path.relative_to(root)}")
            else:
                skipped += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  {fixed} file(s) {'would be' if dry_run else ''} restored")
    print(f"  {skipped} file(s) already had metadata (skipped)")
    if dry_run:
        print("\nRun without --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Restore missing metadata divs to extracted HTML files."
    )
    parser.add_argument("--dir",     default=HTML_ROOT,
                        help=f"Root folder to scan (default: {HTML_ROOT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files")
    args = parser.parse_args()

    print(f"Scanning: {args.dir}{'  [DRY RUN]' if args.dry_run else ''}\n")
    process_folder(args.dir, args.dry_run)


if __name__ == "__main__":
    main()

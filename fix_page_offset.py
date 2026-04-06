"""
Post-processing script to strip extra leading content from extracted HTML files.

The generate_html.py bug caused each file to start one physical PDF page too early,
meaning the HTML contains content from the page BEFORE the intended start page.

Page number markers appear in the HTML as standalone <p>N</p> tags.
This script finds the last such marker before the file's intended start page
and removes everything up to and including it.

Example:
  File: 937_oral testimony.html  (intended start = 937)
  HTML contains: [content from 936] <p>936</p> [content from 937 onwards]
  Fix: remove everything up to and including <p>936</p>

Usage:
    python fix_page_offset.py              # process extracted_html/, apply changes
    python fix_page_offset.py --dry-run    # preview only, no writes
    python fix_page_offset.py --dir path/to/extracted_html
"""

import os
import re
import argparse
from pathlib import Path


def find_cutpoint(html: str, start_page: int) -> int | None:
    """
    Find the character index of the END of the last <p>N</p> marker
    where N < start_page. Returns None if no such marker found (file is clean).
    """
    # Match standalone page number markers: <p>NNN</p> (with optional whitespace)
    pattern = re.compile(r'<p>\s*(\d+)\s*</p>', re.IGNORECASE)

    last_end = None
    for m in pattern.finditer(html):
        n = int(m.group(1))
        if n < start_page:
            last_end = m.end()

    return last_end


def process_file(path: Path, dry_run: bool) -> bool:
    """
    Process one HTML file. Returns True if a fix was applied (or would be).
    """
    # Parse start page from filename: "937_oral testimony.html" -> 937
    m = re.match(r'^(\d+)_', path.name)
    if not m:
        return False
    start_page = int(m.group(1))

    html = path.read_text(encoding="utf-8", errors="replace")

    # Find the end of the metadata block (the <hr> after the metadata div)
    # so we preserve it and only strip extra content after it
    hr_match = re.search(r'<hr\s*/?>', html, re.IGNORECASE)
    if hr_match:
        header = html[:hr_match.end()]
        body   = html[hr_match.end():]
    else:
        header = ""
        body   = html

    cutpoint = find_cutpoint(body, start_page)
    if cutpoint is None:
        return False  # nothing to strip

    stripped = header + body[cutpoint:].lstrip()

    if not dry_run:
        path.write_text(stripped, encoding="utf-8")

    return True


def process_folder(root_dir: str, dry_run: bool):
    root = Path(root_dir)
    html_files = sorted(root.rglob("*.html"))

    if not html_files:
        print(f"No HTML files found under '{root_dir}'")
        return

    fixed = 0
    skipped = 0

    for path in html_files:
        changed = process_file(path, dry_run)
        if changed:
            fixed += 1
            prefix = "[DRY RUN] " if dry_run else ""
            print(f"  {prefix}Fixed: {path.relative_to(root)}")
        else:
            skipped += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  {fixed} file(s) {'would be' if dry_run else ''} fixed")
    print(f"  {skipped} file(s) already clean (no leading content to strip)")
    if dry_run:
        print("\nRun without --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Strip extra leading page content from extracted HTML files."
    )
    parser.add_argument("--dir",     default="extracted_html",
                        help="Root folder to scan (default: extracted_html)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files")
    args = parser.parse_args()

    print(f"Scanning: {args.dir}{'  [DRY RUN]' if args.dry_run else ''}\n")
    process_folder(args.dir, args.dry_run)


if __name__ == "__main__":
    main()

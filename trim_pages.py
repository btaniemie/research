"""
Trims HTML files in extracted_html/ so that:
  - Content before the start page is removed (everything up to and including
    the last paragraph ending with a number < start_page)
  - Content after the end page is removed (everything after the last paragraph
    ending with end_page)

Page numbers appear at the end of <p> tags, e.g.:
  <p>1383  </p>
  <p>...según  1370  </p>

Start/end pages are read from the metadata div: <b>PAGES:</b> 1371-1371

Usage:
    python trim_pages.py              # apply to extracted_html/
    python trim_pages.py --dry-run    # preview only, no writes
    python trim_pages.py --dir path/to/extracted_html
"""

import re
import argparse
from pathlib import Path


HTML_ROOT = "extracted_html"

# Matches a number at the end of a <p> tag (with optional surrounding whitespace)
END_OF_PARA_NUM = re.compile(r'(\d+)\s*</p>', re.IGNORECASE)


def get_pages_from_metadata(html: str):
    """Parse start and end page from the PAGES field in the metadata div."""
    m = re.search(r'<b>PAGES:</b>\s*(\d+)(?:\s*-\s*(\d+))?', html)
    if not m:
        return None, None
    start = int(m.group(1))
    end   = int(m.group(2)) if m.group(2) else start
    return start, end


def split_header_body_footer(html: str):
    """
    Split HTML into three parts:
      header : everything up to and including <hr>
      body   : content between <hr> and </body>
      footer : </body></html>
    """
    hr = re.search(r'<hr\s*/?>', html, re.IGNORECASE)
    header = html[:hr.end()] if hr else ""
    rest   = html[hr.end():] if hr else html

    footer_m = re.search(r'\s*</body>\s*</html>\s*$', rest, re.IGNORECASE)
    if footer_m:
        body   = rest[:footer_m.start()]
        footer = rest[footer_m.start():]
    else:
        body   = rest
        footer = ""

    return header, body, footer


def trim_body(body: str, start: int, end: int):
    """
    - Strip everything up to and including the last <p>...</p> that ends
      with a number < start.
    - Strip everything after the last <p>...</p> that ends with end.
    Returns (trimmed_body, start_was_trimmed, end_was_trimmed).
    """
    # ── trim leading extra content ────────────────────────────────────────────
    last_pre_start = None
    for m in END_OF_PARA_NUM.finditer(body):
        n = int(m.group(1))
        if n < start:
            last_pre_start = m.end()  # end of the closing </p>

    start_trimmed = last_pre_start is not None
    if start_trimmed:
        body = body[last_pre_start:].lstrip('\n')

    # ── trim trailing extra content ───────────────────────────────────────────
    last_end_marker = None
    for m in END_OF_PARA_NUM.finditer(body):
        n = int(m.group(1))
        if n == end:
            last_end_marker = m.end()

    end_trimmed = False
    if last_end_marker is not None and last_end_marker < len(body.rstrip()):
        body = body[:last_end_marker]
        end_trimmed = True

    return body, start_trimmed, end_trimmed


def process_file(path: Path, dry_run: bool, preview: bool = False) -> tuple[bool, bool]:
    """
    Process one file. Returns (start_trimmed, end_trimmed).
    """
    html = path.read_text(encoding="utf-8", errors="replace")

    start, end = get_pages_from_metadata(html)
    if start is None:
        print(f"  [SKIP - no metadata] {path.name}")
        return False, False

    header, body, footer = split_header_body_footer(html)
    new_body, start_trimmed, end_trimmed = trim_body(body, start, end)

    if not start_trimmed and not end_trimmed:
        return False, False

    if preview:
        SNIP = 300
        print(f"\n  {'='*60}")
        print(f"  FILE:  {path.name}  (pages {start}–{end})")
        if start_trimmed:
            cut = body[:len(body) - len(new_body) + (len(new_body) - len(new_body))]
            # recompute what was cut from the start
            cut_len = len(body) - len(new_body) if not end_trimmed else None
            # simpler: re-derive cut region
            last_pre = None
            for m in END_OF_PARA_NUM.finditer(body):
                if int(m.group(1)) < start:
                    last_pre = m.end()
            if last_pre:
                removed = body[:last_pre].strip()
                print(f"\n  ── REMOVED FROM START ──")
                print(f"  {repr(removed[:SNIP])}{'...' if len(removed) > SNIP else ''}")
        if end_trimmed:
            last_end = None
            for m in END_OF_PARA_NUM.finditer(new_body):
                if int(m.group(1)) == end:
                    last_end = m.end()
            if last_end:
                removed = new_body[last_end:].strip()
                print(f"\n  ── REMOVED FROM END ──")
                print(f"  {repr(removed[:SNIP])}{'...' if len(removed) > SNIP else ''}")
        print(f"\n  ── RESULT STARTS WITH ──")
        print(f"  {new_body.strip()[:SNIP]}{'...' if len(new_body.strip()) > SNIP else ''}")
        print(f"\n  ── RESULT ENDS WITH ──")
        print(f"  ...{new_body.strip()[-SNIP:]}")

    if not dry_run:
        path.write_text(header + new_body + footer, encoding="utf-8")

    return start_trimmed, end_trimmed


def process_folder(root_dir: str, dry_run: bool, preview: bool = False):
    root       = Path(root_dir)
    html_files = sorted(root.rglob("*.html"))

    if not html_files:
        print(f"No HTML files found under '{root_dir}'")
        return

    start_fixed = end_fixed = both_fixed = clean = 0

    for path in html_files:
        st, et = process_file(path, dry_run, preview=preview)

        if st or et:
            tag = []
            if st: tag.append("start trimmed")
            if et: tag.append("end trimmed")
            prefix = "[DRY RUN] " if dry_run else ""
            print(f"  {prefix}{path.relative_to(root)}  ({', '.join(tag)})")

        if st and et: both_fixed += 1
        elif st:      start_fixed += 1
        elif et:      end_fixed   += 1
        else:         clean       += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  {both_fixed} file(s) trimmed on both ends")
    print(f"  {start_fixed} file(s) trimmed at start only")
    print(f"  {end_fixed} file(s) trimmed at end only")
    print(f"  {clean} file(s) already clean")
    if dry_run:
        print("\nRun without --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Trim extra leading/trailing page content from extracted HTML files."
    )
    parser.add_argument("--dir",     default=HTML_ROOT,
                        help=f"Root folder to scan (default: {HTML_ROOT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files")
    parser.add_argument("--preview", action="store_true",
                        help="Show what gets cut and what the result looks like (implies --dry-run)")
    args = parser.parse_args()

    if args.preview:
        args.dry_run = True

    print(f"Scanning: {args.dir}{'  [DRY RUN]' if args.dry_run else ''}\n")
    process_folder(args.dir, args.dry_run, preview=args.preview)


if __name__ == "__main__":
    main()

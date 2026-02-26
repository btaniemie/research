"""
Two-pass cleanup for extracted HTML files:

  PASS 1 — Merge adjacent <i> tags into a single span.
            "<i>Tus</i> <i>saetas</i> <i>son</i>" → "<i>Tus saetas son</i>"
            Tags are merged as long as they are separated only by whitespace.

  PASS 2 — Strip <i> tags that still wrap only a single word/number
            after merging (these are false-positive italic detections).
            "<i>Y</i>"  → "Y"

Genuine multi-word Bible quotes survive both passes untouched.

Usage:
    python clean_html.py              # process extracted_html/
    python clean_html.py --dry-run    # preview only, no writes
    python clean_html.py --dir path/to/extracted_html
"""

import os
import re
import argparse
from pathlib import Path


# ── Pass 1: merge adjacent <i> tags ──────────────────────────────────────────
# Matches: </i> followed by optional whitespace followed by <i>
# We replace that boundary with a single space, collapsing the two tags.
# Run repeatedly until no more merges are possible.

ADJACENT_ITALIC = re.compile(r'</i>(\s*)<i>', re.IGNORECASE)


def merge_adjacent_italics(html: str) -> tuple[str, int]:
    """Repeatedly merge </i><i> boundaries until stable. Returns (html, merge_count)."""
    total = 0
    while True:
        new_html, n = ADJACENT_ITALIC.subn(lambda m: ' ' if m.group(1) else '', html)
        total += n
        if n == 0:
            break
        html = new_html
    return html, total


# ── Pass 2: strip single-word <i> tags ───────────────────────────────────────
# After merging, any <i> tag whose content is still a single whitespace-delimited
# token is a false positive (stray italic detection on one word).

SINGLE_WORD_ITALIC = re.compile(r'<i>\s*(\S+)\s*</i>', re.IGNORECASE)


def strip_single_word_italics(html: str) -> tuple[str, int]:
    """Remove <i> tags wrapping a single token. Returns (html, strip_count)."""
    count = 0

    def replacer(m):
        nonlocal count
        count += 1
        return m.group(1)

    return SINGLE_WORD_ITALIC.sub(replacer, html), count


# ── File processor ────────────────────────────────────────────────────────────

def process_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Process one HTML file. Returns (merges, strips)."""
    original = path.read_text(encoding="utf-8", errors="replace")

    after_merge, merges = merge_adjacent_italics(original)
    after_strip, strips = strip_single_word_italics(after_merge)

    if merges == 0 and strips == 0:
        return 0, 0

    if not dry_run:
        path.write_text(after_strip, encoding="utf-8")

    return merges, strips


def process_folder(root_dir: str, dry_run: bool):
    root       = Path(root_dir)
    html_files = sorted(root.rglob("*.html"))

    if not html_files:
        print(f"No HTML files found under '{root_dir}'")
        return

    total_files  = 0
    total_merges = 0
    total_strips = 0

    for path in html_files:
        merges, strips = process_file(path, dry_run)
        if merges == 0 and strips == 0:
            continue

        total_files  += 1
        total_merges += merges
        total_strips += strips

        rel    = path.relative_to(root)
        prefix = "[DRY RUN] " if dry_run else ""
        print(f"  {prefix}{rel}")
        print(f"    merged {merges} adjacent tag pair(s), stripped {strips} single-word tag(s)")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  {total_files} file(s) changed")
    print(f"  {total_merges} adjacent <i> boundaries merged")
    print(f"  {total_strips} single-word <i> tags stripped")
    if dry_run:
        print("\nRun without --dry-run to apply changes.")


# ── Quick sanity test ─────────────────────────────────────────────────────────

def _run_tests():
    cases = [
        # (input, expected_output, description)
        (
            "<i>Tus</i> <i>saetas</i> <i>son</i> <i>agudas</i>",
            "<i>Tus saetas son agudas</i>",
            "merge four adjacent tags"
        ),
        (
            "<i>Y</i> primeramente",
            "Y primeramente",
            "strip standalone single-word tag"
        ),
        (
            "<i>Dixit</i> <i>Dominus</i>",
            "<i>Dixit Dominus</i>",
            "merge two tags into a known Bible quote"
        ),
        (
            "texto <i>Y</i> texto",
            "texto Y texto",
            "strip mid-sentence single letter"
        ),
        (
            "<i>sobre</i> <i>aquella</i> <i>piedra</i>",
            "<i>sobre aquella piedra</i>",
            "merge three tags"
        ),
        (
            "<i>Gratia et pax Christi</i>",
            "<i>Gratia et pax Christi</i>",
            "leave intact multi-word tag unchanged"
        ),
        (
            "<i>Et</i> <i>vidi</i> <i>in</i> <i>dextera</i>",
            "<i>Et vidi in dextera</i>",
            "merge Latin citation tags"
        ),
    ]

    print("── Running sanity tests ──────────────────────────────────")
    passed = failed = 0
    for html_in, expected, desc in cases:
        merged, _ = merge_adjacent_italics(html_in)
        result, _ = strip_single_word_italics(merged)
        ok = result == expected
        status = "✅" if ok else "❌"
        print(f"  {status} {desc}")
        if not ok:
            print(f"     input:    {html_in}")
            print(f"     expected: {expected}")
            print(f"     got:      {result}")
            failed += 1
        else:
            passed += 1
    print(f"\n  {passed} passed, {failed} failed")
    print("─────────────────────────────────────────────────────────\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Merge adjacent <i> tags then strip single-word italic tags from extracted HTML."
    )
    parser.add_argument("--dir",     default="extracted_html",
                        help="Root folder to scan (default: extracted_html)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files")
    parser.add_argument("--test",    action="store_true",
                        help="Run sanity tests and exit")
    args = parser.parse_args()

    if args.test:
        _run_tests()
        return

    print(f"Scanning: {args.dir}{'  [DRY RUN]' if args.dry_run else ''}\n")
    process_folder(args.dir, args.dry_run)


if __name__ == "__main__":
    main()
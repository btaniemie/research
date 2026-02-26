"""
classify_italics.py
───────────────────
Extracts <i> passages WITH surrounding context from HTML files, sends
them to OpenAI, and outputs a CSV of identified Bible references.

Setup:
    pip install openai beautifulsoup4 python-dotenv
    Add OPENAI_API_KEY=sk-... to your .env file

Usage:
    python classify_italics.py
    python classify_italics.py --sample 5 --out findings.csv
"""

import csv
import json
import random
import argparse
import time
from pathlib import Path
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

MODEL       = "gpt-4o"
SAMPLE_SIZE = 20
INPUT_DIR   = "/Users/minhle/Desktop/Dana RA /research/extracted_html"
OUTPUT_CSV  = "bible_references.csv"
BATCH_SIZE  = 10
MIN_LENGTH  = 6

# ── PROMPT ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert in 16th-century Spanish religious texts, the Latin Vulgate Bible,
and Biblical scripture. You will be given entries from Spanish Inquisition trial records (~1570-1580).

Each entry has:
  - CONTEXT: the full paragraph the italic text appears in
  - ITALIC: the specific italicized passage

Italic text in these documents marks direct quotations. Identify which ones quote the Bible.

Strong signals that an italic passage IS a Bible quotation:
  - Latin phrases matching the Vulgate (e.g. "cesare faciam", "De vinea sodomorum", "excepto verbo Uriae")
  - Spanish text that paraphrases known scripture (Psalms, Deuteronomy, Gospels, Epistles, Apocalypse)
  - The context says "dice el salmo", "dice la Escritura", "dice Moisés", "dice el Apocalipsis", etc.
  - The passage is introduced with "que" after a verb of saying/writing

NOT a Bible reference:
  - OCR noise or garbled text (dashes, brackets, random characters)
  - Institutional phrases like "Iglesia de Babilonia", "pueblo de Israel" used as labels
  - Someone speaking or testifying in their own words
  - Administrative text (secretary names, dates, procedural notes)

Respond with a JSON object with a single key "results" containing an array.
Each item in the array must have:
  "id"         : integer id from the input
  "confidence" : "high", "medium", or "low"
  "reference"  : book + verse if identifiable (e.g. "Deuteronomy 32:26"), otherwise null
  "italic"     : the exact italic text
  "note"       : one sentence explaining why this is a Bible quotation

If nothing in the batch is a Bible reference, return {"results": []}.

Example response:
{"results": [
  {"id": 5, "confidence": "high", "reference": "Deuteronomy 32:26", "italic": "cesare faciam,", "note": "Latin Vulgate Deuteronomy 32:26 — God threatens to erase Israel from memory."},
  {"id": 7, "confidence": "high", "reference": "Deuteronomy 32:32", "italic": "De vinea sodomorum,", "note": "Vulgate Dt 32:32 describing the vine of Sodom."}
]}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_passages_with_context(html: str) -> list[dict]:
    """For each <i> tag, return the italic text and its containing paragraph."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for tag in soup.find_all("i"):
        italic_text = tag.get_text(" ", strip=True)
        if len(italic_text) < MIN_LENGTH or italic_text in seen:
            continue
        seen.add(italic_text)
        parent  = tag.find_parent("p")
        context = parent.get_text(" ", strip=True) if parent else italic_text
        out.append({"italic": italic_text, "context": context})
    return out


def classify_batch(client: OpenAI, entries: list[dict], id_offset: int, debug_first: bool = False) -> list[dict]:
    """Send one batch with context to OpenAI."""
    formatted = ""
    for i, entry in enumerate(entries):
        num = id_offset + i + 1
        formatted += (
            f'--- Entry {num} ---\n'
            f'CONTEXT: {entry["context"]}\n'
            f'ITALIC:  {entry["italic"]}\n\n'
        )

    if debug_first:
        print("\n====== FIRST BATCH SENT TO API ======")
        print(formatted)
        print("=====================================\n")

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},  # requires dict response — prompt asks for {"results": [...]}
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": (
                f"Review these {len(entries)} italic passages and identify any Bible references:\n\n"
                f"{formatted}"
            )}
        ]
    )

    raw = json.loads(response.choices[0].message.content)

    # Extract the results array from the {"results": [...]} wrapper
    if isinstance(raw, dict):
        if "results" in raw:
            return raw["results"]
        # fallback: find first list value
        for v in raw.values():
            if isinstance(v, list):
                return v
        return []
    if isinstance(raw, list):
        return raw
    return []


def classify_all(client: OpenAI, entries: list[dict], debug: bool = False) -> list[dict]:
    """Classify all entries in batches, return combined results."""
    results = []
    for i in range(0, len(entries), BATCH_SIZE):
        batch         = entries[i:i + BATCH_SIZE]
        is_first      = (i == 0)
        print(f"      -> entries {i+1}-{i+len(batch)} of {len(entries)}")
        batch_results = classify_batch(client, batch, id_offset=i, debug_first=(debug and is_first))
        print(f"      -> {len(batch_results)} Bible hit(s) in this batch")
        results.extend(batch_results)
        if i + BATCH_SIZE < len(entries):
            time.sleep(3)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main(input_dir: str, output_csv: str, sample_size: int, debug: bool):
    all_files = sorted(Path(input_dir).rglob("*.html"))
    if not all_files:
        print(f"No HTML files found in '{input_dir}'")
        return

    sample = random.sample(all_files, min(sample_size, len(all_files)))
    print(f"Sampled {len(sample)} / {len(all_files)} files\n")

    client      = OpenAI()
    csv_rows    = []
    total_bible = 0

    for path in sorted(sample):
        print(f"  {path.name}")
        html    = path.read_text(encoding="utf-8", errors="replace")
        entries = extract_passages_with_context(html)

        if not entries:
            print(f"    (no italic passages)\n")
            continue

        print(f"    {len(entries)} passage(s) found")
        results = classify_all(client, entries, debug=debug)
        print(f"    {len(results)} total Bible hit(s) for this file")

        for result in results:
            idx        = result.get("id", 1) - 1
            entry      = entries[idx] if 0 <= idx < len(entries) else {}
            italic     = result.get("italic") or entry.get("italic", f"[index error: id={result.get('id')}]")
            confidence = result.get("confidence", "low")
            reference  = result.get("reference") or ""
            note       = result.get("note", "")
            context    = entry.get("context", "")

            total_bible += 1
            ref_str = f" [{reference}]" if reference else ""
            print(f"    Bible ({confidence}){ref_str}: {italic[:70]}{'...' if len(italic) > 70 else ''}")

            csv_rows.append({
                "file":       path.name,
                "italic":     italic,
                "context":    context[:300],
                "confidence": confidence,
                "reference":  reference,
                "note":       note,
            })
        print()

    fieldnames = ["file", "italic", "context", "confidence", "reference", "note"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Done.")
    print(f"  Files processed : {len(sample)}")
    print(f"  Bible refs found: {total_bible}")
    print(f"  CSV written to  : {output_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify italic passages as Bible references via OpenAI.")
    parser.add_argument("--dir",    default=INPUT_DIR,   help=f"Extracted HTML folder (default: {INPUT_DIR})")
    parser.add_argument("--sample", default=SAMPLE_SIZE, type=int, help=f"Files to sample (default: {SAMPLE_SIZE})")
    parser.add_argument("--out",    default=OUTPUT_CSV,  help=f"Output CSV path (default: {OUTPUT_CSV})")
    parser.add_argument("--debug",  action="store_true", help="Print first batch sent to API for inspection")
    args = parser.parse_args()
    main(args.dir, args.out, args.sample, args.debug)
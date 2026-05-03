"""Convert scraped_docs/all_documents.json into a JSON Lines file.

JSONL (one record per line) is the format Hugging Face's `datasets` library
auto-detects most cleanly, and it streams without loading the whole corpus
into memory. Run after `python scraper.py` to refresh `frus_1971.jsonl`.
"""

import json
from pathlib import Path

docs = json.loads(Path("scraped_docs/all_documents.json").read_text(encoding="utf-8"))
with open("frus_1971.jsonl", "w", encoding="utf-8") as f:
    for d in docs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"Wrote {len(docs)} records to frus_1971.jsonl")

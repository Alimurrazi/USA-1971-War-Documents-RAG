"""
STEP 1: Scraper for history.state.gov FRUS documents
Scrapes all documents from one or more FRUS compilations and saves them as JSON.

Add as many compilation URLs to COMP_URLS as you like — the scraper handles
deduplication, per-volume sub-folders, and full resumability.

Usage:
    pip install requests beautifulsoup4
    python 1_scrape.py
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
from pathlib import Path

# ── Config — add/remove URLs here ────────────────────────────────────────────
BASE_URL = "https://history.state.gov"

COMP_URLS = [
     f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch1",  # India and Pakistan: Pre-Crisis
     f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch2",  # India and Pakistan: Crisis and War
     f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch3",  # U.S. relation with India and Pakistan
     f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch4",  # Bangladesh
     f"{BASE_URL}/historicaldocuments/frus1969-76v11/comp1",   # South Asia crisis, 1971
]

OUTPUT_DIR = Path("scraped_docs")   # individual JSONs land here (flat)
DELAY_SEC  = 1.0                    # pause between requests — be polite!

HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic research scraper; contact: yourname@email.com)"
}
# ─────────────────────────────────────────────────────────────────────────────


def extract_volume_id(compilation_url: str) -> str:
    """Extract the FRUS volume id from a compilation URL, e.g. 'frus1969-76ve07'."""
    match = re.search(r"historicaldocuments/([^/]+)/", compilation_url)
    return match.group(1) if match else compilation_url.split("/")[-2]


def fetch_page(url: str) -> BeautifulSoup:
    """Download a URL and return its parsed HTML."""
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def collect_document_urls(compilation_url: str) -> list[str]:
    """Walk the paginated compilation index and return every document URL.

    The index is paginated via ?start=1, 31, 61, … We walk pages until one
    returns no new /dN links.
    """
    print(f"  Fetching index: {compilation_url}")
    document_urls: list[str] = []
    seen: set[str] = set()
    start = 1
    page_size = 30
    max_pages = 200  # safety bound

    for _ in range(max_pages):
        page_url = compilation_url if start == 1 else f"{compilation_url}?start={start}"
        soup = fetch_page(page_url)
        before = len(document_urls)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Document links look like /historicaldocuments/frus.../dNNN
            if re.search(r"/d\d+$", href):
                full_url = href if href.startswith("http") else BASE_URL + href
                if full_url not in seen:
                    seen.add(full_url)
                    document_urls.append(full_url)
        added = len(document_urls) - before
        if added == 0:
            break
        print(f"    page start={start}: +{added} (total {len(document_urls)})")
        start += page_size
        time.sleep(DELAY_SEC)

    print(f"    → {len(document_urls)} document links found")
    return document_urls


def parse_document(url: str, volume: str) -> dict | None:
    """Download and parse a single document page."""
    try:
        soup = fetch_page(url)

        doc_id = url.rstrip("/").split("/")[-1]

        # Title
        title_tag = soup.find("h1") or soup.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Metadata fields (date, source, subject, etc.)
        metadata = {}
        for definition_list in soup.find_all("dl"):
            items = definition_list.find_all(["dt", "dd"])
            for i in range(0, len(items) - 1, 2):
                key = items[i].get_text(strip=True).rstrip(":")
                val = items[i + 1].get_text(strip=True)
                metadata[key] = val

        # Main body text
        body_element = (
            soup.find("div", class_="document-body")
            or soup.find("div", id="document-body")
            or soup.find("article")
            or soup.find("main")
        )
        if body_element:
            for footnote_node in body_element.find_all(["section", "div"], class_=re.compile(r"foot|note")):
                footnote_node.decompose()
            body_text = body_element.get_text(separator="\n", strip=True)
        else:
            body_text = "\n".join(p.get_text(strip=True) for p in soup.find_all("p"))

        # Footnotes (kept separately — useful context for the LLM)
        footnotes = []
        for footnote_section in soup.find_all(["section", "div"], class_=re.compile(r"foot|note")):
            footnotes.append(footnote_section.get_text(separator=" ", strip=True))

        return {
            "doc_id":    doc_id,
            "volume":    volume,
            "url":       url,
            "title":     title,
            "metadata":  metadata,
            "body":      body_text,
            "footnotes": "\n".join(footnotes),
        }

    except Exception as e:
        print(f"    ERROR on {url}: {e}")
        return None


def scrape_compilation(compilation_url: str, global_index: dict) -> list[dict]:
    """Scrape every document under one compilation URL; returns the docs."""
    volume     = extract_volume_id(compilation_url)
    volume_dir = OUTPUT_DIR / volume
    volume_dir.mkdir(parents=True, exist_ok=True)

    document_urls = collect_document_urls(compilation_url)
    documents = []

    for i, url in enumerate(document_urls, 1):
        doc_id      = url.rstrip("/").split("/")[-1]
        # Use volume-prefixed key so d1 from two volumes don't collide
        doc_key     = f"{volume}__{doc_id}"
        output_path = volume_dir / f"{doc_id}.json"

        if output_path.exists():
            print(f"  [{i}/{len(document_urls)}] Skip {volume}/{doc_id} (cached)")
            with open(output_path, encoding="utf-8") as f:
                documents.append(json.load(f))
            continue

        print(f"  [{i}/{len(document_urls)}] Scraping {volume}/{doc_id} ...")
        doc = parse_document(url, volume)
        if doc:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            documents.append(doc)
            global_index[doc_key] = {"volume": volume, "url": url, "title": doc["title"]}

        time.sleep(DELAY_SEC)

    return documents


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    index_path = OUTPUT_DIR / "index.json"

    # Load existing index (allows resuming across runs)
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            global_index = json.load(f)
    else:
        global_index = {}

    all_docs = []

    for compilation_url in COMP_URLS:
        volume = extract_volume_id(compilation_url)
        print(f"\n{'═'*60}")
        print(f"  Volume: {volume}")
        print(f"{'═'*60}")

        documents = scrape_compilation(compilation_url, global_index)
        all_docs.extend(documents)

        # Persist index after every volume
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(global_index, f, ensure_ascii=False, indent=2)

    # Save one combined JSON (used by 2_index.py)
    combined_path = OUTPUT_DIR / "all_documents.json"
    # Merge with any already-saved docs from previous runs
    existing_docs = []
    if combined_path.exists():
        with open(combined_path, encoding="utf-8") as f:
            existing_docs = json.load(f)
        existing_urls = {d["url"] for d in existing_docs}
        new_docs = [d for d in all_docs if d["url"] not in existing_urls]
        all_docs = existing_docs + new_docs

    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_docs, f, ensure_ascii=False, indent=2)

    print(f"\n{'═'*60}")
    print(f"✅ Done!  {len(all_docs)} total documents across {len(COMP_URLS)} volume(s)")
    print(f"   Individual JSONs : {OUTPUT_DIR}/<volume>/")
    print(f"   Combined file    : {combined_path}")
    print(f"   Index            : {index_path}")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()

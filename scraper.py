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
    # f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch2",  # India and Pakistan: Crisis and War
    # f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch3",  # U.S. relation with India and Pakistan
    # f"{BASE_URL}/historicaldocuments/frus1969-76ve07/ch4",  # Bangladesh
    # f"{BASE_URL}/historicaldocuments/frus1969-76v11/comp1",   # South Asia crisis, 1971
]

OUTPUT_DIR = Path("scraped_docs")   # individual JSONs land here (flat)
DELAY_SEC  = 1.0                    # pause between requests — be polite!

HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic research scraper; contact: yourname@email.com)"
}
# ─────────────────────────────────────────────────────────────────────────────


def volume_slug(comp_url: str) -> str:
    """Extract a short identifier from the URL, e.g. 'frus1969-76ve07'."""
    m = re.search(r"historicaldocuments/([^/]+)/", comp_url)
    return m.group(1) if m else comp_url.split("/")[-2]


def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_doc_links(comp_url: str) -> list[str]:
    """Parse the paginated compilation index and return all document URLs.

    The index is paginated via ?start=1, 31, 61, … We walk pages until one
    returns no new /dN links.
    """
    print(f"  Fetching index: {comp_url}")
    links: list[str] = []
    seen: set[str] = set()
    start = 1
    page_size = 30
    max_pages = 200  # safety bound

    for _ in range(max_pages):
        page_url = comp_url if start == 1 else f"{comp_url}?start={start}"
        soup = get_soup(page_url)
        before = len(links)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Document links look like /historicaldocuments/frus.../dNNN
            if re.search(r"/d\d+$", href):
                full = href if href.startswith("http") else BASE_URL + href
                if full not in seen:
                    seen.add(full)
                    links.append(full)
        added = len(links) - before
        if added == 0:
            break
        print(f"    page start={start}: +{added} (total {len(links)})")
        start += page_size
        time.sleep(DELAY_SEC)

    print(f"    → {len(links)} document links found")
    return links


def parse_document(url: str, volume: str) -> dict | None:
    """Download and parse a single document page."""
    try:
        soup = get_soup(url)

        doc_id = url.rstrip("/").split("/")[-1]

        # Title
        title_tag = soup.find("h1") or soup.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Metadata fields (date, source, subject, etc.)
        metadata = {}
        for dl in soup.find_all("dl"):
            items = dl.find_all(["dt", "dd"])
            for i in range(0, len(items) - 1, 2):
                key = items[i].get_text(strip=True).rstrip(":")
                val = items[i + 1].get_text(strip=True)
                metadata[key] = val

        # Main body text
        body_div = (
            soup.find("div", class_="document-body")
            or soup.find("div", id="document-body")
            or soup.find("article")
            or soup.find("main")
        )
        if body_div:
            for fn in body_div.find_all(["section", "div"], class_=re.compile(r"foot|note")):
                fn.decompose()
            body_text = body_div.get_text(separator="\n", strip=True)
        else:
            body_text = "\n".join(p.get_text(strip=True) for p in soup.find_all("p"))

        # Footnotes (kept separately — useful context for the LLM)
        footnotes = []
        for fn_section in soup.find_all(["section", "div"], class_=re.compile(r"foot|note")):
            footnotes.append(fn_section.get_text(separator=" ", strip=True))

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


def scrape_volume(comp_url: str, global_index: dict) -> list[dict]:
    """Scrape one compilation URL; returns list of newly-scraped docs."""
    volume  = volume_slug(comp_url)
    vol_dir = OUTPUT_DIR / volume
    vol_dir.mkdir(parents=True, exist_ok=True)

    doc_links = get_doc_links(comp_url)
    docs = []

    for i, url in enumerate(doc_links, 1):
        doc_id   = url.rstrip("/").split("/")[-1]
        # Use volume-prefixed key so d1 from two volumes don't collide
        uniq_key = f"{volume}__{doc_id}"
        out_file = vol_dir / f"{doc_id}.json"

        if out_file.exists():
            print(f"  [{i}/{len(doc_links)}] Skip {volume}/{doc_id} (cached)")
            with open(out_file, encoding="utf-8") as f:
                docs.append(json.load(f))
            continue

        print(f"  [{i}/{len(doc_links)}] Scraping {volume}/{doc_id} ...")
        doc = parse_document(url, volume)
        if doc:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            docs.append(doc)
            global_index[uniq_key] = {"volume": volume, "url": url, "title": doc["title"]}

        time.sleep(DELAY_SEC)

    return docs


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    index_file = OUTPUT_DIR / "index.json"

    # Load existing index (allows resuming across runs)
    if index_file.exists():
        with open(index_file, encoding="utf-8") as f:
            global_index = json.load(f)
    else:
        global_index = {}

    all_docs = []

    for comp_url in COMP_URLS:
        volume = volume_slug(comp_url)
        print(f"\n{'═'*60}")
        print(f"  Volume: {volume}")
        print(f"{'═'*60}")

        docs = scrape_volume(comp_url, global_index)
        all_docs.extend(docs)

        # Persist index after every volume
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(global_index, f, ensure_ascii=False, indent=2)

    # Save one combined JSON (used by 2_index.py)
    combined_file = OUTPUT_DIR / "all_documents.json"
    # Merge with any already-saved docs from previous runs
    existing = []
    if combined_file.exists():
        with open(combined_file, encoding="utf-8") as f:
            existing = json.load(f)
        existing_urls = {d["url"] for d in existing}
        new_docs = [d for d in all_docs if d["url"] not in existing_urls]
        all_docs = existing + new_docs

    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(all_docs, f, ensure_ascii=False, indent=2)

    print(f"\n{'═'*60}")
    print(f"✅ Done!  {len(all_docs)} total documents across {len(COMP_URLS)} volume(s)")
    print(f"   Individual JSONs : {OUTPUT_DIR}/<volume>/")
    print(f"   Combined file    : {combined_file}")
    print(f"   Index            : {index_file}")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()

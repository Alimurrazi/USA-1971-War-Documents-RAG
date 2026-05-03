# FRUS 1971 Bangladesh Liberation War Corpus

A scraped, structured copy of US State Department **Foreign Relations of the United States (FRUS)** documents covering the **1971 Bangladesh Liberation War** — the political crisis that led to it, the war itself, and its aftermath — as recorded by the Nixon administration's National Security Council and State Department.

The corpus is intended for retrieval-augmented generation (RAG), historical NLP, and information-retrieval research over primary diplomatic sources.

## What the corpus covers

The documents trace the war through three phases:

1. **Lead-up (Jan 1969 – Feb 1971).** How the crisis built gradually: rising tensions between West and East Pakistan, the December 1970 Pakistani election, growing autonomy demands from the Awami League, and US assessments of Yahya Khan's regime.
2. **Crisis and war (Mar – Dec 1971).** The military crackdown in East Pakistan, the refugee exodus into India, the Indo-Pakistan war, the Nixon administration's "tilt" toward Pakistan, and the surrender of Pakistani forces in Dhaka.
3. **Aftermath (Jan – Dec 1972).** Recognition of Bangladesh, the reconfiguration of US relations with India and Pakistan, the new US relationship with Bangladesh, and lingering diplomatic fallout from the war.

## At a glance

| | |
|---|---|
| **Documents** | ~712 |
| **Volumes** | 2 (`frus1969-76ve07`, `frus1969-76v11`) |
| **Format** | One JSON file per document + one combined `all_documents.json` |
| **Size** | ~12 MB uncompressed |
| **Language** | English |
| **Time period covered** | 1969–1972 |
| **Source** | https://history.state.gov |
| **Scrape date** | May 2026 |
| **License** | US Government work — public domain (17 U.S.C. § 105) |

## Source and provenance

All documents are scraped from the **Office of the Historian, US Department of State**, which publishes the FRUS series online at `history.state.gov/historicaldocuments/`. FRUS is the official documentary record of major US foreign-policy decisions and is in the public domain as a work of the US federal government.

Source URLs follow the pattern:

```
https://history.state.gov/historicaldocuments/<volume>/d<N>
```

The `url` field on every record is the canonical link back to the original page.

## What's included

| Volume | Coverage | Chapters scraped |
|---|---|---|
| `frus1969-76ve07` | South Asia, 1969–1972 | ch1 (India and Pakistan: Pre-Crisis), ch2 (India and Pakistan: Crisis and War), ch3 (US Relations with India and Pakistan, 1972), ch4 (Bangladesh, Dec 1971 – Dec 1972) |
| `frus1969-76v11`  | South Asia Crisis, 1971 | comp1 |

The corpus contains memoranda, telegrams, conversations, intelligence assessments, and policy briefings produced before, during, and after the 1971 Indo-Pakistan war that led to Bangladesh's independence.

## File layout

```
scraped_docs/
├── all_documents.json          # combined array of every document (used by index.py)
├── index.json                  # {<volume>__<doc_id>: {volume, url, title}}
├── frus1969-76ve07/
│   ├── d1.json
│   ├── d2.json
│   └── ...
└── frus1969-76v11/
    ├── d1.json
    └── ...
```

## Record schema

Each document is a JSON object:

```json
{
  "doc_id": "d1",
  "volume": "frus1969-76ve07",
  "url": "https://history.state.gov/historicaldocuments/frus1969-76ve07/d1",
  "title": "Foreign Relations of the United States, 1969–1972, Volume E–7, Documents on South Asia, 1969–1972",
  "metadata": {"<key>": "<value>"},
  "body": "...full document text...",
  "footnotes": "...see caveat below..."
}
```

| Field | Type | Notes |
|---|---|---|
| `doc_id` | string | Per-volume identifier (e.g. `d1`, `d122`). Not unique across volumes — pair with `volume` for a global key. |
| `volume` | string | FRUS volume identifier (e.g. `frus1969-76ve07`). |
| `url` | string | Canonical source URL on history.state.gov. |
| `title` | string | Page title. May contain newlines/whitespace from the original HTML. |
| `metadata` | object | Key/value pairs extracted from the page's `<dl>` definition lists (date, source, subject, etc.). Schema is **not** uniform across documents. |
| `body` | string | Main document text, newline-separated. This is the field used for RAG indexing. |
| `footnotes` | string | **Caveat: currently boilerplate.** See known issues. |

## Known issues / caveats

- **`footnotes` is unreliable.** Due to an over-broad CSS-class regex in the scraper, the `footnotes` field contains the page's site-chrome footer (contact info, accessibility links) rather than actual document footnotes. Every record has the same boilerplate. **Do not use this field**; treat it as effectively empty.
- **Body text contains some site chrome at the end** (navigation links like "Contents", "Press Release", "Preface", lists of persons, "Citing the Foreign Relations series", etc.). Researchers may want to truncate body text after the first occurrence of `"Download\nPDF"` or strip the trailing nav block before chunking.
- **Whitespace is preserved as-scraped** — expect mid-word newlines and indentation artifacts from the source HTML.
- **`metadata` schema varies.** Some documents have `Date`, `Source`, `Subject`; others have numbered keys from list structures on the source page.
- **PDFs are not included** — only the HTML transcription. The original scanned pages are linked from the source URL.

## Suggested uses

- **RAG / question-answering** over Cold War-era diplomatic primary sources covering the 1971 war (the original use case — see [`README.md`](README.md) and [`ask.py`](ask.py)).
- **Historical NLP**: NER on diplomatic actors, event extraction, sentiment over time across the lead-up / war / aftermath phases.
- **Information retrieval** benchmarks for long-form, domain-specific text.
- **Education**: a clean, structured corpus for teaching IR / South Asian history / diplomatic history with computational methods.

## How to extend the corpus

The scraper in this repository (`scraper.py`) is resumable and supports any FRUS compilation URL. To add more volumes:

1. Append chapter URLs to `COMP_URLS` in `scraper.py`.
2. Run `python scraper.py` — already-scraped documents are skipped.
3. Run `python index.py` to rebuild the vector store.

See [`CLAUDE.md`](CLAUDE.md) and [`README.md`](README.md) for full pipeline details.

## Citation

If you use this dataset, please cite the original source:

> *Foreign Relations of the United States*, 1969–1972, Volumes E-7 and XI. Office of the Historian, U.S. Department of State. https://history.state.gov

And, optionally, this repository for the scraping/structuring step.

## License

The underlying documents are works of the United States federal government and are in the public domain under 17 U.S.C. § 105. The scraping code in this repository is released under the repository's license. No additional restrictions are placed on the scraped data.

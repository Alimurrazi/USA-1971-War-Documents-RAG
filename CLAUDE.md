# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Local RAG pipeline over **FRUS** (Foreign Relations of the United States, 1969–1976) State Department documents scraped from `history.state.gov`. Everything runs locally — no cloud APIs. Embeddings + generation go through **Ollama**; vectors live in a local **ChromaDB** persistent store.

## Pipeline (run order)

The four scripts are a sequential pipeline that hands off via files on disk:

1. `scraper.py` → writes `scraped_docs/<volume>/d<NNN>.json` + `scraped_docs/all_documents.json` + `scraped_docs/index.json`
2. `index.py`   → reads scraped JSONs, chunks, embeds, writes `chroma_db/`
3. `ask.py`     → CLI REPL that queries `chroma_db/` and calls Ollama
4. `webapp.py`  → Gradio UI alternative to `ask.py` (port 7860)

Steps 3 and 4 are interchangeable consumers of the same `chroma_db/` collection.

## Common commands

```powershell
# One-time setup
pip install requests beautifulsoup4 chromadb ollama gradio
ollama pull mxbai-embed-large    # current EMBED_MODEL
ollama pull qwen2.5:14b          # current default LLM_MODEL in ask.py

# Pipeline
python scraper.py             # scrape (resumable — skips cached JSONs)
python index.py               # rebuild vector index (DROPS the existing collection)
python ask.py                 # CLI Q&A
python ask.py --model mistral --top-k 8
python webapp.py              # Gradio UI at http://localhost:7860
```

There are no tests, no linter config, and no build step.

## Architecture notes

**Config is duplicated, not shared.** `CHROMA_DIR`, `COLLECTION`, `EMBED_MODEL` are redefined at the top of `index.py`, `ask.py`, and `webapp.py`. Changing any of these requires editing all three files in lockstep — they will silently fail (collection-not-found) if they drift.

**`index.py` rebuilds from scratch every run.** It calls `client.delete_collection(COLLECTION)` before re-creating it, so re-running re-embeds everything. There is no incremental indexing.

**Embedding function class is redefined in each consumer.** `OllamaEmbedder` exists separately in `index.py`, `ask.py` (nested inside `RAGChat.__init__`), and `webapp.py`. They must match the indexer's embedding model exactly — Chroma stores vectors, not the function used to make them. Changing `EMBED_MODEL` requires editing all three files **and** running `python index.py` to re-embed (vectors from different models live in different spaces).

**Pagination.** `scraper.py:collect_document_urls` walks `?start=1, 31, 61, …` until a page returns no new `/dN` links — FRUS chapter indexes are paginated 30 documents per page.

**Adding new FRUS volumes/chapters:** append URLs to `COMP_URLS` in `scraper.py:23` (chapter URLs like `.../frus1969-76ve07/ch2`). The scraper deduplicates by per-volume sub-folder + JSON filename, so re-runs are safe and resumable.

**Footnotes are captured but not indexed.** `scraper.py` writes a `footnotes` field into each JSON, but it currently captures the page footer (site chrome) due to an over-broad `class~="foot|note"` regex — every doc gets the same boilerplate. `index.py` deliberately ignores this field; only `body` is chunked. If real document footnotes ever matter, the fix is in `parse_document` (tighten the selector) — not in `index.py`.

**Chunking** (`index.py:chunk_text`): sentence-aware splitter, ~800 chars with ~150-char overlap; chunks under 50 chars are dropped. The "overlap" is implemented in word-units (`overlap // 6` words ≈ overlap chars).

**Conversation history** in `ask.py` is capped at 20 messages and stores only Q/A turns — the retrieved context is *not* persisted across turns, so each turn re-retrieves from scratch using only the current question.

## Repository layout

`scraped_docs/` **is committed** to the repo intentionally — re-scraping is slow and hits a public government archive, and pinning the corpus keeps everyone testing against the same data. `chroma_db/` is gitignored (regeneratable, large, embedding-model-specific).

## Scraper etiquette

`scraper.py` hits a public government archive. Keep `DELAY_SEC = 1.0` (or higher) and the contact-email `User-Agent` honest before any large scrape.

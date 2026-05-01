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
ollama pull nomic-embed-text
ollama pull llama3            # or mistral, phi3, gemma2, etc.

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

**Known bug — file layout mismatch between `scraper.py` and `index.py`:**
- `scraper.py` writes per-document JSONs to `scraped_docs/<volume>/d<NNN>.json` (one subdirectory per FRUS volume).
- `index.py`'s `load_documents()` uses `SCRAPED_DIR.glob("d*.json")` — non-recursive, top-level only — so it will load **zero** documents from the actual scraper output. Either change the glob to `**/d*.json` (rglob) or have `index.py` read the combined `scraped_docs/all_documents.json` instead. The docstring comments in both files (`1_scrape.py`, `2_index.py`) reference renamed earlier versions.

**Embedding function class is redefined in each consumer.** `OllamaEmbedder` exists separately in `index.py`, `ask.py` (nested inside `RAGChat.__init__`), and `webapp.py`. They must match the indexer's embedding model exactly (`nomic-embed-text`) — Chroma stores vectors, not the function used to make them.

**Adding new FRUS volumes:** append URLs to `COMP_URLS` in `scraper.py:23`. The scraper deduplicates by per-volume sub-folder + JSON filename, so re-runs are safe.

**Chunking** (`index.py:34`): sentence-aware splitter, ~800 chars with ~150-char overlap; chunks under 50 chars are dropped.

**Conversation history** in `ask.py` is capped at 20 messages and stores only Q/A turns — the retrieved context is *not* persisted across turns, so each turn re-retrieves from scratch using only the current question.

## Scraper etiquette

`scraper.py` hits a public government archive. Keep `DELAY_SEC = 1.0` (or higher) and the contact-email `User-Agent` honest before any large scrape.

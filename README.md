# FRUS Document Q&A — Local RAG over Declassified US State Department Records

A fully-local **Retrieval-Augmented Generation (RAG)** system that lets you ask natural-language questions about declassified US State Department documents from the [Foreign Relations of the United States (FRUS)](https://history.state.gov/historicaldocuments) series, 1969–1976.

Everything runs on your laptop — no API keys, no cloud calls, no data leaves the machine. Embeddings and language models are served by [Ollama](https://ollama.com/), and vectors are stored in a local [ChromaDB](https://www.trychroma.com/) instance.

The included corpus focuses on the **South Asia volumes** (the lead-up to and aftermath of the 1971 Indo-Pakistan War / Bangladesh Liberation War), but the scraper is generic — point it at any FRUS chapter URL and it will pull every document on that index.

---

## What you can ask

Once indexed, you can ask the system things like:

- *"What was the American thinking before the 1971 India–Pakistan war?"*
- *"How did Kissinger view Yahya Khan's role in the East Pakistan crisis?"*
- *"Why did the Nixon administration tilt toward Pakistan?"*
- *"What concerns did the State Department raise about military supplies to Pakistan?"*

The system retrieves the most relevant passages from the indexed memos, telegrams, and meeting notes, then asks a local LLM to synthesize an answer **citing the specific documents it drew from**.

---

## How it works

```
                     ┌─────────────────────────┐
                     │  history.state.gov      │
                     │  (FRUS HTML pages)      │
                     └────────────┬────────────┘
                                  │
                          1. scraper.py
                                  │
                                  ▼
                     ┌─────────────────────────┐
                     │  scraped_docs/<volume>/ │
                     │      d<N>.json          │  ← one JSON per document
                     └────────────┬────────────┘
                                  │
                          2. index.py
                                  │   chunk + embed (Ollama)
                                  ▼
                     ┌─────────────────────────┐
                     │     chroma_db/          │  ← local vector store
                     │   (HNSW index, cosine)  │
                     └────────────┬────────────┘
                                  │
                          3. ask.py
                             (CLI REPL)
```

The three scripts are a sequential pipeline that hands off via files on disk:

1. **`scraper.py`** — Crawls one or more FRUS chapter index pages. Walks the `?start=1, 31, 61, …` pagination until exhausted, then downloads each document, parses it (title, metadata, body), and writes `scraped_docs/<volume>/d<N>.json`. Resumable: re-runs skip already-downloaded files.
2. **`index.py`** — Reads every `d*.json` from `scraped_docs/`, splits the body into sentence-aware ~800-character chunks with ~150-character overlap, embeds each chunk via Ollama (`mxbai-embed-large` by default), and writes everything to a ChromaDB collection at `chroma_db/`. **Drops and rebuilds the collection on every run.**
3. **`ask.py`** — Interactive REPL. Embeds your question with the same model used by the indexer, retrieves the top-K most similar chunks, builds a prompt with the retrieved context, and asks a local LLM (`qwen2.5:14b` by default) to answer. Prints citations.

---

## Prerequisites

- **Python 3.10+** (uses `list[str]` / `dict | None` syntax)
- **Ollama** — install from [ollama.com](https://ollama.com/download). On Windows it runs as a tray app; on macOS/Linux it's a CLI daemon (`ollama serve`).
- **A reasonably fast machine.** The default LLM (`qwen2.5:14b`) needs ~10GB RAM/VRAM. You can swap in something smaller if needed (see *Switching models* below).

---

## Quick start

```powershell
# 1. Install Python dependencies
pip install requests beautifulsoup4 chromadb ollama

# 2. Pull the local models
ollama pull mxbai-embed-large       # embedding model (~670 MB)
ollama pull qwen2.5:14b             # generation model (~9 GB)

# 3. (Optional) Re-scrape — skip this if scraped_docs/ is already populated
python scraper.py

# 4. Build the vector index
python index.py

# 5. Ask questions
python ask.py
```

The scraped documents (`scraped_docs/`) are committed to the repository, so on a fresh clone you can skip step 3 entirely and jump straight to indexing.

---

## Detailed pipeline

### Step 1 — Scraping (`scraper.py`)

Open `scraper.py` and edit `COMP_URLS` near the top to choose which FRUS chapters to crawl. URLs look like:

```
https://history.state.gov/historicaldocuments/frus1969-76ve07/ch1
                                              └─ volume id ─┘ └ chapter
```

The scraper:

- Walks the paginated index (each chapter shows 30 documents per page; pages are accessed via `?start=1`, `?start=31`, `?start=61`, …).
- Downloads each document page found there.
- Parses out the title, metadata (date, source, subject…), body text, and footnotes.
- Saves one JSON file per document under `scraped_docs/<volume>/d<N>.json`.
- Writes a combined `scraped_docs/all_documents.json` and a per-volume `scraped_docs/index.json` for convenience.
- Sleeps 1 second between requests (`DELAY_SEC`) — be polite to the public archive.

Re-runs are safe: if a document JSON already exists, the scraper skips the network request.

### Step 2 — Indexing (`index.py`)

```powershell
python index.py
```

What it does:

1. Recursively loads every `d*.json` from `scraped_docs/`.
2. For each document, splits the body into chunks via `chunk_text()` — sentence-aware, ~800 chars per chunk, ~150 chars of overlap.
3. **Drops** the existing `frus_documents` Chroma collection (clean rebuild every run).
4. **Creates** a new collection configured for cosine similarity over an HNSW index.
5. For every chunk, sends it to Ollama for embedding (`mxbai-embed-large`), and upserts the resulting vector + metadata (`doc_id`, `title`, `date`, `url`, `chunk_index`) into Chroma.

Embeddings happen one chunk at a time over HTTP to Ollama, so for ~hundreds of documents this takes a few minutes. The result is a `chroma_db/` directory you should not commit (it's gitignored).

#### What "~800 chars per chunk, ~150 chars of overlap" actually means

**Why split at all?** A FRUS document body is far too long to embed as a single vector — and even if it weren't, you wouldn't want one vector per document. Retrieval would return whole memos instead of pinpointing the relevant paragraph, and the cosine-similarity score would be diluted by all the unrelated text inside that document.

**~800 chars per chunk.** Each chunk is roughly 800 characters — about 120–150 English words, or one moderate paragraph. Small enough that a chunk is usually about a single idea; big enough that quoting it back to the LLM gives useful context.

The `~` is because the splitter breaks at **sentence boundaries** (`.`, `!`, `?`). It greedily packs sentences until adding the next one would exceed 800 chars, so real chunk sizes wobble between ~600 and ~900 characters depending on where the sentences fall. 800 is a target, not a hard cap.

**~150 chars of overlap.** Each chunk repeats the **last ~150 characters of the previous chunk** at its start:

```
Chunk 1:  [sentence A][sentence B][sentence C][sentence D]
                                         ↓ overlap ↓
Chunk 2:                       [sentence D][sentence E][sentence F][sentence G]
                                         ↓ overlap ↓
Chunk 3:                                                [sentence G][sentence H]...
```

Why? Imagine a critical sentence like *"Yahya Khan agreed in principle, but only if China were consulted first"* falls right on the 800-char boundary. Without overlap, half ends up in chunk 1 and half in chunk 2 — neither chunk's embedding fully captures the idea, so a query like *"who did Yahya want China consulted about"* might miss it. With overlap, the boundary sentence appears in **both** adjacent chunks, so retrieval still finds it cleanly.

The cost is some duplicated text → slightly more chunks → slightly slower indexing. For RAG quality, the trade-off is almost always worth it.

**A note on the implementation.** Inside `chunk_text()`:

```python
words = current.split()
current = " ".join(words[-(overlap // 6):]) + " " + sent
```

The overlap is implemented in **words**, not characters — it carries forward `overlap // 6` words from the end of the previous chunk. The `// 6` is a rough character-to-word conversion (English averages `~6 characters per word including spaces). So with `overlap = 150`, that's `150 // 6 = 25` words, which is *approximately* 150 characters — hence the "~"`. Not exact, but close enough for retrieval purposes.

#### What "cosine similarity over an HNSW index" actually means

When `index.py` creates the Chroma collection, it passes `metadata={"hnsw:space": "cosine"}`. That single line bundles two distinct decisions: the **distance metric** (cosine) and the **search algorithm** (HNSW). Both matter for retrieval quality and speed.

**Cosine similarity** is the *math* used to decide which stored vectors are "closest" to your query vector when you ask a question.

A vector is just a list of numbers. After embedding, every chunk and every query becomes a point in a high-dimensional space (1024 dimensions for `mxbai-embed-large`). Cosine similarity measures the **angle** between two vectors, ignoring how long either one is:

```
cosine similarity = 1   →  vectors point in exactly the same direction (very similar)
cosine similarity = 0   →  vectors are perpendicular (unrelated)
cosine similarity = -1  →  vectors point in opposite directions (rare with embeddings)
```

If a question vector and a chunk vector point in roughly the same direction, the embedding model is telling you their meanings overlap. The reason "ignoring length" is the right call for text embeddings: a long paragraph and a short sentence about the same topic should be considered similar even if their vectors have very different magnitudes.

Chroma supports three options here — `"cosine"`, `"l2"` (Euclidean distance), and `"ip"` (inner product). For sentence-transformer-style embeddings like `mxbai-embed-large`, `bge-m3`, and `nomic-embed-text`, **cosine is the right default** — it's the metric those models were trained with.

**HNSW** = **Hierarchical Navigable Small World**, the *algorithm* used to find the nearest vectors quickly.

The naive way to find the most similar chunks to a query is to compare the query vector to *every* stored vector, sort the results, and return the top K. That's an **O(n) linear scan** — instant for 1,000 chunks, painful at 1,000,000.

HNSW instead builds a **graph** of vectors during indexing where each vector has links to a handful of its nearest neighbors. To answer a query, it starts at one entry point and "walks" the graph greedily — always stepping toward neighbors closer to the query — until it can't get any closer. With a multi-layer structure (the "Hierarchical" part: a sparse top layer for big jumps and a dense bottom layer for fine-grained navigation), the lookup time drops to roughly **O(log n)** at the cost of being **approximate**: you might miss the absolute true top-K by a small margin, but in practice the recall is >95%.

For RAG, "approximate but 1000× faster" is a clear win — perfect ranking doesn't matter when you're going to feed 12 chunks to an LLM anyway, and the LLM is the bottleneck on the answer-quality side, not retrieval.

So when you read the line in `index.py`:

```python
collection = client.create_collection(
    name=COLLECTION,
    embedding_function=embedder,
    metadata={"hnsw:space": "cosine"},
)
```

…the `metadata={"hnsw:space": "cosine"}` part is saying: "store the vectors in an HNSW graph index, and rank candidates by cosine similarity at query time." The HNSW graph is built incrementally as chunks are upserted; the cosine metric is consulted on every `collection.query(...)` call from `ask.py`.

### Step 3 — Asking (`ask.py`)

`ask.py` is a CLI REPL:

```powershell
python ask.py
```

For each question:

1. Embeds the question with the **same** embedding model used by the indexer.
2. Queries Chroma for the top-K most similar chunks (default `TOP_K = 12`).
3. Wraps the retrieved chunks into a context block and sends them, along with a system prompt that instructs the LLM to behave as a diplomatic historian and cite sources, to Ollama.
4. Prints the answer plus a list of source documents (title, date, URL).
5. Maintains a multi-turn conversation history (capped at 20 messages). Type `clear` to reset, `quit`/`exit`/`q` to leave.

#### What "top-K most similar chunks" actually means

"Top-K" is a generic information-retrieval term — it means "the K best-scoring results from the search." Three pieces of the phrase:

**"K"** — A configurable integer. In this project:

```python
# ask.py:30
TOP_K        = 12          # number of chunks to retrieve
```

So K = 12, meaning every question retrieves the 12 chunks most similar to the question. You can override it from the command line:

```powershell
python ask.py --top-k 8
```

**"Most similar"** — Determined by the cosine similarity metric configured on the collection (see the Step 2 section above). For every question the flow is:

1. The question text is embedded into a 1024-dimensional vector via `mxbai-embed-large`.
2. Chroma walks the HNSW graph to find vectors close to the query.
3. Each candidate chunk gets a cosine-similarity score against the query.
4. Chroma sorts those scores from highest to lowest.
5. The top 12 are returned.

**"Chunks"** — Not whole documents, but the ~800-character pieces produced by `chunk_text()` during indexing. Each chunk has its own embedding, so when you ask *"what did Kissinger say about military supplies?"*, you get back **specific paragraphs** about that topic — possibly drawn from 12 *different* documents — instead of entire memos.

In `ask.py`, the actual call looks like this:

```python
results = self.collection.query(
    query_texts=[question],
    n_results=self.top_k,        # ← this is K
)
```

Chroma returns a dict with parallel arrays — `documents`, `metadatas`, `distances` — each containing exactly K entries, ordered from most to least similar. `ask.py` then formats those K chunks into a context block and sends them to the LLM as evidence to answer the question.

##### How to think about choosing K

| K value | Trade-off |
|---|---|
| **Small (3–6)** | Tight, focused context. Fast. Risk: misses relevant info if it's spread across many documents. |
| **Medium (8–12)** | Sweet spot for most RAG. Default here is 12. |
| **Large (20–30)** | More context for the LLM to weave together. Risk: dilutes the prompt with marginal-relevance chunks ("noise") and costs more tokens. |
| **Very large (50+)** | Pointless without a re-ranker — most of those chunks are barely relevant. |

The right K depends on:

- **Question complexity.** Synthesis questions like *"compare Nixon's and Kissinger's positions on Bangladesh"* benefit from larger K because they need evidence from many places. Lookup questions like *"what was the date of memo X"* are happiest with smaller K.
- **Chunk size.** Smaller chunks → need higher K to cover the same amount of underlying text.
- **LLM context window.** Each chunk is ~800 chars ≈ 200 tokens. K = 12 ≈ 2,400 tokens of context. `qwen2.5:14b` has a 128k-token context window, so even K = 50 fits comfortably — the limit on K is *answer quality*, not *what physically fits in the prompt*.

---

## Configuration

Each script defines its config at the top, in a `# ── Config ──` block. **The configs are duplicated, not shared.** If you change `CHROMA_DIR`, `COLLECTION`, or `EMBED_MODEL`, you must edit `index.py` and `ask.py` together — they will silently fail (`collection-not-found`) if they drift.

| Setting | File(s) | Default | Notes |
|---|---|---|---|
| `CHROMA_DIR` | `index.py`, `ask.py` | `Path("chroma_db")` | Where the vector store lives. |
| `COLLECTION` | `index.py`, `ask.py` | `"frus_documents"` | Chroma collection name. |
| `EMBED_MODEL` | `index.py`, `ask.py` | `"mxbai-embed-large"` | Must match across files. |
| `LLM_MODEL` | `ask.py` | `"qwen2.5:14b"` | Overridable via `--model`. |
| `TOP_K` | `ask.py` | `12` | Chunks retrieved per question. |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `index.py` | `800` / `150` | Characters. |
| `COMP_URLS` | `scraper.py` | South Asia chapters | List of FRUS chapter URLs. |
| `DELAY_SEC` | `scraper.py` | `1.0` | Seconds between HTTP requests. |

---

## Adding new FRUS volumes or chapters

1. Browse to the FRUS volume you want at https://history.state.gov/historicaldocuments.
2. Find the chapter index URL (looks like `.../frusYYYY-YYvNN/chN` or `.../comp1`).
3. Append it to `COMP_URLS` in `scraper.py:23`.
4. Re-run the pipeline:
   ```powershell
   python scraper.py
   python index.py
   ```

Different volumes go into different `scraped_docs/<volume>/` sub-folders, so document IDs (which restart at `d1` per volume) don't collide.

---

## Switching models

### Embedding model

Pulled from the [Ollama embedding model list](https://ollama.com/library?type=embedding). Strong choices for English retrieval:

| Model | Dim | Context | Notes |
|---|---|---|---|
| `mxbai-embed-large` *(current)* | 1024 | 512 tok | Best English retrieval per size; fits 800-char chunks comfortably. |
| `bge-m3` | 1024 | 8192 tok | Multilingual, longer context; pick this if you grow chunk size. |
| `nomic-embed-text` | 768 | 8192 tok | Smaller/faster; lower retrieval accuracy. |

To switch:

1. `ollama pull <new-model>`
2. Update `EMBED_MODEL` in **both** `index.py` and `ask.py`.
3. **Re-run `python index.py`** — vectors from one embedding model are not comparable to vectors from another. Skip this and your existing `chroma_db/` will return cosine-distance gibberish.

### LLM (generation model)

Anything Ollama can run. Heavier = better synthesis on multi-document questions, but more RAM/VRAM:

| Tier | Models | RAM/VRAM |
|---|---|---|
| Lightweight | `llama3.2:3b`, `phi3:mini` | 2–4 GB |
| Mid | `llama3.1:8b`, `mistral`, `qwen2.5:7b` | 6–8 GB |
| Heavy *(current default)* | `qwen2.5:14b` | ~10 GB |
| Very heavy | `llama3.1:70b`, `qwen2.5:32b` | 32+ GB |

Pull the model and either change `LLM_MODEL` in `ask.py`, or pass `--model <name>` at the command line.

---

## Project structure

```
.
├── scraper.py              # Step 1: scrape FRUS documents
├── index.py                # Step 2: chunk + embed → ChromaDB
├── ask.py                  # Step 3: CLI Q&A REPL
├── scraped_docs/           # Committed corpus (per-volume sub-folders)
│   ├── frus1969-76ve07/
│   │   ├── d1.json
│   │   ├── d2.json
│   │   └── ...
│   ├── all_documents.json  # combined dump
│   └── index.json          # per-doc title/url index
├── chroma_db/              # Vector store (gitignored — regenerate with index.py)
├── CLAUDE.md               # Guidance for the Claude Code agent
├── README.md               # This file
└── .gitignore
```

---

## Tech stack and design notes

- **[ChromaDB](https://www.trychroma.com/)** — local vector store with persistent on-disk storage, built-in HNSW + cosine similarity, and metadata filtering. Chosen over FAISS / sqlite-vec because it bundles the embedding-function-callback pattern (the indexer's `EmbeddingFunction` subclass is invoked automatically on `upsert` / `query`), which keeps the pipeline scripts small.
- **[Ollama](https://ollama.com/)** — runs both the embedding model and the chat model locally. Replaces OpenAI / Anthropic API calls entirely.
- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** — HTML parser for the scraper.

The codebase is intentionally **flat and procedural**. Each script is self-contained and runnable. There is no shared library, no package, no dependency injection — config constants are duplicated at the top of each file. This is a deliberate trade-off: simpler to read, modify, and run, at the cost of having to keep two config blocks in sync.

---

## Known limitations and gotchas

- **Footnote extraction is broken.** The scraper's footnote selector (`class~="foot|note"`) over-matches and captures the page footer (site chrome) on every document. The `footnotes` field in each JSON is therefore identical boilerplate across all documents. The indexer (`index.py`) deliberately ignores this field — only `body` is chunked. If real document footnotes ever matter, fix `parse_document` in `scraper.py` with a tighter selector.
- **No incremental indexing.** `index.py` drops and recreates the Chroma collection every run. For a few hundred documents this takes a few minutes. At thousands of documents it would become annoying — adding incremental upsert would be a worthwhile change at that scale.
- **One embedding call per chunk.** `OllamaEmbedder` issues a sequential HTTP request per chunk. Ollama doesn't have a true batch-embed API, but you could parallelize with a thread pool if it ever becomes a bottleneck.
- **No retrieval re-ranking.** A cross-encoder re-ranker after the initial top-K would likely improve answer quality further but isn't implemented.
- **Conversation context is not re-retrieved across turns.** Each turn in `ask.py` retrieves chunks based only on the current question — follow-up questions like *"and what about Bhutto?"* won't carry the previous turn's topic into retrieval (only into the LLM prompt as chat history).

---

## A note on the source corpus

FRUS volumes are published by the [Office of the Historian, US Department of State](https://history.state.gov/about/hac) and are in the **public domain**. The documents are declassified diplomatic records — memos, telegrams, meeting minutes — covering US foreign policy from the late 18th century forward. The 1969–1976 volumes used here include the South Asia crisis (`frus1969-76ve07`, `frus1969-76v11`) and contain meeting notes from Nixon, Kissinger, Yahya Khan, and other principals during the lead-up to and aftermath of the 1971 war.

Please be respectful of `history.state.gov`'s servers when scraping — keep `DELAY_SEC` at 1 second or higher, and update the contact email in `scraper.py`'s `User-Agent` to your own before running large scrapes.

---

## License

The code in this repository is provided as-is for research and educational use. The FRUS source documents are US government works and are in the public domain.

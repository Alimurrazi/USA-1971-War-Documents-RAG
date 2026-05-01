"""
STEP 2: Build a local vector index from the scraped documents.

Uses:
  - ChromaDB  → local vector store (no cloud needed)
  - Ollama    → local embeddings via `nomic-embed-text` model

Install:
    pip install chromadb ollama
    ollama pull nomic-embed-text

Usage:
    python 2_index.py
"""

import json
import os
import re
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
import ollama

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPED_DIR   = Path("scraped_docs")
CHROMA_DIR    = Path("chroma_db")
COLLECTION    = "frus_documents"
EMBED_MODEL   = "nomic-embed-text"   # pull with: ollama pull nomic-embed-text
CHUNK_SIZE    = 800    # characters per chunk
CHUNK_OVERLAP = 150
# ──────────────────────────────────────────────────────────────────────────────


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks, breaking at sentence boundaries."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) > size and current:
            chunks.append(current.strip())
            # keep overlap
            words = current.split()
            current = " ".join(words[-(overlap // 6):]) + " " + sent
        else:
            current += " " + sent
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 50]


class OllamaEmbedder(embedding_functions.EmbeddingFunction):
    def __init__(self, model: str = EMBED_MODEL):
        self.model = model

    def __call__(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            resp = ollama.embeddings(model=self.model, prompt=text)
            embeddings.append(resp["embedding"])
        return embeddings


def load_documents() -> list[dict]:
    docs = []
    for json_file in sorted(SCRAPED_DIR.glob("d*.json")):
        with open(json_file, encoding="utf-8") as f:
            docs.append(json.load(f))
    print(f"Loaded {len(docs)} documents from '{SCRAPED_DIR}'")
    return docs


def build_index():
    docs = load_documents()
    if not docs:
        print("No documents found. Run 1_scrape.py first.")
        return

    CHROMA_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    embedder = OllamaEmbedder()
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION,
        embedding_function=embedder,
        metadata={"hnsw:space": "cosine"},
    )

    total_chunks = 0
    for doc in docs:
        doc_id   = doc["doc_id"]
        title    = doc.get("title", "")
        url      = doc.get("url", "")
        metadata = doc.get("metadata", {})
        date     = metadata.get("Date", metadata.get("date", ""))

        # Combine body + footnotes for richer context
        full_text = doc.get("body", "") + "\n" + doc.get("footnotes", "")
        chunks = chunk_text(full_text)

        if not chunks:
            print(f"  Skipping {doc_id} – no text content")
            continue

        ids, texts, metas = [], [], []
        for j, chunk in enumerate(chunks):
            ids.append(f"{doc_id}_chunk{j}")
            texts.append(chunk)
            metas.append({
                "doc_id": doc_id,
                "title":  title,
                "date":   date,
                "url":    url,
                "chunk":  j,
            })

        # Upsert in batches of 32
        batch = 32
        for start in range(0, len(ids), batch):
            collection.upsert(
                ids=ids[start:start+batch],
                documents=texts[start:start+batch],
                metadatas=metas[start:start+batch],
            )

        total_chunks += len(chunks)
        print(f"  Indexed {doc_id} ({len(chunks)} chunks) | {title[:60]}")

    print(f"\n✅ Index built! {total_chunks} chunks across {len(docs)} documents.")
    print(f"   Vector DB saved to: {CHROMA_DIR}/")


if __name__ == "__main__":
    build_index()

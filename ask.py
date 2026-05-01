"""
STEP 3: Ask questions about the FRUS documents using local RAG.

Uses:
  - ChromaDB  → retrieve relevant document chunks
  - Ollama    → generate answers (llama3, mistral, etc.)

Install:
    pip install chromadb ollama
    ollama pull llama3          # or: mistral, phi3, gemma2, etc.
    ollama pull nomic-embed-text

Usage:
    python 3_ask.py
    python 3_ask.py --model mistral --top-k 8
"""

import argparse
import textwrap
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
import ollama

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_DIR   = Path("chroma_db")
COLLECTION   = "frus_documents"
EMBED_MODEL  = "nomic-embed-text"
LLM_MODEL    = "llama3"   # change to any model you have in Ollama
TOP_K        = 6          # number of chunks to retrieve
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a diplomatic historian specializing in US foreign policy.
You answer questions EXCLUSIVELY based on the declassified State Department documents
provided in the context below. These are from the Foreign Relations of the United States
(FRUS) series covering 1969–1976.

Rules:
- Cite specific documents (title, date, doc_id) when you make claims.
- If the context doesn't contain enough information, say so clearly.
- Reflect the actual thinking expressed in the documents — do not add modern interpretation.
- Be precise and analytical. Quote key phrases when illuminating.
"""

def build_context(results) -> str:
    """Format retrieved chunks into a readable context block."""
    parts = []
    for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0]), 1):
        parts.append(
            f"[Source {i}]\n"
            f"Document: {meta.get('doc_id')} | {meta.get('title', 'Untitled')}\n"
            f"Date: {meta.get('date', 'unknown')}\n"
            f"URL: {meta.get('url', '')}\n"
            f"---\n{doc}\n"
        )
    return "\n\n".join(parts)


class RAGChat:
    def __init__(self, llm_model: str = LLM_MODEL, top_k: int = TOP_K):
        self.llm_model = llm_model
        self.top_k     = top_k
        self.history   = []   # for multi-turn conversation

        class OllamaEmbedder(embedding_functions.EmbeddingFunction):
            def __init__(self, model=EMBED_MODEL):
                self.model = model
            def __call__(self, texts):
                return [ollama.embeddings(model=self.model, prompt=t)["embedding"] for t in texts]

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = client.get_collection(
            name=COLLECTION,
            embedding_function=OllamaEmbedder(),
        )
        print(f"✅ Loaded collection with {self.collection.count()} chunks")
        print(f"   LLM: {self.llm_model} | Embed: {EMBED_MODEL} | Top-K: {self.top_k}\n")

    def ask(self, question: str) -> str:
        # 1. Retrieve relevant chunks
        results = self.collection.query(
            query_texts=[question],
            n_results=self.top_k,
        )
        context = build_context(results)

        # 2. Build prompt
        user_msg = (
            f"Context (declassified US State Department documents):\n\n"
            f"{context}\n\n"
            f"---\nQuestion: {question}"
        )

        # 3. Build message list (with history for multi-turn)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_msg})

        # 4. Call local LLM
        response = ollama.chat(model=self.llm_model, messages=messages)
        answer   = response["message"]["content"]

        # 5. Store in history (only question+answer, not the huge context)
        self.history.append({"role": "user",      "content": question})
        self.history.append({"role": "assistant", "content": answer})

        # Keep history manageable
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return answer, results["metadatas"][0]


def print_sources(metadatas: list[dict]):
    print("\n📄 Sources used:")
    seen = set()
    for m in metadatas:
        key = m.get("doc_id", "")
        if key not in seen:
            seen.add(key)
            print(f"   • [{key}] {m.get('title', '')[:70]}  ({m.get('date', '')})")
            print(f"     {m.get('url', '')}")


def main():
    parser = argparse.ArgumentParser(description="Ask questions about FRUS documents")
    parser.add_argument("--model",  default=LLM_MODEL,  help="Ollama LLM model name")
    parser.add_argument("--top-k",  type=int, default=TOP_K, help="Chunks to retrieve")
    args = parser.parse_args()

    if not CHROMA_DIR.exists():
        print("❌ No vector database found. Run 2_index.py first.")
        return

    rag = RAGChat(llm_model=args.model, top_k=args.top_k)

    print("=" * 70)
    print("  FRUS Document Q&A  (type 'quit' to exit, 'clear' to reset history)")
    print("=" * 70)

    while True:
        try:
            question = input("\n🔍 Your question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        if question.lower() == "clear":
            rag.history = []
            print("History cleared.")
            continue

        print("\n⏳ Thinking...\n")
        answer, metas = rag.ask(question)

        print("─" * 70)
        # Word-wrap the answer nicely
        for line in answer.split("\n"):
            if line.strip():
                print(textwrap.fill(line, width=70))
            else:
                print()

        print_sources(metas)


if __name__ == "__main__":
    main()

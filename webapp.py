"""
OPTIONAL: Web UI version of the FRUS Q&A system using Gradio.

Install:
    pip install chromadb ollama gradio

Usage:
    python 4_webapp.py
    Then open http://localhost:7860 in your browser
"""

from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
import ollama
import gradio as gr

# ── Config (must match 2_index.py / 3_ask.py) ─────────────────────────────────
CHROMA_DIR   = Path("chroma_db")
COLLECTION   = "frus_documents"
EMBED_MODEL  = "nomic-embed-text"
DEFAULT_LLM  = "llama3"
TOP_K        = 6
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a diplomatic historian specializing in US foreign policy.
You answer questions EXCLUSIVELY based on the declassified State Department documents
provided. These are from the Foreign Relations of the United States (FRUS) series,
1969–1976.

- Cite documents (title, date) when making claims.
- If the context is insufficient, say so clearly.
- Be precise. Quote key phrases where illuminating.
"""

class OllamaEmbedder(embedding_functions.EmbeddingFunction):
    def __call__(self, texts):
        return [ollama.embeddings(model=EMBED_MODEL, prompt=t)["embedding"] for t in texts]

client     = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = client.get_collection(name=COLLECTION, embedding_function=OllamaEmbedder())


def retrieve(question: str, top_k: int = TOP_K):
    results = collection.query(query_texts=[question], n_results=top_k)
    docs, metas = results["documents"][0], results["metadatas"][0]
    context_parts = []
    sources = []
    for doc, meta in zip(docs, metas):
        context_parts.append(
            f"[{meta['doc_id']}] {meta.get('title','')} ({meta.get('date','')})\n{doc}"
        )
        sources.append(f"**[{meta['doc_id']}]** {meta.get('title','')[:70]}  \n{meta.get('url','')}")
    return "\n\n---\n\n".join(context_parts), "\n\n".join(sources)


def chat(message: str, history: list, model_name: str, top_k_slider: int):
    context, sources = retrieve(message, int(top_k_slider))
    user_msg = f"Context:\n{context}\n\n---\nQuestion: {message}"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for human, assistant in history:
        messages.append({"role": "user",      "content": human})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_msg})

    response = ollama.chat(model=model_name, messages=messages)
    answer   = response["message"]["content"]

    return answer, sources


def gradio_chat(message, history, model_name, top_k_slider):
    answer, sources = chat(message, history, model_name, top_k_slider)
    return answer, sources


def get_available_models():
    try:
        models = ollama.list()
        return [m["name"] for m in models.get("models", [])] or [DEFAULT_LLM]
    except Exception:
        return [DEFAULT_LLM]


with gr.Blocks(title="FRUS Document Q&A", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🗂️ FRUS 1969–76 Document Q&A
    Ask questions about US foreign policy based on declassified State Department documents.
    """)

    with gr.Row():
        with gr.Column(scale=3):
            chatbot    = gr.Chatbot(height=500, label="Conversation")
            msg_input  = gr.Textbox(
                placeholder="e.g. What was the American thinking before the 1971 India-Pakistan war?",
                label="Your question",
                lines=2,
            )
            with gr.Row():
                submit_btn = gr.Button("Ask", variant="primary")
                clear_btn  = gr.ClearButton([msg_input, chatbot])

        with gr.Column(scale=1):
            model_dd   = gr.Dropdown(
                choices=get_available_models(),
                value=DEFAULT_LLM,
                label="LLM Model (Ollama)",
            )
            top_k_sl   = gr.Slider(2, 12, value=TOP_K, step=1, label="Chunks to retrieve (top-K)")
            sources_md = gr.Markdown(label="📄 Sources", value="Sources will appear here after your first question.")

    history_state = gr.State([])

    def on_submit(message, history, model, top_k):
        answer, sources = chat(message, history, model, top_k)
        history.append((message, answer))
        return "", history, history, sources

    submit_btn.click(
        on_submit,
        inputs=[msg_input, history_state, model_dd, top_k_sl],
        outputs=[msg_input, chatbot, history_state, sources_md],
    )
    msg_input.submit(
        on_submit,
        inputs=[msg_input, history_state, model_dd, top_k_sl],
        outputs=[msg_input, chatbot, history_state, sources_md],
    )

if __name__ == "__main__":
    print(f"Collection has {collection.count()} chunks loaded.")
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)

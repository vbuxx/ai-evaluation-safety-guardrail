"""Retrieval-augmented generation untuk knowledge base helpdesk."""

import asyncio
import os
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parent.parent / "data" / "it_helpdesk_knowledge_base.csv"
EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-3.5-flash-lite"

_client = None
_index = None
_documents = None
_df = None


def _get_client():
    """Membuat Gemini client hanya ketika jalur RAG digunakan."""
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY belum dikonfigurasi")
        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000),
        )
    return _client


def _get_embeddings(texts: list[str], task_type: str) -> np.ndarray:
    result = _get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=768,
        ),
    )
    vectors = np.asarray([item.values for item in result.embeddings], dtype="float32")
    faiss.normalize_L2(vectors)
    return vectors


def _get_embedding(text: str) -> np.ndarray:
    return _get_embeddings([text], "RETRIEVAL_QUERY")[0]


def build_index():
    """Memuat knowledge base dan membangun index FAISS sekali per proses."""
    global _index, _documents, _df

    _df = pd.read_csv(KNOWLEDGE_BASE_PATH, dtype=str)
    if _df.empty:
        raise RuntimeError("Knowledge base kosong")

    _documents = [
        f"Kategori: {row.category}\nPertanyaan: {row.question}\nJawaban: {row.answer}"
        for row in _df.itertuples(index=False)
    ]
    vectors = _get_embeddings(_documents, "RETRIEVAL_DOCUMENT")
    _index = faiss.IndexFlatIP(vectors.shape[1])
    _index.add(vectors)
    return _index


def semantic_search(query: str, top_k: int = 3) -> list[dict]:
    """Mengembalikan baris knowledge base terdekat beserta cosine score."""
    global _index

    query = query.strip()
    if not query:
        raise ValueError("Query tidak boleh kosong")
    if _index is None:
        build_index()

    limit = min(max(top_k, 1), len(_documents))
    scores, indices = _index.search(_get_embedding(query).reshape(1, -1), limit)
    return [
        {
            "category": _df.iloc[index]["category"],
            "question": _df.iloc[index]["question"],
            "answer": _df.iloc[index]["answer"],
            "score": float(score),
        }
        for score, index in zip(scores[0], indices[0])
        if index >= 0
    ]


async def answer_from_knowledge_base(query: str) -> str:
    """Menjawab pertanyaan hanya dengan konteks hasil retrieval."""
    results = semantic_search(query)
    context = "\n\n".join(
        f"Sumber {number}\nKategori: {item['category']}\n"
        f"Pertanyaan: {item['question']}\nJawaban: {item['answer']}"
        for number, item in enumerate(results, start=1)
    )
    prompt = f"""Persona:
Anda adalah asisten internal People & IT Operations yang ringkas dan akurat.

Tugas:
Jawab pertanyaan pengguna hanya berdasarkan konteks. Jika konteks tidak memuat
jawaban, katakan bahwa informasi tersebut tidak tersedia di knowledge base.

Konteks:
{context}

Pertanyaan pengguna:
{query}

Format:
Jawab dalam Bahasa Indonesia, maksimal tiga kalimat, tanpa mengarang informasi.
"""
    response = await asyncio.to_thread(
        _get_client().models.generate_content,
        model=GENERATION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            max_output_tokens=512,
        ),
    )
    answer = (response.text or "").strip()
    if not answer:
        raise RuntimeError("Gemini tidak menghasilkan jawaban")
    return answer

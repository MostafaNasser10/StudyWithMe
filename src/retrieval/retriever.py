from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from src.config import TOP_K
from src.retrieval.vector_store import get_vector_store


def retrieve_chunks(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    return vector_store.similarity_search(query=query, k=k)


def retrieve_chunks_with_scores(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    return retrieve_chunks_with_scores_from_store(vector_store, query, k)


def retrieve_chunks_with_scores_from_store(vector_store: Any, query: str, k: int = TOP_K):
    try:
        return vector_store.similarity_search_with_score(query=query, k=k)
    except Exception:
        return [(chunk, None) for chunk in vector_store.similarity_search(query=query, k=k)]


def retrieve_chunks_bm25(query: str, k: int = TOP_K, chat_id: str | None = None):
    """Run a small BM25 lexical search over the existing FAISS docstore.

    Vector search is semantic: it can find meaning even when words differ. BM25
    is lexical: it rewards exact term overlap. Running both in parallel gives
    the tutor a stronger retrieval mix without creating a second index.
    """

    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    return retrieve_chunks_bm25_from_store(vector_store, query, k)


def retrieve_chunks_bm25_from_store(vector_store: Any, query: str, k: int = TOP_K):
    documents = _documents_from_vector_store(vector_store)
    if not documents:
        return []

    query_terms = _tokenize(query)
    if not query_terms:
        return []

    doc_terms = [_tokenize(getattr(doc, "page_content", "")) for doc in documents]
    doc_lengths = [len(terms) for terms in doc_terms]
    avg_doc_length = sum(doc_lengths) / max(len(doc_lengths), 1)
    doc_frequency: Counter[str] = Counter()
    for terms in doc_terms:
        doc_frequency.update(set(terms))

    scored = []
    for doc, terms, doc_length in zip(documents, doc_terms, doc_lengths):
        counts = Counter(terms)
        score = 0.0
        for term in query_terms:
            if not counts.get(term):
                continue
            idf = math.log(1 + (len(documents) - doc_frequency[term] + 0.5) / (doc_frequency[term] + 0.5))
            tf = counts[term]
            score += idf * ((tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * doc_length / max(avg_doc_length, 1))))
        if score > 0:
            scored.append((doc, round(score, 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]


def _documents_from_vector_store(vector_store: Any) -> list[Any]:
    docstore = getattr(vector_store, "docstore", None)
    raw = getattr(docstore, "_dict", None)
    if isinstance(raw, dict):
        return list(raw.values())
    return []


def _tokenize(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u0600-\u06FF]{2,}", text or "")
        if len(token) >= 2
    ]

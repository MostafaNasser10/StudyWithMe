from src.config import TOP_K
from src.vector_store import get_vector_store


def retrieve_chunks(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    return vector_store.similarity_search(query=query, k=k)


def retrieve_chunks_with_scores(query: str, k: int = TOP_K, chat_id: str | None = None):
    vector_store = get_vector_store(chat_id)
    if vector_store is None:
        return []
    try:
        return vector_store.similarity_search_with_score(query=query, k=k)
    except Exception:
        return [(chunk, None) for chunk in vector_store.similarity_search(query=query, k=k)]


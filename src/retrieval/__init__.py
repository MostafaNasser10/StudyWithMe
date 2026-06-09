_EXPORTS = {
    "load_documents": "src.retrieval.document_loader",
    "get_embedding_model": "src.retrieval.embeddings",
    "retrieve_chunks": "src.retrieval.retriever",
    "retrieve_chunks_bm25": "src.retrieval.retriever",
    "retrieve_chunks_bm25_from_store": "src.retrieval.retriever",
    "retrieve_chunks_with_scores": "src.retrieval.retriever",
    "retrieve_chunks_with_scores_from_store": "src.retrieval.retriever",
    "split_documents": "src.retrieval.text_splitter",
    "analyze_index_changes": "src.retrieval.vector_store",
    "create_vector_store": "src.retrieval.vector_store",
    "delete_vector_store": "src.retrieval.vector_store",
    "get_vector_store": "src.retrieval.vector_store",
    "index_exists": "src.retrieval.vector_store",
    "load_index_metadata": "src.retrieval.vector_store",
    "load_manifest": "src.retrieval.vector_store",
    "load_vector_store": "src.retrieval.vector_store",
    "rebuild_all": "src.retrieval.vector_store",
    "save_index_metadata": "src.retrieval.vector_store",
    "save_manifest": "src.retrieval.vector_store",
    "save_vector_store": "src.retrieval.vector_store",
}

__all__ = [
    "analyze_index_changes",
    "create_vector_store",
    "delete_vector_store",
    "get_embedding_model",
    "get_vector_store",
    "index_exists",
    "load_documents",
    "load_index_metadata",
    "load_manifest",
    "load_vector_store",
    "rebuild_all",
    "retrieve_chunks",
    "retrieve_chunks_bm25",
    "retrieve_chunks_bm25_from_store",
    "retrieve_chunks_with_scores",
    "retrieve_chunks_with_scores_from_store",
    "save_index_metadata",
    "save_manifest",
    "save_vector_store",
    "split_documents",
]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'src.retrieval' has no attribute {name!r}")
    from importlib import import_module

    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value

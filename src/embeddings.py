from functools import lru_cache

from src.config import EMBEDDING_MODEL_NAME


@lru_cache(maxsize=1)
def get_embedding_model():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME
    )

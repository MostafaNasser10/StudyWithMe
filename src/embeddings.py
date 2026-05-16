from langchain_community.embeddings import HuggingFaceEmbeddings
from src.config import EMBEDDING_MODEL_NAME


def get_embedding_model():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME
    )
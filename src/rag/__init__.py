__all__ = ["rag_answer"]


def __getattr__(name: str):
    if name != "rag_answer":
        raise AttributeError(f"module 'src.rag' has no attribute {name!r}")
    from src.rag.pipeline import rag_answer

    globals()["rag_answer"] = rag_answer
    return rag_answer

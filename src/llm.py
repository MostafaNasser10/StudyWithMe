try:
    from langchain_ollama import ChatOllama
except ImportError:
    from langchain_community.chat_models import ChatOllama

from src.config import EVALUATOR_LLM_TEMPERATURE, EVALUATOR_OLLAMA_MODEL, OLLAMA_MODEL


def get_llm(temperature: float = 0.3, model: str | None = None):
    """
    Create and return the local chat model.

    The model runs locally through Ollama.
    """

    return ChatOllama(
        model=model or OLLAMA_MODEL,
        temperature=temperature,
    )


def get_evaluator_llm():
    return get_llm(
        temperature=EVALUATOR_LLM_TEMPERATURE,
        model=EVALUATOR_OLLAMA_MODEL or OLLAMA_MODEL,
    )


def stream_llm(prompt: str, temperature: float = 0.3):
    llm = get_llm(temperature=temperature)
    if hasattr(llm, "stream"):
        for chunk in llm.stream(prompt):
            content = getattr(chunk, "content", str(chunk))
            if content:
                yield content
        return

    content = llm.invoke(prompt).content
    for idx in range(0, len(content), 28):
        yield content[idx : idx + 28]

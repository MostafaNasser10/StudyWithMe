try:
    from langchain_ollama import ChatOllama
except ImportError:
    from langchain_community.chat_models import ChatOllama

from src.config import (
    EVALUATOR_LLM_TEMPERATURE,
    EVALUATOR_OLLAMA_MODEL,
    LLM_PROVIDER,
    LLM_REQUEST_TIMEOUT_SECONDS,
    MODEL_PROFILE_GPT4O_MINI,
    MODEL_PROFILE_LOCAL,
    MODEL_PROFILES,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


def resolve_model_profile(profile: str | None = None, provider: str | None = None, model: str | None = None) -> dict:
    if profile in MODEL_PROFILES:
        settings = dict(MODEL_PROFILES[profile])
    elif provider:
        settings = {"provider": provider, "model": model or ""}
    elif LLM_PROVIDER == "openai":
        settings = {"provider": "openai", "model": OPENAI_MODEL or "gpt-4o-mini"}
    else:
        settings = dict(MODEL_PROFILES[MODEL_PROFILE_LOCAL])

    resolved_provider = (settings.get("provider") or "ollama").strip().lower()
    if resolved_provider == "openai":
        resolved_model = model or settings.get("model") or OPENAI_MODEL or "gpt-4o-mini"
        profile_id = MODEL_PROFILE_GPT4O_MINI if resolved_model == "gpt-4o-mini" else "openai_custom"
    else:
        resolved_model = model or settings.get("model") or OLLAMA_MODEL
        profile_id = MODEL_PROFILE_LOCAL

    return {
        "profile": profile or profile_id,
        "provider": resolved_provider,
        "model": resolved_model,
        "label": settings.get("label") or f"{resolved_provider}: {resolved_model}",
    }


def model_is_configured(provider: str | None = None) -> tuple[bool, str]:
    resolved = (provider or LLM_PROVIDER or "ollama").strip().lower()
    if resolved == "openai" and not OPENAI_API_KEY:
        return False, "OPENAI_API_KEY is missing. Add it to your environment to use OpenAI gpt-4o-mini."
    return True, ""


def get_llm(
    temperature: float = 0.3,
    model: str | None = None,
    provider: str | None = None,
    profile: str | None = None,
    timeout_seconds: int | None = None,
):
    """
    Create and return the configured chat model.

    Ollama remains the default for backward compatibility. OpenAI can be selected
    per graph run with profile="openai_gpt_4o_mini".
    """

    settings = resolve_model_profile(profile=profile, provider=provider, model=model)
    if settings["provider"] == "openai":
        ok, message = model_is_configured("openai")
        if not ok:
            raise RuntimeError(message)
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("Install langchain-openai to use OpenAI models: pip install langchain-openai") from exc

        return ChatOpenAI(
            model=settings["model"],
            temperature=temperature,
            timeout=timeout_seconds or LLM_REQUEST_TIMEOUT_SECONDS,
            api_key=OPENAI_API_KEY,
        )

    return ChatOllama(model=settings["model"], temperature=temperature)


def get_evaluator_llm():
    return get_llm(
        temperature=EVALUATOR_LLM_TEMPERATURE,
        model=EVALUATOR_OLLAMA_MODEL or OLLAMA_MODEL,
        provider="ollama",
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

"""Build prompt messages with all memory layers.

This module is the single memory injection point for the graph. It combines
long-term preferences, recent messages, and embedding-retrieved chat history
before the LLM is called.
"""

from __future__ import annotations

from src.memory.chat_memory import build_relevant_context, load_recent_messages, search_relevant_history
from src.memory.preference_memory import build_preferences_context


def _format_recent_messages(messages: list[dict[str, str]]) -> str:
    """Render recent conversation messages for prompt context."""

    lines: list[str] = []
    for item in messages:
        role = "User" if item.get("role") == "user" else "Assistant"
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"{role}: {content[:900]}")
    return "\n\n".join(lines) if lines else "No recent conversation yet."


def build_memory_augmented_messages(
    session_id: str,
    current_user_prompt: str,
    system_prompt: str,
    recent_limit: int = 8,
    relevant_top_k: int = 3,
    recent_messages_override: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build the final LLM message list with all memory layers.

    Args:
        session_id:
            Chat/session identifier used for recent and relevant memory lookup.

        current_user_prompt:
            Current user message.

        system_prompt:
            Base system instruction from the graph or agent.

        recent_limit:
            Number of latest messages to include as short-term memory.

        relevant_top_k:
            Number of embedding-retrieved older messages to include.

        recent_messages_override:
            Optional recent messages from the live UI chat store. When provided,
            these messages are used for short-term memory instead of reading the
            persistent memory file.

    Returns:
        OpenAI-style role/content message dictionaries.

    Side effects:
        Reads memory files and creates one query embedding for relevant search.

    This is the only place where memory is injected into the answer prompt.

    Example:
        >>> messages = build_memory_augmented_messages("chat_1", "Explain RAG", "You are a tutor")
        >>> messages[-1]["role"]
        'user'
    """

    preferences_context = build_preferences_context()
    recent_messages = (
        recent_messages_override
        if recent_messages_override is not None
        else load_recent_messages(session_id, limit=recent_limit)
    )
    relevant_history = search_relevant_history(
        session_id=session_id,
        query=current_user_prompt,
        top_k=relevant_top_k,
    )

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": f"User Preferences:\n{preferences_context}",
        },
        {
            "role": "system",
            "content": f"Relevant Previous Chat:\n{build_relevant_context(relevant_history)}",
        },
        {
            "role": "system",
            "content": f"Recent Conversation:\n{_format_recent_messages(recent_messages)}",
        },
        {"role": "user", "content": current_user_prompt},
    ]


def render_messages_as_prompt(messages: list[dict[str, str]]) -> str:
    """Render role/content messages into a plain prompt string.

    Args:
        messages:
            Message dictionaries produced by ``build_memory_augmented_messages``.

    Returns:
        A readable prompt string with role headings and separators.

    Example:
        >>> render_messages_as_prompt([{"role": "user", "content": "Hi"}])
        'USER:\\nHi'
    """

    rendered: list[str] = []
    for item in messages:
        role = str(item.get("role") or "system").upper()
        content = str(item.get("content") or "").strip()
        if content:
            rendered.append(f"{role}:\n{content}")
    return "\n\n---\n\n".join(rendered)

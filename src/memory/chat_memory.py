"""Persistent chat-memory storage and embedding search.

This module implements the conversation-memory layer used by the graph prompt
builder. Messages are persisted per chat/session, each new message is embedded
once, and later queries can retrieve semantically related historical messages.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from src.config import DATA_DIR
from src.embeddings import get_embedding_model


MEMORY_CHAT_DIR = DATA_DIR / "memory" / "chats"
MEMORY_CHAT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_session_id(session_id: str) -> str:
    """Return a filesystem-safe session identifier."""

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or "default").strip("_")
    return cleaned or "default"


def _chat_memory_path(session_id: str) -> Path:
    """Return the JSON path that stores memory for one session."""

    return MEMORY_CHAT_DIR / f"session_{_safe_session_id(session_id)}.json"


def _now_iso() -> str:
    """Return the current UTC timestamp in a stable ISO format."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_messages(session_id: str) -> list[dict[str, Any]]:
    """Load persisted messages for a session, returning an empty list on errors."""

    path = _chat_memory_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    messages = data.get("messages") if isinstance(data, dict) else data
    return messages if isinstance(messages, list) else []


def _save_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    """Persist all memory messages for a session."""

    path = _chat_memory_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"session_id": session_id, "messages": messages}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _create_embedding(text: str) -> list[float]:
    """Create a query embedding using the project's shared embedding model."""

    embedding = get_embedding_model().embed_query(text)
    return [float(value) for value in embedding]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute cosine similarity for two equal-length embedding vectors."""

    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def save_chat_message(
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save one chat message and embed it once.

    Args:
        session_id:
            Stable chat/session identifier used to choose the memory file.

        role:
            Message role, usually ``"user"`` or ``"assistant"``.

        content:
            Message text to persist and embed.

        metadata:
            Optional structured metadata stored with the message.

    Returns:
        The saved message dictionary, including timestamp and embedding ID.

    Side effects:
        Writes to ``data/memory/chats/session_<session_id>.json``.

    If embedding creation fails, the message is still saved. Search simply skips
    messages that do not have an embedding.

    Example:
        >>> saved = save_chat_message("chat_1", "user", "Explain RAG")
        >>> saved["role"]
        'user'
    """

    messages = _load_messages(session_id)
    embedding_id = f"emb_{uuid4().hex[:12]}"
    message = {
        "role": role,
        "content": content,
        "timestamp": _now_iso(),
        "embedding_id": embedding_id,
        "metadata": metadata or {},
    }
    try:
        message["embedding"] = _create_embedding(content)
    except Exception as exc:
        message["embedding"] = None
        message["metadata"] = {**message["metadata"], "embedding_error": str(exc)[:240]}
    messages.append(message)
    _save_messages(session_id, messages)
    return message


def load_recent_messages(session_id: str, limit: int = 8) -> list[dict[str, str]]:
    """Load the latest user/assistant messages for short-term memory.

    Args:
        session_id:
            Chat/session identifier.

        limit:
            Maximum number of most recent messages to return.

    Returns:
        Role/content dictionaries ordered from oldest to newest.

    Example:
        >>> messages = load_recent_messages("chat_1", limit=2)
        >>> isinstance(messages, list)
        True
    """

    messages = _load_messages(session_id)
    recent = messages[-max(limit, 0) :]
    return [
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
        for item in recent
        if item.get("role") in {"user", "assistant"} and str(item.get("content") or "").strip()
    ]


def load_recent_message_records(session_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Load recent memory messages with metadata for routing decisions.

    Args:
        session_id:
            Chat/session identifier.

        limit:
            Maximum number of most recent messages to return.

    Returns:
        Recent message dictionaries ordered from oldest to newest. The returned
        records include role, content, timestamp, and metadata, but never expose
        embedding vectors to callers.

    Example:
        >>> records = load_recent_message_records("chat_1", limit=2)
        >>> isinstance(records, list)
        True
    """

    messages = _load_messages(session_id)
    recent = messages[-max(limit, 0) :]
    return [
        {
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or ""),
            "timestamp": str(item.get("timestamp") or ""),
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        }
        for item in recent
        if item.get("role") in {"user", "assistant"} and str(item.get("content") or "").strip()
    ]


def search_relevant_history(session_id: str, query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Search older chat memory with embedding similarity.

    Args:
        session_id:
            Chat/session identifier.

        query:
            Current user prompt used to create the query embedding.

        top_k:
            Maximum number of relevant historical messages to return.

    Returns:
        Matching memory messages ordered by descending similarity score.

    Side effects:
        Reads persisted memory and creates one query embedding.

    Example:
        >>> matches = search_relevant_history("chat_1", "Return to RAG", top_k=3)
        >>> isinstance(matches, list)
        True
    """

    messages = _load_messages(session_id)
    if not messages or not (query or "").strip():
        return []
    try:
        query_embedding = _create_embedding(query)
    except Exception:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in messages:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            continue
        score = _cosine_similarity(query_embedding, [float(value) for value in embedding])
        if score <= 0:
            continue
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "role": item.get("role"),
            "content": item.get("content"),
            "timestamp": item.get("timestamp"),
            "score": round(score, 4),
            "metadata": item.get("metadata") or {},
        }
        for score, item in scored[: max(top_k, 0)]
    ]


def build_relevant_context(messages: list[dict[str, Any]]) -> str:
    """Render retrieved memory messages as prompt-ready context.

    Args:
        messages:
            Memory records returned by ``search_relevant_history``.

    Returns:
        Human-readable context block for the LLM prompt.

    Example:
        >>> build_relevant_context([])
        'No relevant previous chat memory found.'
    """

    lines: list[str] = []
    for item in messages:
        role = "User" if item.get("role") == "user" else "Assistant"
        content = " ".join(str(item.get("content") or "").split())
        if not content:
            continue
        lines.append(f"{role}: {content[:900]}")
    return "\n\n".join(lines) if lines else "No relevant previous chat memory found."

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class FileMeta:
    file_id: str
    original_name: str
    saved_name: str
    path: str
    size_bytes: int
    extension: str
    upload_time: str
    indexing_status: str = "FILES_UPLOADED"


@dataclass
class ChatMessage:
    message_id: str
    role: str
    content: str
    created_at: str
    agent: str | None = None
    docs: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str | None = None
    evaluation_id: str | None = None


@dataclass
class ChatStats:
    prompts_count: int = 0
    created_at: str = field(default_factory=now_iso)
    total_response_time_ms: int = 0
    tokens_total: int | None = None


@dataclass
class Chat:
    chat_id: str
    title: str
    created_at: str
    updated_at: str
    files: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=lambda: asdict(ChatStats()))
    indexing_status: str = "EMPTY"
    indexing_step: str = ""


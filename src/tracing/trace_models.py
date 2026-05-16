from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.chat.chat_models import new_id, now_iso


@dataclass
class ComponentStep:
    name: str
    input_summary: str = ""
    output_summary: str = ""
    status: str = "running"
    start_time: str = field(default_factory=now_iso)
    end_time: str | None = None
    duration_ms: int | None = None
    error: str | None = None


@dataclass
class PromptTrace:
    prompt_id: str
    chat_id: str
    user_query: str
    selected_agent: str = ""
    retrieved_docs: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    component_steps: list[dict[str, Any]] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)
    final_answer: str = ""
    evaluation_result: dict[str, Any] | None = None
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def create(cls, chat_id: str, user_query: str) -> "PromptTrace":
        return cls(prompt_id=new_id("prompt"), chat_id=chat_id, user_query=user_query)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


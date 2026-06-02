from __future__ import annotations

from typing import Any, TypedDict


class StudyGraphState(TypedDict, total=False):
    chat_id: str
    user_query: str
    source_scope: str
    web_enabled: bool
    model_profile: str
    llm_provider: str
    llm_model: str

    route: str
    intent: list[str]
    tasks: list[dict[str, Any]]
    current_task_index: int
    task_outputs: dict[str, Any]
    task_results: list[dict[str, Any]]
    final_sections: list[dict[str, Any]]
    is_multi_task: bool
    active_task: dict[str, Any] | None
    needs_documents: bool
    needs_web: bool
    answer_style: str
    planned_tool_calls: list[dict[str, Any]]

    docs: list[dict[str, Any]]
    context: str
    web_sources: list[dict[str, Any]]

    tools_used: list[str]
    tool_call: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]

    selected_agent: str | None
    prompt: str | None
    raw_answer: str | None
    final_answer: str | None
    explanation_before_quiz: str | None
    reflection_enabled: bool
    critic_enabled: bool
    reflection_result: dict[str, Any] | None
    critic_result: dict[str, Any] | None
    answer_before_reflection: str | None
    answer_before_critic: str | None

    quiz: dict[str, Any] | None
    user_answers: dict[str, str] | None
    quiz_result: dict[str, Any] | None
    feedback: dict[str, Any] | None

    evaluation: dict[str, Any] | None
    trace: dict[str, Any]
    timings_ms: dict[str, int]

    error: str | None
    next_action: str | None

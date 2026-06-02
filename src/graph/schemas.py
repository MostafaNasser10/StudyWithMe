from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, validator


class QuizQuestion(BaseModel):
    id: str
    question: str
    choices: dict[str, str]
    correct_answer: str
    explanation: str
    difficulty: str
    source_refs: list[dict[str, Any]] = Field(default_factory=list)

    @validator("choices")
    def validate_choices(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"A", "B", "C", "D"}
        if set(value.keys()) != required:
            raise ValueError("choices must contain exactly A, B, C, and D")
        return value

    @validator("correct_answer")
    def validate_correct_answer(cls, value: str) -> str:
        answer = value.strip().upper()
        if answer not in {"A", "B", "C", "D"}:
            raise ValueError("correct_answer must be A, B, C, or D")
        return answer


class Quiz(BaseModel):
    quiz_id: str
    title: str
    questions: list[QuizQuestion]


class QuizSubmission(BaseModel):
    quiz_id: str
    answers: dict[str, str]


class QuizResult(BaseModel):
    quiz_id: str
    total: int
    correct: int
    percentage: float
    details: list[dict[str, Any]]
    weak_concepts: list[str]


class ToolCallRequest(BaseModel):
    """Structured LLM request for function calling.

    In real function calling, the LLM does not execute code. It only selects a
    tool name and prepares JSON arguments. Python then validates and executes
    the selected tool.
    """

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""

    @validator("tool_name")
    def validate_tool_name(cls, value: str) -> str:
        allowed = {
            "calculator",
            "document_search",
            "web_search",
            "flashcard_generator",
            "concept_extractor",
            "study_progress",
            "none",
        }
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"tool_name must be one of: {', '.join(sorted(allowed))}")
        return normalized


class ToolCallPlan(BaseModel):
    """A small plan of function tools selected by the LLM.

    One user request may need more than one tool. For example, "Calculate this
    and extract the key concepts" should execute calculator and
    concept_extractor before the normal answer node runs.
    """

    tool_calls: list[ToolCallRequest] = Field(default_factory=list)

    @validator("tool_calls")
    def validate_tool_calls(cls, value: list[ToolCallRequest]) -> list[ToolCallRequest]:
        if not value:
            return [ToolCallRequest(tool_name="none", arguments={}, reasoning="No tool required.")]

        cleaned: list[ToolCallRequest] = []
        seen: set[str] = set()
        has_real_tool = any(call.tool_name != "none" for call in value)
        for call in value:
            if has_real_tool and call.tool_name == "none":
                continue
            if call.tool_name in seen:
                continue
            cleaned.append(call)
            seen.add(call.tool_name)
            if len(cleaned) >= 4:
                break
        return cleaned or [ToolCallRequest(tool_name="none", arguments={}, reasoning="No tool required.")]


class ToolCallResponse(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    ok: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PlannerDecision(BaseModel):
    """LLM planner output for graph routing and tool selection.

    The planner chooses study tasks for LangGraph and function tools for Python
    execution in the same JSON object. Calculator, document search, and web
    search are tools, not manual graph routes.
    """

    route: str
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    selected_agent: str = ""
    needs_documents: bool = False
    needs_web: bool = False
    answer_style: str = "direct"
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)

    @validator("route")
    def validate_route(cls, value: str) -> str:
        allowed = {
            "tutor_rag",
            "summary",
            "quiz_generate",
            "study_plan",
            "web_search",
            "documents_plus_web",
            "feedback",
            "multi_task",
            "clarify",
        }
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"route must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @validator("answer_style")
    def validate_answer_style(cls, value: str) -> str:
        normalized = (value or "direct").strip().lower()
        return normalized if normalized in {"direct", "study_report"} else "direct"


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

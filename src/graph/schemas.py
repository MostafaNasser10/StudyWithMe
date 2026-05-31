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


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

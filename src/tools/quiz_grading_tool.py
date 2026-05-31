from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QuizGradingTool:
    name = "quiz_grading"

    def grade(self, quiz: dict[str, Any], user_answers: dict[str, str]) -> dict[str, Any]:
        questions = quiz.get("questions") or []
        details = []
        correct_count = 0
        weak_concepts: list[str] = []

        for question in questions:
            qid = str(question.get("id", ""))
            correct_answer = str(question.get("correct_answer", "")).strip().upper()
            user_answer = str(user_answers.get(qid, "")).strip().upper()
            is_correct = bool(user_answer) and user_answer == correct_answer
            if is_correct:
                correct_count += 1
            else:
                weak_concepts.append(str(question.get("question", qid))[:90])

            details.append(
                {
                    "question_id": qid,
                    "question": question.get("question", ""),
                    "correct": is_correct,
                    "correct_answer": correct_answer,
                    "user_answer": user_answer or None,
                    "explanation": question.get("explanation", ""),
                    "source_refs": question.get("source_refs", []) or [],
                }
            )

        total = len(questions)
        percentage = round((correct_count / total) * 100, 2) if total else 0.0
        return {
            "quiz_id": quiz.get("quiz_id", ""),
            "total": total,
            "correct": correct_count,
            "percentage": percentage,
            "details": details,
            "weak_concepts": weak_concepts,
        }

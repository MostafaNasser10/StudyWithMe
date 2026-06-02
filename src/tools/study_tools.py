from __future__ import annotations

import re
from typing import Any


def _sentences(text: str, limit: int = 6) -> list[str]:
    parts = re.split(r"(?<=[.!؟\n])\s+", (text or "").strip())
    return [part.strip() for part in parts if len(part.strip()) > 20][:limit]


class FlashcardGeneratorTool:
    name = "flashcard_generator"

    def run(self, topic: str = "", context: str = "", count: int = 5) -> dict[str, Any]:
        source = context or topic
        cards = []
        for idx, sentence in enumerate(_sentences(source, limit=count), start=1):
            cards.append(
                {
                    "front": f"ما الفكرة رقم {idx}؟",
                    "back": sentence[:260],
                }
            )
        if not cards and topic:
            cards.append({"front": f"ما معنى {topic}؟", "back": "راجع السياق المتاح ثم اكتب التعريف بكلماتك."})
        return {"flashcards": cards, "count": len(cards)}


class ConceptExtractorTool:
    name = "concept_extractor"

    def run(self, text: str = "", max_concepts: int = 8) -> dict[str, Any]:
        candidates = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u0600-\u06FF]{4,}", text or "")
        stop = {"this", "that", "with", "from", "have", "what", "when", "where", "اشرح", "الملف", "الفايل"}
        concepts: list[str] = []
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized.lower() in stop or normalized in concepts:
                continue
            concepts.append(normalized)
            if len(concepts) >= max_concepts:
                break
        return {"concepts": concepts}


class StudyProgressTool:
    name = "study_progress"

    def run(self, quiz_result: dict[str, Any] | None = None) -> dict[str, Any]:
        quiz_result = quiz_result or {}
        total = int(quiz_result.get("total") or 0)
        correct = int(quiz_result.get("correct") or 0)
        weak = list(quiz_result.get("weak_concepts") or [])
        percentage = round((correct / total) * 100, 2) if total else 0.0
        return {
            "total": total,
            "correct": correct,
            "percentage": percentage,
            "weak_concepts": weak,
            "status": "needs_review" if total and percentage < 70 else "ok",
        }

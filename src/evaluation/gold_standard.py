from __future__ import annotations

import json
from difflib import SequenceMatcher

from src.config import GOLD_STANDARDS_PATH


def load_gold_standards() -> list[dict]:
    if not GOLD_STANDARDS_PATH.exists():
        GOLD_STANDARDS_PATH.write_text("[]", encoding="utf-8")
        return []
    try:
        data = json.loads(GOLD_STANDARDS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def match_gold_standard(query: str) -> dict | None:
    best = None
    best_score = 0.0
    for item in load_gold_standards():
        score = SequenceMatcher(None, query.strip(), item.get("question", "").strip()).ratio()
        if score > best_score:
            best = item
            best_score = score
    return best if best and best_score >= 0.82 else None


def grade_against_gold(query: str, answer: str) -> dict | None:
    standard = match_gold_standard(query)
    if not standard:
        return None

    answer_lower = answer.lower()
    expected_points = standard.get("expected_points", [])
    required_structure = standard.get("required_structure", [])

    covered = [point for point in expected_points if point.lower() in answer_lower]
    structure = [heading for heading in required_structure if heading.lower() in answer_lower]

    coverage_score = round((len(covered) / max(len(expected_points), 1)) * 10, 2)
    structure_score = round((len(structure) / max(len(required_structure), 1)) * 10, 2)
    return {
        "gold_standard_id": standard.get("id"),
        "coverage_score": coverage_score,
        "structure_score": structure_score,
        "covered_points": covered,
        "matched_structure": structure,
    }


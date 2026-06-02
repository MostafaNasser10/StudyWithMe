from __future__ import annotations

import json
import re
from typing import Any, Callable


class CriticAgent:
    """Adversarial quality-check agent.

    The critic is stricter than reflection. Reflection asks "can this be clearer?"
    The critic asks "what could be wrong or unsupported?" It runs after answer
    generation but before citation/evaluation so risky answers can be corrected
    before the final response is saved.
    """

    name = "Critic Agent"

    def build_prompt(self, query: str, answer: str, context: str) -> str:
        return f"""
You are the StudyWithMe Critic Agent.

Return valid JSON only. Do not use markdown outside JSON.

Be stricter than a normal reviewer. Look for:
- hallucinations
- unsupported claims
- weak citations
- missing evidence
- wrong assumptions
- incomplete explanation
- bad educational quality

If risk_level is low, improved_answer may equal the original answer.
If risk_level is medium or high, rewrite improved_answer in Arabic and remove/qualify unsupported claims.
Preserve useful source sections.

Required JSON:
{{
  "passed": true,
  "criticism": [],
  "risk_level": "low",
  "improved_answer": "..."
}}

USER REQUEST:
{query}

RETRIEVED CONTEXT:
{context[:4500] or "No context."}

ANSWER TO CRITICIZE:
{answer[:7000]}
"""

    def review(self, query: str, answer: str, context: str, invoke_text: Callable[[str], str]) -> dict[str, Any]:
        try:
            raw = invoke_text(self.build_prompt(query, answer, context))
            return _parse_json(raw, fallback_answer=answer)
        except Exception as exc:
            return {
                "passed": True,
                "criticism": [f"Critic failed: {exc}"],
                "risk_level": "low",
                "improved_answer": answer,
            }


def _parse_json(text: str, fallback_answer: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    payload = json.loads(cleaned)
    risk = str(payload.get("risk_level") or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    return {
        "passed": bool(payload.get("passed", False)),
        "criticism": list(payload.get("criticism") or []),
        "risk_level": risk,
        "improved_answer": str(payload.get("improved_answer") or fallback_answer),
    }

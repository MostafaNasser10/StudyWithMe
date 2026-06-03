from __future__ import annotations

import json
import re
from typing import Any, Callable


class ReflectionAgent:
    """Self-review agent.

    Reflection is a gentle second pass after the answer is generated. It checks
    whether the assistant followed the user request, stayed clear for a beginner,
    used Arabic, respected retrieved context, and kept a useful structure.
    """

    name = "Reflection Agent"

    def build_prompt(self, query: str, answer: str, context: str) -> str:
        return f"""
You are the StudyWithMe Reflection Agent.

Return valid JSON only. Do not use markdown outside JSON.

Review the assistant answer before final output.
Check:
- Did it follow the user request?
- Is it clear for a beginner student?
- Is it Arabic except necessary technical terms?
- Did it use retrieved context correctly?
- Is the structure good?
- Is anything important missing?

If the answer is already good, set passed=true and repeat the same answer in improved_answer.
If it needs improvement, rewrite improved_answer in Arabic while preserving sources.

Required JSON:
{{
  "passed": true,
  "issues": [],
  "improved_answer": "..."
}}

USER REQUEST:
{query}

RETRIEVED CONTEXT:
{context[:4500] or "No context."}

ANSWER TO REVIEW:
{answer[:7000]}
"""

    def build_dimension_prompt(self, dimension: str, query: str, answer: str, context: str) -> str:
        checks = {
            "fact": "Focus only on factual grounding, source use, missing evidence, and unsupported claims.",
            "style": "Focus only on Arabic quality, beginner friendliness, structure, and study usefulness.",
            "safety": "Focus only on whether the answer follows the user request, avoids unsafe assumptions, and refuses unsupported work correctly.",
        }
        return f"""
You are one parallel reviewer inside the StudyWithMe Reflection Agent.

Return valid JSON only. Do not use markdown outside JSON.

DIMENSION:
{dimension}

CHECK INSTRUCTIONS:
{checks.get(dimension, checks["fact"])}

Required JSON:
{{
  "passed": true,
  "issues": [],
  "improved_answer": "..."
}}

USER REQUEST:
{query}

RETRIEVED CONTEXT:
{context[:3500] or "No context."}

ANSWER TO REVIEW:
{answer[:6000]}
"""

    def review(self, query: str, answer: str, context: str, invoke_text: Callable[[str], str]) -> dict[str, Any]:
        try:
            raw = invoke_text(self.build_prompt(query, answer, context))
            return _parse_json(raw, fallback_answer=answer)
        except Exception as exc:
            return {"passed": True, "issues": [f"Reflection failed: {exc}"], "improved_answer": answer}


def _parse_json(text: str, fallback_answer: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    payload = json.loads(cleaned)
    return {
        "passed": bool(payload.get("passed", False)),
        "issues": list(payload.get("issues") or []),
        "improved_answer": str(payload.get("improved_answer") or fallback_answer),
    }

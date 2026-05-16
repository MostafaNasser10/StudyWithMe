from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean

from src.arabic_guard import contains_disallowed_language
from src.chat.chat_models import new_id, now_iso
from src.evaluation.code_evaluators import deterministic_checks
from src.evaluation.gold_standard import grade_against_gold
from src.evaluation.rubric import RUBRIC_STANDARDS


@dataclass
class EvaluationResult:
    evaluation_id: str
    status: str
    overall_score: float
    rubric: dict[str, int]
    deterministic_checks: list[dict] = field(default_factory=list)
    llm_judge: dict | None = None
    gold_standard: dict | None = None
    recommendations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


def _source_summary(docs: list[dict], web_sources: list[dict]) -> str:
    lines = []
    for doc in docs[:5]:
        lines.append(f"ملف: {doc.get('source_name') or doc.get('source')} | {doc.get('location')} | {doc.get('snippet', '')[:220]}")
    for src in web_sources[:5]:
        lines.append(f"ويب: {src.get('title')} | {src.get('url')} | {src.get('snippet', '')[:220]}")
    return "\n".join(lines) or "لا توجد مصادر ملفات أو ويب."


def evaluate_response(
    query: str,
    answer: str,
    docs: list[dict],
    tools_used: list[str] | None = None,
    mode: str = "deterministic",
    web_sources: list[dict] | None = None,
) -> dict:
    tools_used = tools_used or []
    web_sources = web_sources or []
    checks = deterministic_checks(query, answer, tools_used, docs=docs, web_sources=web_sources)

    rubric = {standard: 7 for standard in RUBRIC_STANDARDS}
    check_map = {check["name"]: check for check in checks}

    rubric["Answer follows requested language"] = 10 if check_map["arabic_language"]["passed"] else 3
    rubric["Uses retrieved context"] = 9 if docs and check_map["source_grounding"]["passed"] else (7 if web_sources else 5)
    rubric["Does not hallucinate unsupported claims"] = 8 if check_map["source_grounding"]["passed"] else 5
    rubric["Clear structure"] = 9 if check_map["required_learning_structure"]["passed"] else 4
    rubric["Correct technical explanation"] = 7
    rubric["Cites sources"] = 9 if check_map["source_grounding"]["passed"] else 3
    rubric["Completeness"] = 8 if len(answer) > 500 else 5
    rubric["Conciseness according to request"] = 8 if len(answer) < 5000 else 5
    rubric["Educational usefulness"] = 9 if ("مثال" in answer and "ملخص" in answer) else 6
    rubric["Formatting quality"] = 9 if answer.count("#") >= 3 else 5

    for check in checks:
        if not check.get("passed"):
            if check["name"] in {"line_count", "word_count", "quiz_question_count"}:
                rubric["Conciseness according to request"] = min(rubric["Conciseness according to request"], 5)

    gold = grade_against_gold(query, answer)
    if gold:
        rubric["Completeness"] = round((rubric["Completeness"] + gold["coverage_score"]) / 2)
        rubric["Clear structure"] = round((rubric["Clear structure"] + gold["structure_score"]) / 2)

    recommendations = []
    if not check_map["arabic_language"]["passed"] or contains_disallowed_language(answer):
        recommendations.append("راجع اللغة: يجب أن تكون الإجابة عربية مع السماح بالمصطلحات التقنية الضرورية فقط.")
    if not check_map["required_learning_structure"]["passed"]:
        recommendations.append("أضف بنية تعليمية واضحة: مختصر، شرح، مثال، مصادر، وملخص.")
    if not check_map["source_grounding"]["passed"]:
        recommendations.append("اربط الإجابة بوضوح بمصادر الملفات أو الويب أو اذكر أنها من معرفة النموذج.")

    llm_judge = None
    if mode in {"same LLM", "evaluator LLM"}:
        try:
            if mode == "evaluator LLM":
                from src.config import EVALUATOR_LLM_ENABLED, EVALUATOR_OLLAMA_MODEL, OLLAMA_MODEL
                from src.llm import get_evaluator_llm

                if not EVALUATOR_LLM_ENABLED:
                    llm_judge = {
                        "mode": "evaluator LLM",
                        "status": "disabled",
                        "message": "Set EVALUATOR_LLM_ENABLED=true to use a separate judge model.",
                    }
                else:
                    judge_llm = get_evaluator_llm()
                    judge_model = EVALUATOR_OLLAMA_MODEL or OLLAMA_MODEL
                    llm_judge = {"mode": "evaluator LLM", "model": judge_model}
            else:
                from src.llm import get_llm

                judge_llm = get_llm(temperature=0)
                llm_judge = {"mode": "same LLM"}

            if llm_judge and "status" not in llm_judge:
                judge_prompt = f"""
قيّم الإجابة من 0 إلى 10 بناء على:
1. الالتزام بالعربية.
2. البنية التعليمية: مختصر، شرح، مثال، مصادر، ملخص.
3. دقة استخدام المصادر التالية وعدم اختراع معلومات غير مدعومة.

السؤال:
{query}

المصادر المتاحة:
{_source_summary(docs, web_sources)}

الإجابة:
{answer[:2600]}

أعد الدرجة والتعليق المختصر فقط.
"""
                judge_answer = judge_llm.invoke(judge_prompt).content
                llm_judge["comment"] = judge_answer[:1200]
        except Exception as exc:
            llm_judge = {"mode": mode, "error": str(exc)}

    overall = round(mean(rubric.values()), 2)
    return EvaluationResult(
        evaluation_id=new_id("eval"),
        status="completed",
        overall_score=overall,
        rubric=rubric,
        deterministic_checks=checks,
        llm_judge=llm_judge,
        gold_standard=gold,
        recommendations=recommendations,
    ).to_dict()


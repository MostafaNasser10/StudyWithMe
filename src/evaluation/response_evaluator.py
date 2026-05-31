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
    rubric_reasons: dict[str, str] = field(default_factory=dict)
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


def _language_reason(actual: dict | str) -> str:
    if not isinstance(actual, dict):
        return str(actual)
    reasons = [
        f"نسبة الحروف العربية: {actual.get('arabic_ratio')}.",
        f"عدد الكلمات: {actual.get('word_count')}.",
    ]
    latin_words = actual.get("disallowed_latin_words") or []
    occurrences = actual.get("disallowed_latin_occurrences") or []
    script_samples = actual.get("disallowed_script_samples") or []
    if latin_words:
        reasons.append(
            "تم تخفيض الدرجة بسبب كلمات إنجليزية غير مسموحة أو غير مفسرة عربيا: "
            + ", ".join(latin_words)
            + "."
        )
    if occurrences:
        examples = []
        for item in occurrences[:5]:
            examples.append(f"`{item.get('word')}` في: \"{item.get('context')}\"")
        reasons.append("أمثلة من النص: " + " | ".join(examples) + ".")
    if script_samples:
        reasons.append("تم رصد أحرف من كتابة غير مسموحة داخل الإجابة.")
    if not latin_words and not script_samples and actual.get("arabic_ratio", 0) >= 0.55:
        reasons.append("اللغة مناسبة ولم تظهر مشكلة واضحة.")
    return " ".join(reasons)


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

    rubric_reasons = {
        "Answer follows requested language": _language_reason(check_map["arabic_language"]["actual"]),
        "Uses retrieved context": (
            "Passed source grounding with retrieved documents."
            if docs and check_map["source_grounding"]["passed"]
            else "No file context was available or the answer did not clearly connect claims to retrieved sources."
        ),
        "Does not hallucinate unsupported claims": (
            "Source grounding passed."
            if check_map["source_grounding"]["passed"]
            else "Source grounding failed, so unsupported claims are possible."
        ),
        "Clear structure": (
            f"العناصر المطلوبة: {check_map['required_learning_structure']['expected']}. العناصر الموجودة: {check_map['required_learning_structure']['actual']}."
        ),
        "Correct technical explanation": "Deterministic evaluator keeps this neutral; use LLM judge for deeper technical scoring.",
        "Cites sources": (
            "Answer has a recognizable source section."
            if check_map["source_grounding"]["passed"]
            else f"Source check details: {check_map['source_grounding']['actual']}"
        ),
        "Completeness": f"Answer length is {len(answer)} characters.",
        "Conciseness according to request": f"Answer length is {len(answer)} characters; requested line/word/quiz checks may lower this.",
        "Educational usefulness": "Looks for an example and a study summary in the answer.",
        "Formatting quality": f"Markdown heading count: {answer.count('#')}.",
    }

    for check in checks:
        if not check.get("passed"):
            if check["name"] in {"line_count", "word_count", "quiz_question_count"}:
                rubric["Conciseness according to request"] = min(rubric["Conciseness according to request"], 5)
                rubric_reasons["Conciseness according to request"] += f" Failed {check['name']}: expected {check.get('expected')}, actual {check.get('actual')}."

    gold = grade_against_gold(query, answer)
    if gold:
        rubric["Completeness"] = round((rubric["Completeness"] + gold["coverage_score"]) / 2)
        rubric["Clear structure"] = round((rubric["Clear structure"] + gold["structure_score"]) / 2)
        rubric_reasons["Completeness"] += " Adjusted using matching gold-standard coverage."
        rubric_reasons["Clear structure"] += " Adjusted using matching gold-standard structure score."

    recommendations = []
    if not check_map["arabic_language"]["passed"] or contains_disallowed_language(answer):
        language_actual = check_map["arabic_language"]["actual"]
        bad_words = language_actual.get("disallowed_latin_words", []) if isinstance(language_actual, dict) else []
        suffix = f" الكلمات التي سببت المشكلة: {', '.join(bad_words)}." if bad_words else ""
        recommendations.append("راجع اللغة: يجب أن تكون الإجابة عربية مع السماح بالمصطلحات التقنية الضرورية فقط." + suffix)
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
        rubric_reasons=rubric_reasons,
        recommendations=recommendations,
    ).to_dict()

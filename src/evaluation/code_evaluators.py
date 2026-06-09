from __future__ import annotations

import re

from src.guardrails.arabic import contains_disallowed_language, disallowed_language_details


ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def check_arabic_language(query: str, answer: str) -> dict:
    words = re.findall(r"\S+", answer or "")
    arabic_chars = len(ARABIC_RE.findall(answer or ""))
    total_letters = len(re.findall(r"[A-Za-z\u0600-\u06FF]", answer or ""))
    arabic_ratio = arabic_chars / max(total_letters, 1)
    disallowed = contains_disallowed_language(answer)
    details = disallowed_language_details(answer)
    return {
        "name": "arabic_language",
        "passed": arabic_ratio >= 0.55 and not disallowed,
        "expected": "Arabic answer with only necessary English technical terms and file names",
        "actual": {
            "arabic_ratio": round(arabic_ratio, 2),
            "disallowed_language": disallowed,
            "word_count": len(words),
            **details,
        },
    }


def check_required_structure(query: str, answer: str) -> dict:
    text = (query or "").lower()
    has_quiz_intent = any(word in text for word in ["quiz", "اختبار", "أسئلة", "اسئلة", "كويز"])
    has_file_intent = any(
        word in text
        for word in ["summary", "summarize", "تلخيص", "لخص", "ملخص", "document", "file", "مستند", "ملف", "فايل"]
    )
    if has_quiz_intent and has_file_intent:
        required = ["نظرة عامة", "خريطة", "الشرح", "المراجع"]
    elif has_quiz_intent:
        required = ["الاختبار", "السؤال", "الإجابة", "المصادر"]
    elif any(word in text for word in ["feedback", "evaluate", "correct", "قيّم", "قيم", "صحح"]):
        required = ["النتيجة", "الصحيح", "الأخطاء", "الدليل"]
    elif any(word in text for word in ["plan", "schedule", "خطة", "جدول"]):
        required = ["الهدف", "خطة", "تمارين", "مصادر"]
    elif has_file_intent:
        required = ["نظرة عامة", "خريطة", "الشرح", "خلاصة", "المراجع"]
    else:
        required = ["الإجابة", "الشرح", "المصادر"]
    present = [heading for heading in required if heading in answer]
    return {
        "name": "required_learning_structure",
        "passed": len(present) >= min(3, len(required)),
        "expected": required,
        "actual": present,
    }


def check_source_grounding(query: str, answer: str, docs: list[dict], web_sources: list[dict] | None = None) -> dict:
    web_sources = web_sources or []
    has_source_section = any(
        marker in (answer or "")
        for marker in (
            "# قائمة المصادر",
            "# المراجع المستخدمة",
            "# المراجع",
            "# المصادر",
            "# المصدر",
            "# المصادر والدليل",
            "# الدليل من الملف",
            "# الدليل من المصادر",
        )
    )
    mentions_files = (
        "من الملفات" in answer
        or "ملفات" in answer
        or "الملف:" in answer
        or bool(docs and any((doc.get("source_name") or doc.get("source", "")) in answer for doc in docs[:3]))
    )
    mentions_web = "من الويب" in answer or "ويب" in answer or bool(
        web_sources and any(src.get("title", "") in answer for src in web_sources[:3])
    )
    mentions_model = "من النموذج" in answer

    expected = []
    if docs:
        expected.append("file sources")
    if web_sources:
        expected.append("web sources")
    if not docs and not web_sources:
        expected.append("model source label")

    passed = has_source_section and (
        (bool(docs) and mentions_files)
        or (bool(web_sources) and mentions_web)
        or (not docs and not web_sources and mentions_model)
    )
    return {
        "name": "source_grounding",
        "passed": passed,
        "expected": expected,
        "actual": {
            "has_source_section": has_source_section,
            "mentions_files": mentions_files,
            "mentions_web": mentions_web,
            "mentions_model": mentions_model,
        },
    }


def check_line_count(query: str, answer: str) -> dict | None:
    match = re.search(r"(\d+)\s*(lines|سطور|أسطر|اسطر)", query, re.IGNORECASE)
    if not match:
        return None
    expected = int(match.group(1))
    actual = len([line for line in answer.splitlines() if line.strip()])
    return {"name": "line_count", "passed": actual == expected, "expected": expected, "actual": actual}


def check_word_count(query: str, answer: str) -> dict | None:
    match = re.search(r"(\d+)\s*(words|كلمة|كلمات)", query, re.IGNORECASE)
    if not match:
        return None
    expected = int(match.group(1))
    actual = len(re.findall(r"\S+", answer))
    tolerance = max(5, round(expected * 0.15))
    return {
        "name": "word_count",
        "passed": abs(actual - expected) <= tolerance,
        "expected": expected,
        "actual": actual,
        "tolerance": tolerance,
    }


def check_quiz_count(query: str, answer: str) -> dict | None:
    if not any(word in (query or "").lower() for word in ["quiz", "اختبار", "أسئلة", "اسئلة", "كويز"]):
        return None
    expected_match = re.search(r"(\d+)", query)
    expected = int(expected_match.group(1)) if expected_match else 5
    actual = len(re.findall(r"(?:^|\n)\s*(?:\d+[\).]|# السؤال|السؤال)", answer))
    return {"name": "quiz_question_count", "passed": actual >= expected, "expected": expected, "actual": actual}


def deterministic_checks(
    query: str,
    answer: str,
    tools_used: list[str],
    docs: list[dict] | None = None,
    web_sources: list[dict] | None = None,
) -> list[dict]:
    checks = [
        check_arabic_language(query, answer),
        check_required_structure(query, answer),
        check_source_grounding(query, answer, docs or [], web_sources or []),
        check_line_count(query, answer),
        check_word_count(query, answer),
        check_quiz_count(query, answer),
    ]
    if "calculator" in tools_used:
        checks.append({"name": "calculator_used", "passed": True, "expected": "tool trace", "actual": "tool used"})
    return [check for check in checks if check is not None]

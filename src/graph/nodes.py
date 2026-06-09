from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
import random
import re
from threading import Thread
from time import perf_counter
from typing import Any, Callable

from src.guardrails.arabic import contains_disallowed_language, enforce_arabic_answer
from src.chat.chat_models import new_id, now_iso
from src.config import (
    AUTOMATIC_EXTERNAL_RAG_EVAL,
    ARABIC_GUARD_LLM_REPAIR_ENABLED,
    ARABIC_GUARD_LLM_TEMPERATURE,
    ANSWER_LLM_TEMPERATURE,
    CRITIC_LLM_TEMPERATURE,
    ENABLE_DEEPEVAL_EVAL,
    ENABLE_RAGAS_EVAL,
    FUNCTION_CALLING_LLM_TEMPERATURE,
    LLM_DEFAULT_TEMPERATURE,
    LANGSMITH_PROJECT,
    LANGSMITH_TRACING_ENABLED,
    QUALITY_AGENT_LLM_REVIEW_ENABLED,
    QUALITY_AGENT_LLM_TIMEOUT_SECONDS,
    QUIZ_FEEDBACK_LLM_TEMPERATURE,
    QUIZ_GENERATION_LLM_TEMPERATURE,
    QUIZ_REPAIR_LLM_TEMPERATURE,
    REFLECTION_LLM_TEMPERATURE,
    ROUTER_LLM_TEMPERATURE,
    STUDY_PLAN_LLM_TEMPERATURE,
    QUIZ_SYNTHETIC_FALLBACK_ENABLED,
    TOP_K,
)
from src.evaluation.rag_evaluation_service import RAGEvaluationInput, RAGEvaluationService
from src.evaluation.response_evaluator import evaluate_response
from src.graph.schemas import PlannerDecision, Quiz, ToolCallPlan, ToolCallRequest, ToolCallResponse, model_to_dict
from src.graph.state import StudyGraphState
from src.llm import get_llm, model_is_configured, resolve_model_profile
from src.memory.chat_memory import load_recent_message_records, load_recent_messages
from src.memory.memory_context_builder import build_memory_augmented_messages, render_messages_as_prompt
from src.prompts import FEEDBACK_FROM_QUIZ_PROMPT, FUNCTION_CALLING_PROMPT, QUIZ_JSON_PROMPT, ROUTER_PROMPT, STUDY_PLAN_FROM_WEAKNESS_PROMPT
from src.tools.citation_checker_tool import CitationCheckerTool
from src.tools.quiz_grading_tool import QuizGradingTool
from src.tools.tool_registry import execute_registered_tool
from src.tools.web_search_tool import WebSearchTool


GRAPH_RETRIEVAL_TIMEOUT_SECONDS = int(os.getenv("GRAPH_RETRIEVAL_TIMEOUT_SECONDS", "60"))
GRAPH_LLM_TIMEOUT_SECONDS = int(os.getenv("GRAPH_LLM_TIMEOUT_SECONDS", "180"))
GRAPH_DOCUMENT_OVERVIEW_PAGES = int(os.getenv("GRAPH_DOCUMENT_OVERVIEW_PAGES", "10"))
GRAPH_DOCUMENT_OVERVIEW_CHARS_PER_PAGE = int(os.getenv("GRAPH_DOCUMENT_OVERVIEW_CHARS_PER_PAGE", "1200"))


def _trace(state: StudyGraphState) -> dict[str, Any]:
    trace = state.get("trace") or {}
    trace.setdefault("prompt_id", new_id("prompt"))
    trace.setdefault("chat_id", state.get("chat_id", ""))
    trace.setdefault("user_query", state.get("user_query", ""))
    trace.setdefault("selected_agent", state.get("selected_agent") or "")
    trace.setdefault("retrieved_docs", state.get("docs") or [])
    trace.setdefault("tools_used", state.get("tools_used") or [])
    trace.setdefault("component_steps", [])
    trace.setdefault("timings_ms", state.get("timings_ms") or {})
    trace.setdefault("final_answer", state.get("final_answer") or "")
    trace.setdefault("evaluation_result", state.get("evaluation"))
    trace.setdefault("created_at", now_iso())
    trace["route"] = ["LangGraph", state.get("route") or ""]
    trace["web_sources"] = state.get("web_sources") or []
    return trace


def _record(state: StudyGraphState, name: str, started: float, status: str = "ok", output: str = "") -> None:
    duration_ms = round((perf_counter() - started) * 1000)
    trace = _trace(state)
    output_text = "" if output is None else str(output)
    trace["component_steps"].append(
        {
            "name": name,
            "input_summary": state.get("user_query", "")[:180],
            "output_summary": output_text[:240],
            "status": status,
            "start_time": now_iso(),
            "end_time": now_iso(),
            "duration_ms": duration_ms,
            "error": state.get("error"),
        }
    )
    timings = state.setdefault("timings_ms", {})
    timings[f"{name.lower().replace(' ', '_')}_ms"] = duration_ms
    state["trace"] = trace


def _add_tool(state: StudyGraphState, tool: str) -> None:
    tools = state.setdefault("tools_used", [])
    if tool not in tools:
        tools.append(tool)


def _run_with_timeout(func: Callable[[], Any], timeout_seconds: int, label: str) -> Any:
    queue: Queue[tuple[str, Any]] = Queue(maxsize=1)

    def worker() -> None:
        try:
            queue.put(("ok", func()))
        except Exception as exc:
            queue.put(("error", exc))

    Thread(target=worker, daemon=True).start()
    try:
        status, payload = queue.get(timeout=timeout_seconds)
    except Empty as exc:
        raise TimeoutError(f"{label} timed out after {timeout_seconds} seconds.") from exc
    if status == "error":
        raise payload
    return payload


def _llm_settings(state: StudyGraphState) -> dict[str, str]:
    return resolve_model_profile(
        profile=state.get("model_profile"),
        provider=state.get("llm_provider"),
        model=state.get("llm_model"),
    )


def _set_llm_settings(state: StudyGraphState) -> dict[str, str]:
    settings = _llm_settings(state)
    state["model_profile"] = settings["profile"]
    state["llm_provider"] = settings["provider"]
    state["llm_model"] = settings["model"]
    trace = _trace(state)
    trace["llm"] = {
        "provider": settings["provider"],
        "model": settings["model"],
        "profile": settings["profile"],
    }
    state["trace"] = trace
    return settings


def _invoke_llm(
    state: StudyGraphState,
    prompt: str,
    temperature: float | None = LLM_DEFAULT_TEMPERATURE,
    timeout_seconds: int = GRAPH_LLM_TIMEOUT_SECONDS,
) -> str:
    settings = _set_llm_settings(state)
    ok, message = model_is_configured(settings["provider"])
    if not ok:
        raise RuntimeError(message)
    return _run_with_timeout(
        lambda: get_llm(
            temperature=temperature,
            provider=settings["provider"],
            model=settings["model"],
            profile=settings["profile"],
            timeout_seconds=timeout_seconds,
        ).invoke(prompt).content,
        timeout_seconds,
        f"LLM call ({settings['provider']}:{settings['model']})",
    )


def _agent_for(route: str):
    if route == "summary":
        from src.agents.summary_agent import SummaryAgent

        return SummaryAgent()
    if route == "study_plan":
        from src.agents.study_plan_agent import StudyPlanAgent

        return StudyPlanAgent()
    if route == "web_search":
        from src.agents.web_search_agent import WebSearchAgent

        return WebSearchAgent()
    if route == "feedback":
        from src.agents.feedback_agent import FeedbackAgent

        return FeedbackAgent()
    if route == "quiz_generate":
        from src.agents.quiz_agent import QuizAgent

        return QuizAgent()
    from src.agents.tutor_agent import TutorAgent

    return TutorAgent()


TASK_AGENT_NAMES = {
    "explain": "RAG Tutor",
    "summary": "Summary",
    "quiz_generate": "Quiz",
    "study_plan": "Study Plan",
    "web_search": "Web Search",
    "quiz_feedback": "Feedback",
    "feedback": "Feedback",
    "clarify": "Input Guard",
}

TASK_SECTION_TITLES = {
    "explain": "الإجابة",
    "summary": "شرح الملف",
    "quiz_generate": "الاختبار",
    "study_plan": "خطة المذاكرة",
    "web_search": "مصادر الويب",
    "quiz_feedback": "مراجعة الاختبار",
    "feedback": "التصحيح",
    "clarify": "توضيح الطلب",
}

TASK_ROUTES = {
    "explain": "tutor_rag",
    "summary": "summary",
    "quiz_generate": "quiz_generate",
    "study_plan": "study_plan",
    "web_search": "web_search",
    "quiz_feedback": "quiz_feedback",
    "feedback": "feedback",
    "clarify": "clarify",
}


def _task_section_title(task_type: str, fallback: str | None = None) -> str:
    return TASK_SECTION_TITLES.get(task_type, fallback or task_type)


def _active_task(state: StudyGraphState) -> dict[str, Any]:
    tasks = state.get("tasks") or []
    idx = int(state.get("current_task_index") or 0)
    if 0 <= idx < len(tasks):
        return tasks[idx]
    return {}


def _execution_route(state: StudyGraphState) -> str:
    if state.get("route") == "multi_task":
        task_type = _active_task(state).get("type", "explain")
        return TASK_ROUTES.get(task_type, "tutor_rag")
    return state.get("route", "tutor_rag")


def _selected_agent_for_route(route: str) -> str:
    return {
        "summary": "Summary",
        "quiz_generate": "Quiz",
        "quiz_feedback": "Feedback",
        "feedback": "Feedback",
        "study_plan": "Study Plan",
        "web_search": "Web Search",
        "documents_plus_web": "RAG Tutor + Web Search",
        "tutor_rag": "RAG Tutor",
        "clarify": "Input Guard",
        "multi_task": "Planner",
    }.get(route, "RAG Tutor")


def _task(type_: str, title: str, **extra: Any) -> dict[str, Any]:
    item = {"type": type_, "title": title}
    item.update({key: value for key, value in extra.items() if value is not None})
    return item


def _contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _has_summary_intent(text: str, query: str) -> bool:
    return _is_document_summary_request(query) or _contains_any(text, ["summary", "summarize", "تلخيص", "لخص", "ملخص"])


def _has_study_plan_intent(text: str) -> bool:
    return _contains_any(text, ["plan", "schedule", "roadmap", "خطة", "جدول", "ذاكر"])


def _has_feedback_intent(text: str) -> bool:
    return _contains_any(text, ["feedback", "evaluate", "correct", "score", "قيّم", "قيم", "صحح", "درجة"])


def _has_current_web_intent(text: str) -> bool:
    web_request_words = [
        "latest",
        "today",
        "news",
        "current",
        "recent",
        "now",
        "web",
        "search",
        "أحدث",
        "آخر",
        "اليوم",
        "حالي",
        "الويب",
        "ابحث",
    ]
    return _contains_any(text, web_request_words)


def _has_brief_answer_request(query: str) -> bool:
    text = (query or "").lower()
    if re.search(r"\b(?:in\s+)?(?:one|two|three|\d+)\s+sentences?\b", text):
        return True
    brief_words = [
        "briefly",
        "short answer",
        "very short",
        "concise",
        "quick summary",
        "باختصار",
        "مختصر",
        "بسرعة",
        "في جملة",
        "في جملتين",
        "جملتين",
        "جملة واحدة",
        "سطرين",
        "تلخيص سريع",
    ]
    return any(word in text for word in brief_words)


def _has_explicit_document_intent(text: str) -> bool:
    doc_words = [
        "file",
        "document",
        "lecture",
        "chapter",
        "pdf",
        "my file",
        "uploaded",
        "ملف",
        "ملفي",
        "الملف",
        "فايل",
        "الفايل",
        "محاضرة",
        "الفصل",
        "المستند",
        "المرفوع",
    ]
    return _contains_any(text, doc_words)


def _is_generic_document_request(text: str) -> bool:
    tokens = re.findall(r"[a-zA-Z]+|[\u0600-\u06FF]+", (text or "").lower())
    if not tokens or len(tokens) > 3:
        return False
    generic_words = {
        "explain",
        "summarize",
        "summary",
        "اشرح",
        "اشرحلي",
        "اشرحلى",
        "لخص",
        "لخصلي",
        "لخصلى",
    }
    filler_words = {"me", "please", "لي", "لى", "ده", "دا"}
    return any(token in generic_words for token in tokens) and all(
        token in generic_words or token in filler_words for token in tokens
    )


def _requires_live_source(text: str) -> bool:
    return _has_current_web_intent(text)


def _wants_study_report(text: str, query: str) -> bool:
    study_words = [
        "study report",
        "study guide",
        "summarize",
        "summary",
        "full explanation",
        "detailed explanation",
        "explain file",
        "explain the file",
        "explain document",
        "explain the document",
        "تقرير مذاكرة",
        "دليل مذاكرة",
        "ملخص",
        "لخص",
        "تلخيص",
        "اشرح الملف",
        "اشرح ملفي",
        "اشرحلي الملف",
        "اشرحلى الملف",
        "اشرح المستند",
        "اشرحلي المستند",
        "اشرحلى المستند",
        "اشرح الفايل",
        "اشرحلي الفايل",
        "اشرحلى الفايل",
        "ذاكر",
    ]
    return _is_document_overview_query(query) or _is_generic_document_request(text) or _contains_any(text, study_words)


def _content_tokens(text: str) -> set[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "who", "what", "when", "where", "why", "how",
        "from", "with", "about", "this", "that", "and", "or", "in", "on", "of", "to", "my",
        "من", "ما", "ماذا", "متى", "أين", "كيف", "هل", "في", "من", "على", "عن", "هذا", "هذه", "هو", "هي",
    }
    tokens = re.findall(r"[a-zA-Z]{3,}|[\u0600-\u06FF]{3,}|\d{2,}", (text or "").lower())
    return {token for token in tokens if token not in stopwords}


def _docs_look_relevant(query: str, docs: list[dict[str, Any]]) -> bool:
    query_tokens = _content_tokens(query)
    if not query_tokens:
        return False
    doc_text = " ".join(
        str(doc.get("snippet") or doc.get("source_name") or doc.get("source") or "")
        for doc in (docs or [])[:5]
    )
    doc_tokens = _content_tokens(doc_text)
    if not doc_tokens:
        return False
    overlap = query_tokens & doc_tokens
    return len(overlap) >= min(2, len(query_tokens))


def _dedupe_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tasks:
        task_type = item.get("type")
        if not task_type or task_type in seen:
            continue
        deduped.append(item)
        seen.add(task_type)
    return deduped


def _task_needs_documents(task_type: str) -> bool:
    return task_type in {"explain", "summary", "quiz_generate", "study_plan", "feedback"}


def _tasks_need_documents(tasks: list[dict[str, Any]], source_scope: str) -> bool:
    if source_scope == "Web only":
        return False
    if source_scope in {"Documents only", "Documents + Web"}:
        return any(_task_needs_documents(str(task.get("type"))) for task in tasks)
    return any(_task_needs_documents(str(task.get("type"))) for task in tasks)


def _tasks_need_web(tasks: list[dict[str, Any]], source_scope: str, web_enabled: bool) -> bool:
    return source_scope == "Web only" or any(task.get("type") == "web_search" for task in tasks)


def _direct_answer(body: str, source: str = "من النموذج") -> str:
    return f"""# الإجابة
{body}

# المصدر
- {source}
"""
    return f"""# الإجابة المختصرة
{body}

# الشرح التفصيلي
هذه إجابة مباشرة من مسار الأدوات داخل النظام.

# مثال توضيحي
يمكنك طلب مثال إضافي إذا أردت تطبيق النتيجة على حالة دراسية.

# المصادر والدليل
- {source}

# ملخص للمذاكرة
- راجع النتيجة وتأكد من صياغة السؤال إذا احتجت دقة أعلى.
"""


def _brief_two_sentence_answer(answer: str) -> str:
    cleaned_lines: list[str] = []
    skip_sources = False
    for line in (answer or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if any(word in stripped for word in ("المصادر", "المراجع", "الدليل", "Source", "References")):
                skip_sources = True
            continue
        if skip_sources:
            continue
        if stripped.startswith(("-", "*", "•")):
            stripped = stripped.lstrip("-*• ").strip()
        cleaned_lines.append(stripped)

    compact = " ".join(cleaned_lines).strip()
    if not compact:
        return (answer or "").strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!؟。])\s+", compact) if part.strip()]
    if len(sentences) >= 2:
        return " ".join(sentences[:2])
    fallback_parts = [part.strip() for part in re.split(r"[؛;]\s+|\s{2,}", compact) if part.strip()]
    return " ".join(fallback_parts[:2]).strip() or compact


def _answer_style_extra(state: StudyGraphState, route: str) -> str:
    if state.get("answer_style") == "study_report" or route in {"summary", "study_plan"}:
        return """
Grounding requirements:
- Treat retrieved context as a partial view unless the context explicitly covers the whole file.
- Do not infer chapter order, document structure, lifecycle stages, or complete coverage from a few snippets.
- Prefer phrases like "حسب المقاطع المتاحة" and "تظهر المقاطع" when explaining uploaded files.
- If a point is useful background but not directly in the context, label it as "خلفية عامة" or omit it.
- Finish every markdown table completely; use bullets if there is not enough evidence for a table.
"""
    return """
Output style override:
- Do not use the study report template unless the user explicitly asks for a study report, summary, study guide, or full document explanation.
- Answer the exact question directly first.
- Use short Arabic markdown with only useful headings, for example: "# الإجابة" and "# المصادر".
- Do not add a story example, study summary, quiz-style review points, or long educational sections unless requested.
- If context is from uploaded files, cite only relevant file evidence. If context is from web, cite web sources.
"""


def _needs_web(text: str, source_scope: str, web_enabled: bool) -> bool:
    web_words = ["latest", "today", "news", "current", "recent", "web", "الويب", "أحدث", "آخر", "اليوم", "حالي"]
    return source_scope == "Web only" or (web_enabled and any(word in text for word in web_words))


def _needs_docs(text: str, source_scope: str) -> bool:
    doc_words = ["file", "document", "lecture", "chapter", "ملف", "محاضرة", "الفصل", "المستند"]
    return source_scope in {"Documents only", "Documents + Web"} or any(word in text for word in doc_words)


def _is_document_overview_query(query: str) -> bool:
    text = (query or "").lower()
    overview_words = [
        "explain the document",
        "explain document",
        "explain the file",
        "explain file",
        "explain the uploaded file",
        "summarize the document",
        "summarize document",
        "summarize the file",
        "summarize file",
        "overview",
        "اشرح الملف",
        "اشرحلي الملف",
        "اشرحلى الملف",
        "اشرح المستند",
        "اشرحلي المستند",
        "اشرحلى المستند",
        "اشرح الفايل",
        "اشرحلي الفايل",
        "اشرحلى الفايل",
        "لخص الملف",
        "لخص المستند",
        "ملخص الملف",
        "ملخص المستند",
    ]
    return any(word in text for word in overview_words)


def _is_document_summary_request(query: str) -> bool:
    text = (query or "").lower()
    return _is_document_overview_query(query) or (
        _has_explicit_document_intent(text)
        and _contains_any(text, ["summary", "summarize", "تلخيص", "لخص", "لخصلي", "لخصلى", "ملخص"])
    )


def _has_quiz_intent(text: str) -> bool:
    latin_quiz = bool(re.search(r"\b(quiz|mcq|test|questions?)\b", text))
    arabic_quiz = any(word in text for word in ["اختبر", "اختبار", "أسئلة", "اسئلة", "كويز", "امتحان", "اختبرني"])
    return latin_quiz or arabic_quiz


def _extract_arithmetic_expression(text: str) -> str | None:
    candidates = re.findall(r"[-+*/().%^ 0-9]{3,}", text or "")
    candidates = [
        candidate.strip()
        for candidate in candidates
        if any(char.isdigit() for char in candidate) and re.search(r"\d\s*[-+*/%^]\s*\d", candidate)
    ]
    return max(candidates, key=len) if candidates else None


def _has_arithmetic_request(text: str) -> bool:
    return _extract_arithmetic_expression(text) is not None


def _has_explain_intent(text: str) -> bool:
    latin_explain = bool(re.search(r"\b(explain|teach|describe|clarify)\b", text))
    arabic_explain = any(word in text for word in ["اشرح", "شرح", "فهمني", "وضح", "فسر"])
    return latin_explain or arabic_explain


def _is_follow_up_clarification(query: str) -> bool:
    """
    Detect short follow-up clarification requests that need recent chat context.

    Args:
        query: Current user message.

    Returns:
        True when the message is likely asking to clarify the previous answer.
    """
    text = " ".join((query or "").strip().lower().split())
    if not text:
        return False
    follow_up_phrases = [
        "i did not understand",
        "i don't understand",
        "i dont understand",
        "didn't understand",
        "didnt understand",
        "not clear",
        "explain more",
        "clarify more",
        "can you explain more",
        "لم افهم",
        "لم أفهم",
        "مش فاهم",
        "مش فاهمة",
        "ما فهمت",
        "مفهمتش",
        "ممكن توضح",
        "وضحلي",
        "وضح لى",
        "وضح لي",
        "اشرح اكتر",
        "اشرح أكثر",
        "فهمني",
        "مش واضح",
    ]
    return any(phrase in text for phrase in follow_up_phrases)


def _has_recent_conversation_memory(chat_id: str | None) -> bool:
    """
    Check whether a chat has an assistant answer available for short-term memory.

    Args:
        chat_id: Persistent chat/session identifier.

    Returns:
        True when recent memory contains at least one assistant message.
    """
    if not chat_id:
        return False
    try:
        recent_messages = load_recent_messages(chat_id, limit=6)
    except Exception:
        return False
    return any(
        item.get("role") == "assistant" and str(item.get("content") or "").strip()
        for item in recent_messages
    )


def _assistant_answer_is_generic_clarification(content: str) -> bool:
    """
    Detect generic clarification answers that should not become follow-up topics.

    Args:
        content: Assistant answer text.

    Returns:
        True when the answer is a generic "please clarify" response.
    """
    text = " ".join((content or "").split())
    generic_markers = [
        "أحتاج طلبا أوضح",
        "يبدو أنك لم تقدم",
        "يرجى توضيح",
        "السؤال غير محدد",
        "لا توجد مصادر متاحة لأن السؤال غير محدد",
        "تحديد السؤال أو الموضوع",
        "please clarify",
        "not specific",
    ]
    return any(marker.lower() in text.lower() for marker in generic_markers)


def _message_indicates_document_context(
    assistant: dict[str, Any],
    previous_user_query: str,
    previous_user_metadata: dict[str, Any],
) -> bool:
    """
    Decide whether a previous assistant turn was grounded in uploaded documents.

    Args:
        assistant: Assistant message record.

        previous_user_query: User request that triggered the assistant message.

        previous_user_metadata: Metadata saved with the previous user message.

    Returns:
        True when the turn appears to have used uploaded files.
    """
    assistant_metadata = assistant.get("metadata") if isinstance(assistant.get("metadata"), dict) else {}
    assistant_route = str(assistant_metadata.get("route") or previous_user_metadata.get("route") or "")
    assistant_agent = str(assistant_metadata.get("agent") or assistant.get("agent") or "")
    assistant_text = str(assistant.get("content") or "")
    docs = assistant.get("docs") if isinstance(assistant.get("docs"), list) else []
    document_markers = ("المراجع المستخدمة", "الصفحة", "ملفات", "الملف", "document_search")
    return bool(
        assistant_route in {"summary", "quiz_generate", "study_plan", "feedback"}
        or assistant_metadata.get("needs_documents")
        or previous_user_metadata.get("needs_documents")
        or assistant_metadata.get("docs_count")
        or docs
        or assistant_agent == "Summary"
        or _has_explicit_document_intent(previous_user_query.lower())
        or any(marker in assistant_text for marker in document_markers)
    )


def _recent_conversation_profile(
    chat_id: str | None,
    recent_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Summarize recent memory for follow-up routing.

    Args:
        chat_id: Persistent chat/session identifier.

        recent_records: Optional recent chat records from the UI chat store.

    Returns:
        Dictionary describing the last assistant answer, the previous user
        request, and whether that previous turn appears document-grounded.
    """
    profile: dict[str, Any] = {
        "has_assistant": False,
        "previous_user_query": "",
        "assistant_route": "",
        "document_related": False,
    }
    records = list(recent_records or [])
    if not records and chat_id:
        try:
            records = load_recent_message_records(chat_id, limit=12)
        except Exception:
            records = []
    if not records:
        return profile

    fallback_profile: dict[str, Any] | None = None
    for assistant_index in range(len(records) - 1, -1, -1):
        assistant = records[assistant_index]
        if assistant.get("role") != "assistant":
            continue
        previous_user = next(
            (
                records[idx]
                for idx in range(assistant_index - 1, -1, -1)
                if records[idx].get("role") == "user"
            ),
            {},
        )
        previous_user_query = str(previous_user.get("content") or "").strip()
        previous_user_metadata = previous_user.get("metadata") if isinstance(previous_user.get("metadata"), dict) else {}
        assistant_metadata = assistant.get("metadata") if isinstance(assistant.get("metadata"), dict) else {}
        assistant_route = str(assistant_metadata.get("route") or previous_user_metadata.get("route") or "")
        candidate = {
            "has_assistant": True,
            "previous_user_query": previous_user_query,
            "assistant_route": assistant_route,
            "document_related": _message_indicates_document_context(
                assistant,
                previous_user_query,
                previous_user_metadata,
            ),
        }
        if fallback_profile is None:
            fallback_profile = candidate
        if candidate["document_related"]:
            profile.update(candidate)
            return profile
        if not _assistant_answer_is_generic_clarification(str(assistant.get("content") or "")):
            profile.update(candidate)
            return profile

    if fallback_profile:
        profile.update(fallback_profile)
    return profile


def _looks_like_unknown_placeholder_topic(query: str) -> bool:
    """
    Detect invented placeholder topics that should ask for clarification.

    Args:
        query: Current user message.

    Returns:
        True for prompts like ``explain KKKK`` where the requested topic looks
        like a placeholder rather than a known concept.
    """
    text = (query or "").strip()
    if not _has_explain_intent(text.lower()):
        return False
    allowed_terms = {"ai", "llm", "rag", "qa", "mcq", "pdf", "faiss", "ocr", "bm25"}
    action_terms = {"explain", "clarify", "describe", "teach"}
    latin_tokens = re.findall(r"[A-Za-z]{3,12}", text)
    candidate_tokens = [
        token
        for token in latin_tokens
        if token.lower() not in allowed_terms and token.lower() not in action_terms
    ]
    if not candidate_tokens:
        return False
    for token in candidate_tokens:
        lowered = token.lower()
        if re.fullmatch(r"([a-z])\1{2,}", lowered):
            return True
        if len(lowered) <= 6 and not re.search(r"[aeiou]", lowered):
            return True
    return False


def _can_answer_from_model_knowledge(query: str) -> bool:
    """
    Decide whether a clarify route should become a normal model answer.

    Args:
        query: Current user message.

    Returns:
        True when the query has enough semantic content for a general tutor
        answer without requiring documents or web retrieval.
    """
    return not _is_low_information_query(query) and not _looks_like_unknown_placeholder_topic(query)


def _remove_document_tool_calls(decision: PlannerDecision) -> None:
    """
    Remove document-search tool calls from a planner decision in place.

    Args:
        decision: Planner decision returned by the LLM and normalized by Python.

    Side effects:
        Mutates ``decision.tool_calls``.
    """
    decision.tool_calls = [
        call for call in decision.tool_calls if call.tool_name != "document_search"
    ]


def _requested_question_count(query: str, default: int = 5) -> int:
    text = (query or "").lower()
    digit_match = re.search(r"\b(\d{1,2})\b", text)
    if digit_match:
        return max(1, min(int(digit_match.group(1)), 10))
    arabic_counts = [
        ("سؤالين", 2),
        ("سؤالان", 2),
        ("اتنين", 2),
        ("اثنين", 2),
        ("ثلاثة", 3),
        ("تلاتة", 3),
        ("أربعة", 4),
        ("اربعة", 4),
        ("خمسة", 5),
        ("سؤال", 1),
    ]
    for word, count in arabic_counts:
        if word in text:
            return count
    return default


def _is_low_information_query(query: str) -> bool:
    text = (query or "").strip().lower()
    if len(text) < 3:
        return True

    allowed_short_terms = {"ai", "llm", "rag", "qa", "mcq", "pdf", "faiss"}
    action_words = {
        "explain",
        "summarize",
        "summary",
        "quiz",
        "test",
        "plan",
        "calculate",
        "compare",
        "اشرح",
        "لخص",
        "اختبار",
        "خطة",
        "احسب",
    }
    tokens = re.findall(r"[a-zA-Z]+|[\u0600-\u06FF]+|\d+", text)
    if not tokens:
        return True
    if any(token in allowed_short_terms or token in action_words for token in tokens):
        return False
    if re.search(r"[\u0600-\u06FF]", text):
        return False
    if len(tokens) == 1 and re.fullmatch(r"[a-zA-Z]{3,6}", tokens[0]):
        return True
    if len(tokens) <= 3 and not any(len(token) > 6 for token in tokens):
        return True
    return False


def _default_task_for_route(route: str) -> dict[str, Any]:
    return {
        "summary": _task("summary", _task_section_title("summary")),
        "quiz_generate": _task("quiz_generate", _task_section_title("quiz_generate")),
        "study_plan": _task("study_plan", _task_section_title("study_plan")),
        "web_search": _task("web_search", _task_section_title("web_search")),
        "feedback": _task("feedback", _task_section_title("feedback")),
        "clarify": _task("clarify", _task_section_title("clarify")),
    }.get(route, _task("explain", _task_section_title("explain")))


def _upsert_task(tasks: list[dict[str, Any]], task_type: str, title: str, **extra: Any) -> list[dict[str, Any]]:
    updated = list(tasks or [])
    for item in updated:
        if str(item.get("type") or "") == task_type:
            item.update({key: value for key, value in extra.items() if value is not None})
            item.setdefault("title", title)
            return updated
    updated.append(_task(task_type, title, **extra))
    return updated


def _normalize_planner_tasks(tasks: list[dict[str, Any]], route: str) -> list[dict[str, Any]]:
    allowed = {"explain", "summary", "quiz_generate", "study_plan", "web_search", "quiz_feedback", "feedback", "clarify"}
    normalized: list[dict[str, Any]] = []
    for item in tasks or []:
        task_type = str(item.get("type") or "").strip().lower()
        if task_type == "calculator":
            task_type = "explain"
        if task_type not in allowed:
            continue
        title = _task_section_title(task_type)
        normalized.append(_task(task_type, title, num_questions=item.get("num_questions")))
    return _dedupe_tasks(normalized or [_default_task_for_route(route)])


def _filter_planned_tool_calls(
    tool_calls: list[ToolCallRequest],
    source_scope: str,
    web_enabled: bool,
) -> list[ToolCallRequest]:
    filtered: list[ToolCallRequest] = []
    for call in tool_calls:
        if call.tool_name == "document_search" and source_scope == "Web only":
            continue
        if call.tool_name == "web_search" and (source_scope == "Documents only" or (not web_enabled and source_scope != "Web only")):
            continue
        filtered.append(call)
    return ToolCallPlan(tool_calls=filtered).tool_calls


def _enforce_source_policy(decision: PlannerDecision, source_scope: str, web_enabled: bool, query: str = "") -> PlannerDecision:
    if source_scope == "Documents only":
        decision.needs_web = False
        if decision.route in {"web_search", "documents_plus_web"}:
            decision.route = "tutor_rag"
        decision.tasks = [task for task in decision.tasks if task.get("type") != "web_search"]
    elif source_scope == "Web only":
        if _has_explicit_document_intent((query or "").lower()):
            decision.route = "clarify"
            decision.tasks = [_task("clarify", _task_section_title("clarify"))]
            decision.needs_documents = False
            decision.needs_web = False
            decision.tool_calls = []
            return decision
        decision.needs_documents = False
        decision.needs_web = True
        if decision.route in {"tutor_rag", "summary", "quiz_generate", "study_plan", "documents_plus_web", "clarify"}:
            decision.route = "web_search"
        decision.tasks = [_task("web_search", _task_section_title("web_search"))]
        if not any(call.tool_name == "web_search" for call in decision.tool_calls):
            decision.tool_calls = [
                ToolCallRequest(
                    tool_name="web_search",
                    arguments={"query": query},
                    reasoning="Source mode is Web only, so the answer needs web results.",
                )
            ] + list(decision.tool_calls or [])
    elif source_scope == "Documents + Web" and web_enabled and decision.needs_documents:
        decision.needs_web = True
        if decision.needs_documents and not any(task.get("type") == "web_search" for task in decision.tasks):
            decision.tasks = list(decision.tasks) + [_task("web_search", "بحث الويب المرتبط بالملف")]
    return decision


def _planner_decision_from_payload(
    payload: dict[str, Any],
    query: str,
    source_scope: str,
    web_enabled: bool,
) -> PlannerDecision:
    decision = PlannerDecision(**payload)
    text = (query or "").lower()
    arithmetic_expression = _extract_arithmetic_expression(query)
    quiz_requested = _has_quiz_intent(text)
    document_summary_requested = source_scope != "Web only" and _is_document_summary_request(query)
    if document_summary_requested:
        decision.route = "summary"
        decision.tasks = [
            _task("summary", _task_section_title("summary")),
            *[
                task
                for task in decision.tasks
                if str(task.get("type") or "") not in {"explain", "summary", "clarify"}
            ],
        ]
        decision.selected_agent = "Summary"
        decision.needs_documents = True
        decision.answer_style = "direct" if _has_brief_answer_request(query) else "study_report"
        if not any(call.tool_name == "document_search" for call in decision.tool_calls):
            decision.tool_calls = [
                ToolCallRequest(
                    tool_name="document_search",
                    arguments={"query": query, "top_k": max(TOP_K, 10)},
                    reasoning="The user asked to explain the uploaded file.",
                )
            ] + list(decision.tool_calls or [])

    if quiz_requested:
        decision.tasks = _upsert_task(
            decision.tasks,
            "quiz_generate",
            _task_section_title("quiz_generate"),
            num_questions=_requested_question_count(query),
        )
        if source_scope != "Web only":
            decision.needs_documents = True

    if arithmetic_expression:
        if not quiz_requested:
            decision.tasks = [
                task
                for task in decision.tasks
                if str(task.get("type") or "") not in {"quiz_generate", "clarify"}
            ]
            if decision.route in {"quiz_generate", "clarify"}:
                decision.route = "tutor_rag"
                decision.selected_agent = "RAG Tutor"
                decision.needs_documents = bool(document_summary_requested)
                decision.needs_web = False
                decision.answer_style = "direct"
            if not decision.tasks:
                decision.tasks = [_task("explain", _task_section_title("explain"))]
        if not any(call.tool_name == "calculator" for call in decision.tool_calls):
            decision.tool_calls = [
                ToolCallRequest(
                    tool_name="calculator",
                    arguments={"expression": arithmetic_expression},
                    reasoning="The user requested an arithmetic calculation.",
                )
            ] + list(decision.tool_calls or [])
    decision.tasks = _normalize_planner_tasks(decision.tasks, decision.route)
    if len(decision.tasks) > 1:
        decision.route = "multi_task"
    decision.needs_documents = bool(decision.needs_documents and source_scope != "Web only")
    decision.needs_web = bool(decision.needs_web and web_enabled and source_scope != "Documents only")
    decision = _enforce_source_policy(decision, source_scope, web_enabled, query)
    decision.tasks = _normalize_planner_tasks(decision.tasks, decision.route)
    if len(decision.tasks) > 1 and decision.route not in {"documents_plus_web"}:
        decision.route = "multi_task"
    elif len(decision.tasks) == 1 and decision.route == "multi_task":
        only = str((decision.tasks[0] or {}).get("type") or "explain")
        decision.route = "tutor_rag" if only == "explain" else TASK_ROUTES.get(only, "tutor_rag")
    general_knowledge_query = (
        source_scope != "Web only"
        and decision.route in {"clarify", "tutor_rag"}
        and not document_summary_requested
        and not quiz_requested
        and not _has_explicit_document_intent(text)
        and not _requires_live_source(text)
        and _can_answer_from_model_knowledge(query)
    )
    if general_knowledge_query:
        decision.route = "tutor_rag"
        decision.selected_agent = "RAG Tutor"
        decision.tasks = [_task("explain", _task_section_title("explain"))]
        decision.needs_documents = False
        decision.needs_web = False
        decision.answer_style = "direct"
        _remove_document_tool_calls(decision)
    decision.tool_calls = _filter_planned_tool_calls(decision.tool_calls, source_scope, web_enabled)
    if decision.route == "multi_task":
        decision.selected_agent = "Planner"
    if not decision.selected_agent:
        decision.selected_agent = _selected_agent_for_route(decision.route)
    return decision


def router_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    settings = _set_llm_settings(state)
    source_scope = state.get("source_scope", "Documents only")
    web_enabled = bool(state.get("web_enabled"))
    prompt = f"""
{ROUTER_PROMPT}

USER QUERY:
{state.get("user_query", "")}

SOURCE MODE:
{source_scope}

WEB ENABLED:
{web_enabled}

HAS ACTIVE QUIZ:
{bool(state.get("quiz"))}

HAS SUBMITTED QUIZ ANSWERS:
{state.get("user_answers") is not None}
"""
    try:
        raw = _invoke_llm(state, prompt, temperature=ROUTER_LLM_TEMPERATURE, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 25))
        decision = _planner_decision_from_payload(_json_from_text(raw), state.get("user_query", ""), source_scope, web_enabled)
    except Exception as exc:
        state["error"] = str(exc)
        fallback_payload = {
            "route": "clarify",
            "tasks": [_task("clarify", "تعذر التخطيط")],
            "selected_agent": "Input Guard",
            "needs_documents": False,
            "needs_web": False,
            "answer_style": "direct",
            "tool_calls": [
                {
                    "tool_name": "none",
                    "arguments": {},
                    "reasoning": "Planner LLM failed.",
                }
            ],
        }
        decision = _planner_decision_from_payload(
            fallback_payload,
            state.get("user_query", ""),
            source_scope,
            web_enabled,
        )

    recent_profile = _recent_conversation_profile(
        state.get("chat_id"),
        state.get("recent_chat_messages") if isinstance(state.get("recent_chat_messages"), list) else None,
    )
    if decision.route in {"clarify", "tutor_rag"} and _is_follow_up_clarification(state.get("user_query", "")) and recent_profile["has_assistant"]:
        retrieval_query = recent_profile.get("previous_user_query") or state.get("user_query", "")
        needs_documents_for_follow_up = bool(recent_profile.get("document_related") and source_scope != "Web only")
        decision.route = "tutor_rag"
        decision.selected_agent = "RAG Tutor"
        decision.tasks = [_task("explain", _task_section_title("explain"))]
        decision.needs_documents = needs_documents_for_follow_up
        decision.needs_web = False
        decision.answer_style = "direct"
        decision.tool_calls = [
            ToolCallRequest(
                tool_name="document_search",
                arguments={"query": retrieval_query, "top_k": TOP_K},
                reasoning="The user is clarifying a previous document-grounded answer.",
            )
        ] if needs_documents_for_follow_up else []
        state["retrieval_query"] = retrieval_query
        state.setdefault("trace", {})["follow_up"] = {
            "detected": True,
            "previous_user_query": retrieval_query,
            "previous_route": recent_profile.get("assistant_route"),
            "needs_documents": needs_documents_for_follow_up,
        }

    route = decision.route
    tasks = decision.tasks
    state.setdefault("task_outputs", {})
    state.setdefault("task_results", [])
    state.setdefault("final_sections", [])
    state.update(
        {
            "route": route,
            "selected_agent": decision.selected_agent or _selected_agent_for_route(route),
            "intent": [str(task.get("type")) for task in tasks],
            "tasks": tasks,
            "current_task_index": 0,
            "is_multi_task": route == "multi_task",
            "needs_documents": decision.needs_documents,
            "needs_web": decision.needs_web,
            "answer_style": decision.answer_style,
            "planned_tool_calls": [model_to_dict(call) for call in decision.tool_calls],
            "next_action": None,
        }
    )
    trace = _trace(state)
    trace["planner"] = {
        "route": route,
        "tasks": tasks,
        "needs_documents": decision.needs_documents,
        "needs_web": decision.needs_web,
        "answer_style": decision.answer_style,
        "planned_tool_calls": state.get("planned_tool_calls") or [],
    }
    state["trace"] = trace
    if route == "clarify":
        clarify_body = (
            "أنت في وضع الويب فقط، لذلك لا أستطيع قراءة الملفات المرفوعة في هذا السؤال. غيّر وضع المصادر إلى المستندات فقط أو المستندات مع الويب إذا كنت تريد شرح الملف."
            if source_scope == "Web only"
            else "أحتاج طلبا أوضح أو وضع مصادر مناسب قبل أن أبدأ. اكتب مثلا: اشرح الملف، اعمل اختبارا من المحاضرة، أو فعّل الويب إذا كان السؤال عن معلومة حديثة."
        )
        state["final_answer"] = _direct_answer(
            clarify_body,
            "مخطط سير العمل",
        )
        state["next_action"] = "final"
    _record(
        state,
        "Planner",
        started,
        status="error" if state.get("error") else "ok",
        output=f"{route} | tasks={len(tasks)} | tools={len(state.get('planned_tool_calls') or [])} | {settings['provider']}:{settings['model']}",
    )
    return state


def _tool_call_to_context(tool_name: str, result: dict[str, Any]) -> str:
    payload = result.get("result") or {}
    if tool_name == "calculator":
        if payload.get("ok"):
            return f"FUNCTION TOOL RESULT - calculator:\nExpression: {payload.get('expression')}\nResult: {payload.get('result')}"
        return f"FUNCTION TOOL RESULT - calculator error:\n{payload.get('error')}"
    if tool_name == "document_search":
        return str(payload.get("context") or "")
    if tool_name == "web_search":
        rows = []
        for idx, item in enumerate(payload.get("results") or [], start=1):
            rows.append(
                f"[Function Web {idx}]\nTitle: {item.get('title')}\nURL: {item.get('url')}\nSnippet: {item.get('snippet')}"
            )
        return "\n\n".join(rows)
    if tool_name == "flashcard_generator":
        return "FUNCTION TOOL RESULT - flashcards:\n" + json.dumps(payload, ensure_ascii=False)
    if tool_name == "concept_extractor":
        return "FUNCTION TOOL RESULT - concepts:\n" + ", ".join(payload.get("concepts") or [])
    if tool_name == "study_progress":
        return "FUNCTION TOOL RESULT - study progress:\n" + json.dumps(payload, ensure_ascii=False)
    return ""


def _calculator_result_section(state: StudyGraphState, answer: str) -> str:
    sections: list[str] = []
    for item in state.get("tool_results") or []:
        if item.get("tool_name") != "calculator" or not item.get("ok"):
            continue
        payload = item.get("result") or {}
        if not payload.get("ok"):
            continue
        result_text = str(payload.get("result"))
        if result_text and result_text in (answer or ""):
            continue
        expression = str(payload.get("expression") or "").strip()
        sections.append(
            "\n".join(
                [
                    "## نتيجة الحساب",
                    f"- العملية: `{expression}`",
                    f"- الناتج: `{result_text}`",
                ]
            )
        )
    return "\n\n".join(sections)


def tool_calling_node(state: StudyGraphState) -> StudyGraphState:
    """LLM function-calling learning node.

    Function Calling is different from LangGraph routing:
    - The router chooses the high-level workflow path, such as summary, quiz, or RAG.
    - Function calling lets the LLM select one small capability/tool inside that path.

    The LLM never executes tools. It returns structured JSON saying which tool it
    wants and which arguments to pass. Python validates the JSON, executes the
    actual tool, then stores the result in state and appends useful output to
    `state["context"]` so the later answer node can use it.
    """

    started = perf_counter()
    route = state.get("route")
    planned_tool_calls = state.get("planned_tool_calls") or []
    if planned_tool_calls:
        plan = ToolCallPlan(tool_calls=[ToolCallRequest(**call) for call in planned_tool_calls])
        plan.tool_calls = _filter_planned_tool_calls(
            plan.tool_calls,
            state.get("source_scope", "Documents only"),
            bool(state.get("web_enabled")),
        )
    elif route in {"clarify"} or state.get("next_action") == "final":
        plan = ToolCallPlan(
            tool_calls=[
                ToolCallRequest(tool_name="none", arguments={}, reasoning="No function tool is needed for this graph route.")
            ]
        )
    else:
        # This is the "function calling" LLM step: ask for JSON only. The model
        # is not trusted to run code or touch files; it only chooses a tool.
        prompt = f"""
{FUNCTION_CALLING_PROMPT}

USER QUERY:
{state.get("user_query", "")}

SOURCE MODE:
{state.get("source_scope", "Documents only")}

WEB ENABLED:
{bool(state.get("web_enabled"))}

CURRENT ROUTE:
{state.get("route")}

AVAILABLE CONTEXT PREVIEW:
{(state.get("context") or "")[:1200]}
"""
        try:
            raw = _invoke_llm(state, prompt, temperature=FUNCTION_CALLING_LLM_TEMPERATURE, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 20))
            payload = _json_from_text(raw)
            if "tool_calls" in payload:
                plan = ToolCallPlan(**payload)
            else:
                plan = ToolCallPlan(tool_calls=[ToolCallRequest(**payload)])
            plan.tool_calls = _filter_planned_tool_calls(
                plan.tool_calls,
                state.get("source_scope", "Documents only"),
                bool(state.get("web_enabled")),
            )
        except Exception as exc:
            # No hidden deterministic fallback here: this feature is meant to
            # teach real function calling, so tool choice belongs to the LLM.
            # If the LLM cannot provide valid JSON, Python chooses no tool and
            # records the reason for observability.
            state.setdefault("trace", {})["function_calling_error"] = str(exc)
            plan = ToolCallPlan(
                tool_calls=[
                    ToolCallRequest(
                        tool_name="none",
                        arguments={},
                        reasoning=f"LLM tool selection failed: {str(exc)[:160]}",
                    )
                ]
            )

    # Python executes the selected tool. This is the core safety boundary:
    # LLM chooses intent; application code validates and performs the action.
    call_dicts: list[dict[str, Any]] = []
    response_dicts: list[dict[str, Any]] = []
    context_chunks: list[str] = []
    calls = list(plan.tool_calls)
    tool_results_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(calls), 4))) as executor:
        futures = {
            executor.submit(execute_registered_tool, call.tool_name, call.arguments, dict(state)): idx
            for idx, call in enumerate(calls)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                tool_results_by_index[idx] = future.result()
            except Exception as exc:
                tool_results_by_index[idx] = {
                    "ok": False,
                    "useful": False,
                    "result": {},
                    "error": str(exc),
                }

    for idx, call in enumerate(calls):
        result = tool_results_by_index.get(idx) or {"ok": False, "useful": False, "result": {}, "error": "Tool did not return."}
        response = ToolCallResponse(
            tool_name=call.tool_name,
            arguments=call.arguments,
            reasoning=call.reasoning,
            ok=bool(result.get("ok")),
            result=result.get("result") or {},
            error=result.get("error"),
        )
        call_dicts.append(model_to_dict(call))
        response_dicts.append(model_to_dict(response))
        if call.tool_name != "none":
            _add_tool(state, f"function:{call.tool_name}")

        # Tool outputs are stored in graph state for observability and future nodes.
        # When useful, they are also injected into context so the normal prompt/LLM
        # answer path can cite or use them without changing the existing agents.
        if call.tool_name == "document_search" and result.get("useful"):
            payload = result.get("result") or {}
            state["docs"] = payload.get("docs") or state.get("docs") or []
            state["retrieval_breakdown"] = payload.get("breakdown") or state.get("retrieval_breakdown") or {}
        if call.tool_name == "web_search" and result.get("useful"):
            payload = result.get("result") or {}
            state["web_sources"] = payload.get("results") or state.get("web_sources") or []

        context_addition = _tool_call_to_context(call.tool_name, result)
        if context_addition.strip():
            context_chunks.append(context_addition)

    state["tool_calls"] = call_dicts
    state["tool_results"] = response_dicts
    state["tool_call"] = call_dicts[0] if len(call_dicts) == 1 else {"tool_calls": call_dicts}
    state["tool_result"] = response_dicts[0] if len(response_dicts) == 1 else {"tool_results": response_dicts}

    if context_chunks:
        base_context = state.get("context") or ""
        state["context"] = f"{base_context}\n\nFUNCTION CALL CONTEXT:\n" + "\n\n".join(context_chunks)
        state["context"] = state["context"].strip()

    selected = ", ".join(call.get("tool_name", "none") for call in call_dicts) or "none"
    reasons = "; ".join(call.get("reasoning", "") for call in call_dicts if call.get("reasoning"))
    _record(state, "Function Calling", started, output=f"{selected}: {reasons}")
    return state


def task_dispatcher_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    tasks = state.get("tasks") or []
    idx = int(state.get("current_task_index") or 0)
    if idx >= len(tasks):
        state["active_task"] = None
        state["next_action"] = "compose_final"
        _record(state, "Task Dispatcher", started, output="all tasks complete")
        return state

    task = tasks[idx]
    task_type = str(task.get("type") or "explain")
    route = TASK_ROUTES.get(task_type, "tutor_rag")
    state["active_task"] = task
    state["selected_agent"] = TASK_AGENT_NAMES.get(task_type, _selected_agent_for_route(route))
    state["prompt"] = None
    state["raw_answer"] = None
    state["final_answer"] = None
    state["error"] = None
    if task_type != "quiz_generate":
        state["next_action"] = None
    _record(state, "Task Dispatcher", started, output=f"{idx + 1}/{len(tasks)} {task_type}")
    return state


def collect_task_output_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    task = state.get("active_task") or _active_task(state)
    task_type = str(task.get("type") or "explain")
    idx = int(state.get("current_task_index") or 0)
    title = _task_section_title(task_type)

    content = (state.get("final_answer") or state.get("raw_answer") or "").strip()
    section: dict[str, Any] = {"title": title, "type": task_type, "content": content}
    if task_type == "quiz_generate" and state.get("quiz"):
        section["quiz"] = state.get("quiz")
    if task_type == "web_search" and state.get("web_sources"):
        section["web_sources"] = state.get("web_sources")
        if not content:
            lines = ["تم جلب مصادر الويب التالية:"]
            for item in state.get("web_sources") or []:
                lines.append(f"- {item.get('title')} | {item.get('url')}")
            section["content"] = "\n".join(lines)

    sections = state.setdefault("final_sections", [])
    sections.append(section)
    key = f"{idx + 1}_{task_type}"
    state.setdefault("task_outputs", {})[key] = section
    state.setdefault("task_results", []).append(
        {
            "index": idx,
            "type": task_type,
            "title": title,
            "status": "error" if state.get("error") else "ok",
            "docs": len(state.get("docs") or []),
            "web_sources": len(state.get("web_sources") or []),
            "tools_used": list(state.get("tools_used") or []),
        }
    )

    if task_type == "explain" and content:
        context = state.get("context") or ""
        state["context"] = f"{context}\n\nPREVIOUS EXPLANATION:\n{content}".strip()

    state["current_task_index"] = idx + 1
    _record(state, "Collect Task Output", started, output=f"{task_type} saved")
    return state


def parallel_agents_node(state: StudyGraphState) -> StudyGraphState:
    """Run independent planned tasks in parallel.

    LangGraph routing decides the workflow shape. This node is the parallel
    execution layer for multi-task prompts: each task receives the same retrieved
    context, runs in its own state copy, and returns a section. The original
    task order is restored before final composition so the UI remains stable.
    """

    started = perf_counter()
    tasks = state.get("tasks") or []
    if len(tasks) <= 1:
        _record(state, "Parallel Agents", started, output="single task skipped")
        return task_dispatcher_node(state)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as executor:
        futures = {
            executor.submit(_run_parallel_task, state, idx, task): idx
            for idx, task in enumerate(tasks)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                idx = futures[future]
                task = tasks[idx] or {}
                results.append(
                    {
                        "index": idx,
                        "type": str(task.get("type") or "unknown"),
                        "title": str(task.get("title") or "Task"),
                        "status": "error",
                        "content": _direct_answer("تعذر تنفيذ هذا الجزء من الطلب.", "Parallel Agents"),
                        "error": str(exc),
                    }
                )

    results.sort(key=lambda item: int(item.get("index") or 0))
    sections: list[dict[str, Any]] = []
    task_outputs: dict[str, Any] = {}
    task_results: list[dict[str, Any]] = []
    for result in results:
        section = {
            "title": result.get("title"),
            "type": result.get("type"),
            "content": result.get("content") or "",
        }
        if result.get("quiz"):
            section["quiz"] = result.get("quiz")
            state["quiz"] = result.get("quiz")
        if result.get("web_sources"):
            section["web_sources"] = result.get("web_sources")
            state["web_sources"] = result.get("web_sources") or state.get("web_sources") or []
        sections.append(section)
        key = f"{int(result.get('index') or 0) + 1}_{result.get('type')}"
        task_outputs[key] = section
        task_results.append(
            {
                "index": result.get("index"),
                "type": result.get("type"),
                "title": result.get("title"),
                "status": result.get("status", "ok"),
                "parallel": True,
            }
        )

    state["final_sections"] = sections
    state["task_outputs"] = task_outputs
    state["task_results"] = task_results
    state["parallel_agent_results"] = results
    state["current_task_index"] = len(tasks)
    state["selected_agent"] = "Parallel Agents"
    state["next_action"] = "compose_final"
    state.setdefault("trace", {})["parallel_agent_results"] = results
    _record(state, "Parallel Agents", started, output=f"tasks={len(tasks)}")
    return state


def _run_parallel_task(state: StudyGraphState, idx: int, task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("type") or "explain")
    title = _task_section_title(task_type)
    task_state: StudyGraphState = {
        **dict(state),
        "active_task": task,
        "current_task_index": idx,
        "prompt": None,
        "raw_answer": None,
        "final_answer": None,
        "error": None,
    }

    if task_type in {"explain", "feedback", "summary"}:
        task_state = build_prompt_node(task_state)
        task_state = summary_node(task_state) if task_type == "summary" else tutor_answer_node(task_state)
    elif task_type == "quiz_generate":
        task_state = quiz_generation_node(task_state)
    elif task_type == "study_plan":
        task_state = study_plan_node(task_state)
    elif task_type == "web_search":
        if not task_state.get("web_sources"):
            task_state = web_search_node(task_state)
        if task_state.get("web_sources") and not task_state.get("final_answer"):
            lines = ["تم جلب مصادر الويب التالية:"]
            for item in task_state.get("web_sources") or []:
                lines.append(f"- {item.get('title')} | {item.get('url')}")
            task_state["final_answer"] = "\n".join(lines)
    elif task_type == "clarify":
        task_state["final_answer"] = _direct_answer("أحتاج طلبا أوضح قبل تنفيذ هذا الجزء.", "مخطط سير العمل")

    return {
        "index": idx,
        "type": task_type,
        "title": title,
        "status": "error" if task_state.get("error") else "ok",
        "content": (task_state.get("final_answer") or task_state.get("raw_answer") or "").strip(),
        "quiz": task_state.get("quiz"),
        "web_sources": task_state.get("web_sources") or [],
        "error": task_state.get("error"),
    }


def final_composer_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    sections = state.get("final_sections") or []
    if not sections:
        state["final_answer"] = state.get("final_answer") or ""
        _record(state, "Final Composer", started, output="single direct answer")
        return state

    parts: list[str] = []
    for section in sections:
        section_type = str(section.get("type") or "")
        title = _task_section_title(section_type, str(section.get("title") or "القسم"))
        content = str(section.get("content") or "").strip()
        if section.get("quiz"):
            question_count = len((section.get("quiz") or {}).get("questions") or [])
            content = f"تم إنشاء اختبار تفاعلي من {question_count} أسئلة. اختر الإجابات ثم اضغط زر الإرسال."
        if not content:
            continue
        parts.append(f"# {title}\n{content}")
    composed = "\n\n".join(parts).strip()
    calculator_section = _calculator_result_section(state, composed)
    if calculator_section:
        composed = f"{composed}\n\n# الحساب\n{calculator_section}".strip()
    state["final_answer"] = composed
    if state.get("quiz"):
        state["next_action"] = "await_quiz_submission"
    else:
        state["next_action"] = "final"
    _record(state, "Final Composer", started, output=f"sections={len(sections)}")
    return state


def _retrieval_query(state: StudyGraphState) -> str:
    """
    Return the query that should be used for document/web retrieval.

    Args:
        state: Current graph state.

    Returns:
        The explicit retrieval query for follow-ups, otherwise the current user
        query.
    """
    return str(state.get("retrieval_query") or state.get("user_query") or "")


def retrieve_docs_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    retrieval_breakdown: dict[str, Any] = {
        "parallel": True,
        "document_search": {},
        "web_search": {"enabled": False, "status": "skipped"},
    }
    try:
        retrieval_query = _retrieval_query(state)

        def search_docs():
            from src.tools.document_search_tool import DocumentSearchTool

            top_k = max(TOP_K, 10) if _is_document_summary_request(retrieval_query) else TOP_K
            return DocumentSearchTool().search(
                retrieval_query,
                chat_id=state.get("chat_id"),
                top_k=top_k,
                bm25_enabled=bool(state.get("bm25_enabled")),
            )

        def search_web():
            query = _document_grounded_web_query(state)
            result = WebSearchTool().search(query)
            return query, result

        jobs: dict[str, Callable[[], Any]] = {"document_search": search_docs}
        should_search_web = bool(
            state.get("needs_web")
            and state.get("web_enabled")
            and state.get("source_scope") != "Documents only"
        )
        if should_search_web:
            jobs["web_search"] = search_web
            retrieval_breakdown["web_search"] = {"enabled": True, "status": "running"}

        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            futures = {executor.submit(func): name for name, func in jobs.items()}
            for future in as_completed(futures, timeout=GRAPH_RETRIEVAL_TIMEOUT_SECONDS):
                name = futures[future]
                results[name] = future.result()

        result = results["document_search"]
        state["docs"] = result.docs
        state["context"] = result.context
        state.setdefault("timings_ms", {})["document_search_ms"] = result.timing_ms
        retrieval_breakdown["document_search"] = result.breakdown

        if "web_search" in results:
            query, web_result = results["web_search"]
            state.setdefault("trace", {})["web_search_query"] = query[:1600]
            state["web_sources"] = web_result.get("results") or []
            _add_tool(state, "web_search")
            web_context = "\n\n".join(
                f"[ويب {idx}]\nTitle: {item.get('title')}\nURL: {item.get('url')}\nProvider: {item.get('provider')}\nSnippet: {item.get('snippet')}"
                for idx, item in enumerate(state["web_sources"], start=1)
            )
            if web_context:
                state["context"] = f"{state.get('context') or ''}\n\nWEB CONTEXT:\n{web_context}".strip()
            retrieval_breakdown["web_search"] = {
                "enabled": True,
                "status": "ok" if web_result.get("available") else "unavailable",
                "results": len(state.get("web_sources") or []),
                "provider": web_result.get("provider"),
            }
        if _is_document_summary_request(retrieval_query):
            sample_context, sample_docs = _sample_uploaded_documents(
                state.get("chat_id"),
                max_docs=GRAPH_DOCUMENT_OVERVIEW_PAGES,
                max_chars=GRAPH_DOCUMENT_OVERVIEW_CHARS_PER_PAGE,
            )
            if sample_docs:
                state["docs"] = sample_docs
                state["context"] = sample_context
        if not state["docs"] and state.get("route") in {"quiz_generate", "summary", "tutor_rag"}:
            sample_context, sample_docs = _sample_uploaded_documents(state.get("chat_id"))
            if sample_docs:
                state["docs"] = sample_docs
                state["context"] = sample_context
    except Exception as exc:
        state["docs"] = []
        state["context"] = ""
        state["error"] = str(exc)
        retrieval_breakdown["error"] = str(exc)
    _add_tool(state, "document_search")
    if state.get("bm25_enabled"):
        _add_tool(state, "bm25_search")
    state["retrieval_breakdown"] = retrieval_breakdown
    state.setdefault("trace", {})["retrieval_breakdown"] = retrieval_breakdown

    if state.get("source_scope") == "Documents only" and not state.get("docs") and state.get("route") != "quiz_generate":
        state["final_answer"] = _direct_answer(
            "لم أستطع استرجاع مقاطع من المستندات الآن. قد لا توجد مستندات مفهرسة، أو أن تحميل الفهرس استغرق وقتا أطول من المهلة. جرّب تحديث الفهرس ثم أعد السؤال.",
            "حالة قاعدة المعرفة",
        )
        state["next_action"] = "final"
    elif (
        state.get("source_scope") == "Documents only"
        and state.get("route") != "quiz_generate"
        and state.get("answer_style") == "direct"
        and not _has_explicit_document_intent(_retrieval_query(state).lower())
        and not _docs_look_relevant(_retrieval_query(state), state.get("docs") or [])
    ):
        state["final_answer"] = _direct_answer(
            "لم أجد دليلا واضحا في المستندات الحالية يربط سؤالك بمحتوى الملفات، والبحث في الويب غير مستخدم في وضع Documents only. غيّر Source mode إلى Web only أو Documents + Web إذا كان السؤال عاما أو حديثا.",
            "سياسة اختيار المصادر",
        )
        state["next_action"] = "final"
    _record(
        state,
        "Document Search",
        started,
        status="error" if state.get("error") else "ok",
        output=f"docs={len(state.get('docs') or [])}, bm25={bool(state.get('bm25_enabled'))}, web={retrieval_breakdown.get('web_search', {}).get('status')}",
    )
    return state


def _sample_uploaded_documents(chat_id: str | None, max_docs: int = 4, max_chars: int = 900) -> tuple[str, list[dict[str, Any]]]:
    try:
        from pathlib import Path

        from src.retrieval.document_loader import load_documents
    except Exception:
        return "", []

    try:
        loaded_docs = load_documents(chat_id=chat_id)
    except Exception:
        return "", []

    docs: list[dict[str, Any]] = []
    context_parts: list[str] = []
    for idx, doc in enumerate(loaded_docs[:max_docs], start=1):
        source = doc.metadata.get("source", "Unknown source")
        source_name = doc.metadata.get("file_name") or Path(source).name
        location = f"الصفحة {doc.metadata.get('page')}" if doc.metadata.get("page") is not None else "بداية المستند"
        snippet = (doc.page_content or "").strip()[:max_chars]
        if not snippet:
            continue
        docs.append(
            {
                "rank": idx,
                "title": f"{source_name} | {location}",
                "source": source,
                "source_name": source_name,
                "location": location,
                "page": doc.metadata.get("page"),
                "line": doc.metadata.get("line"),
                "score": "sample",
                "snippet": snippet,
            }
        )
        context_parts.append(
            f"[المقطع {idx}]\nFile: {source_name}\nLocation: {location}\nSimilarity score: sample\nContent:\n{snippet}"
        )
    return "\n\n".join(context_parts), docs


def _document_grounded_web_query(state: StudyGraphState) -> str:
    user_query = _retrieval_query(state).strip()
    context = (state.get("context") or "").strip()
    if not context:
        context = "\n".join(str(doc.get("snippet") or "") for doc in (state.get("docs") or [])[:4]).strip()
    if state.get("source_scope") == "Documents + Web" and context:
        compact_context = re.sub(r"\s+", " ", context)[:1200]
        return (
            f"{user_query}\n\n"
            "Search for external information that is specifically related to this uploaded document content. "
            "Do not search the generic wording of the user request alone.\n"
            f"Document content preview: {compact_context}"
        )
    return user_query


def web_search_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    web_allowed = state.get("source_scope") != "Documents only" and (
        bool(state.get("web_enabled")) or state.get("source_scope") == "Web only"
    )
    if not web_allowed:
        state["web_sources"] = []
        if state.get("route") == "web_search":
            state["final_answer"] = _direct_answer(
                "البحث في الويب غير مفعّل في وضع المصادر الحالي. اختر Web only أو Documents + Web إذا أردت استخدام الويب.",
                "سياسة اختيار المصادر",
            )
            state["next_action"] = "final"
        _record(state, "Web Search", started, output="skipped by source mode")
        return state

    query = _document_grounded_web_query(state)
    result = WebSearchTool().search(query)
    state.setdefault("trace", {})["web_search_query"] = query[:1600]
    state["web_sources"] = result["results"]
    _add_tool(state, "web_search")
    web_context = "\n\n".join(
        f"[ويب {idx}]\nTitle: {item.get('title')}\nURL: {item.get('url')}\nProvider: {item.get('provider')}\nSnippet: {item.get('snippet')}"
        for idx, item in enumerate(state["web_sources"], start=1)
    )
    base_context = state.get("context") or ""
    state["context"] = f"{base_context}\n\nWEB CONTEXT:\n{web_context}".strip()
    if not result["available"] and state.get("route") == "web_search":
        state["final_answer"] = _direct_answer(
            "البحث في الويب غير متاح حاليا في هذا التشغيل. فعّل إعداد البحث في الويب واختر مزودا حيا مع مفتاح مناسب.",
            "حالة أداة الويب",
        )
        state["next_action"] = "final"
    _record(state, "Web Search", started, output=f"results={len(state['web_sources'])}")
    return state


def build_prompt_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    route = _execution_route(state)
    agent = _agent_for(route)
    extra = _answer_style_extra(state, route)
    if state.get("route") == "documents_plus_web" or (state.get("route") == "multi_task" and state.get("web_sources")):
        extra = f"{extra}\nUse both uploaded documents and web results. Separate file evidence from web evidence."
    if state.get("retrieval_query") and state.get("retrieval_query") != state.get("user_query"):
        extra = f"""
{extra}

Follow-up handling:
- The current user message is a clarification/follow-up, not a standalone topic.
- Use the recent conversation to understand what the user did not understand.
- Use retrieved context for the previous request: {state.get("retrieval_query")}.
- Explain the same topic again in a simpler way instead of saying there is no context for the short follow-up phrase.
"""
    if route == "summary" and _is_document_summary_request(state.get("user_query", "")):
        if _has_brief_answer_request(state.get("user_query", "")):
            extra = """
Priority override:
- The user explicitly asked for a very short summary.
- Do NOT use the study-report template.
- Answer in exactly two Arabic sentences unless the user asked for a different number.
- Do not add headings such as الشرح or نقاط للمذاكرة.
- Add one short source line only if needed, for example: "المصدر: الملف المرفوع."
- Use only information supported by the retrieved context.
"""
        else:
            extra = """
This is a document-level explanation request, not a narrow QA request.
Write a grounded study guide from the available pages/chunks only. If the available context is only a sample,
say that the explanation is based on the indexed/extracted parts currently available. Do not invent a full
document outline, chapter sequence, design lifecycle, or table entries unless those details appear in the context.
Prefer concise bullets over long speculative sections.
"""
    system_prompt = f"""
{agent.prompt}

CONTEXT:
{state.get("context", "") or 'No uploaded document context was retrieved. If you answer from model knowledge, label it clearly as من النموذج.'}

{extra}
"""
    memory_messages = build_memory_augmented_messages(
        session_id=state.get("chat_id", "default"),
        current_user_prompt=state.get("user_query", ""),
        system_prompt=system_prompt,
        recent_messages_override=state.get("recent_chat_messages") if isinstance(state.get("recent_chat_messages"), list) else None,
    )
    state["prompt"] = render_messages_as_prompt(memory_messages)
    state.setdefault("trace", {})["memory"] = {
        "recent_limit": 8,
        "relevant_top_k": 3,
        "injected": True,
    }
    _record(state, "Build Prompt", started, output=agent.name)
    return state


def tutor_answer_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    try:
        state["raw_answer"] = _invoke_llm(
            state,
            state.get("prompt") or state.get("user_query", ""),
            temperature=ANSWER_LLM_TEMPERATURE,
        )
    except Exception as exc:
        state["error"] = str(exc)
        state["raw_answer"] = None
        settings = _llm_settings(state)
        if settings["provider"] == "openai":
            body = (
                f"تعذر استخدام نموذج OpenAI `{settings['model']}` الآن. "
                f"السبب التقني: {str(exc)[:220]}. "
                "تأكد من وجود OPENAI_API_KEY ومن اتصال الشبكة، أو اختر النموذج المحلي من قائمة Model."
            )
        else:
            body = (
                f"النموذج المحلي `{settings['model']}` لم ينهِ الإجابة خلال مهلة {GRAPH_LLM_TIMEOUT_SECONDS} ثانية أو تعذر الاتصال به. "
                "تأكد أن Ollama يعمل وأن اسم النموذج صحيح، أو اختر OpenAI gpt-4o-mini من قائمة Model."
            )
        state["final_answer"] = _direct_answer(
            body,
            "حالة نموذج اللغة",
        )
    if state.get("raw_answer"):
        answer = state["raw_answer"]
        if _execution_route(state) == "summary" and _has_brief_answer_request(state.get("user_query", "")):
            answer = _brief_two_sentence_answer(answer)
            state["raw_answer"] = answer
        calculator_section = _calculator_result_section(state, answer)
        state["final_answer"] = f"{answer.rstrip()}\n\n{calculator_section}" if calculator_section else answer
    _record(state, "Tutor Answer", started, status="error" if state.get("error") else "ok", output=state.get("raw_answer", ""))
    return state


def summary_node(state: StudyGraphState) -> StudyGraphState:
    return tutor_answer_node(state)


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _validate_quiz(data: dict[str, Any]) -> dict[str, Any]:
    quiz = Quiz(**data)
    return _randomize_quiz_answer_positions(model_to_dict(quiz))


def _randomize_quiz_answer_positions(quiz: dict[str, Any]) -> dict[str, Any]:
    letters = ["A", "B", "C", "D"]
    for question in quiz.get("questions") or []:
        choices = question.get("choices") or {}
        correct_letter = question.get("correct_answer")
        correct_text = choices.get(correct_letter)
        if not correct_text:
            continue

        items = [(letter, str(choices.get(letter, ""))) for letter in letters]
        items = sorted(items, key=lambda item: item[1])
        seed = f"{quiz.get('quiz_id', '')}|{question.get('id', '')}|{question.get('question', '')}"
        rng = random.Random(seed)
        rng.shuffle(items)

        new_choices = {letter: item[1] for letter, item in zip(letters, items)}
        new_correct = next((letter for letter, text in new_choices.items() if text == correct_text), "A")
        question["choices"] = new_choices
        question["correct_answer"] = new_correct
    return quiz


def _quiz_topic_from_doc(doc: dict[str, Any], index: int) -> str:
    snippet = str(doc.get("snippet") or "")
    technical_terms = re.findall(r"\b(?:RAG|LLM|LLMs|QA|AI|NLP|CRAG|RAGBench|benchmark|retrieval|generation|ground truth)\b", snippet, re.IGNORECASE)
    normalized_terms = []
    for term in technical_terms:
        clean = term.strip()
        if clean.lower() not in {item.lower() for item in normalized_terms}:
            normalized_terms.append(clean)
    if normalized_terms:
        return normalized_terms[index % len(normalized_terms)]
    source_name = str(doc.get("source_name") or doc.get("source") or "المستند")
    return source_name.rsplit(".", 1)[0].replace("_", " ")


def _fallback_question(topic: str, doc: dict[str, Any], idx: int) -> dict[str, Any]:
    source_name = doc.get("source_name") or doc.get("source") or "المستند"
    location = doc.get("location") or "موضع غير محدد"
    templates = [
        {
            "question": f"ما الهدف الأقرب لاستخدام {topic} في سياق أنظمة الذكاء الاصطناعي المعتمدة على المصادر؟",
            "choices": {
                "A": "تحسين الإجابة بالاعتماد على معلومات مسترجعة أو موثقة بدلا من التخمين فقط.",
                "B": "حذف مرحلة البحث عن المصادر والاكتفاء بإجابة محفوظة مسبقا.",
                "C": "إخفاء المراجع حتى لا يعرف الطالب مصدر المعلومة.",
                "D": "تحويل كل الأسئلة إلى ترجمة حرفية دون قياس الفهم.",
            },
            "explanation": f"السؤال مبني على ظهور فكرة {topic} في المصدر، وهي مرتبطة بفهم الأنظمة المعتمدة على الاسترجاع أو التقييم الموثق.",
        },
        {
            "question": f"أي اختيار يصف دور التقييم الموثق عند دراسة {topic}؟",
            "choices": {
                "A": "قياس جودة الإجابات بمقارنتها بمصادر أو إجابات صحيحة يمكن الرجوع إليها.",
                "B": "اعتبار أي إجابة صحيحة لمجرد أنها مكتوبة بأسلوب منظم.",
                "C": "منع استخدام الأدلة والمراجع أثناء الحكم على الإجابة.",
                "D": "تغيير السؤال بعد رؤية إجابة الطالب حتى تصبح النتيجة أعلى.",
            },
            "explanation": "التقييم الجيد يعتمد على دليل أو مرجع واضح، لا على شكل الإجابة فقط.",
        },
        {
            "question": f"لماذا تعد جودة المصادر مهمة عند استخدام {topic}؟",
            "choices": {
                "A": "لأن ضعف المصدر قد يؤدي إلى إجابة غير دقيقة حتى لو كان النموذج قويا.",
                "B": "لأن المصدر يستخدم فقط لتزيين الإجابة ولا يؤثر في صحتها.",
                "C": "لأن النموذج يجب أن يتجاهل كل ما يأتي من الملفات.",
                "D": "لأن وجود مصدر واحد يعني أن كل الإجابات صحيحة تلقائيا.",
            },
            "explanation": "جودة المصدر جزء أساسي من جودة الإجابة في أنظمة الدراسة المعتمدة على الملفات.",
        },
    ]
    item = templates[(idx - 1) % len(templates)]
    return {
        "id": f"q{idx}",
        "question": item["question"],
        "choices": item["choices"],
        "correct_answer": "A",
        "explanation": item["explanation"],
        "difficulty": "medium",
        "source_refs": [{"type": "file", "title": source_name, "location": location}],
    }


def _fallback_quiz(query: str, docs: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    docs = docs or []
    if not docs:
        return None
    count = _requested_question_count(query)
    questions = []
    for idx in range(count):
        doc = docs[idx % len(docs)]
        topic = _quiz_topic_from_doc(doc, idx)
        questions.append(_fallback_question(topic, doc, idx + 1))
    return {
        "quiz_id": new_id("quiz"),
        "title": "اختبار من المستند",
        "questions": questions,
    }


def _normalize_quiz_count(quiz: dict[str, Any], query: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    expected = _requested_question_count(query)
    questions = list(quiz.get("questions") or [])
    if len(questions) > expected:
        quiz["questions"] = questions[:expected]
        return quiz
    if len(questions) < expected and docs and QUIZ_SYNTHETIC_FALLBACK_ENABLED:
        fallback = _fallback_quiz(query, docs)
        for item in (fallback or {}).get("questions", []):
            if len(questions) >= expected:
                break
            item["id"] = f"q{len(questions) + 1}"
            questions.append(item)
        quiz["questions"] = questions
    return quiz


def _quiz_count_is_valid(quiz: dict[str, Any], query: str) -> bool:
    return len(quiz.get("questions") or []) == _requested_question_count(query)


def _quiz_created_message(state: StudyGraphState) -> str:
    message = "تم إنشاء الاختبار. اختر الإجابات ثم اضغط زر الإرسال."
    explanation = (state.get("explanation_before_quiz") or "").strip()
    if not explanation:
        return message
    return f"""{explanation}

---

## الاختبار التفاعلي
{message}
"""


def _quiz_error_message(state: StudyGraphState, body: str, source: str) -> str:
    explanation = (state.get("explanation_before_quiz") or "").strip()
    error_answer = _direct_answer(body, source)
    if not explanation:
        return error_answer
    return f"""{explanation}

---

## ملاحظة عن الاختبار
{body}
"""


def _preserve_explanation_before_quiz(state: StudyGraphState) -> None:
    if state.get("explanation_before_quiz"):
        return
    if state.get("route") not in {"quiz_generate", "multi_task"}:
        return
    candidate = (state.get("final_answer") or state.get("raw_answer") or "").strip()
    if not candidate:
        return
    if "تم إنشاء الاختبار" in candidate or "الاختبار التفاعلي" in candidate:
        return
    state["explanation_before_quiz"] = candidate


def quiz_generation_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    _preserve_explanation_before_quiz(state)
    if not state.get("context") and not state.get("docs") and not state.get("web_sources"):
        state["final_answer"] = _quiz_error_message(
            state,
            "لا أستطيع إنشاء اختبار مرتبط بالمستند لأنني لم أسترجع أي سياق من الملفات. تأكد أن الفهرس مبني، أو أعد صياغة الطلب بذكر موضوع من الملف.",
            "حالة قاعدة المعرفة",
        )
        state["next_action"] = "final"
        _record(state, "Quiz Generation", started, status="error", output="missing document context")
        return state

    if state.get("docs") and not state.get("context"):
        sample_context, sample_docs = _sample_uploaded_documents(state.get("chat_id"))
        if sample_docs:
            state["docs"] = sample_docs
            state["context"] = sample_context

    if not state.get("context") and state.get("docs"):
        state["context"] = "\n\n".join(str(doc.get("snippet", "")) for doc in state.get("docs") or [])

    if not state.get("context"):
        if not QUIZ_SYNTHETIC_FALLBACK_ENABLED:
            state["final_answer"] = _quiz_error_message(
                state,
                "لا توجد مادة مسترجعة كافية لإنشاء اختبار موثوق من المستند. ابنِ الفهرس أو اسأل عن موضوع أوضح من الملف، ثم أعد طلب الاختبار.",
                "حالة قاعدة المعرفة",
            )
            state["next_action"] = "final"
            _record(state, "Quiz Generation", started, status="error", output="missing quiz material")
            return state
        fallback = _fallback_quiz(state.get("user_query", ""), state.get("docs") or [])
        if fallback is None:
            state["final_answer"] = _quiz_error_message(
                state,
                "لا توجد مادة كافية لإنشاء اختبار موثوق من المستند.",
                "حالة قاعدة المعرفة",
            )
            state["next_action"] = "final"
            _record(state, "Quiz Generation", started, status="error", output="missing quiz material")
            return state
        quiz = _validate_quiz(fallback)
        state["quiz"] = quiz
        state["final_answer"] = _quiz_created_message(state)
        state["next_action"] = "await_quiz_submission"
        _record(state, "Quiz Generation", started, output=f"document fallback questions={len(quiz.get('questions', []))}")
        return state

    prompt = f"""
{QUIZ_JSON_PROMPT}

USER REQUEST:
{state.get("user_query", "")}

CONTEXT:
{state.get("context") or "No retrieved context. If you must generate from model knowledge, mark source_refs as model."}
"""
    try:
        answer = _invoke_llm(state, prompt, temperature=QUIZ_GENERATION_LLM_TEMPERATURE)
        try:
            quiz = _validate_quiz(_json_from_text(answer))
        except Exception:
            repair_prompt = f"{QUIZ_JSON_PROMPT}\nRepair this invalid quiz into valid JSON only:\n{answer}"
            repaired = _invoke_llm(state, repair_prompt, temperature=QUIZ_REPAIR_LLM_TEMPERATURE)
            quiz = _validate_quiz(_json_from_text(repaired))
        quiz = _validate_quiz(_normalize_quiz_count(quiz, state.get("user_query", ""), state.get("docs") or []))
        if not _quiz_count_is_valid(quiz, state.get("user_query", "")):
            expected = _requested_question_count(state.get("user_query", ""))
            count_repair_prompt = f"""
{QUIZ_JSON_PROMPT}

Return exactly {expected} MCQ questions. Use the context below. JSON only.

CURRENT QUIZ:
{json.dumps(quiz, ensure_ascii=False)}

CONTEXT:
{state.get("context") or ""}
"""
            repaired = _invoke_llm(state, count_repair_prompt, temperature=QUIZ_REPAIR_LLM_TEMPERATURE)
            quiz = _validate_quiz(_json_from_text(repaired))
            if not _quiz_count_is_valid(quiz, state.get("user_query", "")):
                raise ValueError(f"Quiz model returned {len(quiz.get('questions') or [])} questions instead of {expected}.")
    except Exception as exc:
        state["error"] = str(exc)
        fallback = _fallback_quiz(state.get("user_query", ""), state.get("docs") or []) if QUIZ_SYNTHETIC_FALLBACK_ENABLED else None
        if fallback is None:
            state["final_answer"] = _quiz_error_message(
                state,
                "فشل نموذج اللغة في إنشاء اختبار JSON صالح بالعدد المطلوب. لم أعرض اختبارا احتياطيا حتى لا أقدم أسئلة ضعيفة أو غير مرتبطة بالمستند.",
                "حالة نموذج اللغة",
            )
            state["next_action"] = "final"
            _record(state, "Quiz Generation", started, status="error", output=str(exc))
            return state
        quiz = _validate_quiz(fallback)

    state["quiz"] = quiz
    state["final_answer"] = _quiz_created_message(state)
    state["next_action"] = "await_quiz_submission"
    _record(
        state,
        "Quiz Generation",
        started,
        status="error" if state.get("error") else "ok",
        output=f"questions={len(quiz.get('questions', []))}",
    )
    return state


def quiz_feedback_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    quiz = state.get("quiz") or {}
    user_answers = state.get("user_answers") or {}
    result = QuizGradingTool().grade(quiz, user_answers)
    state["quiz_result"] = result
    _add_tool(state, "quiz_grading")

    prompt = f"""
{FEEDBACK_FROM_QUIZ_PROMPT}

QUIZ:
{json.dumps(quiz, ensure_ascii=False)}

GRADING RESULT:
{json.dumps(result, ensure_ascii=False)}
"""
    try:
        feedback_text = _invoke_llm(state, prompt, temperature=QUIZ_FEEDBACK_LLM_TEMPERATURE)
    except Exception as exc:
        state["error"] = str(exc)
        feedback_text = _format_feedback_fallback(result)

    state["feedback"] = {"text": feedback_text, "quiz_result": result}
    state["final_answer"] = feedback_text
    _record(state, "Quiz Feedback", started, status="error" if state.get("error") else "ok", output=feedback_text)
    return state


def _format_feedback_fallback(result: dict[str, Any]) -> str:
    details = "\n".join(
        f"- {item['question_id']}: إجابتك {item.get('user_answer') or 'بدون إجابة'}، الصحيح {item.get('correct_answer')}. {item.get('explanation')}"
        for item in result.get("details", [])
    )
    return f"""# النتيجة
درجتك: {result.get('correct')} من {result.get('total')} ({result.get('percentage')}%).

# الإجابات الصحيحة
{details}

# الأخطاء المهمة
راجع الأسئلة التي كانت إجابتها غير صحيحة أو فارغة.

# المفاهيم الضعيفة
{", ".join(result.get("weak_concepts") or ["لا توجد مفاهيم ضعيفة واضحة."])}

# ماذا تراجع الآن
- اقرأ الشرح الخاص بكل سؤال.
- أعد حل الأسئلة التي أخطأت فيها.

# المصادر
- من الاختبار المنظم المحفوظ في المحادثة.
"""


def study_plan_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    weak = state.get("quiz_result", {}).get("weak_concepts", []) if state.get("quiz_result") else []
    prompt = f"""
{STUDY_PLAN_FROM_WEAKNESS_PROMPT}

USER REQUEST:
{state.get("user_query", "")}

WEAK CONCEPTS:
{json.dumps(weak, ensure_ascii=False)}

CONTEXT:
{state.get("context", "")}
"""
    try:
        answer = _invoke_llm(state, prompt, temperature=STUDY_PLAN_LLM_TEMPERATURE)
    except Exception as exc:
        state["error"] = str(exc)
        answer = _direct_answer("تعذر إنشاء خطة مخصصة من نموذج اللغة الآن.", "حالة نموذج اللغة")
    state["final_answer"] = answer
    _record(state, "Study Plan", started, status="error" if state.get("error") else "ok", output=answer)
    return state


def arabic_guard_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    if state.get("quiz") and state.get("next_action") == "await_quiz_submission" and not state.get("final_sections"):
        _record(state, "Arabic Guard", started, output="skipped for structured quiz")
        return state
    if state.get("final_answer") and not state.get("raw_answer"):
        _record(state, "Arabic Guard", started, output="skipped for graph-authored direct answer")
        return state
    try:
        answer = state.get("final_answer") or state.get("raw_answer") or ""
        from src.agents.base_agent import append_sources_section

        if not answer.strip():
            state["final_answer"] = _direct_answer("لم ينتج النموذج إجابة قابلة للعرض.", "حالة نموذج اللغة")
        elif not contains_disallowed_language(answer):
            state["final_answer"] = append_sources_section(answer, state.get("docs") or [], state.get("web_sources") or [])
        elif not ARABIC_GUARD_LLM_REPAIR_ENABLED:
            state.setdefault("trace", {})["arabic_guard_warning"] = (
                "LLM repair is disabled. The answer may contain non-Arabic words beyond the allowed technical terms."
            )
            state["final_answer"] = append_sources_section(answer, state.get("docs") or [], state.get("web_sources") or [])
        else:
            settings = _set_llm_settings(state)
            guarded = _run_with_timeout(
                lambda: enforce_arabic_answer(
                    answer,
                    state.get("user_query", ""),
                    get_llm(
                        temperature=ARABIC_GUARD_LLM_TEMPERATURE,
                        provider=settings["provider"],
                        model=settings["model"],
                        profile=settings["profile"],
                        timeout_seconds=GRAPH_LLM_TIMEOUT_SECONDS,
                    ),
                ),
                GRAPH_LLM_TIMEOUT_SECONDS,
                "Arabic guard",
            )
            state["final_answer"] = append_sources_section(guarded, state.get("docs") or [], state.get("web_sources") or [])
    except Exception as exc:
        state["error"] = str(exc)
    _record(state, "Arabic Guard", started, status="error" if state.get("error") else "ok", output=state.get("final_answer", ""))
    return state


def _skip_quality_agents_for_quiz(state: StudyGraphState) -> bool:
    return bool(
        state.get("quiz")
        and state.get("next_action") == "await_quiz_submission"
        and not state.get("final_sections")
    )


def _quality_fast_review(state: StudyGraphState, answer: str) -> dict[str, Any]:
    answer_text = (answer or "").strip()
    context = state.get("context") or ""
    docs = state.get("docs") or []
    answer_tokens = _content_tokens(answer_text)
    context_tokens = _content_tokens(context)
    issues: list[str] = []

    if len(answer_text) < 160 and not state.get("tool_result"):
        issues.append("answer is very short")
    if not state.get("tool_result") and contains_disallowed_language(answer_text):
        issues.append("answer may contain too much non-Arabic text")
    if docs and not any(marker in answer_text for marker in ["# المصدر", "# المصادر", "المصدر", "المصادر", "Source", "Sources"]):
        issues.append("source section is missing or unclear")
    if context_tokens and answer_tokens:
        overlap = len(answer_tokens & context_tokens) / max(len(answer_tokens), 1)
        if overlap < 0.06 and len(answer_tokens) >= 12:
            issues.append("answer has weak lexical grounding in retrieved context")

    passed = not issues
    return {
        "status": "fast",
        "mode": "deterministic",
        "passed": passed,
        "issues": issues,
        "improved_answer": answer_text,
    }


def _critic_fast_review(state: StudyGraphState, answer: str) -> dict[str, Any]:
    review = _quality_fast_review(state, answer)
    issues = list(review.get("issues") or [])
    high_risk_terms = ["invented", "guaranteed", "always", "never", "100%", "proves"]
    lower_answer = (answer or "").lower()
    if any(term in lower_answer for term in high_risk_terms) and state.get("context"):
        issues.append("answer includes strong claims that should be checked against context")

    risk_level = "low"
    if any("weak lexical grounding" in issue for issue in issues):
        risk_level = "medium"
    if len(issues) >= 3:
        risk_level = "medium"

    return {
        "status": "fast",
        "mode": "deterministic",
        "passed": risk_level == "low",
        "criticism": issues,
        "risk_level": risk_level,
        "improved_answer": answer,
    }


def reflection_node(state: StudyGraphState) -> StudyGraphState:
    """Run the self-review agent after answer generation.

    Reflection is a constructive review pass: it checks whether the answer
    followed the request, is beginner-friendly, Arabic, grounded, and structured.
    It runs before citation/evaluation so an improved answer can still receive
    citations and normal quality checks.
    """

    started = perf_counter()
    if not state.get("reflection_enabled", True):
        state["reflection_result"] = {"status": "disabled"}
        state.setdefault("trace", {})["reflection"] = state["reflection_result"]
        _record(state, "Reflection Agent", started, output="disabled")
        return state
    if _skip_quality_agents_for_quiz(state):
        state["reflection_result"] = {"status": "skipped", "reason": "structured quiz waiting for submission"}
        state.setdefault("trace", {})["reflection"] = state["reflection_result"]
        _record(state, "Reflection Agent", started, output="skipped for quiz")
        return state

    answer = state.get("final_answer") or ""
    if not answer.strip():
        state["reflection_result"] = {"status": "skipped", "reason": "empty answer"}
        state.setdefault("trace", {})["reflection"] = state["reflection_result"]
        _record(state, "Reflection Agent", started, output="empty answer")
        return state

    fast_review = _quality_fast_review(state, answer)
    if not QUALITY_AGENT_LLM_REVIEW_ENABLED or fast_review.get("passed"):
        state["reflection_result"] = fast_review
        state["reflection_checks"] = {"fast": fast_review}
        state.setdefault("trace", {})["reflection"] = fast_review
        _record(state, "Reflection Agent", started, output=str(fast_review)[:240])
        return state

    try:
        from src.agents.reflection_agent import ReflectionAgent

        state["answer_before_reflection"] = answer
        agent = ReflectionAgent()
        dimensions = ["fact", "style", "safety"]

        def run_dimension(dimension: str) -> dict[str, Any]:
            prompt = agent.build_dimension_prompt(
                dimension,
                state.get("user_query", ""),
                answer,
                state.get("context", ""),
            )
            try:
                payload = _json_from_text(
                    _invoke_llm(
                        state,
                        prompt,
                        temperature=REFLECTION_LLM_TEMPERATURE,
                        timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, QUALITY_AGENT_LLM_TIMEOUT_SECONDS),
                    )
                )
                return {
                    "passed": bool(payload.get("passed")),
                    "issues": list(payload.get("issues") or []),
                    "improved_answer": str(payload.get("improved_answer") or answer),
                }
            except Exception as exc:
                return {"passed": True, "issues": [f"{dimension} reflection failed: {exc}"], "improved_answer": answer}

        checks: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(dimensions)) as executor:
            futures = {executor.submit(run_dimension, dimension): dimension for dimension in dimensions}
            for future in as_completed(futures):
                checks[futures[future]] = future.result()

        state["reflection_checks"] = checks
        passed = all(bool((checks.get(dimension) or {}).get("passed")) for dimension in dimensions)
        issues: list[str] = []
        for dimension in dimensions:
            for issue in (checks.get(dimension) or {}).get("issues") or []:
                issues.append(f"{dimension}: {issue}")
        improved = answer
        # Safety and factual corrections have higher priority than style edits.
        for dimension in ["style", "fact", "safety"]:
            candidate = str((checks.get(dimension) or {}).get("improved_answer") or "").strip()
            if candidate and candidate != answer and not (checks.get(dimension) or {}).get("passed"):
                improved = candidate
        result = {
            "status": "ok",
            "parallel": True,
            "passed": passed,
            "issues": issues,
            "checks": checks,
            "improved_answer": improved,
        }
        improved = str(result.get("improved_answer") or "").strip()
        if improved:
            state["final_answer"] = improved
        state["reflection_result"] = result
        state.setdefault("trace", {})["reflection"] = result
    except Exception as exc:
        state["reflection_result"] = {"status": "error", "error": str(exc)}
        state.setdefault("trace", {})["reflection"] = state["reflection_result"]
        state["error"] = str(exc)
    _record(
        state,
        "Reflection Agent",
        started,
        status="error" if (state.get("reflection_result") or {}).get("status") == "error" else "ok",
        output=str(state.get("reflection_result", {}))[:240],
    )
    return state


def critic_node(state: StudyGraphState) -> StudyGraphState:
    """Run the adversarial quality-check agent after reflection.

    The critic is stricter than reflection. It looks for hallucinations, weak
    evidence, bad assumptions, and educational risk. It only replaces the answer
    when risk is medium/high so low-risk answers are not churned unnecessarily.
    """

    started = perf_counter()
    if not state.get("critic_enabled", True):
        state["critic_result"] = {"status": "disabled"}
        state.setdefault("trace", {})["critic"] = state["critic_result"]
        _record(state, "Critic Agent", started, output="disabled")
        return state
    if _skip_quality_agents_for_quiz(state):
        state["critic_result"] = {"status": "skipped", "reason": "structured quiz waiting for submission"}
        state.setdefault("trace", {})["critic"] = state["critic_result"]
        _record(state, "Critic Agent", started, output="skipped for quiz")
        return state

    answer = state.get("final_answer") or ""
    if not answer.strip():
        state["critic_result"] = {"status": "skipped", "reason": "empty answer"}
        state.setdefault("trace", {})["critic"] = state["critic_result"]
        _record(state, "Critic Agent", started, output="empty answer")
        return state

    fast_review = _critic_fast_review(state, answer)
    if not QUALITY_AGENT_LLM_REVIEW_ENABLED or fast_review.get("risk_level") == "low":
        state["critic_result"] = fast_review
        state.setdefault("trace", {})["critic"] = fast_review
        _record(state, "Critic Agent", started, output=str(fast_review)[:240])
        return state

    try:
        from src.agents.critic_agent import CriticAgent

        state["answer_before_critic"] = answer
        agent = CriticAgent()
        result = agent.review(
            state.get("user_query", ""),
            answer,
            state.get("context", ""),
            lambda prompt: _invoke_llm(
                state,
                prompt,
                temperature=CRITIC_LLM_TEMPERATURE,
                timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, QUALITY_AGENT_LLM_TIMEOUT_SECONDS),
            ),
        )
        result["status"] = "ok"
        improved = str(result.get("improved_answer") or "").strip()
        if improved and result.get("risk_level") != "low":
            state["final_answer"] = improved
        state["critic_result"] = result
        state.setdefault("trace", {})["critic"] = result
    except Exception as exc:
        state["critic_result"] = {"status": "error", "error": str(exc)}
        state.setdefault("trace", {})["critic"] = state["critic_result"]
        state["error"] = str(exc)
    _record(
        state,
        "Critic Agent",
        started,
        status="error" if (state.get("critic_result") or {}).get("status") == "error" else "ok",
        output=str(state.get("critic_result", {}))[:240],
    )
    return state


def citation_checker_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    check = CitationCheckerTool().check(state.get("final_answer") or "", state.get("docs"), state.get("web_sources"))
    state.setdefault("trace", {}).setdefault("citation_check", check)
    if not check["passed"]:
        state["final_answer"] = (state.get("final_answer") or "").rstrip() + f"\n\n> تنبيه المصادر: {check['message']}"
    _record(state, "Citation Checker", started, output=str(check))
    return state


def evaluation_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    answer = state.get("final_answer") or ""
    if state.get("quiz") and state.get("next_action") == "await_quiz_submission" and not state.get("final_sections"):
        answer = json.dumps(state.get("quiz"), ensure_ascii=False)
    external_enabled = bool(state.get("external_rag_eval_enabled") or AUTOMATIC_EXTERNAL_RAG_EVAL)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            deterministic_future = executor.submit(
                evaluate_response,
                query=state.get("user_query", ""),
                answer=answer,
                docs=state.get("docs") or [],
                tools_used=state.get("tools_used") or [],
                mode="deterministic",
                web_sources=state.get("web_sources") or [],
            )
            rag_future = executor.submit(
                RAGEvaluationService(
                    enable_ragas=external_enabled and ENABLE_RAGAS_EVAL,
                    enable_deepeval=external_enabled and ENABLE_DEEPEVAL_EVAL,
                ).evaluate,
                RAGEvaluationInput(
                    query=state.get("user_query", ""),
                    answer=answer,
                    docs=state.get("docs") or [],
                    context=state.get("context") or "",
                    web_sources=state.get("web_sources") or [],
                ),
            )
            deterministic = deterministic_future.result()
            rag_bundle = rag_future.result()
        state["evaluation"] = {
            "evaluation_id": deterministic.get("evaluation_id") or new_id("eval"),
            "status": deterministic.get("status", "completed"),
            "overall_score": deterministic.get("overall_score"),
            "deterministic": deterministic,
            "ragas": rag_bundle.get("ragas"),
            "deepeval": rag_bundle.get("deepeval"),
            "summary_scores": rag_bundle.get("summary_scores"),
            # Backward-compatible fields used by the current sidebar and chat store.
            "rubric": deterministic.get("rubric", {}),
            "rubric_reasons": deterministic.get("rubric_reasons", {}),
            "deterministic_checks": deterministic.get("deterministic_checks", []),
            "recommendations": deterministic.get("recommendations", []),
            "llm_judge": deterministic.get("llm_judge"),
            "gold_standard": deterministic.get("gold_standard"),
            "created_at": deterministic.get("created_at"),
        }
        if state.get("quiz"):
            state["evaluation"]["quiz_valid"] = True
    except Exception as exc:
        state["evaluation"] = {"evaluation_id": new_id("eval"), "status": "error", "error": str(exc)}
    _record(state, "Evaluation", started, output=str(state.get("evaluation", {}))[:240])
    return state


def save_trace_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    trace = _trace(state)
    trace["selected_agent"] = state.get("selected_agent") or ""
    trace["retrieved_docs"] = state.get("docs") or []
    trace["tools_used"] = state.get("tools_used") or []
    trace["planned_tool_calls"] = state.get("planned_tool_calls") or []
    trace["tool_calls"] = state.get("tool_calls") or []
    trace["tool_results"] = state.get("tool_results") or []
    trace["parallel_agent_results"] = state.get("parallel_agent_results") or []
    trace["retrieval_breakdown"] = state.get("retrieval_breakdown") or {}
    trace["timings_ms"] = state.get("timings_ms") or {}
    trace["final_answer"] = state.get("final_answer") or ""
    trace["evaluation_result"] = state.get("evaluation")
    trace["reflection"] = state.get("reflection_result")
    trace["critic"] = state.get("critic_result")
    evaluation = state.get("evaluation") or {}
    trace["deterministic_evaluation"] = evaluation.get("deterministic", evaluation)
    trace["ragas_evaluation"] = evaluation.get("ragas")
    trace["deepeval_evaluation"] = evaluation.get("deepeval")
    trace["evaluation_summary_scores"] = evaluation.get("summary_scores")
    trace["route"] = ["LangGraph", state.get("route", "")]
    trace["graph_state_summary"] = {
        "route": state.get("route"),
        "next_action": state.get("next_action"),
        "docs": len(state.get("docs") or []),
        "web_sources": len(state.get("web_sources") or []),
        "tools_used": state.get("tools_used") or [],
        "has_quiz": bool(state.get("quiz")),
        "has_quiz_result": bool(state.get("quiz_result")),
        "tasks": state.get("tasks") or [],
        "task_results": state.get("task_results") or [],
        "final_sections": len(state.get("final_sections") or []),
        "is_multi_task": bool(state.get("is_multi_task")),
        "parallel_agent_results": len(state.get("parallel_agent_results") or []),
        "planned_tool_calls": state.get("planned_tool_calls") or [],
        "tool_call": state.get("tool_call"),
        "tool_calls": state.get("tool_calls") or [],
        "tool_results": state.get("tool_results") or [],
        "has_tool_result": bool(state.get("tool_result")),
        "bm25_enabled": bool(state.get("bm25_enabled")),
        "retrieval_breakdown": state.get("retrieval_breakdown") or {},
        "reflection_enabled": bool(state.get("reflection_enabled")),
        "critic_enabled": bool(state.get("critic_enabled")),
        "has_reflection": bool(state.get("reflection_result")),
        "reflection_checks": state.get("reflection_checks") or {},
        "has_critic": bool(state.get("critic_result")),
    }
    trace["llm"] = {
        "provider": state.get("llm_provider"),
        "model": state.get("llm_model"),
        "profile": state.get("model_profile"),
    }
    state["trace"] = trace
    _record(state, "Save Trace", started, output="trace ready")
    return state


def enable_langsmith_if_configured() -> None:
    if not LANGSMITH_TRACING_ENABLED:
        return
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", LANGSMITH_PROJECT)

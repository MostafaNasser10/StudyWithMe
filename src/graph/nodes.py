from __future__ import annotations

import json
import os
from queue import Empty, Queue
import random
import re
from threading import Thread
from time import perf_counter
from typing import Any, Callable

from src.arabic_guard import contains_disallowed_language, enforce_arabic_answer
from src.chat.chat_models import new_id, now_iso
from src.config import (
    ARABIC_GUARD_LLM_REPAIR_ENABLED,
    LANGSMITH_PROJECT,
    LANGSMITH_TRACING_ENABLED,
    QUIZ_SYNTHETIC_FALLBACK_ENABLED,
    TOP_K,
)
from src.evaluation.rag_evaluation_service import RAGEvaluationInput, RAGEvaluationService
from src.evaluation.response_evaluator import evaluate_response
from src.graph.schemas import PlannerDecision, Quiz, ToolCallPlan, ToolCallRequest, ToolCallResponse, model_to_dict
from src.graph.state import StudyGraphState
from src.llm import get_llm, model_is_configured, resolve_model_profile
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
    temperature: float = 0.3,
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
    return _is_document_overview_query(query) or _contains_any(text, ["summary", "summarize", "تلخيص", "لخص", "ملخص"])


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


def _answer_style_extra(state: StudyGraphState, route: str) -> str:
    if state.get("answer_style") == "study_report" or route in {"summary", "study_plan"}:
        return ""
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
        "summary": _task("summary", "الملخص"),
        "quiz_generate": _task("quiz_generate", "الاختبار"),
        "study_plan": _task("study_plan", "خطة المذاكرة"),
        "web_search": _task("web_search", "بحث الويب"),
        "feedback": _task("feedback", "التصحيح"),
        "clarify": _task("clarify", "توضيح الطلب"),
    }.get(route, _task("explain", "الشرح"))


def _normalize_planner_tasks(tasks: list[dict[str, Any]], route: str) -> list[dict[str, Any]]:
    allowed = {"explain", "summary", "quiz_generate", "study_plan", "web_search", "quiz_feedback", "feedback", "clarify"}
    normalized: list[dict[str, Any]] = []
    for item in tasks or []:
        task_type = str(item.get("type") or "").strip().lower()
        if task_type == "calculator":
            task_type = "explain"
        if task_type not in allowed:
            continue
        title = str(item.get("title") or TASK_AGENT_NAMES.get(task_type) or task_type)
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
        if call.tool_name == "web_search" and (not web_enabled or source_scope == "Documents only"):
            continue
        filtered.append(call)
    return ToolCallPlan(tool_calls=filtered).tool_calls


def _enforce_source_policy(decision: PlannerDecision, source_scope: str, web_enabled: bool) -> PlannerDecision:
    if source_scope == "Documents only":
        decision.needs_web = False
        if decision.route in {"web_search", "documents_plus_web"}:
            decision.route = "tutor_rag"
        decision.tasks = [task for task in decision.tasks if task.get("type") != "web_search"]
    elif source_scope == "Web only":
        decision.needs_documents = False
        if decision.route in {"tutor_rag", "summary", "quiz_generate", "study_plan", "documents_plus_web"}:
            decision.route = "web_search" if web_enabled else "clarify"
        decision.tasks = [task for task in decision.tasks if task.get("type") not in {"summary", "quiz_generate"}]
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
    if source_scope != "Web only" and _is_document_overview_query(query):
        decision.route = "summary"
        decision.tasks = [_task("summary", "شرح الملف")]
        decision.selected_agent = "Summary"
        decision.needs_documents = True
        decision.answer_style = "study_report"
        if not any(call.tool_name == "document_search" for call in decision.tool_calls):
            decision.tool_calls = [
                ToolCallRequest(
                    tool_name="document_search",
                    arguments={"query": query, "top_k": max(TOP_K, 10)},
                    reasoning="The user asked to explain the uploaded file.",
                )
            ] + list(decision.tool_calls or [])

    if arithmetic_expression and not _has_quiz_intent(text):
        decision.tasks = [task for task in decision.tasks if str(task.get("type") or "") != "quiz_generate"]
        if decision.route == "quiz_generate":
            decision.route = "tutor_rag"
            decision.selected_agent = "RAG Tutor"
        if not decision.tasks:
            decision.tasks = [_task("explain", "الإجابة")]
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
    decision = _enforce_source_policy(decision, source_scope, web_enabled)
    decision.tasks = _normalize_planner_tasks(decision.tasks, decision.route)
    if len(decision.tasks) > 1 and decision.route not in {"documents_plus_web"}:
        decision.route = "multi_task"
    elif len(decision.tasks) == 1 and decision.route == "multi_task":
        only = str((decision.tasks[0] or {}).get("type") or "explain")
        decision.route = "tutor_rag" if only == "explain" else TASK_ROUTES.get(only, "tutor_rag")
    decision.tool_calls = _filter_planned_tool_calls(decision.tool_calls, source_scope, web_enabled)
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
        raw = _invoke_llm(state, prompt, temperature=0, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 25))
        decision = _planner_decision_from_payload(_json_from_text(raw), state.get("user_query", ""), source_scope, web_enabled)
    except Exception as exc:
        state["error"] = str(exc)
        decision = PlannerDecision(
            route="clarify",
            tasks=[_task("clarify", "تعذر التخطيط")],
            selected_agent="Input Guard",
            needs_documents=False,
            needs_web=False,
            answer_style="direct",
            tool_calls=[ToolCallRequest(tool_name="none", arguments={}, reasoning="Planner LLM failed.")],
        )

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
        state["final_answer"] = _direct_answer(
            "أحتاج طلبا أوضح أو وضع مصادر مناسب قبل أن أبدأ. اكتب مثلا: اشرح الملف، اعمل اختبارا من المحاضرة، أو فعّل الويب إذا كان السؤال عن معلومة حديثة.",
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
            raw = _invoke_llm(state, prompt, temperature=0, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 20))
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
    for call in plan.tool_calls:
        result = execute_registered_tool(call.tool_name, call.arguments, state)
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
    title = str(task.get("title") or TASK_AGENT_NAMES.get(task_type, task_type.title()))

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


def final_composer_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    sections = state.get("final_sections") or []
    if not sections:
        state["final_answer"] = state.get("final_answer") or ""
        _record(state, "Final Composer", started, output="single direct answer")
        return state

    parts: list[str] = []
    for section in sections:
        title = str(section.get("title") or section.get("type") or "Section")
        content = str(section.get("content") or "").strip()
        if section.get("quiz"):
            content = content or "تم إنشاء الاختبار. اختر الإجابات ثم اضغط Submit."
        if not content:
            continue
        parts.append(f"# {title}\n{content}")
    state["final_answer"] = "\n\n".join(parts).strip()
    if state.get("quiz"):
        state["next_action"] = "await_quiz_submission"
    else:
        state["next_action"] = "final"
    _record(state, "Final Composer", started, output=f"sections={len(sections)}")
    return state


def retrieve_docs_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    try:
        def search_docs():
            from src.tools.document_search_tool import DocumentSearchTool

            top_k = max(TOP_K, 10) if _is_document_overview_query(state.get("user_query", "")) else TOP_K
            return DocumentSearchTool().search(state.get("user_query", ""), chat_id=state.get("chat_id"), top_k=top_k)

        result = _run_with_timeout(search_docs, GRAPH_RETRIEVAL_TIMEOUT_SECONDS, "Document retrieval")
        state["docs"] = result.docs
        state["context"] = result.context
        state.setdefault("timings_ms", {})["document_search_ms"] = result.timing_ms
        if _is_document_overview_query(state.get("user_query", "")):
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
    _add_tool(state, "document_search")

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
        and not _has_explicit_document_intent((state.get("user_query") or "").lower())
        and not _docs_look_relevant(state.get("user_query", ""), state.get("docs") or [])
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
        output=f"docs={len(state.get('docs') or [])}",
    )
    return state


def _sample_uploaded_documents(chat_id: str | None, max_docs: int = 4, max_chars: int = 900) -> tuple[str, list[dict[str, Any]]]:
    try:
        from pathlib import Path

        from src.document_loader import load_documents
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
    user_query = (state.get("user_query") or "").strip()
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
    if state.get("source_scope") == "Documents only" or not state.get("web_enabled"):
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
    if route == "summary" and _is_document_overview_query(state.get("user_query", "")):
        extra = """
This is a document-level explanation request, not a narrow QA request.
Write a broad study guide from the available pages/chunks. If the available context is only a sample,
say that the explanation is based on the indexed/extracted parts currently available.
Do not over-focus on only the highest-similarity chunks.
"""
    state["prompt"] = agent.build_prompt(state.get("user_query", ""), context=state.get("context", ""), extra=extra)
    _record(state, "Build Prompt", started, output=agent.name)
    return state


def tutor_answer_node(state: StudyGraphState) -> StudyGraphState:
    started = perf_counter()
    try:
        state["raw_answer"] = _invoke_llm(state, state.get("prompt") or state.get("user_query", ""))
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
    message = "تم إنشاء الاختبار. اختر الإجابات ثم اضغط Submit."
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
        answer = _invoke_llm(state, prompt, temperature=0.2)
        try:
            quiz = _validate_quiz(_json_from_text(answer))
        except Exception:
            repair_prompt = f"{QUIZ_JSON_PROMPT}\nRepair this invalid quiz into valid JSON only:\n{answer}"
            repaired = _invoke_llm(state, repair_prompt, temperature=0)
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
            repaired = _invoke_llm(state, count_repair_prompt, temperature=0)
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
        feedback_text = _invoke_llm(state, prompt)
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
        answer = _invoke_llm(state, prompt)
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
                        temperature=0,
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

    try:
        from src.agents.reflection_agent import ReflectionAgent

        state["answer_before_reflection"] = answer
        agent = ReflectionAgent()
        result = agent.review(
            state.get("user_query", ""),
            answer,
            state.get("context", ""),
            lambda prompt: _invoke_llm(state, prompt, temperature=0, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 60)),
        )
        result["status"] = "ok"
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

    try:
        from src.agents.critic_agent import CriticAgent

        state["answer_before_critic"] = answer
        agent = CriticAgent()
        result = agent.review(
            state.get("user_query", ""),
            answer,
            state.get("context", ""),
            lambda prompt: _invoke_llm(state, prompt, temperature=0, timeout_seconds=min(GRAPH_LLM_TIMEOUT_SECONDS, 60)),
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
    try:
        deterministic = evaluate_response(
            query=state.get("user_query", ""),
            answer=answer,
            docs=state.get("docs") or [],
            tools_used=state.get("tools_used") or [],
            mode="deterministic",
            web_sources=state.get("web_sources") or [],
        )
        rag_bundle = RAGEvaluationService().evaluate(
            RAGEvaluationInput(
                query=state.get("user_query", ""),
                answer=answer,
                docs=state.get("docs") or [],
                context=state.get("context") or "",
                web_sources=state.get("web_sources") or [],
            )
        )
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
        "planned_tool_calls": state.get("planned_tool_calls") or [],
        "tool_call": state.get("tool_call"),
        "tool_calls": state.get("tool_calls") or [],
        "tool_results": state.get("tool_results") or [],
        "has_tool_result": bool(state.get("tool_result")),
        "reflection_enabled": bool(state.get("reflection_enabled")),
        "critic_enabled": bool(state.get("critic_enabled")),
        "has_reflection": bool(state.get("reflection_result")),
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

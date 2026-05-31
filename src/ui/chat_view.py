from __future__ import annotations

import os
from time import perf_counter, sleep
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from src.chat.chat_store import ChatStore
from src.config import MODEL_PROFILES, SOURCE_SCOPES
from src.graph.app_graph import run_study_graph, stream_study_graph
from src.llm import model_is_configured, resolve_model_profile
from src.tools.quiz_grading_tool import QuizGradingTool
from src.ui.components import safe_text


CHAT_MESSAGE_RENDER_LIMIT = int(os.getenv("CHAT_MESSAGE_RENDER_LIMIT", "30"))

STAGE_LABELS = {
    "router": "Planning requested tasks",
    "task_dispatcher": "Selecting next task",
    "collect_task_output": "Saving task output",
    "final_composer": "Composing final study response",
    "retrieve_docs": "Searching document index and embeddings",
    "web_search": "Calling web search tool",
    "build_prompt": "Building agent prompt",
    "tutor_answer": "Calling selected LLM",
    "summary": "Calling summary agent",
    "quiz_generation": "Generating structured quiz JSON",
    "quiz_feedback": "Grading quiz and building feedback",
    "study_plan": "Building study plan",
    "arabic_guard": "Checking Arabic output",
    "citation_checker": "Checking sources and citations",
    "evaluation": "Running deterministic evaluation",
    "save_trace": "Saving trace state",
    "calculator": "Running calculator",
}


def _initial_graph_state(
    chat: dict,
    query: str,
    quiz: dict[str, Any] | None = None,
    user_answers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "chat_id": chat["chat_id"],
        "user_query": query,
        "source_scope": st.session_state.source_scope,
        "web_enabled": st.session_state.web_search_enabled,
        "model_profile": st.session_state.model_profile,
        "quiz": quiz,
        "user_answers": user_answers,
    }


def _next_stage(last_node: str, state: dict[str, Any]) -> str:
    route = state.get("route")
    if last_node == "router":
        if route == "multi_task":
            if state.get("needs_documents"):
                return "Searching document index and embeddings"
            if state.get("needs_web"):
                return "Calling web search tool"
            return "Selecting next task"
        return {
            "calculator": "Running calculator",
            "clarify": "Preparing clarification",
            "web_search": "Calling web search tool",
            "study_plan": "Searching document index and embeddings",
            "quiz_generate": "Searching document index and embeddings",
            "documents_plus_web": "Searching document index and embeddings",
        }.get(route, "Searching document index and embeddings")
    if last_node == "task_dispatcher":
        tasks = state.get("tasks") or []
        idx = int(state.get("current_task_index") or 0)
        if idx >= len(tasks):
            return "Composing final study response"
        task_type = (tasks[idx] or {}).get("type")
        return {
            "explain": "Building tutor prompt",
            "summary": "Building summary prompt",
            "quiz_generate": "Generating structured quiz JSON",
            "study_plan": "Building study plan",
            "web_search": "Calling web search tool",
            "calculator": "Running calculator",
            "quiz_feedback": "Grading submitted quiz",
        }.get(task_type, "Building agent prompt")
    if last_node == "collect_task_output":
        return "Selecting next task"
    if last_node == "final_composer":
        return "Checking Arabic output"
    if last_node == "retrieve_docs":
        if state.get("next_action") == "final":
            return "Checking Arabic output"
        if route == "quiz_generate":
            return "Generating structured quiz JSON"
        if route == "study_plan":
            return "Building study plan"
        if route == "documents_plus_web":
            return "Calling web search tool"
        return "Building agent prompt"
    if last_node == "web_search":
        if route == "multi_task":
            return "Selecting next task"
        return "Building agent prompt" if state.get("next_action") != "final" else "Checking Arabic output"
    if last_node == "build_prompt":
        return "Calling selected LLM"
    if last_node in {"tutor_answer", "summary", "study_plan", "quiz_feedback"}:
        return "Checking Arabic output"
    if last_node == "arabic_guard":
        return "Checking sources and citations"
    if last_node == "citation_checker":
        return "Running deterministic evaluation"
    if last_node == "evaluation":
        return "Saving trace state"
    return "Working"


def _render_runtime_status(placeholder, started: float, last_node: str, state: dict[str, Any]) -> None:
    elapsed = round(perf_counter() - started, 1)
    completed = STAGE_LABELS.get(last_node, last_node)
    current = _next_stage(last_node, state)
    docs = len(state.get("docs") or [])
    tools = ", ".join(state.get("tools_used") or ["none"])
    route = state.get("route") or "pending"
    model_label = f"{state.get('llm_provider', 'llm')}:{state.get('llm_model', 'pending')}"
    error = state.get("error")
    error_line = f"<div>Last warning: {safe_text(error)}</div>" if error else ""
    tasks = state.get("tasks") or []
    current_task_index = int(state.get("current_task_index") or 0)
    task_lines = ""
    if tasks:
        rows = []
        for idx, task in enumerate(tasks):
            marker = "done" if idx < current_task_index else ("now" if idx == current_task_index else "next")
            rows.append(f"<span class='chat-meta'>{idx + 1}. {safe_text(task.get('title') or task.get('type'))} · {marker}</span>")
        task_lines = "<div class='runtime-task-list'>" + "<br>".join(rows) + "</div>"
    placeholder.markdown(
        f"""
        <div class="trace-step">
            <b>Runtime stage</b><br>
            <span class="chat-meta">Elapsed: {elapsed}s | Route: {safe_text(route)} | Model: {safe_text(model_label)}</span><br>
            <span class="chat-meta">Docs: {docs} | Tools: {safe_text(tools)}</span><br>
            <span class="chat-meta">Completed: {safe_text(completed)}</span><br>
            <span class="chat-meta">Now: {safe_text(current)}</span>
            {task_lines}
            {error_line}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _scroll_chat_to_bottom() -> None:
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const messages = Array.from(doc.querySelectorAll('[data-testid="stChatMessage"]'));
        const lastMessage = messages[messages.length - 1];
        if (lastMessage) {
          let el = lastMessage.parentElement;
          while (el && el !== doc.body) {
            const style = window.parent.getComputedStyle(el);
            const canScroll = el.scrollHeight > el.clientHeight + 24;
            const overflowY = style.overflowY;
            if (canScroll && (overflowY === 'auto' || overflowY === 'scroll')) {
              el.scrollTop = el.scrollHeight;
              break;
            }
            el = el.parentElement;
          }
        }
        </script>
        """,
        height=0,
    )


def _answer_stream(answer: str):
    text = answer or ""
    for idx in range(0, len(text), 36):
        yield text[idx : idx + 36]
        _scroll_chat_to_bottom()
        sleep(0.018)


def _stream_answer_preview(answer: str) -> str:
    text = answer or ""
    if not text:
        return ""
    if hasattr(st, "write_stream"):
        return st.write_stream(_answer_stream(text))

    placeholder = st.empty()
    chunks: list[str] = []
    for chunk in _answer_stream(text):
        chunks.append(chunk)
        placeholder.markdown("".join(chunks))
    return "".join(chunks)


def _invoke_graph(
    chat: dict,
    query: str,
    quiz: dict[str, Any] | None = None,
    user_answers: dict[str, str] | None = None,
    progress_placeholder=None,
) -> dict[str, Any]:
    initial_state = _initial_graph_state(chat, query, quiz=quiz, user_answers=user_answers)
    if progress_placeholder is not None:
        started = perf_counter()
        state: dict[str, Any] = initial_state
        progress_placeholder.info("Runtime stage: routing request...")
        for node_name, state in stream_study_graph(initial_state):
            _render_runtime_status(progress_placeholder, started, node_name, state)
        return state
    return run_study_graph(initial_state)


def _persist_graph_result(
    chat: dict,
    store: ChatStore,
    state: dict[str, Any],
    response_time_ms: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    evaluation = state.get("evaluation")
    trace = state.get("trace") or {}
    final_answer = state.get("final_answer") or ""

    store.record_assistant_result(
        chat["chat_id"],
        content=final_answer,
        agent=state.get("selected_agent"),
        docs=state.get("docs") or [],
        trace=trace,
        evaluation=evaluation,
        response_time_ms=response_time_ms,
        metadata=metadata,
    )

    st.session_state.last_trace = trace
    st.session_state.last_evaluation = evaluation
    st.session_state.last_prepared = {
        "route": state.get("route"),
        "selected_agent": state.get("selected_agent"),
        "tools_used": state.get("tools_used"),
        "prompt": "[hidden]",
    }


def _answer_label(answer: str) -> str:
    return answer if answer in {"A", "B", "C", "D"} else "A"


def _format_quiz_result(result: dict[str, Any]) -> str:
    lines = [
        "# نتيجة الاختبار",
        f"درجتك: {result.get('correct')} من {result.get('total')} ({result.get('percentage')}%).",
        "",
        "# تصحيح سريع",
    ]
    for idx, item in enumerate(result.get("details") or [], start=1):
        mark = "صحيح" if item.get("correct") else "خطأ"
        lines.append(
            f"- السؤال {idx}: {mark}. إجابتك: {item.get('user_answer') or 'بدون إجابة'}، "
            f"الإجابة الصحيحة: {item.get('correct_answer')}."
        )
    lines.extend(["", "اضغط Review feedback إذا أردت شرحا تعليميا مفصلا للأخطاء والمفاهيم الضعيفة."])
    return "\n".join(lines)


def _render_pending_quiz_feedback(chat: dict, store: ChatStore) -> None:
    history = chat.get("quiz_history") or []
    if not history:
        return
    latest = history[-1]
    if latest.get("feedback") or not latest.get("quiz_result"):
        return

    if not st.button("Review feedback", type="secondary", use_container_width=True):
        return

    started = perf_counter()
    runtime_placeholder = st.empty()
    state = _invoke_graph(
        chat,
        "راجع نتيجة الاختبار واشرح أخطائي",
        quiz=latest.get("quiz"),
        user_answers=latest.get("user_answers"),
        progress_placeholder=runtime_placeholder,
    )
    response_time_ms = round((perf_counter() - started) * 1000)
    latest["feedback"] = state.get("feedback")
    latest["feedback_trace_id"] = (state.get("trace") or {}).get("prompt_id")
    latest["feedback_evaluation_id"] = (state.get("evaluation") or {}).get("evaluation_id") if state.get("evaluation") else None
    history[-1] = latest
    store.update_chat(chat["chat_id"], quiz_history=history)
    _persist_graph_result(
        chat,
        store,
        state,
        response_time_ms,
        metadata={"quiz_result": state.get("quiz_result"), "feedback": state.get("feedback")},
    )
    st.rerun()


def _render_active_quiz(chat: dict, store: ChatStore) -> None:
    quiz = chat.get("active_quiz")
    if not quiz:
        return

    st.markdown("<div class='rtl'>", unsafe_allow_html=True)
    st.subheader(quiz.get("title") or "اختبار")
    with st.form(f"quiz_form_{quiz.get('quiz_id', chat['chat_id'])}"):
        answers: dict[str, str] = {}
        for idx, question in enumerate(quiz.get("questions") or [], start=1):
            qid = str(question.get("id") or f"q{idx}")
            st.markdown(f"**{idx}. {safe_text(question.get('question', ''))}**")
            choices = question.get("choices") or {}
            labels = [
                f"{letter}. {choices.get(letter, '')}"
                for letter in ("A", "B", "C", "D")
                if choices.get(letter) is not None
            ]
            selected = st.radio(
                "اختر الإجابة",
                options=labels,
                index=0,
                key=f"quiz_{quiz.get('quiz_id')}_{qid}",
                label_visibility="collapsed",
            )
            answers[qid] = _answer_label(selected.split(".", 1)[0].strip())

        submitted = st.form_submit_button("Submit", type="primary", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)
    if not submitted:
        return

    started = perf_counter()
    result = QuizGradingTool().grade(quiz, answers)
    response_time_ms = round((perf_counter() - started) * 1000)

    store.add_message(
        chat["chat_id"],
        role="user",
        content="تم إرسال إجابات الاختبار.",
        metadata={"quiz_submission": {"quiz_id": quiz.get("quiz_id"), "answers": answers}},
    )
    history = chat.get("quiz_history") or []
    history.append(
        {
            "quiz": quiz,
            "user_answers": answers,
            "quiz_result": result,
            "feedback": None,
            "trace_id": None,
            "evaluation_id": None,
        }
    )
    store.update_chat(chat["chat_id"], active_quiz=None, quiz_history=history)
    store.add_message(
        chat["chat_id"],
        role="assistant",
        content=_format_quiz_result(result),
        agent="QuizGradingTool",
        docs=[],
        metadata={"quiz_result": result, "feedback_pending": True},
    )
    updated_chat = store.ensure_chat(chat["chat_id"])
    stats = updated_chat.setdefault("stats", {})
    stats["total_response_time_ms"] = int(stats.get("total_response_time_ms", 0) or 0) + response_time_ms
    store.update_chat(chat["chat_id"], stats=stats)
    st.rerun()


def render_chat_view(chat: dict, store: ChatStore) -> None:
    chat_title = safe_text(chat.get("title", "Study session"))
    st.markdown(
        f"""
        <div class="topbar">
            <div class="chat-title-row">
                <div class="chat-title-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5v-9Z"></path>
                    </svg>
                </div>
                <div>
                    <h1>{chat_title}</h1>
                    <div class="muted">Private chat workspace with isolated files, graph workflow, traces, quizzes, and evaluation.</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='control-strip'>", unsafe_allow_html=True)
    current_scope = st.session_state.source_scope if st.session_state.source_scope in SOURCE_SCOPES else SOURCE_SCOPES[0]
    model_keys = list(MODEL_PROFILES.keys())
    current_model = st.session_state.model_profile if st.session_state.model_profile in MODEL_PROFILES else model_keys[0]
    source_col, model_col = st.columns([0.46, 0.54])
    with source_col:
        st.session_state.source_scope = st.selectbox("Source mode", SOURCE_SCOPES, index=SOURCE_SCOPES.index(current_scope))
    with model_col:
        st.session_state.model_profile = st.selectbox(
            "Model",
            model_keys,
            index=model_keys.index(current_model),
            format_func=lambda key: MODEL_PROFILES[key]["label"],
        )
        selected_settings = resolve_model_profile(profile=st.session_state.model_profile)
        configured, config_message = model_is_configured(selected_settings["provider"])
        if not configured:
            st.caption(config_message)
    st.session_state.web_search_enabled = st.session_state.source_scope in {"Web only", "Documents + Web"}
    st.markdown("</div>", unsafe_allow_html=True)

    message_area = st.container(height=620, border=False)
    with message_area:
        messages = chat.get("messages", [])
        hidden_count = max(len(messages) - CHAT_MESSAGE_RENDER_LIMIT, 0)
        if hidden_count:
            st.caption(f"Showing latest {CHAT_MESSAGE_RENDER_LIMIT} messages. Older messages remain saved in this chat.")
        for message in messages[-CHAT_MESSAGE_RENDER_LIMIT:]:
            with st.chat_message(message.get("role", "assistant")):
                content = message.get("content", "")
                if message.get("role") == "assistant":
                    st.markdown(content)
                else:
                    st.markdown(content)

        if not chat.get("messages"):
            st.info("Upload files for this chat, build the index, then ask a study question or request a quiz or study plan.")

        _render_active_quiz(chat, store)
        _render_pending_quiz_feedback(chat, store)
        _scroll_chat_to_bottom()

    query = st.chat_input("Ask about your files...")
    if not query:
        return

    store.add_message(chat["chat_id"], role="user", content=query)
    with message_area:
        with st.chat_message("user"):
            st.markdown(query)
        _scroll_chat_to_bottom()

    started = perf_counter()
    runtime_placeholder = st.empty()
    state = _invoke_graph(chat, query, progress_placeholder=runtime_placeholder)
    response_time_ms = round((perf_counter() - started) * 1000)
    runtime_placeholder.empty()

    with message_area:
        with st.chat_message("assistant"):
            _stream_answer_preview(state.get("final_answer") or "")
        _scroll_chat_to_bottom()

    metadata = {}
    if state.get("quiz"):
        metadata["quiz"] = state.get("quiz")
        store.update_chat(chat["chat_id"], active_quiz=state.get("quiz"))

    _persist_graph_result(chat, store, state, response_time_ms, metadata=metadata or None)
    if state.get("quiz"):
        with message_area:
            fresh_chat = store.ensure_chat(chat["chat_id"])
            _render_active_quiz(fresh_chat, store)
            _scroll_chat_to_bottom()

    # The right sidebar is rendered before the prompt runs, so refresh once
    # after persisting to show the latest trace/evaluation for all routes.
    st.rerun()

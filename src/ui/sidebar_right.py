"""Right-side chat dashboard for files, traces, evaluations, and stats.

The right sidebar is per-chat state only. Global preferences live in the left
sidebar because they apply across all chats.
"""

import os

import streamlit as st

from src.chat.chat_store import ChatStore
from src.files.indexing_jobs import start_indexing_job
from src.files.indexing_status import STATUS_COLORS, STATUS_LABELS, IndexingStatus
from src.ui.components import format_bytes, safe_text, short_name
from src.ui.upload_panel import render_file_delete_button, render_upload_controls


RIGHT_SIDEBAR_HEIGHT = int(os.getenv("RIGHT_SIDEBAR_HEIGHT", "900"))


def _badge(status: str) -> str:
    """Render a compact indexing-status badge as HTML."""

    color = STATUS_COLORS.get(status, "blue")
    label = STATUS_LABELS.get(status, status)
    return f"<span class='badge {color}'>{safe_text(label)}</span>"


def _indexing_progress(step: str) -> int:
    """Map an indexing status message to a progress-bar percentage."""

    text = (step or "").lower()
    if "checking" in text:
        return 12
    if "loading" in text:
        return 24
    if "splitting" in text:
        return 42
    if "embedding" in text:
        return 68
    if "saving" in text:
        return 88
    if "ready" in text:
        return 100
    return 35


def _latest_trace(chat: dict) -> dict | None:
    """Return the latest trace for a chat, if one exists."""

    traces = chat.get("traces") or []
    return traces[-1] if traces else None


def _latest_evaluation(chat: dict, trace: dict | None = None) -> dict | None:
    """Return the evaluation that best matches the latest assistant answer."""

    evaluations = chat.get("evaluations") or []
    if not evaluations:
        return None

    trace_evaluation = trace.get("evaluation_result") if trace else None
    if isinstance(trace_evaluation, dict) and trace_evaluation.get("evaluation_id"):
        target_id = trace_evaluation["evaluation_id"]
        for evaluation in reversed(evaluations):
            if evaluation.get("evaluation_id") == target_id:
                return evaluation

    latest_assistant = None
    for message in reversed(chat.get("messages") or []):
        if message.get("role") == "assistant":
            latest_assistant = message
            break

    if latest_assistant and latest_assistant.get("evaluation_id"):
        target_id = latest_assistant["evaluation_id"]
        for evaluation in reversed(evaluations):
            if evaluation.get("evaluation_id") == target_id:
                return evaluation

    return evaluations[-1]


def _current_process(chat: dict) -> tuple[dict | None, dict | None]:
    """Return the latest trace and its matching evaluation."""

    trace = _latest_trace(chat)
    evaluation = _latest_evaluation(chat, trace)
    return trace, evaluation


def _metric_color(value: float | None, lower_is_better: bool = False) -> str:
    """Choose a display color for a normalized metric value."""

    if value is None:
        return "#64748b"
    score = 1 - value if lower_is_better else value
    if score >= 0.8:
        return "#15803d"
    if score >= 0.55:
        return "#b45309"
    return "#b91c1c"


def _metric_text(value) -> str:
    """Format a metric value as a percentage or ``N/A``."""

    if value is None:
        return "N/A"
    try:
        return f"{round(float(value) * 100)}%"
    except Exception:
        return "N/A"


def _render_metric_window(title: str, result: dict | None, metrics: list[tuple[str, str, bool]]) -> None:
    """Render one RAGAS or DeepEval metric panel."""

    st.markdown(f"<div class='section-title'>{safe_text(title)}</div>", unsafe_allow_html=True)
    if not result:
        st.caption("No metrics recorded.")
        return
    status = result.get("status", "unknown")
    if status != "ok":
        st.caption(f"Status: {status}")
        if status == "disabled":
            st.caption("External evaluator is manual for fast chat responses. Use Run RAGAS / DeepEval on an assistant message when you need it.")
            return
        message = result.get("message") or result.get("error")
        if message:
            st.caption(str(message)[:220])
        return
    if result.get("evaluation_language") == "english":
        st.caption("Evaluation language: English judge copy of the answer.")
    elif (result.get("translation") or {}).get("status") in {"error", "unavailable"}:
        st.caption((result.get("translation") or {}).get("message", "Evaluation translation was skipped.")[:220])

    for key, label, lower_is_better in metrics:
        value = result.get(key)
        color = _metric_color(float(value) if isinstance(value, (int, float)) else None, lower_is_better)
        st.markdown(
            f"""
            <div class="trace-step">
                <b>{safe_text(label)}</b>
                <span style="float:right;color:{color};font-weight:700">{safe_text(_metric_text(value))}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        reason = (result.get("reasons") or {}).get(key)
        evidence = (result.get("evidence") or {}).get(key)
        if reason or evidence:
            with st.expander(f"Why {label}?"):
                if reason:
                    st.caption(reason)
                if isinstance(evidence, dict):
                    for evidence_key, evidence_value in evidence.items():
                        st.markdown(f"**{safe_text(evidence_key.replace('_', ' ').title())}**")
                        if isinstance(evidence_value, list):
                            if evidence_value:
                                for item in evidence_value:
                                    st.caption(f"- {item}")
                            else:
                                st.caption("None detected.")
                        else:
                            st.caption(str(evidence_value))
    notes = result.get("notes")
    if notes:
        st.caption(notes)


@st.fragment(run_every="6s")
def _render_uploaded_files_panel(chat_id: str, store: ChatStore) -> dict:
    """Render upload/index controls and return the refreshed chat."""

    chat = store.ensure_chat(chat_id)
    files = chat.get("files", [])
    file_summary = f"{len(files)} file(s) - {chat.get('indexing_status', IndexingStatus.EMPTY)}"
    with st.container(border=True):
        st.markdown(
            "<span class='config-surface-marker'></span><div class='config-kicker'>Source Configuration</div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Workspace Files**")
        st.caption(file_summary)
        st.caption("Configuration area: add, remove, and index the files used by this chat.")
        render_upload_controls(chat, store)

        st.markdown(_badge(chat.get("indexing_status", IndexingStatus.EMPTY)), unsafe_allow_html=True)
        if chat.get("indexing_step"):
            st.caption(chat["indexing_step"])
        if chat.get("indexing_status") == IndexingStatus.INDEXING:
            st.progress(_indexing_progress(chat.get("indexing_step", "")))
            st.caption("Indexing is running in the background.")

        if files:
            for file_meta in files:
                col_a, col_b = st.columns([0.82, 0.18])
                with col_a:
                    st.markdown(
                        f"""
                        <div class="file-card">
                            <div class="file-name">{safe_text(short_name(file_meta.get("original_name", "")))}</div>
                            <div class="chat-meta">{safe_text(file_meta.get("extension", ""))} - {format_bytes(file_meta.get("size_bytes"))}</div>
                            {_badge(file_meta.get("indexing_status", chat.get("indexing_status", "")))}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_b:
                    render_file_delete_button(chat["chat_id"], file_meta["file_id"], store)
        else:
            st.caption("No files in this chat.")

        if files and chat.get("indexing_status") == IndexingStatus.FAILED:
            if st.button("Retry indexing", width="stretch", type="primary"):
                start_indexing_job(chat["chat_id"], store, step="Retrying index", force=True)
                st.rerun()
    return chat


def _force_right_sidebar_scroll() -> None:
    """Ensure the generated Streamlit right dashboard container scrolls.

    Streamlit wraps height containers in generated DOM elements whose exact
    attributes can shift between versions. The helper marks the nearest wrapper
    around ``right-dashboard-scroll-marker`` as the scroll owner after render.
    """

    st.iframe(
        """
        <script>
        const doc = window.parent.document;
        function applyRightScroll() {
          const marker = doc.querySelector('.right-dashboard-scroll-marker');
          if (!marker) return;

          const column = marker.closest('[data-testid="column"]');
          if (column) {
            column.style.height = 'calc(100vh - 1.5rem)';
            column.style.maxHeight = 'calc(100vh - 1.5rem)';
            column.style.overflow = 'hidden';
            column.style.alignSelf = 'flex-start';
          }

          let scrollEl = marker.parentElement;
          while (scrollEl && scrollEl !== column) {
            const style = window.parent.getComputedStyle(scrollEl);
            const testId = scrollEl.getAttribute('data-testid') || '';
            const hasHeight = scrollEl.style.height || style.maxHeight !== 'none';
            const isStreamlitBox = testId === 'stVerticalBlockBorderWrapper';
            if (hasHeight || isStreamlitBox || style.overflowY === 'auto' || style.overflowY === 'scroll') {
              break;
            }
            scrollEl = scrollEl.parentElement;
          }

          if (!scrollEl || scrollEl === column) {
            scrollEl = marker.parentElement;
          }

          if (scrollEl) {
            scrollEl.style.height = 'calc(100vh - 1.5rem)';
            scrollEl.style.maxHeight = 'calc(100vh - 1.5rem)';
            scrollEl.style.minHeight = '0';
            scrollEl.style.overflowY = 'auto';
            scrollEl.style.overflowX = 'hidden';
            scrollEl.style.boxSizing = 'border-box';
            scrollEl.style.paddingRight = '4px';
            scrollEl.style.paddingBottom = '12px';
          }
        }

        applyRightScroll();
        window.parent.requestAnimationFrame(applyRightScroll);
        setTimeout(applyRightScroll, 200);
        setTimeout(applyRightScroll, 800);
        </script>
        """,
        height=1,
    )


def _render_right_dashboard_body(chat: dict, store: ChatStore) -> None:
    """Render all per-chat right dashboard sections."""

    chat = _render_uploaded_files_panel(chat["chat_id"], store)
    trace, evaluation = _current_process(chat)

    agent_summary = trace.get("selected_agent", "No route yet") if trace else "Ask to see routing"
    with st.expander("Agent / Tools", expanded=False):
        st.caption(agent_summary)
        if trace:
            st.write(f"Selected agent: **{trace.get('selected_agent', 'N/A')}**")
            llm = trace.get("llm") or {}
            if llm:
                st.write(f"Model: **{llm.get('provider', 'llm')} / {llm.get('model', 'unknown')}**")
            route = trace.get("route") or ["LangGraph", trace.get("selected_agent", "N/A")]
            st.caption(" -> ".join(route))
            st.write(f"Tools: {', '.join(trace.get('tools_used') or ['None'])}")
            st.write(f"Retrieved docs: {len(trace.get('retrieved_docs') or [])}")
            tool_calls = trace.get("tool_calls") or (trace.get("graph_state_summary") or {}).get("tool_calls") or []
            if tool_calls:
                st.caption("LLM function calls")
                for call in tool_calls:
                    st.caption(f"- {call.get('tool_name', 'none')}: {call.get('reasoning', '')}")
        else:
            st.caption("Ask a question to see routing.")

    with st.expander("Reflection / Critic", expanded=False):
        st.caption("Quality checks")
        if trace:
            summary = trace.get("graph_state_summary") or {}
            reflection = trace.get("reflection") or {}
            critic = trace.get("critic") or {}
            st.caption(f"Reflection: {'Enabled' if summary.get('reflection_enabled') else 'Disabled'}")
            if reflection:
                st.caption(f"Reflection status: {reflection.get('status', 'ok')}")
                if reflection.get("passed") is not None:
                    st.caption(f"Reflection passed: {reflection.get('passed')}")
                for issue in (reflection.get("issues") or [])[:3]:
                    st.caption(f"- {issue}")
            st.caption(f"Critic: {'Enabled' if summary.get('critic_enabled') else 'Disabled'}")
            if critic:
                st.caption(f"Critic status: {critic.get('status', 'ok')}")
                if critic.get("risk_level"):
                    st.caption(f"Risk level: {critic.get('risk_level')}")
                if critic.get("passed") is not None:
                    st.caption(f"Critic passed: {critic.get('passed')}")
                for item in (critic.get("criticism") or [])[:3]:
                    st.caption(f"- {item}")
        else:
            st.caption("No reflection or critic trace yet.")

    trace_count = len((trace or {}).get("component_steps", [])) if trace else 0
    with st.expander("Trace", expanded=False):
        st.caption(f"{trace_count} recorded step(s)")
        if trace:
            for step in trace.get("component_steps", [])[-4:]:
                st.markdown(
                    f"<div class='trace-step'><b>{safe_text(step.get('name'))}</b><br>"
                    f"<span class='chat-meta'>{safe_text(step.get('status'))} - {safe_text(step.get('duration_ms'))} ms</span></div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No prompt trace yet.")

    score_summary = f"Score {evaluation.get('overall_score', 'N/A')}" if evaluation else "No score yet"
    with st.expander("Evaluation", expanded=False):
        st.caption(score_summary)
        if evaluation:
            st.metric("Score", evaluation.get("overall_score", "N/A"))
            deterministic = evaluation.get("deterministic") if isinstance(evaluation.get("deterministic"), dict) else evaluation
            rubric = deterministic.get("rubric", {})
            reasons = deterministic.get("rubric_reasons", {})
            rows = [
                {
                    "Criterion": name,
                    "Score": f"{score}/10",
                    "Reason": reasons.get(name, "No deterministic reason recorded."),
                }
                for name, score in rubric.items()
            ]
            st.dataframe(rows, width="stretch", hide_index=True, height=260)
            with st.expander("Score Reasons"):
                for row in rows:
                    st.markdown(f"**{row['Criterion']} - {row['Score']}**")
                    st.caption(row["Reason"])
            if evaluation.get("recommendations"):
                st.caption("Recommendations")
                for item in deterministic.get("recommendations", []):
                    st.caption(f"- {item}")
            for check in deterministic.get("deterministic_checks", []):
                st.caption(f"{check['name']}: {'passed' if check.get('passed') else 'failed'}")
            if deterministic.get("llm_judge"):
                judge = deterministic["llm_judge"]
                judge_text = judge.get("status") or judge.get("message") or judge.get("error") or judge.get("comment", "")
                st.caption(f"Judge: {judge.get('mode')} - {judge_text[:140]}")
        else:
            st.caption("No evaluation yet.")

    with st.expander("RAG Evaluations", expanded=False):
        st.caption("RAGAS / DeepEval metrics")
        if evaluation:
            _render_metric_window(
                "RAGAS",
                evaluation.get("ragas"),
                [
                    ("faithfulness", "Faithfulness", False),
                    ("answer_relevancy", "Answer Relevancy", False),
                    ("context_precision", "Context Precision", False),
                    ("context_recall", "Context Recall", False),
                ],
            )
            st.divider()
            _render_metric_window(
                "DeepEval",
                evaluation.get("deepeval"),
                [
                    ("correctness", "Correctness", False),
                    ("relevance", "Relevance", False),
                    ("hallucination", "Hallucination", True),
                    ("helpfulness", "Helpfulness", False),
                ],
            )
        else:
            st.caption("Ask a question to generate RAG evaluation metrics.")

    stats = chat.get("stats", {})
    with st.expander("Stats", expanded=False):
        st.caption(f"{safe_text(stats.get('prompts_count', 0))} prompt(s)")
        st.write(f"Prompts: **{stats.get('prompts_count', 0)}**")
        total_ms = int(stats.get("total_response_time_ms", 0) or 0)
        prompts = max(int(stats.get("prompts_count", 0) or 0), 1)
        st.write(f"Avg response: **{round(total_ms / prompts)} ms**")
        st.write(f"Tokens: **{stats.get('tokens_total') or 'N/A'}**")


def render_right_sidebar(chat: dict, store: ChatStore) -> None:
    """Render the right dashboard for the active chat.

    Args:
        chat:
            Active chat dictionary.

        store:
            Persistent chat store used for file/indexing actions.

    Side effects:
        May start indexing jobs, delete files, or rerun Streamlit when a user
        clicks dashboard controls.
    """

    st.markdown("<div class='right-dashboard-root'></div>", unsafe_allow_html=True)
    with st.container(height=RIGHT_SIDEBAR_HEIGHT, border=False):
        st.markdown("<div class='right-dashboard-scroll-marker'></div>", unsafe_allow_html=True)
        _render_right_dashboard_body(chat, store)
    _force_right_sidebar_scroll()

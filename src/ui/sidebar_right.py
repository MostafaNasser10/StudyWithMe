import streamlit as st

from src.chat.chat_store import ChatStore
from src.files.indexing_jobs import start_indexing_job
from src.files.indexing_status import STATUS_COLORS, STATUS_LABELS, IndexingStatus
from src.ui.components import format_bytes, safe_text, short_name
from src.ui.upload_panel import render_file_delete_button, render_upload_controls


def _badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "blue")
    label = STATUS_LABELS.get(status, status)
    return f"<span class='badge {color}'>{safe_text(label)}</span>"


def _indexing_progress(step: str) -> int:
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
    traces = chat.get("traces") or []
    return traces[-1] if traces else None


def _latest_evaluation(chat: dict, trace: dict | None = None) -> dict | None:
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
    trace = _latest_trace(chat)
    evaluation = _latest_evaluation(chat, trace)
    return trace, evaluation


def _metric_color(value: float | None, lower_is_better: bool = False) -> str:
    if value is None:
        return "#64748b"
    score = 1 - value if lower_is_better else value
    if score >= 0.8:
        return "#15803d"
    if score >= 0.55:
        return "#b45309"
    return "#b91c1c"


def _metric_text(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{round(float(value) * 100)}%"
    except Exception:
        return "N/A"


def _render_metric_window(title: str, result: dict | None, metrics: list[tuple[str, str, bool]]) -> None:
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


@st.fragment(run_every="2s")
def _render_uploaded_files_panel(chat_id: str, store: ChatStore) -> dict:
    chat = store.ensure_chat(chat_id)
    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Uploaded files</div>", unsafe_allow_html=True)
    render_upload_controls(chat, store)

    st.markdown(_badge(chat.get("indexing_status", IndexingStatus.EMPTY)), unsafe_allow_html=True)
    if chat.get("indexing_step"):
        st.caption(chat["indexing_step"])
    if chat.get("indexing_status") == IndexingStatus.INDEXING:
        st.progress(_indexing_progress(chat.get("indexing_step", "")))
        st.caption("Indexing is running in the background.")

    files = chat.get("files", [])
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
    st.markdown("</div>", unsafe_allow_html=True)
    return chat


def render_right_sidebar(chat: dict, store: ChatStore) -> None:
    chat = _render_uploaded_files_panel(chat["chat_id"], store)
    trace, evaluation = _current_process(chat)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Agent / tools</div>", unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Reflection / Critic</div>", unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Trace</div>", unsafe_allow_html=True)
    if trace:
        for step in trace.get("component_steps", [])[-6:]:
            st.markdown(
                f"<div class='trace-step'><b>{safe_text(step.get('name'))}</b><br>"
                f"<span class='chat-meta'>{safe_text(step.get('status'))} - {safe_text(step.get('duration_ms'))} ms</span></div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No prompt trace yet.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Evaluation</div>", unsafe_allow_html=True)
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
        with st.expander("Why these scores?"):
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
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>RAG Evaluations</div>", unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Stats</div>", unsafe_allow_html=True)
    stats = chat.get("stats", {})
    st.write(f"Prompts: **{stats.get('prompts_count', 0)}**")
    total_ms = int(stats.get("total_response_time_ms", 0) or 0)
    prompts = max(int(stats.get("prompts_count", 0) or 0), 1)
    st.write(f"Avg response: **{round(total_ms / prompts)} ms**")
    st.write(f"Tokens: **{stats.get('tokens_total') or 'N/A'}**")
    st.markdown("</div>", unsafe_allow_html=True)

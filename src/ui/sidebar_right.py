import streamlit as st

from src.chat.chat_store import ChatStore
from src.files.indexing_status import STATUS_COLORS, STATUS_LABELS, IndexingStatus
from src.ui.components import format_bytes, safe_text, short_name
from src.ui.upload_panel import render_file_delete_button, render_upload_controls
from src.vector_store import rebuild_all


def _badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "blue")
    label = STATUS_LABELS.get(status, status)
    return f"<span class='badge {color}'>{safe_text(label)}</span>"


def render_right_sidebar(chat: dict, store: ChatStore) -> None:
    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Uploaded files</div>", unsafe_allow_html=True)
    render_upload_controls(chat, store)
    st.markdown(_badge(chat.get("indexing_status", IndexingStatus.EMPTY)), unsafe_allow_html=True)
    if chat.get("indexing_step"):
        st.caption(chat["indexing_step"])

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

    if files and st.button("Build / refresh index", use_container_width=True, type="primary"):
        store.update_chat(chat["chat_id"], indexing_status=IndexingStatus.INDEXING, indexing_step="Loading documents")
        with st.spinner("Indexing this chat..."):
            result = rebuild_all(chat["chat_id"])
        new_chat = store.ensure_chat(chat["chat_id"])
        for item in new_chat.get("files", []):
            item["indexing_status"] = result.status
        store.update_chat(
            chat["chat_id"],
            files=new_chat.get("files", []),
            indexing_status=result.status,
            indexing_step=result.step,
        )
        st.session_state.last_index_result = result.to_dict()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    prepared = st.session_state.get("last_prepared")
    trace = st.session_state.get("last_trace")
    evaluation = st.session_state.get("last_evaluation")

    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Agent / tools</div>", unsafe_allow_html=True)
    if prepared:
        st.write(f"Selected agent: **{prepared.get('selected_agent', 'N/A')}**")
        st.caption(" -> ".join(prepared.get("route", [])))
        st.write(f"Tools: {', '.join(prepared.get('tools_used') or ['None'])}")
        st.write(f"Retrieved docs: {len(prepared.get('docs', []))}")
    else:
        st.caption("Ask a question to see routing.")
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
        for name, score in list(evaluation.get("rubric", {}).items())[:5]:
            st.caption(f"{name}: {score}/10")
        for check in evaluation.get("deterministic_checks", []):
            st.caption(f"{check['name']}: {'passed' if check.get('passed') else 'failed'}")
        if evaluation.get("llm_judge"):
            judge = evaluation["llm_judge"]
            judge_text = judge.get("status") or judge.get("message") or judge.get("error") or judge.get("comment", "")
            st.caption(f"Judge: {judge.get('mode')} - {judge_text[:140]}")
    else:
        st.caption("No evaluation yet.")
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

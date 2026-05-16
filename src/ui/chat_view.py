from __future__ import annotations

from dataclasses import asdict
from queue import Empty, Queue
from threading import Thread
from time import perf_counter

import streamlit as st

from src.agents.supervisor import Supervisor
from src.chat.chat_store import ChatStore
from src.config import SOURCE_SCOPES
from src.evaluation.response_evaluator import evaluate_response
from src.tracing.tracer import Tracer
from src.ui.components import safe_text


WAITING_MESSAGES = [
    "اصبر يا حبيبي...",
    "اعملك شاي لحد ما اخلص...",
    "اصبر الدنيا مش هتطير...",
]


def _stream_with_waiting(supervisor: Supervisor, prepared, placeholder) -> str:
    queue: Queue[tuple[str, str | None]] = Queue()

    def worker() -> None:
        try:
            for chunk in supervisor.stream_prepared(prepared):
                queue.put(("chunk", chunk))
            queue.put(("done", None))
        except Exception as exc:
            queue.put(("error", str(exc)))

    Thread(target=worker, daemon=True).start()

    chunks: list[str] = []
    waiting_index = 0
    done = False
    while not done:
        try:
            kind, payload = queue.get(timeout=1.25)
        except Empty:
            if not chunks:
                placeholder.markdown(
                    f"<div class='waiting-answer rtl'>{WAITING_MESSAGES[waiting_index % len(WAITING_MESSAGES)]}</div>",
                    unsafe_allow_html=True,
                )
                waiting_index += 1
            continue

        if kind == "chunk" and payload:
            chunks.append(payload)
            placeholder.markdown(f"<div class='rtl'>{''.join(chunks)}</div>", unsafe_allow_html=True)
        elif kind == "error":
            raise RuntimeError(payload or "Streaming failed")
        elif kind == "done":
            done = True

    return "".join(chunks)


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
                    <div class="muted">Private chat workspace with isolated files, streaming answers, traces, and evaluation.</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='control-strip'>", unsafe_allow_html=True)
    current_scope = st.session_state.source_scope if st.session_state.source_scope in SOURCE_SCOPES else SOURCE_SCOPES[0]
    st.session_state.source_scope = st.selectbox("Source mode", SOURCE_SCOPES, index=SOURCE_SCOPES.index(current_scope))
    st.session_state.web_search_enabled = st.session_state.source_scope in {"Web only", "Documents + Web"}
    st.markdown("</div>", unsafe_allow_html=True)

    message_area = st.container(height=620, border=False)
    with message_area:
        for message in chat.get("messages", []):
            with st.chat_message(message.get("role", "assistant")):
                content = message.get("content", "")
                if message.get("role") == "assistant":
                    st.markdown(f"<div class='rtl'>{content}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(content)

        if not chat.get("messages"):
            st.info("Upload files for this chat, build the index, then ask a study question or request a quiz or study plan.")

    query = st.chat_input("Ask about your files...")
    if not query:
        return

    store.add_message(chat["chat_id"], role="user", content=query)
    with message_area:
        with st.chat_message("user"):
            st.markdown(query)

    supervisor = Supervisor()
    tracer = Tracer(chat["chat_id"], query)
    response_started = perf_counter()

    with tracer.step("Supervisor route", query):
        prepared = supervisor.prepare(
            query,
            chat_id=chat["chat_id"],
            source_scope=st.session_state.source_scope,
            web_enabled=st.session_state.web_search_enabled,
        )

    tracer.set_agent(prepared.selected_agent)
    tracer.set_docs(prepared.docs)
    for tool in prepared.tools_used:
        tracer.add_tool(tool)

    st.session_state.last_prepared = {**asdict(prepared), "prompt": "[hidden]"}

    with message_area:
        with st.chat_message("assistant"):
            placeholder = st.empty()
            with tracer.step("Streaming LLM response", prepared.selected_agent):
                raw_answer = _stream_with_waiting(supervisor, prepared, placeholder)

            with tracer.step("Arabic guard and sources", "post-process final answer"):
                final_answer = supervisor.finalize_answer(raw_answer, query, prepared)
            placeholder.markdown(f"<div class='rtl'>{final_answer}</div>", unsafe_allow_html=True)

    response_time_ms = round((perf_counter() - response_started) * 1000)
    evaluation_mode = st.session_state.evaluation_mode
    if evaluation_mode == "disabled":
        evaluation_mode = "deterministic"

    with tracer.step("Response evaluation", evaluation_mode):
        evaluation = evaluate_response(
            query=query,
            answer=final_answer,
            docs=prepared.docs,
            tools_used=prepared.tools_used,
            mode=evaluation_mode,
            web_sources=prepared.web_sources,
        )
        store.append_evaluation(chat["chat_id"], evaluation)

    trace = tracer.finish(final_answer=final_answer, evaluation_result=evaluation)
    trace["timings_ms"].update(prepared.timings_ms)
    trace["timings_ms"]["total_response_ms"] = response_time_ms
    trace["route"] = prepared.route
    trace["web_sources"] = prepared.web_sources
    store.append_trace(chat["chat_id"], trace)

    store.add_message(
        chat["chat_id"],
        role="assistant",
        content=final_answer,
        agent=prepared.selected_agent,
        docs=prepared.docs,
        trace_id=trace["prompt_id"],
        evaluation_id=evaluation.get("evaluation_id") if evaluation else None,
    )

    updated_chat = store.ensure_chat(chat["chat_id"])
    stats = updated_chat.setdefault("stats", {})
    stats["total_response_time_ms"] = int(stats.get("total_response_time_ms", 0) or 0) + response_time_ms
    store.update_chat(chat["chat_id"], stats=stats)

    st.session_state.last_trace = trace
    st.session_state.last_evaluation = evaluation
    st.rerun()


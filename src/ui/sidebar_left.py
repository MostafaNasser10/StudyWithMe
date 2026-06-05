from __future__ import annotations

import base64
import os
from pathlib import Path

import streamlit as st

from src.chat.chat_store import ChatStore
from src.files.file_manager import delete_chat_assets
from src.memory.preference_memory import add_preference, delete_preference, load_preferences


LOGO_PATH = Path("assets") / "logo.png"
CHAT_LIST_RENDER_LIMIT = int(os.getenv("CHAT_LIST_RENDER_LIMIT", "28"))


@st.cache_data(show_spinner=False)
def _sidebar_logo() -> str | None:
    if not LOGO_PATH.exists():
        return None
    return base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")


def _activate_next_chat(store: ChatStore) -> None:
    remaining = store.list_chats()
    if remaining:
        st.session_state.active_chat_id = remaining[0]["chat_id"]
    else:
        st.session_state.active_chat_id = store.create_chat()["chat_id"]


def _delete_one_chat(store: ChatStore, chat_id: str) -> None:
    delete_chat_assets(chat_id)
    store.delete_chat(chat_id)
    if st.session_state.get("active_chat_id") == chat_id:
        _activate_next_chat(store)


def _clear_all_chats(store: ChatStore) -> None:
    for chat in store.list_chats():
        delete_chat_assets(chat["chat_id"])
        store.delete_chat(chat["chat_id"])
    st.session_state.active_chat_id = store.create_chat()["chat_id"]
    st.session_state.editing_chat_id = None


def _render_long_term_memory_panel() -> None:
    preferences = load_preferences()
    with st.container(border=True):
        st.markdown(
            "<span class='config-surface-marker'></span><div class='config-kicker'>Global Configuration</div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Long-Term Memory**")
        st.caption(f"{len(preferences)} saved preference(s)")
        preference_text = st.text_input(
            "Add preference",
            key="long_term_memory_preference_text",
            placeholder="Example: Add an Automotive example in every explanation",
        )
        if st.button("Add", key="add_long_term_preference", width="stretch"):
            add_preference(preference_text)
            st.rerun()

        if not preferences:
            st.caption("No saved preferences.")
        for idx, preference in enumerate(preferences):
            col_a, col_b = st.columns([0.76, 0.24])
            with col_a:
                st.caption(preference)
            with col_b:
                if st.button("×", key=f"delete_long_term_preference_{idx}"):
                    delete_preference(idx)
                    st.rerun()


def render_left_sidebar(store: ChatStore) -> None:
    with st.sidebar:
        logo = _sidebar_logo()
        logo_html = (
            f"<img class='sidebar-logo' src='data:image/png;base64,{logo}' alt='StudyWithMe logo'>"
            if logo
            else "<div class='sidebar-logo-fallback'>SW</div>"
        )
        st.markdown(
            f"""
            <div class="sidebar-brand">
                {logo_html}
                <div>
                    <div class="app-title">StudyWithMe</div>
                    <div class="app-subtitle">Arabic AI Tutor</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Home", width="stretch"):
            st.session_state.page = "Home"
            st.rerun()

        if st.button("New chat", width="stretch", type="primary"):
            chat = store.create_chat()
            st.session_state.active_chat_id = chat["chat_id"]
            st.session_state.page = "Chat"
            st.session_state.editing_chat_id = None
            st.rerun()

        st.markdown("<div class='sidebar-section-label'>Recent chats</div>", unsafe_allow_html=True)

        st.session_state.setdefault("editing_chat_id", None)
        chats = store.list_chats()
        visible_chats = chats[:CHAT_LIST_RENDER_LIMIT]
        if len(chats) > CHAT_LIST_RENDER_LIMIT:
            st.caption(f"Showing latest {CHAT_LIST_RENDER_LIMIT} chats.")
        for chat in visible_chats:
            chat_id = chat["chat_id"]
            active = chat_id == st.session_state.active_chat_id
            title = chat.get("title") or "New Conversation"

            st.markdown(
                f"<div class='chat-card-row {'active' if active else ''}'>",
                unsafe_allow_html=True,
            )
            open_col, edit_col, delete_col = st.columns([0.74, 0.13, 0.13], gap="small")
            with open_col:
                if st.button(
                    title[:46],
                    key=f"open_{chat_id}",
                    width="stretch",
                    type="primary" if active else "secondary",
                ):
                    st.session_state.active_chat_id = chat_id
                    st.session_state.editing_chat_id = None
                    st.rerun()
            with edit_col:
                if st.button("✎", key=f"edit_{chat_id}", help="Rename chat", width="stretch"):
                    st.session_state.editing_chat_id = chat_id
                    st.rerun()
            with delete_col:
                if st.button("×", key=f"delete_{chat_id}", help="Delete chat", width="stretch"):
                    _delete_one_chat(store, chat_id)
                    st.rerun()

            if st.session_state.editing_chat_id == chat_id:
                new_title = st.text_input(
                    "Chat name",
                    value=title,
                    key=f"rename_input_{chat_id}",
                    label_visibility="collapsed",
                )
                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button("Save", key=f"save_rename_{chat_id}", width="stretch"):
                        store.rename_chat(chat_id, new_title)
                        st.session_state.editing_chat_id = None
                        st.rerun()
                with cancel_col:
                    if st.button("Cancel", key=f"cancel_rename_{chat_id}", width="stretch"):
                        st.session_state.editing_chat_id = None
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='sidebar-section-label'>Global memory</div>", unsafe_allow_html=True)
        _render_long_term_memory_panel()

        st.markdown("<div class='sidebar-section-label'>Maintenance</div>", unsafe_allow_html=True)
        if st.button("Clear all chat history", width="stretch"):
            _clear_all_chats(store)
            st.rerun()

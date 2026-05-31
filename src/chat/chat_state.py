import streamlit as st

from src.chat.chat_store import ChatStore
from src.config import DEFAULT_EVALUATION_MODE, DEFAULT_MODEL_PROFILE


def get_store() -> ChatStore:
    return ChatStore()


def init_session_state() -> None:
    store = get_store()
    chat = store.ensure_chat(st.session_state.get("active_chat_id"))

    st.session_state.setdefault("active_chat_id", chat["chat_id"])
    st.session_state.setdefault("page", "Home")
    st.session_state.setdefault("source_scope", "Documents only")
    st.session_state.setdefault("web_search_enabled", False)
    st.session_state.setdefault("model_profile", DEFAULT_MODEL_PROFILE)
    st.session_state["evaluation_mode"] = DEFAULT_EVALUATION_MODE
    st.session_state.setdefault("last_prepared", None)
    st.session_state.setdefault("last_trace", None)
    st.session_state.setdefault("last_evaluation", None)

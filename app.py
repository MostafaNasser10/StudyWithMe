import streamlit as st

from src.chat.chat_state import get_store, init_session_state
from src.ui.home import render_home_page
from src.ui.layout import configure_page
from src.ui.styles import apply_styles


def main() -> None:
    configure_page()
    apply_styles()
    init_session_state()

    if st.session_state.page == "Home":
        top_left, top_right = st.columns([0.82, 0.18])
        with top_right:
            if st.button("Open Chat", type="primary", width="stretch"):
                st.session_state.page = "Chat"
                st.rerun()
        render_home_page()
        return

    from src.ui.chat_view import render_chat_view
    from src.ui.sidebar_left import render_left_sidebar
    from src.ui.sidebar_right import render_right_sidebar

    store = get_store()
    render_left_sidebar(store)

    chat = store.ensure_chat(st.session_state.active_chat_id)
    st.session_state.active_chat_id = chat["chat_id"]
    
    center, right = st.columns([2.35, 1], gap="large")
    with center:
        render_chat_view(chat, store)
    with right:
        latest_chat = store.ensure_chat(st.session_state.active_chat_id)
        render_right_sidebar(latest_chat, store)


if __name__ == "__main__":
    main()

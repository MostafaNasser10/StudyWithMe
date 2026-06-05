"""Streamlit entrypoint for the StudyWithMe application.

The entrypoint keeps application composition thin: page configuration and
global styles are applied first, session state is initialized, and then the
home or chat workspace is rendered.
"""

import streamlit as st

from src.chat.chat_state import get_store, init_session_state
from src.ui.home import render_home_page
from src.ui.layout import configure_page
from src.ui.styles import apply_styles


def main() -> None:
    """Render the active Streamlit page.

    Side effects:
        Initializes Streamlit session state, may switch pages, and renders UI
        components that read/write chat JSON files through ``ChatStore``.

    Example:
        >>> # Run with: streamlit run app.py
        >>> callable(main)
        True
    """

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

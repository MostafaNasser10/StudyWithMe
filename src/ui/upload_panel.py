import streamlit as st

from src.chat.chat_store import ChatStore
from src.config import SUPPORTED_EXTENSIONS
from src.files.file_manager import delete_file, save_uploaded_files


def render_upload_controls(chat: dict, store: ChatStore) -> None:
    uploaded = st.file_uploader(
        "Upload files",
        type=[ext.removeprefix(".") for ext in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="PDF, TXT, MD, CSV, DOCX",
    )

    if uploaded:
        if st.button("Add uploaded files", use_container_width=True):
            save_uploaded_files(chat["chat_id"], uploaded, store)
            st.rerun()


def render_file_delete_button(chat_id: str, file_id: str, store: ChatStore) -> None:
    if st.button("x", key=f"delete_file_{file_id}", help="Delete file"):
        delete_file(chat_id, file_id, store)
        st.rerun()


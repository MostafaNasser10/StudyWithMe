import streamlit as st

from src.chat.chat_store import ChatStore
from src.config import SUPPORTED_EXTENSIONS
from src.files.file_manager import delete_file, save_uploaded_files
from src.files.indexing_jobs import start_indexing_job


def render_upload_controls(chat: dict, store: ChatStore) -> None:
    upload_key = f"upload_{chat['chat_id']}"
    uploaded = st.file_uploader(
        "Upload files",
        type=[ext.removeprefix(".") for ext in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="PDF, TXT, MD, CSV, DOCX",
        key=upload_key,
    )

    if uploaded:
        signature = tuple((item.name, getattr(item, "size", None)) for item in uploaded)
        processed = st.session_state.setdefault("processed_upload_signatures", {})
        if processed.get(chat["chat_id"]) != signature:
            saved = save_uploaded_files(chat["chat_id"], uploaded, store)
            processed[chat["chat_id"]] = signature
            if saved:
                start_indexing_job(chat["chat_id"], store, step="Indexing uploaded files")
                st.success("Files uploaded. Indexing started automatically.")
            st.rerun()


def render_file_delete_button(chat_id: str, file_id: str, store: ChatStore) -> None:
    if st.button("x", key=f"delete_file_{file_id}", help="Delete file"):
        deleted = delete_file(chat_id, file_id, store)
        if deleted:
            start_indexing_job(chat_id, store, step="Rebuilding index after file deletion")
        st.rerun()

import streamlit as st

from src.config import APP_NAME


def configure_page() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        page_icon="SW",
        layout="wide",
        initial_sidebar_state="expanded",
    )


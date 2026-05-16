from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st


LOGO_PATH = Path("assets") / "logo.png"


@st.cache_data(show_spinner=False)
def _logo_base64() -> str | None:
    if not LOGO_PATH.exists():
        return None
    return base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")


def render_home_page() -> None:
    logo = _logo_base64()
    logo_html = (
        f"<img class='home-logo' src='data:image/png;base64,{logo}' alt='StudyWithMe logo'>"
        if logo
        else "<div class='home-logo'></div>"
    )

    st.markdown(
        f"""
        <div class="home-shell">
            <section class="home-hero">
                <div class="home-visual">
                    <div class="logo-stage">{logo_html}</div>
                    <div class="workspace-preview">
                        <div class="preview-card">
                            <div class="preview-label">Knowledge base</div>
                            <div class="preview-value">Per-chat</div>
                            <div class="preview-line"><strong style="width: 78%;"></strong></div>
                            <div class="preview-line"><strong style="width: 58%;"></strong></div>
                        </div>
                        <div class="preview-card">
                            <div class="preview-label">Tutor route</div>
                            <div class="preview-value">Grounded</div>
                            <div class="preview-line"><strong style="width: 66%;"></strong></div>
                            <div class="preview-line"><strong style="width: 86%;"></strong></div>
                        </div>
                        <div class="preview-card">
                            <div class="preview-label">Evaluation</div>
                            <div class="preview-value">Traceable</div>
                            <div class="preview-line"><strong style="width: 72%;"></strong></div>
                            <div class="preview-line"><strong style="width: 46%;"></strong></div>
                        </div>
                    </div>
                </div>
                <div>
                    <div class="home-kicker">Arabic AI Tutor for serious study sessions</div>
                    <h1 class="home-title">StudyWithMe</h1>
                    <p class="home-text">
                        Upload your course files, build a private knowledge base for each chat,
                        ask in Arabic or English, and get structured Arabic explanations with
                        sources, traces, and evaluation.
                    </p>
                    <p class="home-caption">
                        Your old chat history is preserved, and each new chat keeps its own files and vector store.
                    </p>
                </div>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )

    action_col, caption_col = st.columns([0.22, 0.78])
    with action_col:
        if st.button("Start Learning Now", type="primary", use_container_width=True):
            st.session_state.page = "Chat"
            st.rerun()
    with caption_col:
        st.caption("Private documents, streaming tutor answers, traceability, and evaluation in one workspace.")

    st.markdown(
        """
        <div class="home-shell">
            <div class="summary-grid">
                <div class="summary-card">
                    <b>Document RAG</b>
                    <p>PDF, TXT, MD, CSV, and DOCX files are indexed per chat so answers stay grounded in the right material.</p>
                </div>
                <div class="summary-card">
                    <b>Arabic tutoring</b>
                    <p>Responses keep the educational Arabic style with clear structure, technical terms, examples, and study summaries.</p>
                </div>
                <div class="summary-card">
                    <b>Agent workflow</b>
                    <p>A supervisor routes requests to tutor, quiz, feedback, study-plan, summary, calculator, or web-search paths.</p>
                </div>
                <div class="summary-card">
                    <b>Trace and evaluation</b>
                    <p>Each answer stores route, retrieved documents, tools, timings, rubric scores, and optional judge feedback.</p>
                </div>
            </div>
            <div class="home-panel">
                <div class="section-title">How the workspace behaves</div>
                <p class="home-caption">
                    Start a chat, upload files on the right, build the index, then ask your study question.
                    The app streams the answer, applies the Arabic guard, appends sources, saves the trace,
                    and updates the evaluation panel.
                </p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

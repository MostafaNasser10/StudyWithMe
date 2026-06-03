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
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background: #0b0f14 !important;
        }
        .home-shell, .home-shell * {
            box-sizing: border-box;
        }
        .home-shell {
            color: #f3f7fb;
        }
        .home-panel, .summary-card {
            color: #f3f7fb;
        }
        </style>
        """,
        unsafe_allow_html=True,
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
        if st.button("Start Learning Now", type="primary", width="stretch"):
            st.session_state.page = "Chat"
            st.rerun()
    with caption_col:
        st.caption("Private documents, streaming tutor answers, traceability, and evaluation in one workspace.")

    st.markdown(
        """
        <div class="home-shell">
            <section class="workflow-motion">
                <div class="workflow-copy">
                    <div class="home-kicker">Visual workflow</div>
                    <h2>A study prompt becomes a guided Arabic learning session.</h2>
                    <p>
                        The app does not treat your request as one flat answer. It routes the task,
                        retrieves the right notes, explains the material, creates quiz questions when requested,
                        and keeps trace and evaluation visible.
                    </p>
                </div>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(_workflow_visual_markup(), unsafe_allow_html=True)

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
                    <p>LangGraph routes requests to tutor, quiz, feedback, study-plan, summary, calculator, or web-search paths.</p>
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

def _workflow_visual_markup() -> str:
    return """
    <div class="home-shell">
        <div class="workflow-canvas">
            <div class="flow-card flow-input">
                <span>Input</span>
                <b dir="rtl">اشرح المحاضرة ثم اختبرني</b>
                <p class="home-caption">One prompt can become several study tasks.</p>
            </div>
            <div class="flow-engine">
                <div class="packet packet-one"></div>
                <div class="packet packet-two"></div>
                <div class="packet packet-three"></div>
                <div class="engine-ring"></div>
                <div class="engine-core">LangGraph</div>
                <div class="engine-node engine-router">Router</div>
                <div class="engine-node engine-docs">Docs</div>
                <div class="engine-node engine-tutor">Tutor</div>
                <div class="engine-node engine-quiz">Quiz</div>
                <div class="engine-node engine-eval">Eval</div>
            </div>
            <div class="flow-card flow-output">
                <span>Output</span>
                <b dir="rtl">شرح عربي + مصادر + اختبار</b>
                <div class="output-preview"><em></em><em></em><em></em></div>
                <div class="quiz-preview"><i>A</i><i>B</i><i>C</i><i>D</i></div>
            </div>
        </div>
    </div>
    """


def _workflow_visual_html() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
html, body {
    margin: 0;
    padding: 0;
    background: #0b0f14;
    color: #f3f7fb;
    font-family: Inter, "Segoe UI", Arial, sans-serif;
}
* { box-sizing: border-box; }
.visual-wrap {
    width: min(1180px, calc(100vw - 48px));
    height: 500px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: minmax(220px, .92fr) minmax(360px, 1.22fr) minmax(220px, .92fr);
    gap: 18px;
    align-items: center;
    padding: 22px;
    border: 1px solid #2a3440;
    border-radius: 8px;
    background:
        linear-gradient(90deg, rgba(76, 201, 240, .08) 1px, transparent 1px),
        linear-gradient(180deg, rgba(76, 201, 240, .06) 1px, transparent 1px),
        radial-gradient(circle at 50% 45%, #1a3148 0, #101923 58%, #0f151d 100%);
    background-size: 34px 34px, 34px 34px, auto;
    overflow: hidden;
}
.card {
    position: relative;
    min-height: 190px;
    padding: 18px;
    border: 1px solid #3e5369;
    border-radius: 8px;
    background: rgba(18, 28, 39, .96);
    box-shadow: 0 18px 54px rgba(0, 0, 0, .28);
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 12px;
    animation: floatCard 5.2s ease-in-out infinite;
}
.output { animation-direction: reverse; }
.label {
    color: #4cc9f0;
    font-size: 12px;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: .04em;
}
.arabic {
    direction: rtl;
    text-align: right;
    color: #fff;
    font-size: 18px;
    font-weight: 850;
    line-height: 1.75;
}
.hint {
    color: #a9b7c8;
    font-size: 13px;
    line-height: 1.6;
}
.engine {
    position: relative;
    height: 380px;
}
.ring {
    position: absolute;
    inset: 42px;
    border: 1px solid rgba(76, 201, 240, .42);
    border-radius: 999px;
    box-shadow: inset 0 0 34px rgba(76, 201, 240, .08);
    animation: rotateRing 16s linear infinite;
}
.ring::before,
.ring::after {
    content: "";
    position: absolute;
    width: 11px;
    height: 11px;
    border-radius: 999px;
    background: #4cc9f0;
    box-shadow: 0 0 18px rgba(76, 201, 240, .9);
}
.ring::before { top: -6px; left: 50%; }
.ring::after { right: 20%; bottom: -6px; background: #8bd450; }
.core {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 122px;
    height: 122px;
    display: grid;
    place-items: center;
    border-radius: 999px;
    background: #203044;
    border: 1px solid #6a87a6;
    color: #fff;
    font-weight: 900;
    box-shadow: 0 0 42px rgba(76, 201, 240, .24);
    animation: pulseCore 2.8s ease-in-out infinite;
}
.node {
    position: absolute;
    width: 88px;
    min-height: 40px;
    display: grid;
    place-items: center;
    border-radius: 8px;
    background: #101923;
    border: 1px solid #4b6077;
    color: #d5dde8;
    font-size: 13px;
    font-weight: 900;
    box-shadow: 0 10px 28px rgba(0, 0, 0, .24);
    animation: nodeGlow 4.4s ease-in-out infinite;
}
.router { left: 50%; top: 4px; transform: translateX(-50%); }
.docs { left: 4px; top: 44%; animation-delay: .4s; }
.tutor { right: 4px; top: 44%; animation-delay: .8s; }
.quiz { left: 18%; bottom: 4px; animation-delay: 1.2s; }
.eval { right: 18%; bottom: 4px; animation-delay: 1.6s; }
.packet {
    position: absolute;
    top: 50%;
    left: -20px;
    width: 13px;
    height: 13px;
    border-radius: 999px;
    background: #f7c948;
    box-shadow: 0 0 18px rgba(247, 201, 72, .8);
    animation: packetMove 3.9s linear infinite;
}
.packet.two { animation-delay: 1.25s; background: #4cc9f0; }
.packet.three { animation-delay: 2.5s; background: #8bd450; }
.lines i {
    display: block;
    height: 9px;
    border-radius: 999px;
    margin-top: 9px;
    background: linear-gradient(90deg, #4cc9f0, rgba(139, 212, 80, .85));
}
.lines i:nth-child(1) { width: 92%; }
.lines i:nth-child(2) { width: 74%; }
.lines i:nth-child(3) { width: 84%; }
.choices {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 7px;
    margin-top: 8px;
}
.choices b {
    display: grid;
    place-items: center;
    height: 34px;
    border-radius: 8px;
    background: #1f3042;
    border: 1px solid #425873;
    color: #f7fbff;
    animation: answerPulse 4s ease-in-out infinite;
}
.choices b:nth-child(2) { animation-delay: .4s; }
.choices b:nth-child(3) { animation-delay: .8s; }
.choices b:nth-child(4) { animation-delay: 1.2s; }
@keyframes rotateRing { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes floatCard { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
@keyframes pulseCore {
    0%, 100% { box-shadow: 0 0 0 rgba(76, 201, 240, 0); }
    50% { box-shadow: 0 0 38px rgba(76, 201, 240, .36); }
}
@keyframes nodeGlow {
    0%, 100% { border-color: #4a5f76; color: #d5dde8; }
    50% { border-color: #4cc9f0; color: #fff; }
}
@keyframes packetMove {
    0% { transform: translateX(0) scale(.8); opacity: 0; }
    12% { opacity: 1; }
    50% { transform: translateX(250px) scale(1.05); opacity: 1; }
    88% { opacity: 1; }
    100% { transform: translateX(520px) scale(.9); opacity: 0; }
}
@keyframes answerPulse {
    0%, 100% { border-color: #425873; background: #1f3042; }
    50% { border-color: #8bd450; background: #263b4d; }
}
@media (max-width: 860px) {
    .visual-wrap {
        width: calc(100vw - 28px);
        height: auto;
        min-height: 760px;
        grid-template-columns: 1fr;
    }
    .engine { height: 340px; }
    .packet { display: none; }
}
</style>
</head>
<body>
<div class="visual-wrap" aria-label="StudyWithMe animated workflow">
    <section class="card input">
        <div class="label">Student prompt</div>
        <div class="arabic">اشرح RAG من الملف واعمل اختبار من سؤالين</div>
        <div class="hint">One request can become explanation, retrieval, quiz, feedback, and evaluation.</div>
    </section>
    <section class="engine" aria-label="LangGraph route">
        <div class="ring"></div>
        <div class="core">LangGraph</div>
        <div class="node router">Router</div>
        <div class="node docs">Docs</div>
        <div class="node tutor">Tutor</div>
        <div class="node quiz">Quiz</div>
        <div class="node eval">Eval</div>
        <span class="packet"></span>
        <span class="packet two"></span>
        <span class="packet three"></span>
    </section>
    <section class="card output">
        <div class="label">Study output</div>
        <div class="arabic">تقرير مذاكرة منظم + اختبار تفاعلي</div>
        <div class="lines" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="choices" aria-hidden="true"><b>A</b><b>B</b><b>C</b><b>D</b></div>
    </section>
</div>
</body>
</html>
"""

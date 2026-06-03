import streamlit as st


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #0b0f14;
            --bg-2: #111820;
            --surface: #151a21;
            --surface-2: #1b222b;
            --surface-3: #202a35;
            --border: #3a4654;
            --border-soft: #2a3440;
            --text: #f3f7fb;
            --text-soft: #d5dde8;
            --muted: #a9b7c8;
            --accent: #4cc9f0;
            --accent-2: #8bd450;
            --warning: #f7c948;
            --orange: #f59e42;
            --danger: #ff6b6b;
        }

        .stApp {
            background: linear-gradient(180deg, var(--bg), #07090d 100%);
            color: var(--text);
        }
        .block-container { padding-top: 1.2rem; max-width: 100%; }
        p, li, span, label, div { color: var(--text); }
        h1, h2, h3 { color: var(--text); letter-spacing: 0; }
        small, .muted, .chat-meta, .home-caption { color: var(--muted) !important; }

        [data-testid="stSidebar"] {
            background: #0a0d12;
            border-right: 1px solid var(--border-soft);
        }
        [data-testid="stSidebar"] * { color: var(--text); }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: .72rem;
            margin-bottom: 1rem;
        }
        .sidebar-logo, .sidebar-logo-fallback {
            width: 42px;
            height: 42px;
            border-radius: 8px;
            object-fit: contain;
            background: #121b27;
            border: 1px solid var(--border-soft);
            flex: 0 0 auto;
        }
        .sidebar-logo-fallback {
            display: grid;
            place-items: center;
            color: var(--accent);
            font-weight: 900;
        }
        .app-title { font-size: 1.18rem; font-weight: 850; margin-bottom: .15rem; }
        .app-subtitle { color: var(--muted); font-size: .84rem; }

        .home-shell { max-width: 1180px; margin: 0 auto; padding: 1rem 0 2rem; }
        .home-hero {
            min-height: 560px;
            display: grid;
            grid-template-columns: .95fr 1.05fr;
            gap: 3rem;
            align-items: center;
            border-bottom: 1px solid var(--border-soft);
            padding-bottom: 1.5rem;
        }
        .home-visual {
            min-height: 500px;
            display: grid;
            grid-template-columns: 1fr;
            gap: 1rem;
            align-content: center;
        }
        .logo-stage {
            display: grid;
            place-items: center;
            background: linear-gradient(180deg, #171f2b, #101721);
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            min-height: 390px;
            box-shadow: 0 22px 70px rgba(0,0,0,.30);
        }
        .home-logo {
            width: min(430px, 78vw);
            aspect-ratio: 1;
            object-fit: contain;
            filter: drop-shadow(0 22px 56px rgba(0,0,0,.55));
        }
        .workspace-preview {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: .75rem;
        }
        .preview-card {
            background: #151c26;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: .85rem;
            min-height: 112px;
        }
        .preview-label {
            color: var(--muted);
            font-size: .72rem;
            text-transform: uppercase;
            letter-spacing: .05em;
            margin-bottom: .45rem;
        }
        .preview-value { color: var(--text); font-size: 1.15rem; font-weight: 850; margin-bottom: .45rem; }
        .preview-line {
            display: block;
            height: 7px;
            border-radius: 999px;
            background: var(--surface-3);
            margin-top: .38rem;
        }
        .preview-line strong { display: block; height: 100%; border-radius: inherit; background: var(--accent); }
        .home-kicker { color: var(--accent); font-weight: 800; margin-bottom: .6rem; }
        .home-title { font-size: clamp(2.2rem, 6vw, 5.6rem); line-height: .95; font-weight: 900; margin: 0 0 1rem; }
        .home-text { color: var(--text-soft); font-size: 1.08rem; line-height: 1.75; max-width: 680px; }
        .home-actions { display: flex; gap: .75rem; flex-wrap: wrap; margin-top: 1.25rem; }
        .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin-top: 1.25rem; }
        .summary-card, .home-panel, .right-panel, .file-card, .metric-card {
            background: var(--surface);
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            box-shadow: 0 18px 50px rgba(0,0,0,.18);
        }
        .summary-card { padding: 1rem; min-height: 132px; }
        .summary-card b { color: var(--text); display: block; margin-bottom: .45rem; }
        .summary-card p { color: var(--muted); font-size: .88rem; line-height: 1.55; margin: 0; }
        .home-panel { padding: 1rem; margin-top: .9rem; }
        .workflow-motion {
            display: grid;
            grid-template-columns: .82fr 1.18fr;
            gap: 1.25rem;
            align-items: center;
            margin: 1.25rem 0 1rem;
            padding: 1rem;
            background: linear-gradient(180deg, #111923, #0d131b);
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            overflow: hidden;
        }
        .workflow-copy h2 {
            font-size: 1.55rem;
            line-height: 1.25;
            margin: .25rem 0 .65rem;
        }
        .workflow-copy p {
            color: var(--text-soft);
            line-height: 1.72;
            margin: 0;
        }
        @keyframes pulseCore {
            0%, 100% { box-shadow: 0 0 0 rgba(76,201,240,0); }
            50% { box-shadow: 0 0 34px rgba(76,201,240,.34); }
        }
        @keyframes nodeGlow {
            0%, 100% { border-color: #4a5f76; color: var(--text-soft); }
            50% { border-color: var(--accent); color: #ffffff; }
        }
        @keyframes floatStudy {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-7px); }
        }

        .workflow-canvas {
            position: relative;
            min-height: 430px;
            display: grid;
            grid-template-columns: minmax(180px, .85fr) minmax(300px, 1.35fr) minmax(180px, .85fr);
            gap: 1rem;
            align-items: center;
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid #2f4358;
            background:
                linear-gradient(90deg, rgba(76,201,240,.08) 1px, transparent 1px),
                linear-gradient(180deg, rgba(76,201,240,.06) 1px, transparent 1px),
                radial-gradient(circle at 50% 50%, #193049, #0f1721 68%);
            background-size: 34px 34px, 34px 34px, auto;
            overflow: hidden;
            isolation: isolate;
        }
        .workflow-canvas::before {
            content: "";
            position: absolute;
            inset: 16px;
            border: 1px solid rgba(139,212,80,.2);
            border-radius: 8px;
            pointer-events: none;
        }
        .flow-card {
            position: relative;
            z-index: 3;
            min-height: 150px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: .65rem;
            padding: 1rem;
            border-radius: 8px;
            background: #121c27;
            border: 1px solid #3e5369;
            box-shadow: 0 18px 54px rgba(0,0,0,.28);
            overflow-wrap: anywhere;
        }
        .flow-card span {
            color: var(--accent);
            font-size: .74rem;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        .flow-card b {
            color: var(--text);
            font-size: 1rem;
            line-height: 1.7;
            font-weight: 850;
        }
        .flow-input { animation: floatStudy 5.2s ease-in-out infinite; }
        .flow-output { animation: floatStudy 5.2s ease-in-out infinite reverse; }
        .flow-engine {
            position: relative;
            z-index: 2;
            min-height: 340px;
            border-radius: 8px;
        }
        .engine-ring {
            position: absolute;
            inset: 46px;
            border-radius: 999px;
            border: 1px solid rgba(76,201,240,.38);
            box-shadow: inset 0 0 34px rgba(76,201,240,.08);
            animation: rotateRing 14s linear infinite;
        }
        .engine-ring::before,
        .engine-ring::after {
            content: "";
            position: absolute;
            width: 10px;
            height: 10px;
            border-radius: 999px;
            background: var(--accent);
            box-shadow: 0 0 18px rgba(76,201,240,.9);
        }
        .engine-ring::before { top: -5px; left: 50%; }
        .engine-ring::after { bottom: -5px; right: 22%; background: var(--accent-2); }
        .engine-core {
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            width: 112px;
            height: 112px;
            display: grid;
            place-items: center;
            border-radius: 999px;
            background: #203044;
            border: 1px solid #6a87a6;
            color: #ffffff;
            font-weight: 900;
            font-size: .88rem;
            box-shadow: 0 0 42px rgba(76,201,240,.2);
            animation: pulseCore 2.8s ease-in-out infinite;
        }
        .engine-node {
            position: absolute;
            width: 82px;
            min-height: 38px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: #101923;
            border: 1px solid #4b6077;
            color: var(--text-soft);
            font-size: .76rem;
            font-weight: 900;
            box-shadow: 0 10px 28px rgba(0,0,0,.24);
            animation: nodeGlow 4.4s ease-in-out infinite;
        }
        .engine-router { left: 50%; top: 8px; transform: translateX(-50%); }
        .engine-docs { left: 4px; top: 42%; animation-delay: .4s; }
        .engine-tutor { right: 4px; top: 42%; animation-delay: .8s; }
        .engine-quiz { left: 18%; bottom: 10px; animation-delay: 1.2s; }
        .engine-eval { right: 18%; bottom: 10px; animation-delay: 1.6s; }
        .packet {
            position: absolute;
            z-index: 1;
            top: 50%;
            width: 13px;
            height: 13px;
            border-radius: 999px;
            background: var(--warning);
            box-shadow: 0 0 18px rgba(247,201,72,.8);
            animation: packetMove 3.8s linear infinite;
        }
        .packet-one { left: -8%; animation-delay: 0s; }
        .packet-two { left: -8%; animation-delay: 1.2s; background: var(--accent); }
        .packet-three { left: -8%; animation-delay: 2.4s; background: var(--accent-2); }
        .output-preview em {
            display: block;
            height: 8px;
            border-radius: 999px;
            margin-top: .45rem;
            background: linear-gradient(90deg, var(--accent), rgba(139,212,80,.8));
            opacity: .85;
        }
        .output-preview em:nth-child(1) { width: 92%; }
        .output-preview em:nth-child(2) { width: 76%; }
        .output-preview em:nth-child(3) { width: 84%; }
        .quiz-preview {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: .35rem;
            margin-top: .55rem;
        }
        .quiz-preview i {
            display: grid;
            place-items: center;
            height: 28px;
            border-radius: 8px;
            background: #1f3042;
            border: 1px solid #425873;
            color: #f7fbff;
            font-style: normal;
            font-weight: 900;
            animation: answerPulse 4s ease-in-out infinite;
        }
        .quiz-preview i:nth-child(2) { animation-delay: .4s; }
        .quiz-preview i:nth-child(3) { animation-delay: .8s; }
        .quiz-preview i:nth-child(4) { animation-delay: 1.2s; }

        @keyframes rotateRing {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        @keyframes packetMove {
            0% { transform: translateX(0) scale(.8); opacity: 0; }
            12% { opacity: 1; }
            50% { transform: translateX(210px) scale(1.05); opacity: 1; }
            88% { opacity: 1; }
            100% { transform: translateX(430px) scale(.9); opacity: 0; }
        }
        @keyframes answerPulse {
            0%, 100% { border-color: #425873; background: #1f3042; }
            50% { border-color: var(--accent-2); background: #263b4d; }
        }

        .topbar {
            padding: .95rem 1rem;
            border: 1px solid var(--border-soft);
            background: linear-gradient(180deg, #171e27, #111821);
            border-radius: 8px;
            margin-bottom: .85rem;
        }
        .topbar h1 { font-size: 1.35rem; margin: 0 0 .2rem; }
        .chat-title-row { display: flex; align-items: center; gap: .75rem; }
        .chat-title-icon {
            width: 42px;
            height: 42px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            background: #203044;
            border: 1px solid var(--border);
            flex: 0 0 auto;
        }
        .chat-title-icon svg { width: 24px; height: 24px; stroke: var(--accent); }

        .control-strip {
            background: linear-gradient(180deg, #121a24, #0f151d);
            border: 1px solid rgba(226, 239, 255, .22);
            border-radius: 8px;
            padding: .85rem;
            margin-bottom: .85rem;
            box-shadow: 0 14px 38px rgba(0,0,0,.22);
        }
        .settings-summary {
            display: flex;
            flex-wrap: wrap;
            gap: .45rem;
            margin-bottom: .7rem;
        }
        .settings-pill {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            padding: .22rem .6rem;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: #172231;
            color: var(--muted);
            font-size: .78rem;
            font-weight: 750;
            white-space: nowrap;
        }
        .control-strip [data-testid="stTabs"] [role="tablist"] {
            display: grid !important;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .65rem;
            min-height: 58px;
            padding: .48rem;
            border: 1px solid rgba(226, 239, 255, .18);
            border-radius: 8px;
            background: #0d141d;
            box-shadow: inset 0 0 0 1px rgba(255,255,255,.025);
            margin-bottom: .85rem;
        }
        .control-strip [data-testid="stTabs"] [role="tab"] {
            width: 100%;
            min-height: 46px;
            justify-content: center;
            border: 1px solid rgba(226, 239, 255, .18);
            border-radius: 6px;
            padding: .52rem .9rem;
            color: var(--text-soft);
            font-weight: 800;
            background: linear-gradient(180deg, #182433, #121b27);
            box-shadow: 0 8px 20px rgba(0,0,0,.18);
            transition: background .14s ease, border-color .14s ease, color .14s ease, transform .14s ease;
        }
        .control-strip [data-testid="stTabs"] [role="tab"] p {
            color: inherit !important;
            font-size: .95rem;
            font-weight: 900;
            text-align: center;
            white-space: nowrap;
            margin: 0;
        }
        .control-strip [data-testid="stTabs"] [aria-selected="true"] {
            background: linear-gradient(180deg, #f3fbff, #bfeeff) !important;
            border-color: #ffffff !important;
            color: #06111d !important;
            box-shadow: 0 10px 26px rgba(76,201,240,.28);
        }
        .control-strip [data-testid="stTabs"] [aria-selected="true"] p {
            color: #06111d !important;
        }
        .control-strip [data-testid="stTabs"] [role="tab"]:hover {
            border-color: rgba(255,255,255,.55);
            background: linear-gradient(180deg, #213146, #182536);
            transform: translateY(-1px);
        }

        .right-panel {
            padding: .95rem;
            margin-bottom: .9rem;
            border-color: rgba(236, 246, 255, .52) !important;
            background: linear-gradient(180deg, #151b23, #101720);
            box-shadow: 0 16px 42px rgba(0,0,0,.24), inset 0 0 0 1px rgba(255,255,255,.035);
        }
        .section-title {
            display: flex;
            align-items: center;
            gap: .45rem;
            font-weight: 850;
            font-size: .95rem;
            margin-bottom: .7rem;
            color: #f8fbff;
            padding-bottom: .48rem;
            border-bottom: 1px solid rgba(236, 246, 255, .2);
        }
        .section-title::before {
            content: "";
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--accent);
            box-shadow: 0 0 14px rgba(76,201,240,.55);
            flex: 0 0 auto;
        }
        .file-card { background: var(--surface-2); margin-bottom: .5rem; padding: .68rem; }
        .file-name { font-size: .86rem; font-weight: 750; overflow-wrap: anywhere; color: var(--text); }
        .file-row { display: flex; justify-content: space-between; gap: .5rem; align-items: center; }

        .badge {
            display: inline-block;
            padding: .18rem .52rem;
            border-radius: 999px;
            font-size: .72rem;
            font-weight: 800;
            border: 1px solid var(--border);
            color: var(--text);
            background: var(--surface-3);
        }
        .badge.green { color: #d7ffd2; border-color: #2f7b43; background: #12351f; }
        .badge.yellow { color: #fff1a8; border-color: #8a6c15; background: #3b2d08; }
        .badge.blue { color: #c9f1ff; border-color: #27749c; background: #0e344d; }
        .badge.orange { color: #ffddb5; border-color: #9a5a1d; background: #45240b; }
        .badge.red, .badge.dim-red { color: #ffd1d1; border-color: #9b2e35; background: #461317; }

        .rtl { direction: rtl; text-align: right; line-height: 1.85; color: var(--text); }
        .rtl h1, .rtl h2, .rtl h3 {
            line-height: 1.35;
            margin: .9rem 0 .45rem;
            font-weight: 850;
            text-align: right;
        }
        .rtl h1 { font-size: 1.22rem; color: #f7fbff; }
        .rtl h2 { font-size: 1.04rem; color: #e9f3ff; }
        .rtl h3 { font-size: .96rem; color: #dcecff; }
        .rtl p, .rtl li {
            font-size: .98rem;
            line-height: 1.9;
            color: var(--text-soft);
        }
        .waiting-answer {
            padding: .85rem 1rem;
            background: #172231;
            border: 1px solid #384a61;
            border-radius: 8px;
            color: #d9f3ff;
            font-weight: 750;
        }
        .trace-step {
            border-left: 2px solid var(--accent);
            background: rgba(255,255,255,.025);
            padding: .45rem .55rem;
            margin: .45rem 0;
            border-radius: 0 8px 8px 0;
        }

        [data-testid="stChatMessage"] {
            background: #141a22;
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            padding: .85rem 1rem;
            margin-bottom: .75rem;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
        [data-testid="stChatMessage"] .stMarkdown,
        [data-testid="stChatMessage"] [data-testid="stMarkdown"] {
            direction: rtl;
            text-align: right;
        }
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) {
            direction: rtl;
            text-align: right;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] li {
            color: var(--text-soft);
            font-size: .98rem;
            line-height: 1.95;
        }
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) ul,
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) ol,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] ul,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] ol {
            direction: rtl;
            text-align: right;
            padding-right: 1.45rem;
            padding-left: 0;
        }
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) table,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] table {
            direction: rtl;
            text-align: right;
            width: 100%;
            border-collapse: collapse;
            margin: .6rem 0 1rem;
            font-size: .93rem;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] th {
            background: #1d2a38;
            color: #f7fbff;
            text-align: right !important;
            font-weight: 850;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] td {
            text-align: right !important;
            color: var(--text-soft);
        }
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) h1,
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) h2,
        [data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon-user"])) h3,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
            direction: rtl;
            text-align: right !important;
            line-height: 1.45;
            letter-spacing: 0;
            font-weight: 850;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h1 {
            font-size: 1.26rem;
            margin: .35rem 0 .75rem;
            color: #f7fbff;
            border-bottom: 1px solid var(--border-soft);
            padding: 0 0 .5rem;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h2 {
            font-size: 1.06rem;
            margin: 1rem 0 .45rem;
            color: #eaf6ff;
            background: #172231;
            border: 1px solid #2c3a49;
            border-right: 4px solid var(--accent);
            border-radius: 8px;
            padding: .5rem .75rem;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
            font-size: .98rem;
            margin: .85rem 0 .35rem;
            color: #dcecff;
            border-right: 3px solid var(--accent-2);
            padding-right: .55rem;
        }
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: #1a2633;
        }
        [data-testid="stChatInput"] {
            background: #0f151d;
            border: 1px solid #4a5b6f;
            border-radius: 16px;
            padding: .35rem;
        }
        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] form,
        [data-testid="stChatInput"] div {
            background: #111923 !important;
        }
        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] [contenteditable="true"],
        [data-testid="stChatInput"] [role="textbox"],
        [data-testid="stChatInput"] div[data-baseweb="textarea"],
        [data-testid="stChatInput"] div[data-baseweb="base-input"] {
            background: #111923 !important;
            color: var(--text) !important;
            caret-color: var(--accent) !important;
            border: 1px solid #53677d !important;
            box-shadow: none !important;
        }
        [data-testid="stChatInput"] textarea:focus,
        [data-testid="stChatInput"] [contenteditable="true"]:focus,
        [data-testid="stChatInput"] [role="textbox"]:focus {
            outline: none !important;
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 1px rgba(76, 201, 240, .45) !important;
        }
        [data-testid="stChatInput"] textarea::placeholder { color: #b5c2d2 !important; opacity: 1 !important; }
        [data-testid="stChatInput"] svg { color: var(--accent) !important; fill: var(--accent) !important; }
        [data-testid="stChatInput"] button {
            background: #203044 !important;
            border: 1px solid #53677d !important;
            color: var(--text) !important;
        }
        textarea, input, .stTextInput input {
            background: #111923 !important;
            color: var(--text) !important;
            caret-color: var(--accent) !important;
            border: 1px solid #53677d !important;
            border-radius: 8px !important;
        }
        textarea::placeholder, input::placeholder { color: #b5c2d2 !important; opacity: 1 !important; }
        [data-baseweb="select"] > div {
            background: #111923 !important;
            border-color: #53677d !important;
            color: var(--text) !important;
        }
        [data-baseweb="select"] span, [data-baseweb="select"] div { color: var(--text) !important; }
        [data-testid="stWidgetLabel"] {
            color: var(--text-soft) !important;
        }
        [data-testid="stWidgetLabel"] svg,
        [data-testid="stTooltipIcon"] svg,
        [data-testid="stHelp"] svg,
        button[aria-label*="help" i] svg,
        button[aria-label*="info" i] svg,
        svg[aria-label*="help" i],
        svg[aria-label*="info" i] {
            color: #e7f7ff !important;
            fill: #e7f7ff !important;
            stroke: #06111d !important;
            background: #58cdf2 !important;
            border: 1px solid #ffffff !important;
            border-radius: 999px !important;
            box-shadow: 0 0 0 2px rgba(88,205,242,.16), 0 4px 12px rgba(0,0,0,.28);
        }
        [data-testid="stTooltipIcon"]:hover svg,
        button[aria-label*="help" i]:hover svg,
        button[aria-label*="info" i]:hover svg {
            background: #ffffff !important;
            fill: #ffffff !important;
            color: #ffffff !important;
            stroke: #06111d !important;
        }
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        ul[role="listbox"] {
            background: #111923 !important;
            border: 1px solid #53677d !important;
            color: var(--text) !important;
        }
        div[data-baseweb="tooltip"],
        div[data-baseweb="tooltip"] *,
        [role="tooltip"],
        [role="tooltip"] *,
        [data-testid="stTooltipContent"],
        [data-testid="stTooltipContent"] * {
            background: #07111d !important;
            color: #f8fbff !important;
            border-color: #8fdfff !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }
        div[data-baseweb="tooltip"],
        [role="tooltip"],
        [data-testid="stTooltipContent"] {
            border: 1px solid #8fdfff !important;
            border-radius: 8px !important;
            box-shadow: 0 16px 42px rgba(0,0,0,.38) !important;
            padding: .25rem !important;
        }
        div[data-baseweb="tooltip"] p,
        [role="tooltip"] p,
        [data-testid="stTooltipContent"] p {
            color: #f8fbff !important;
            line-height: 1.45 !important;
        }
        li[role="option"],
        li[role="option"] div,
        li[role="option"] span {
            background: #111923 !important;
            color: var(--text) !important;
        }
        li[role="option"]:hover,
        li[role="option"][aria-selected="true"] {
            background: #203044 !important;
            color: #ffffff !important;
        }
        button, .stButton > button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
            border-radius: 8px !important;
            border: 1px solid #60758e !important;
            background: #172231 !important;
            color: #f7fbff !important;
            font-weight: 850 !important;
            opacity: 1 !important;
            text-shadow: none !important;
        }
        button *, .stButton > button *, [data-testid="stBaseButton-secondary"] *, [data-testid="stBaseButton-primary"] * {
            color: #f7fbff !important;
            opacity: 1 !important;
        }
        button:hover, .stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-primary"]:hover {
            background: #22324a !important;
            border-color: var(--accent) !important;
            color: #ffffff !important;
        }
        button[kind="primary"], .stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] {
            background: #59d0f5 !important;
            color: #02101b !important;
            font-weight: 800 !important;
        }
        button[kind="primary"] *, .stButton > button[kind="primary"] *, [data-testid="stBaseButton-primary"] * {
            color: #02101b !important;
        }
        .stAlert {
            background: #182231;
            color: var(--text);
            border: 1px solid var(--border);
        }

        @media (max-width: 900px) {
            .home-hero { grid-template-columns: 1fr; min-height: auto; }
            .workflow-motion { grid-template-columns: 1fr; }
            .workflow-canvas {
                grid-template-columns: 1fr;
                min-height: auto;
                gap: 1rem;
            }
            .flow-engine { min-height: 320px; }
            .packet { display: none; }
            .summary-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 560px) {
            .summary-grid { grid-template-columns: 1fr; }
            .workflow-motion { padding: .85rem; }
            .workflow-canvas { padding: .75rem; }
            .engine-node { width: 72px; font-size: .7rem; }
            .engine-core { width: 96px; height: 96px; font-size: .78rem; }
            .engine-ring { inset: 50px 38px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

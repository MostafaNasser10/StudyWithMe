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
            background: #111821;
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            padding: .75rem;
            margin-bottom: .85rem;
        }

        .right-panel { padding: .9rem; margin-bottom: .85rem; }
        .section-title { font-weight: 850; font-size: .95rem; margin-bottom: .5rem; color: var(--text); }
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
        }
        .rtl h1 { font-size: 1.32rem; color: #f7fbff; }
        .rtl h2 { font-size: 1.12rem; color: #e9f3ff; }
        .rtl h3 { font-size: 1rem; color: #dcecff; }
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
            padding: .65rem .85rem;
            margin-bottom: .65rem;
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
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        ul[role="listbox"] {
            background: #111923 !important;
            border: 1px solid #53677d !important;
            color: var(--text) !important;
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
            .summary-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 560px) {
            .summary-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


APP_NAME = "StudyWithMe Arabic AI Tutor"

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
CHAT_DIR = DATA_DIR / "chats"
RAW_DOCS_DIR = DATA_DIR / "raw_docs"
EVALUATIONS_DIR = DATA_DIR / "evaluations"
GOLD_STANDARDS_PATH = EVALUATIONS_DIR / "gold_standards.json"

VECTOR_STORE_DIR = BASE_DIR / "vector_store"
FAISS_INDEX_DIR = VECTOR_STORE_DIR / "faiss_index"
INDEX_METADATA_PATH = VECTOR_STORE_DIR / "index_metadata.json"

for path in (DATA_DIR, CHAT_DIR, RAW_DOCS_DIR, EVALUATIONS_DIR, VECTOR_STORE_DIR):
    path.mkdir(parents=True, exist_ok=True)


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen:7b")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

MODEL_PROFILE_LOCAL = "local_ollama"
MODEL_PROFILE_GPT4O_MINI = "openai_gpt_4o_mini"
MODEL_PROFILES = {
    MODEL_PROFILE_LOCAL: {
        "label": f"Current local model ({OLLAMA_MODEL})",
        "provider": "ollama",
        "model": OLLAMA_MODEL,
    },
    MODEL_PROFILE_GPT4O_MINI: {
        "label": "OpenAI gpt-4o-mini",
        "provider": "openai",
        "model": "gpt-4o-mini",
    },
}
DEFAULT_MODEL_PROFILE = os.getenv("DEFAULT_MODEL_PROFILE", MODEL_PROFILE_GPT4O_MINI).strip()
if DEFAULT_MODEL_PROFILE not in MODEL_PROFILES:
    DEFAULT_MODEL_PROFILE = MODEL_PROFILE_GPT4O_MINI

LLM_REQUEST_TIMEOUT_SECONDS = int(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "180"))
ARABIC_GUARD_LLM_REPAIR_ENABLED = os.getenv("ARABIC_GUARD_LLM_REPAIR_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
QUIZ_SYNTHETIC_FALLBACK_ENABLED = os.getenv("QUIZ_SYNTHETIC_FALLBACK_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EVALUATOR_OLLAMA_MODEL = os.getenv("EVALUATOR_OLLAMA_MODEL", "").strip()
EVALUATOR_LLM_ENABLED = os.getenv("EVALUATOR_LLM_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EVALUATOR_LLM_TEMPERATURE = float(os.getenv("EVALUATOR_LLM_TEMPERATURE", "0"))
ENABLE_RAGAS_EVAL = os.getenv("ENABLE_RAGAS_EVAL", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENABLE_DEEPEVAL_EVAL = os.getenv("ENABLE_DEEPEVAL_EVAL", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
TOP_K = int(os.getenv("TOP_K", "4"))

SUPPORTED_EXTENSIONS = [".pdf", ".txt", ".md", ".csv", ".docx"]

WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "stub")
WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "")

OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
IMAGE_EXTRACTION_ENABLED = os.getenv("IMAGE_EXTRACTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
TABLE_EXTRACTION_ENABLED = os.getenv("TABLE_EXTRACTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

LANGSMITH_TRACING_ENABLED = os.getenv("LANGSMITH_TRACING_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "studywithme-arabic-ai")

DEFAULT_SOURCE_SCOPE = "Documents only"
SOURCE_SCOPES = ["Documents only", "Web only", "Documents + Web"]

EVALUATION_MODES = ["deterministic", "same LLM", "evaluator LLM"]
DEFAULT_EVALUATION_MODE = os.getenv("DEFAULT_EVALUATION_MODE", "deterministic")
if DEFAULT_EVALUATION_MODE not in EVALUATION_MODES:
    DEFAULT_EVALUATION_MODE = "deterministic"

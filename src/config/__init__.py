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


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


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
# Temperature guide:
# - 0.0: deterministic; best for routing, JSON, repairs, grading, and safety checks.
# - 0.2-0.4: stable but less repetitive; best for grounded study answers.
# - 0.5-0.7: more varied; use when you want alternative explanations/examples.
# - >0.7: creative; not recommended for RAG, citations, or evaluation.
# Recommended default for this app: keep control/planning at 0.0, answers at 0.3.

# General fallback for normal answer generation. Recommended: 0.3.
LLM_DEFAULT_TEMPERATURE = _env_float("LLM_DEFAULT_TEMPERATURE", "0.3")

# Used by any streaming helper. Recommended: same as LLM_DEFAULT_TEMPERATURE.
LLM_STREAM_TEMPERATURE = _env_float("LLM_STREAM_TEMPERATURE", str(LLM_DEFAULT_TEMPERATURE))

# Planner/router must be stable JSON and choose the same route for the same query. Recommended: 0.0.
ROUTER_LLM_TEMPERATURE = _env_float("ROUTER_LLM_TEMPERATURE", "0")

# Function/tool selection should be deterministic and schema-safe. Recommended: 0.0.
FUNCTION_CALLING_LLM_TEMPERATURE = _env_float("FUNCTION_CALLING_LLM_TEMPERATURE", "0")

# Main tutor/explain/summarize answer. Recommended: 0.3; use 0.5-0.6 for more varied wording.
ANSWER_LLM_TEMPERATURE = _env_float("ANSWER_LLM_TEMPERATURE", str(LLM_DEFAULT_TEMPERATURE))

# Quiz creation needs some variety but must stay on-topic. Recommended: 0.2.
QUIZ_GENERATION_LLM_TEMPERATURE = _env_float("QUIZ_GENERATION_LLM_TEMPERATURE", "0.2")

# JSON repair/count repair must be deterministic. Recommended: 0.0.
QUIZ_REPAIR_LLM_TEMPERATURE = _env_float("QUIZ_REPAIR_LLM_TEMPERATURE", "0")

# Quiz feedback can be explanatory but should remain consistent. Recommended: 0.3.
QUIZ_FEEDBACK_LLM_TEMPERATURE = _env_float("QUIZ_FEEDBACK_LLM_TEMPERATURE", str(LLM_DEFAULT_TEMPERATURE))

# Study plans can vary a little for readability. Recommended: 0.3-0.4.
STUDY_PLAN_LLM_TEMPERATURE = _env_float("STUDY_PLAN_LLM_TEMPERATURE", str(LLM_DEFAULT_TEMPERATURE))

# Arabic repair/guard should preserve meaning, not invent. Recommended: 0.0.
ARABIC_GUARD_LLM_TEMPERATURE = _env_float("ARABIC_GUARD_LLM_TEMPERATURE", "0")

# LLM reflection, when enabled, is a quality check. Recommended: 0.0.
REFLECTION_LLM_TEMPERATURE = _env_float("REFLECTION_LLM_TEMPERATURE", "0")

# Critic, when enabled, is an adversarial check. Recommended: 0.0.
CRITIC_LLM_TEMPERATURE = _env_float("CRITIC_LLM_TEMPERATURE", "0")

# Same-LLM evaluation judge should be reproducible. Recommended: 0.0.
EVALUATOR_SAME_LLM_TEMPERATURE = _env_float("EVALUATOR_SAME_LLM_TEMPERATURE", "0")
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
# Separate evaluator model should be reproducible. Recommended: 0.0.
EVALUATOR_LLM_TEMPERATURE = _env_float("EVALUATOR_LLM_TEMPERATURE", "0")
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
AUTOMATIC_EXTERNAL_RAG_EVAL = os.getenv("AUTOMATIC_EXTERNAL_RAG_EVAL", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# External RAGAS/DeepEval judges are slow and token-sensitive. Keep these small
# so manual evaluation finishes quickly and avoids false low scores from judge
# truncation. Recommended: timeout 45s, answer 2500 chars, 4 contexts.
EXTERNAL_RAG_EVAL_TIMEOUT_SECONDS = int(os.getenv("EXTERNAL_RAG_EVAL_TIMEOUT_SECONDS", "45"))
EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS = int(os.getenv("EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS", "2500"))
EXTERNAL_RAG_EVAL_MAX_CONTEXTS = int(os.getenv("EXTERNAL_RAG_EVAL_MAX_CONTEXTS", "4"))
EXTERNAL_RAG_EVAL_MAX_CONTEXT_CHARS = int(os.getenv("EXTERNAL_RAG_EVAL_MAX_CONTEXT_CHARS", "1500"))
# Translate Arabic answers/questions to English before external RAGAS/DeepEval
# when the retrieved PDF context is mostly English. Recommended: true.
EXTERNAL_RAG_EVAL_TRANSLATE_TO_ENGLISH = os.getenv("EXTERNAL_RAG_EVAL_TRANSLATE_TO_ENGLISH", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EXTERNAL_RAG_EVAL_TRANSLATION_TIMEOUT_SECONDS = int(os.getenv("EXTERNAL_RAG_EVAL_TRANSLATION_TIMEOUT_SECONDS", "20"))
QUALITY_AGENT_LLM_REVIEW_ENABLED = os.getenv("QUALITY_AGENT_LLM_REVIEW_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
QUALITY_AGENT_LLM_TIMEOUT_SECONDS = int(os.getenv("QUALITY_AGENT_LLM_TIMEOUT_SECONDS", "12"))
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
TOP_K = int(os.getenv("TOP_K", "4"))
DEFAULT_BM25_SEARCH_ENABLED = os.getenv("DEFAULT_BM25_SEARCH_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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

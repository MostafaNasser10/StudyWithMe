from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.config import TOP_K
from src.llm import get_llm
from src.retriever import retrieve_chunks_with_scores


@dataclass
class AgentResult:
    answer: str
    docs: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    tools_used: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def source_location(metadata: dict) -> str:
    page = metadata.get("page")
    line = metadata.get("line", metadata.get("start_line"))
    parts = []
    if page is not None:
        parts.append(f"الصفحة {page}")
    if line is not None:
        parts.append(f"السطر {line}")
    return "، ".join(parts) if parts else "الموضع غير متاح"


def _source_name(source: str) -> str:
    try:
        return Path(source).name
    except Exception:
        return source or "مصدر غير معروف"


def docs_from_results(results) -> list[dict[str, Any]]:
    docs = []
    for idx, item in enumerate(results, start=1):
        chunk, score = item if isinstance(item, tuple) else (item, None)
        source = chunk.metadata.get("source", "Unknown source")
        location = source_location(chunk.metadata)
        docs.append(
            {
                "rank": idx,
                "title": f"{_source_name(source)} | {location}",
                "source": source,
                "source_name": _source_name(source),
                "location": location,
                "page": chunk.metadata.get("page"),
                "line": chunk.metadata.get("line", chunk.metadata.get("start_line")),
                "score": score if score is not None else "N/A",
                "snippet": chunk.page_content[:700],
            }
        )
    return docs


def context_from_results(results) -> str:
    parts = []
    for idx, item in enumerate(results, start=1):
        chunk, score = item if isinstance(item, tuple) else (item, None)
        source = chunk.metadata.get("source", "Unknown source")
        parts.append(
            f"[المقطع {idx}]\n"
            f"File: {_source_name(source)}\n"
            f"Path: {source}\n"
            f"Location: {source_location(chunk.metadata)}\n"
            f"Similarity score: {score}\n"
            "Instruction: Explain the meaning in Arabic. Do not copy foreign-language sentences.\n"
            f"Content:\n{chunk.page_content}"
        )
    return "\n\n".join(parts)


def append_sources_section(answer: str, docs: list[dict], web_sources: list[dict] | None = None) -> str:
    lines = []
    if docs:
        lines.extend(["", "---", "", "# قائمة المصادر"])
        lines.append("## من الملفات")
        for doc in docs[:6]:
            lines.append(
                f"- [المقطع {doc['rank']}] {doc.get('source_name') or _source_name(doc.get('source', ''))} | "
                f"{doc.get('location', 'الموضع غير متاح')} | درجة التشابه: {doc.get('score', 'N/A')}"
            )
    if web_sources:
        if not lines:
            lines.extend(["", "---", "", "# قائمة المصادر"])
        lines.append("## من الويب")
        for idx, source in enumerate(web_sources[:6], start=1):
            title = source.get("title", "Web source")
            url = source.get("url", "")
            snippet = source.get("snippet", "")
            lines.append(f"- [ويب {idx}] {title} | {url} | {snippet[:160]}".strip())
    if not docs and not web_sources and "من النموذج" not in answer:
        lines.extend(["", "---", "", "# قائمة المصادر", "- من النموذج: لا توجد مصادر ملفات أو ويب مستخدمة في هذه الإجابة."])
    return answer.rstrip() + ("\n" + "\n".join(lines) if lines else "")


class BaseAgent:
    name = "Tutor"
    prompt = ""
    use_retrieval = True

    def retrieve(self, query: str, chat_id: str | None = None, k: int = TOP_K):
        if not self.use_retrieval:
            return "", []
        results = retrieve_chunks_with_scores(query, k=k, chat_id=chat_id)
        return context_from_results(results), docs_from_results(results)

    def build_prompt(self, query: str, context: str = "", extra: str = "") -> str:
        return f"""
{self.prompt}

CONTEXT:
{context or 'No uploaded document context was retrieved. If you answer from model knowledge, label it clearly as من النموذج.'}

{extra}

USER REQUEST:
{query}
"""

    def invoke(self, prompt: str) -> str:
        return get_llm().invoke(prompt).content


from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from src.agents.base_agent import context_from_results, docs_from_results
from src.config import TOP_K
from src.retriever import retrieve_chunks_with_scores


@dataclass
class DocumentSearchResult:
    context: str
    docs: list[dict[str, Any]]
    timing_ms: int


class DocumentSearchTool:
    name = "document_search"

    def search(self, query: str, chat_id: str | None = None, top_k: int = TOP_K) -> DocumentSearchResult:
        started = perf_counter()
        results = retrieve_chunks_with_scores(query, k=top_k, chat_id=chat_id)
        return DocumentSearchResult(
            context=context_from_results(results),
            docs=docs_from_results(results),
            timing_ms=round((perf_counter() - started) * 1000),
        )

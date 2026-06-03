from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any

from src.agents.base_agent import context_from_results, docs_from_results
from src.config import TOP_K
from src.retriever import retrieve_chunks_bm25_from_store, retrieve_chunks_with_scores_from_store
from src.vector_store import get_vector_store


@dataclass
class DocumentSearchResult:
    context: str
    docs: list[dict[str, Any]]
    timing_ms: int
    breakdown: dict[str, Any]


class DocumentSearchTool:
    name = "document_search"

    def search(
        self,
        query: str,
        chat_id: str | None = None,
        top_k: int = TOP_K,
        bm25_enabled: bool = False,
    ) -> DocumentSearchResult:
        started = perf_counter()
        vector_store = get_vector_store(chat_id)
        if vector_store is None:
            return DocumentSearchResult(
                context="",
                docs=[],
                timing_ms=round((perf_counter() - started) * 1000),
                breakdown={
                    "parallel": True,
                    "enabled": ["vector", *([] if not bm25_enabled else ["bm25"])],
                    "counts": {"vector": 0, **({"bm25": 0} if bm25_enabled else {})},
                    "timings_ms": {},
                    "status": "no_index",
                },
            )

        searches = {"vector": lambda: retrieve_chunks_with_scores_from_store(vector_store, query, k=top_k)}
        if bm25_enabled:
            searches["bm25"] = lambda: retrieve_chunks_bm25_from_store(vector_store, query, k=top_k)

        def run_search(name: str, func):
            branch_started = perf_counter()
            try:
                return name, func(), round((perf_counter() - branch_started) * 1000), None
            except Exception as exc:
                return name, [], round((perf_counter() - branch_started) * 1000), str(exc)[:300]

        branch_results: dict[str, list[Any]] = {}
        branch_timings: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(searches)) as executor:
            futures = [executor.submit(run_search, name, func) for name, func in searches.items()]
            for future in as_completed(futures):
                name, items, timing_ms, error = future.result()
                branch_results[name] = items
                branch_timings[name] = timing_ms
                if error:
                    branch_timings[f"{name}_error_message"] = error

        results = _merge_retrieval_results(branch_results, top_k)
        return DocumentSearchResult(
            context=context_from_results(results),
            docs=docs_from_results(results),
            timing_ms=round((perf_counter() - started) * 1000),
            breakdown={
                "parallel": True,
                "enabled": ["vector", *([] if not bm25_enabled else ["bm25"])],
                "counts": {name: len(items) for name, items in branch_results.items()},
                "timings_ms": branch_timings,
            },
        )


def _merge_retrieval_results(results_by_name: dict[str, list[Any]], top_k: int) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    max_len = max((len(items) for items in results_by_name.values()), default=0)
    order = ["vector", "bm25"]
    for idx in range(max_len):
        for name in order:
            items = results_by_name.get(name) or []
            if idx >= len(items):
                continue
            item = items[idx]
            chunk = item[0] if isinstance(item, tuple) else item
            metadata = getattr(chunk, "metadata", {}) or {}
            key = "|".join(
                [
                    str(metadata.get("source", "")),
                    str(metadata.get("page", "")),
                    str(metadata.get("line", metadata.get("start_line", ""))),
                    str(getattr(chunk, "page_content", ""))[:120],
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= top_k:
                return merged
    return merged

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Protocol

from src.config import WEB_SEARCH_API_KEY, WEB_SEARCH_ENABLED, WEB_SEARCH_PROVIDER


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str = WEB_SEARCH_PROVIDER


class WebSearchUnavailable(RuntimeError):
    pass


class WebSearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        ...


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        payload = json.dumps({"query": query, "max_results": max_results, "search_depth": "basic"}).encode("utf-8")
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable(f"Tavily search failed: {exc}") from exc

        results = data.get("results") or []
        return [
            asdict(
                WebSearchResult(
                    title=str(item.get("title") or "Untitled web result"),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or item.get("snippet") or ""),
                    provider=self.name,
                )
            )
            for item in results[:max_results]
        ]


def _api_key() -> str:
    if WEB_SEARCH_API_KEY:
        return WEB_SEARCH_API_KEY
    provider = WEB_SEARCH_PROVIDER.upper()
    return os.getenv(f"{provider}_API_KEY", "")


def _provider() -> WebSearchProvider:
    provider = WEB_SEARCH_PROVIDER.lower().strip()
    api_key = _api_key()
    if provider == "tavily":
        if not api_key:
            raise WebSearchUnavailable("Tavily needs WEB_SEARCH_API_KEY or TAVILY_API_KEY in the environment.")
        return TavilySearchProvider(api_key)
    raise WebSearchUnavailable(
        f"Web provider '{WEB_SEARCH_PROVIDER}' is not configured. Supported live provider now: tavily."
    )


def web_search(query: str, max_results: int = 5) -> list[dict]:
    if not WEB_SEARCH_ENABLED:
        raise WebSearchUnavailable("Web search is disabled. Set WEB_SEARCH_ENABLED=true to enable it.")
    results = _provider().search(query, max_results=max_results)
    if not results:
        return stub_result("لم يرجع مزود البحث أي نتائج.")
    return results


def stub_result(message: str) -> list[dict]:
    return [asdict(WebSearchResult(title="Web search unavailable", url="", snippet=message, provider="unavailable"))]


class WebSearchTool:
    name = "web_search"

    def search(self, query: str, max_results: int = 5) -> dict:
        try:
            return {"available": True, "results": web_search(query, max_results=max_results), "error": None}
        except WebSearchUnavailable as exc:
            return {"available": False, "results": stub_result(str(exc)), "error": str(exc)}

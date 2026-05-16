from __future__ import annotations

from dataclasses import asdict, dataclass

from src.config import WEB_SEARCH_API_KEY, WEB_SEARCH_ENABLED, WEB_SEARCH_PROVIDER


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str = WEB_SEARCH_PROVIDER


class WebSearchUnavailable(RuntimeError):
    pass


def web_search(query: str, max_results: int = 5) -> list[dict]:
    if not WEB_SEARCH_ENABLED:
        raise WebSearchUnavailable("Web search is disabled. Set WEB_SEARCH_ENABLED=true to enable it.")
    if not WEB_SEARCH_API_KEY:
        raise WebSearchUnavailable(
            f"Web search provider '{WEB_SEARCH_PROVIDER}' needs WEB_SEARCH_API_KEY in the environment."
        )

    raise WebSearchUnavailable(
        "No live web provider adapter is configured yet. Add a provider implementation in src/tools/web_search_tool.py."
    )


def stub_result(message: str) -> list[dict]:
    return [asdict(WebSearchResult(title="Web search unavailable", url="", snippet=message))]


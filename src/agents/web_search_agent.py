from src.agents.base_agent import BaseAgent
from src.prompts import WEB_SEARCH_PROMPT
from src.tools.web_search_tool import WebSearchUnavailable, stub_result, web_search


class WebSearchAgent(BaseAgent):
    name = "Web Search"
    prompt = WEB_SEARCH_PROMPT
    use_retrieval = False

    def search(self, query: str) -> list[dict]:
        try:
            return web_search(query)
        except WebSearchUnavailable as exc:
            return stub_result(str(exc))


def web_search_agent(query: str) -> dict:
    agent = WebSearchAgent()
    sources = agent.search(query)
    context = "\n\n".join(
        f"[ويب {idx}] {item.get('title')}\nURL: {item.get('url')}\n{item.get('snippet')}"
        for idx, item in enumerate(sources, start=1)
    )
    answer = agent.invoke(agent.build_prompt(query, context))
    return {"answer": answer, "docs": [], "confidence": None, "tools_used": ["web_search"], "web_sources": sources}


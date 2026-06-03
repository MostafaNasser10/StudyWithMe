from __future__ import annotations

from typing import Any

from src.config import TOP_K
from src.tools.calculator_tool import CalculatorTool
from src.tools.document_search_tool import DocumentSearchTool
from src.tools.study_tools import ConceptExtractorTool, FlashcardGeneratorTool, StudyProgressTool
from src.tools.web_search_tool import WebSearchTool


SUPPORTED_FUNCTION_TOOLS = {
    "calculator",
    "document_search",
    "web_search",
    "flashcard_generator",
    "concept_extractor",
    "study_progress",
    "none",
}


def _document_grounded_web_query(arguments: dict[str, Any], state: dict[str, Any]) -> str:
    query = str(arguments.get("query") or state.get("user_query") or "")
    context = str(arguments.get("context") or state.get("context") or "").strip()
    if not context:
        context = "\n".join(str(doc.get("snippet") or "") for doc in (state.get("docs") or [])[:4]).strip()
    if state.get("source_scope") == "Documents + Web" and context:
        compact_context = " ".join(context.split())[:1200]
        return (
            f"{query}\n\n"
            "Search for external information specifically related to this uploaded document content. "
            "Do not search the generic user wording alone.\n"
            f"Document content preview: {compact_context}"
        )
    return query


def execute_registered_tool(tool_name: str, arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Execute a validated tool call selected by the LLM.

    This file is intentionally simple for learning:
    - The LLM chooses `tool_name` and JSON arguments.
    - This registry maps that name to real Python code.
    - Python executes the tool and returns normal dictionaries.
    """

    arguments = arguments or {}
    if tool_name == "none":
        return {"ok": True, "useful": False, "result": {"message": "No tool required."}}

    if tool_name == "calculator":
        result = CalculatorTool().run(str(arguments.get("expression") or state.get("user_query") or ""))
        return {"ok": bool(result.get("ok")), "useful": bool(result.get("ok")), "result": result}

    if tool_name == "document_search":
        query = str(arguments.get("query") or state.get("user_query") or "")
        top_k = int(arguments.get("top_k") or TOP_K)
        result = DocumentSearchTool().search(
            query,
            chat_id=state.get("chat_id"),
            top_k=top_k,
            bm25_enabled=bool(state.get("bm25_enabled")),
        )
        return {
            "ok": True,
            "useful": bool(result.docs),
            "result": {
                "context": result.context,
                "docs": result.docs,
                "timing_ms": result.timing_ms,
                "breakdown": result.breakdown,
            },
        }

    if tool_name == "web_search":
        web_allowed = state.get("source_scope") != "Documents only" and (
            bool(state.get("web_enabled")) or state.get("source_scope") == "Web only"
        )
        if not web_allowed:
            return {
                "ok": False,
                "useful": False,
                "result": {"available": False, "results": [], "error": "Web search blocked by source mode."},
                "error": "Web search blocked by source mode.",
            }
        query = _document_grounded_web_query(arguments, state)
        max_results = int(arguments.get("max_results") or 5)
        result = WebSearchTool().search(query, max_results=max_results)
        result["query"] = query
        return {"ok": bool(result.get("available")), "useful": bool(result.get("results")), "result": result}

    if tool_name == "flashcard_generator":
        result = FlashcardGeneratorTool().run(
            topic=str(arguments.get("topic") or state.get("user_query") or ""),
            context=str(arguments.get("context") or state.get("context") or ""),
            count=int(arguments.get("count") or 5),
        )
        return {"ok": True, "useful": bool(result.get("flashcards")), "result": result}

    if tool_name == "concept_extractor":
        result = ConceptExtractorTool().run(
            text=str(arguments.get("text") or state.get("context") or state.get("user_query") or ""),
            max_concepts=int(arguments.get("max_concepts") or 8),
        )
        return {"ok": True, "useful": bool(result.get("concepts")), "result": result}

    if tool_name == "study_progress":
        result = StudyProgressTool().run(arguments.get("quiz_result") or state.get("quiz_result") or {})
        return {"ok": True, "useful": True, "result": result}

    return {"ok": False, "useful": False, "result": {}, "error": f"Unsupported tool: {tool_name}"}

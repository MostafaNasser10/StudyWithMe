from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.graph.nodes import _fallback_quiz, _requested_question_count, final_composer_node, quiz_generation_node, router_node
from src.graph.app_graph import run_study_graph
from src.tools.quiz_grading_tool import QuizGradingTool
from src.tools.web_search_tool import WebSearchTool


def _route(query: str, **extra) -> str:
    state = {"chat_id": "test", "user_query": query, "source_scope": "Documents only", "web_enabled": False, **extra}
    return router_node(state)["route"]


def test_router_routes():
    assert _route("Calculate 12 * (4 + 3)") == "calculator"
    assert _route("Explain RAG from my file") == "tutor_rag"
    assert _route("Make 5 MCQ questions from chapter 2") == "quiz_generate"
    assert _route("What is the latest OpenAI news?", source_scope="Web only", web_enabled=True) == "web_search"
    assert _route("Who won champions league 2026") == "tutor_rag"
    assert _route("Who won champions league 2026", source_scope="Web only", web_enabled=True) == "web_search"
    assert _route("Explain attention then test me with MCQ") == "multi_task"
    assert _route("Explain RAG and make a quiz") == "multi_task"
    assert _route("فهمني RAG واعمل كويز") == "multi_task"
    assert _route("explain the document") == "summary"
    assert _route("اشرحلي الفايل") == "summary"
    assert _route("اشرح") == "summary"
    assert _route("اشرحلي الفايل", source_scope="Documents + Web", web_enabled=True) == "summary"
    assert _route("اشرحلي الفايل", source_scope="Web only", web_enabled=True) == "clarify"
    assert _route("havp") == "clarify"


def test_planner_multi_task_routes():
    state = router_node(
        {
            "chat_id": "test",
            "user_query": "Summarize this document and make a study plan.",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "multi_task"
    assert [task["type"] for task in state["tasks"]] == ["summary", "study_plan"]

    state = router_node(
        {
            "chat_id": "test",
            "user_query": "Explain, summarize, and make a quiz.",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "multi_task"
    assert [task["type"] for task in state["tasks"]] == ["explain", "summary", "quiz_generate"]

    state = router_node(
        {
            "chat_id": "test",
            "user_query": "Search web and explain the latest LLM news.",
            "source_scope": "Web only",
            "web_enabled": True,
        }
    )
    assert state["route"] == "multi_task"
    assert [task["type"] for task in state["tasks"]] == ["web_search", "explain"]


def test_quiz_grading_tool():
    quiz = {
        "quiz_id": "quiz_1",
        "questions": [
            {"id": "q1", "question": "Q1", "correct_answer": "A", "explanation": "E1", "source_refs": []},
            {"id": "q2", "question": "Q2", "correct_answer": "C", "explanation": "E2", "source_refs": []},
        ],
    }
    result = QuizGradingTool().grade(quiz, {"q1": "A", "q2": "B"})
    assert result["total"] == 2
    assert result["correct"] == 1
    assert result["percentage"] == 50.0
    assert result["details"][1]["correct_answer"] == "C"


def test_arabic_question_count_and_fallback_quiz():
    assert _requested_question_count("اعملي quiz سؤالين بس") == 2
    quiz = _fallback_quiz(
        "اعملي quiz سؤالين بس",
        [
            {
                "rank": 1,
                "source_name": "global_rag.pdf",
                "location": "الصفحة 1",
                "snippet": "RAG systems use retrieval and generation with reliable ground truth evaluation.",
            }
        ],
    )
    assert quiz is not None
    assert len(quiz["questions"]) == 2
    assert "حسب المقطع" not in quiz["questions"][0]["question"]
    assert "document distributions" not in quiz["questions"][0]["choices"]["A"]


def test_multi_task_quiz_preserves_structured_quiz_message():
    state = {
        "chat_id": "test",
        "user_query": "Explain RAG and make a quiz",
        "route": "multi_task",
        "tasks": [{"type": "quiz_generate", "title": "الاختبار"}],
        "current_task_index": 0,
        "is_multi_task": True,
        "source_scope": "Documents only",
        "web_enabled": False,
        "raw_answer": "## الشرح\nهذا شرح يجب أن يظهر قبل الاختبار.",
        "final_answer": "## الشرح\nهذا شرح يجب أن يظهر قبل الاختبار.",
        "docs": [],
        "context": "",
        "web_sources": [],
        "tools_used": [],
        "trace": {},
        "timings_ms": {},
    }
    result = quiz_generation_node(state)
    assert "هذا شرح يجب أن يظهر قبل الاختبار" in result["final_answer"]
    assert "ملاحظة عن الاختبار" in result["final_answer"]


def test_web_search_disabled_returns_stub():
    import src.tools.web_search_tool as web_search_module

    previous = web_search_module.WEB_SEARCH_ENABLED
    web_search_module.WEB_SEARCH_ENABLED = False
    result = WebSearchTool().search("latest LLM news")
    web_search_module.WEB_SEARCH_ENABLED = previous
    assert result["available"] is False
    assert result["results"]
    assert result["results"][0]["provider"] == "unavailable"


def test_graph_no_docs_tutor_path_returns_clear_message():
    state = run_study_graph(
        {
            "chat_id": "missing-test-chat",
            "user_query": "Explain RAG from my file",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "tutor_rag"
    assert "لا توجد مستندات" in state["final_answer"]


def test_graph_calculator_path_returns_direct_answer():
    state = run_study_graph(
        {
            "chat_id": "test",
            "user_query": "Calculate 12 * (4 + 3)",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "calculator"
    assert "84" in state["final_answer"]


def test_graph_quiz_path_returns_valid_quiz_object():
    state = run_study_graph(
        {
            "chat_id": "test",
            "user_query": "Make 1 MCQ question about RAG",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "quiz_generate"
    assert state.get("quiz") is None
    assert state["next_action"] == "final"
    assert "لا أستطيع إنشاء اختبار" in state["final_answer"]


def test_graph_garbage_path_does_not_retrieve_docs():
    state = run_study_graph(
        {
            "chat_id": "test",
            "user_query": "havp",
            "source_scope": "Documents only",
            "web_enabled": False,
        }
    )
    assert state["route"] == "clarify"
    assert not state.get("docs")
    assert "لم أفهم الطلب" in state["final_answer"]


if __name__ == "__main__":
    test_router_routes()
    test_planner_multi_task_routes()
    test_quiz_grading_tool()
    test_arabic_question_count_and_fallback_quiz()
    test_multi_task_quiz_preserves_structured_quiz_message()
    test_web_search_disabled_returns_stub()
    test_graph_no_docs_tutor_path_returns_clear_message()
    test_graph_calculator_path_returns_direct_answer()
    test_graph_quiz_path_returns_valid_quiz_object()
    test_graph_garbage_path_does_not_retrieve_docs()
    print("graph workflow tests passed")

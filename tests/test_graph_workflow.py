from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.graph.nodes as graph_nodes
import src.tools.document_search_tool as document_search_module
from src.graph.app_graph import run_study_graph
from src.graph.nodes import (
    _fallback_quiz,
    _requested_question_count,
    critic_node,
    quiz_generation_node,
    reflection_node,
    router_node,
    tool_calling_node,
    tutor_answer_node,
)
from src.graph.schemas import ToolCallPlan, ToolCallRequest
from src.tools.quiz_grading_tool import QuizGradingTool
from src.tools.tool_registry import execute_registered_tool
from src.tools.web_search_tool import WebSearchTool
from src.ui.chat_view import _sync_active_quiz_after_graph


def _planner_json(
    route: str,
    tasks: list[dict],
    *,
    selected_agent: str = "RAG Tutor",
    needs_documents: bool = False,
    needs_web: bool = False,
    answer_style: str = "direct",
    tool_calls: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "route": route,
            "tasks": tasks,
            "selected_agent": selected_agent,
            "needs_documents": needs_documents,
            "needs_web": needs_web,
            "answer_style": answer_style,
            "tool_calls": tool_calls or [{"tool_name": "none", "arguments": {}, "reasoning": "No tool needed"}],
        },
        ensure_ascii=False,
    )


def _with_fake_llm(planner_response: str, answer_response: str = "# الإجابة\nتمت الإجابة."):
    original = graph_nodes._invoke_llm

    def fake_llm(state, prompt: str, *args, **kwargs):
        if "StudyWithMe Arabic AI planner" in prompt:
            return planner_response
        return answer_response

    graph_nodes._invoke_llm = fake_llm
    return original


def _restore_llm(original) -> None:
    graph_nodes._invoke_llm = original


def _route(query: str, planner_response: str, **extra) -> str:
    original = _with_fake_llm(planner_response)
    try:
        state = {"chat_id": "test", "user_query": query, "source_scope": "Documents only", "web_enabled": False, **extra}
        return router_node(state)["route"]
    finally:
        _restore_llm(original)


def test_router_uses_llm_planner_routes():
    assert _route("Explain RAG from my file", _planner_json("tutor_rag", [{"type": "explain", "title": "Explanation"}], needs_documents=True)) == "tutor_rag"
    assert _route("Make 5 MCQ questions from chapter 2", _planner_json("quiz_generate", [{"type": "quiz_generate", "title": "Quiz", "num_questions": 5}], needs_documents=True)) == "quiz_generate"
    assert _route(
        "What is the latest OpenAI news?",
        _planner_json("web_search", [{"type": "web_search", "title": "Web Search"}], selected_agent="Web Search", needs_web=True, tool_calls=[{"tool_name": "web_search", "arguments": {"query": "latest OpenAI news"}, "reasoning": "current info"}]),
        source_scope="Web only",
        web_enabled=True,
    ) == "web_search"
    assert _route("Explain RAG and make a quiz", _planner_json("multi_task", [{"type": "explain", "title": "Explanation"}, {"type": "quiz_generate", "title": "Quiz"}], needs_documents=True)) == "multi_task"
    assert _route("havp", _planner_json("clarify", [{"type": "clarify", "title": "Clarify"}], selected_agent="Input Guard")) == "clarify"


def test_planner_can_return_tasks_and_tools_together():
    planner = _planner_json(
        "multi_task",
        [{"type": "explain", "title": "Explanation"}, {"type": "quiz_generate", "title": "Quiz"}],
        needs_documents=True,
        tool_calls=[{"tool_name": "document_search", "arguments": {"query": "RAG", "top_k": 4}, "reasoning": "Need uploaded context"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "Explain RAG and make a quiz", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "multi_task"
    assert [task["type"] for task in state["tasks"]] == ["explain", "quiz_generate"]
    assert state["planned_tool_calls"][0]["tool_name"] == "document_search"


def test_documents_only_blocks_web_route_and_tool():
    planner = _planner_json(
        "multi_task",
        [{"type": "explain", "title": "Explanation"}, {"type": "web_search", "title": "Web Search"}],
        needs_documents=True,
        needs_web=True,
        tool_calls=[
            {"tool_name": "document_search", "arguments": {"query": "uploaded file"}, "reasoning": "Need file"},
            {"tool_name": "web_search", "arguments": {"query": "explain file"}, "reasoning": "Should be blocked"},
        ],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "Explain the file", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert state["needs_web"] is False
    assert [call["tool_name"] for call in state["planned_tool_calls"]] == ["document_search"]


def test_clear_file_explanation_repairs_bad_clarify_plan():
    planner = _planner_json(
        "clarify",
        [{"type": "clarify", "title": "Clarify"}],
        selected_agent="Input Guard",
        needs_documents=True,
        tool_calls=[{"tool_name": "none", "arguments": {}, "reasoning": "Bad planner choice"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرح الملف", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert state["selected_agent"] == "Summary"
    assert state["needs_documents"] is True
    assert state["answer_style"] == "study_report"
    assert state["planned_tool_calls"][0]["tool_name"] == "document_search"


def test_arabic_explain_my_file_repairs_bad_clarify_plan():
    planner = _planner_json(
        "clarify",
        [{"type": "clarify", "title": "Clarify"}],
        selected_agent="Input Guard",
        needs_documents=True,
        tool_calls=[{"tool_name": "none", "arguments": {}, "reasoning": "Bad planner choice"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرحلي الملف", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert state["selected_agent"] == "Summary"
    assert state["planned_tool_calls"][0]["tool_name"] == "document_search"


def test_arabic_explain_fayl_repairs_bad_clarify_plan():
    planner = _planner_json(
        "clarify",
        [{"type": "clarify", "title": "Clarify"}],
        selected_agent="Input Guard",
        needs_documents=True,
        tool_calls=[{"tool_name": "none", "arguments": {}, "reasoning": "Bad planner choice"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرحلي الفايل", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert state["selected_agent"] == "Summary"
    assert state["needs_documents"] is True
    assert state["planned_tool_calls"][0]["tool_name"] == "document_search"


def test_file_request_falls_back_when_planner_llm_fails():
    original = graph_nodes._invoke_llm

    def failing_llm(state, prompt: str, *args, **kwargs):
        raise RuntimeError("planner unavailable")

    graph_nodes._invoke_llm = failing_llm
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرحلي الفايل", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert state["selected_agent"] == "Summary"
    assert state["planned_tool_calls"][0]["tool_name"] == "document_search"


def test_arabic_calculator_repairs_bad_clarify_plan():
    planner = _planner_json(
        "clarify",
        [{"type": "clarify", "title": "Clarify"}],
        selected_agent="Input Guard",
        tool_calls=[{"tool_name": "none", "arguments": {}, "reasoning": "Bad planner choice"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "احسب 4*7", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "tutor_rag"
    assert [task["type"] for task in state["tasks"]] == ["explain"]
    assert state["needs_documents"] is False
    assert state["planned_tool_calls"][0]["tool_name"] == "calculator"
    assert state["planned_tool_calls"][0]["arguments"]["expression"] == "4*7"


def test_web_only_file_explanation_stays_clarify():
    planner = _planner_json(
        "clarify",
        [{"type": "clarify", "title": "Clarify"}],
        selected_agent="Input Guard",
        needs_documents=True,
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرح الملف", "source_scope": "Web only", "web_enabled": True})
    finally:
        _restore_llm(original)
    assert state["route"] == "clarify"
    assert state["needs_documents"] is False


def test_documents_plus_web_search_uses_document_context():
    result = execute_registered_tool(
        "web_search",
        {"query": "explain file"},
        {
            "chat_id": "test",
            "user_query": "explain file",
            "source_scope": "Documents + Web",
            "web_enabled": True,
            "context": "Embedded systems use dedicated processors, real-time constraints, and hardware/software co-design.",
        },
    )
    query = result["result"]["query"]
    assert "explain file" in query
    assert "Embedded systems" in query
    assert "generic user wording" in query


def test_documents_plus_web_file_request_forces_document_grounded_web_step():
    planner = _planner_json(
        "summary",
        [{"type": "summary", "title": "Summary"}],
        selected_agent="Summary",
        needs_documents=True,
        needs_web=False,
        tool_calls=[{"tool_name": "document_search", "arguments": {"query": "explain file"}, "reasoning": "Need file"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "Explain the file", "source_scope": "Documents + Web", "web_enabled": True})
    finally:
        _restore_llm(original)
    assert state["needs_documents"] is True
    assert state["needs_web"] is True
    assert any(task["type"] == "web_search" for task in state["tasks"])


def test_file_plus_arithmetic_request_does_not_become_quiz():
    planner = _planner_json(
        "quiz_generate",
        [{"type": "quiz_generate", "title": "Quiz"}],
        selected_agent="Quiz",
        needs_documents=True,
        tool_calls=[{"tool_name": "none", "arguments": {}, "reasoning": "Bad planner choice"}],
    )
    original = _with_fake_llm(planner)
    try:
        state = router_node({"chat_id": "test", "user_query": "اشرح الفايل و احسب 5*7", "source_scope": "Documents only", "web_enabled": False})
    finally:
        _restore_llm(original)
    assert state["route"] == "summary"
    assert [task["type"] for task in state["tasks"]] == ["summary"]
    assert [call["tool_name"] for call in state["planned_tool_calls"]] == ["calculator", "document_search"]


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


def test_tool_call_request_schema():
    call = ToolCallRequest(tool_name="calculator", arguments={"expression": "25 * 4"}, reasoning="math")
    assert call.tool_name == "calculator"
    plan = ToolCallPlan(tool_calls=[call, ToolCallRequest(tool_name="calculator", arguments={}, reasoning="duplicate")])
    assert len(plan.tool_calls) == 1


def test_function_calling_executes_planned_multiple_tools():
    state = {
        "chat_id": "test",
        "user_query": "Calculate 25 * 4 and extract concepts from RAG retrieval generation",
        "route": "tutor_rag",
        "source_scope": "Documents only",
        "web_enabled": False,
        "context": "",
        "tools_used": [],
        "trace": {},
        "timings_ms": {},
        "planned_tool_calls": [
            {"tool_name": "calculator", "arguments": {"expression": "25 * 4"}, "reasoning": "math requested"},
            {"tool_name": "concept_extractor", "arguments": {"text": "RAG retrieval generation"}, "reasoning": "concept extraction requested"},
        ],
    }
    result = tool_calling_node(state)
    assert [call["tool_name"] for call in result["tool_calls"]] == ["calculator", "concept_extractor"]
    assert result["tool_results"][0]["result"]["result"] == 100
    assert "function:calculator" in result["tools_used"]
    assert "function:concept_extractor" in result["tools_used"]
    assert "FUNCTION CALL CONTEXT" in result["context"]


def test_tutor_answer_appends_calculator_result_if_llm_omits_it():
    original = _with_fake_llm("{}", answer_response="# الإجابة\nشرحت الملف المطلوب.")
    try:
        state = tutor_answer_node(
            {
                "chat_id": "test",
                "user_query": "اشرح الفايل و احسب 5*7",
                "prompt": "answer",
                "tool_results": [
                    {
                        "tool_name": "calculator",
                        "ok": True,
                        "result": {"ok": True, "expression": "5*7", "result": 35},
                    }
                ],
                "trace": {},
                "timings_ms": {},
            }
        )
    finally:
        _restore_llm(original)
    assert "نتيجة الحساب" in state["final_answer"]
    assert "35" in state["final_answer"]


def test_reflection_agent_enabled_updates_answer():
    original = graph_nodes._invoke_llm
    original_quality_mode = graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED

    def fake_llm(state, prompt: str, *args, **kwargs):
        return json.dumps(
            {
                "passed": False,
                "issues": ["Needs clearer Arabic structure."],
                "improved_answer": "# إجابة محسنة\nشرح أوضح.",
            },
            ensure_ascii=False,
        )

    graph_nodes._invoke_llm = fake_llm
    graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = True
    try:
        state = reflection_node(
            {
                "chat_id": "test",
                "user_query": "اشرح RAG",
                "final_answer": "شرح ضعيف",
                "context": "RAG uses retrieval.",
                "reflection_enabled": True,
                "trace": {},
                "timings_ms": {},
            }
        )
    finally:
        graph_nodes._invoke_llm = original
        graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = original_quality_mode
    assert state["answer_before_reflection"] == "شرح ضعيف"
    assert state["reflection_result"]["passed"] is False
    assert "إجابة محسنة" in state["final_answer"]


def test_reflection_agent_disabled_leaves_answer():
    state = reflection_node(
        {
            "chat_id": "test",
            "user_query": "اشرح RAG",
            "final_answer": "الإجابة الأصلية",
            "reflection_enabled": False,
            "trace": {},
            "timings_ms": {},
        }
    )
    assert state["final_answer"] == "الإجابة الأصلية"
    assert state["reflection_result"]["status"] == "disabled"


def test_quality_agents_fast_mode_does_not_call_llm():
    original = graph_nodes._invoke_llm
    original_quality_mode = graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED

    def fail_if_called(state, prompt: str, *args, **kwargs):
        raise AssertionError("quality fast mode should not call the LLM")

    graph_nodes._invoke_llm = fail_if_called
    graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = False
    try:
        state = {
            "chat_id": "test",
            "user_query": "اشرح RAG",
            "final_answer": "# الإجابة\nRAG uses retrieval.\n\n# المصدر\nlecture.pdf",
            "context": "RAG uses retrieval.",
            "docs": [{"snippet": "RAG uses retrieval.", "source_name": "lecture.pdf"}],
            "reflection_enabled": True,
            "critic_enabled": True,
            "trace": {},
            "timings_ms": {},
        }
        reflected = reflection_node(dict(state))
        criticized = critic_node(dict(state))
    finally:
        graph_nodes._invoke_llm = original
        graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = original_quality_mode

    assert reflected["reflection_result"]["status"] == "fast"
    assert criticized["critic_result"]["status"] == "fast"
    assert criticized["critic_result"]["risk_level"] == "low"


def test_critic_agent_disabled_leaves_answer():
    state = critic_node(
        {
            "chat_id": "test",
            "user_query": "اشرح RAG",
            "final_answer": "الإجابة الأصلية",
            "critic_enabled": False,
            "trace": {},
            "timings_ms": {},
        }
    )
    assert state["final_answer"] == "الإجابة الأصلية"
    assert state["critic_result"]["status"] == "disabled"


def test_critic_agent_improves_medium_risk_answer():
    original = graph_nodes._invoke_llm
    original_quality_mode = graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED

    def fake_llm(state, prompt: str, *args, **kwargs):
        return json.dumps(
            {
                "passed": False,
                "criticism": ["Unsupported claim detected."],
                "risk_level": "medium",
                "improved_answer": "# إجابة مصححة\nتم حذف الادعاء غير المدعوم.",
            },
            ensure_ascii=False,
        )

    graph_nodes._invoke_llm = fake_llm
    graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = True
    try:
        state = critic_node(
            {
                "chat_id": "test",
                "user_query": "اشرح RAG",
                "final_answer": "RAG invented the internet.",
                "context": "RAG uses retrieval.",
                "critic_enabled": True,
                "trace": {},
                "timings_ms": {},
            }
        )
    finally:
        graph_nodes._invoke_llm = original
        graph_nodes.QUALITY_AGENT_LLM_REVIEW_ENABLED = original_quality_mode
    assert state["critic_result"]["risk_level"] == "medium"
    assert "إجابة مصححة" in state["final_answer"]


def test_quality_agents_skip_structured_quiz_waiting_state():
    base_state = {
        "chat_id": "test",
        "user_query": "اعمل اختبار",
        "final_answer": "تم إنشاء الاختبار.",
        "quiz": {"quiz_id": "q1", "questions": []},
        "next_action": "await_quiz_submission",
        "final_sections": [],
        "reflection_enabled": True,
        "critic_enabled": True,
        "trace": {},
        "timings_ms": {},
    }
    reflected = reflection_node(dict(base_state))
    criticized = critic_node(dict(base_state))
    assert reflected["reflection_result"]["status"] == "skipped"
    assert criticized["critic_result"]["status"] == "skipped"


def test_non_quiz_graph_result_clears_stale_active_quiz():
    class FakeStore:
        def __init__(self):
            self.updates = []

        def update_chat(self, chat_id, **kwargs):
            self.updates.append((chat_id, kwargs))

    store = FakeStore()
    metadata = _sync_active_quiz_after_graph("chat-test", store, {"final_answer": "answer", "quiz": None})
    assert metadata == {}
    assert store.updates[-1] == ("chat-test", {"active_quiz": None})


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
    planner = _planner_json("tutor_rag", [{"type": "explain", "title": "Explanation"}], needs_documents=True)
    original = _with_fake_llm(planner)
    previous_timeout = graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS
    graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS = 2
    try:
        state = run_study_graph(
            {
                "chat_id": "missing-test-chat",
                "user_query": "Explain RAG from my file",
                "source_scope": "Documents only",
                "web_enabled": False,
            }
        )
    finally:
        graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS = previous_timeout
        _restore_llm(original)
    assert state["route"] == "tutor_rag"
    assert "لا توجد مستندات" in state["final_answer"]


def test_graph_calculator_uses_llm_tool_selection():
    planner = _planner_json(
        "tutor_rag",
        [{"type": "explain", "title": "Explanation"}],
        needs_documents=False,
        tool_calls=[{"tool_name": "calculator", "arguments": {"expression": "12 * (4 + 3)"}, "reasoning": "math requested"}],
    )
    original = _with_fake_llm(planner, answer_response="# الإجابة\nنتيجة العملية هي 84.")
    try:
        state = run_study_graph(
            {
                "chat_id": "test",
                "user_query": "Calculate 12 * (4 + 3)",
                "source_scope": "Documents only",
                "web_enabled": False,
            }
        )
    finally:
        _restore_llm(original)
    assert state["route"] == "tutor_rag"
    assert state["tool_call"]["tool_name"] == "calculator"
    assert state["tool_result"]["result"]["result"] == 84
    assert "function:calculator" in state["tools_used"]
    assert "84" in state["final_answer"]
    assert state["evaluation"]["status"] == "completed"
    assert state["trace"]["evaluation_result"]["evaluation_id"] == state["evaluation"]["evaluation_id"]


def test_graph_quiz_path_returns_valid_quiz_object():
    planner = _planner_json("quiz_generate", [{"type": "quiz_generate", "title": "Quiz"}], needs_documents=True)
    original = _with_fake_llm(planner)
    previous_timeout = graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS
    graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS = 2
    try:
        state = run_study_graph(
            {
                "chat_id": "test",
                "user_query": "Make 1 MCQ question about RAG",
                "source_scope": "Documents only",
                "web_enabled": False,
            }
        )
    finally:
        graph_nodes.GRAPH_RETRIEVAL_TIMEOUT_SECONDS = previous_timeout
        _restore_llm(original)
    assert state["route"] == "quiz_generate"
    assert state.get("quiz") is None
    assert state["next_action"] == "final"
    assert state["evaluation"]["status"] == "completed"
    assert "لا أستطيع إنشاء اختبار" in state["final_answer"]


def test_graph_garbage_path_does_not_retrieve_docs():
    planner = _planner_json("clarify", [{"type": "clarify", "title": "Clarify"}], selected_agent="Input Guard")
    original = _with_fake_llm(planner)
    try:
        state = run_study_graph(
            {
                "chat_id": "test",
                "user_query": "havp",
                "source_scope": "Documents only",
                "web_enabled": False,
            }
        )
    finally:
        _restore_llm(original)
    assert state["route"] == "clarify"
    assert not state.get("docs")
    assert "أحتاج طلبا أوضح" in state["final_answer"]


def test_document_search_can_merge_vector_and_bm25_parallel_branches():
    class FakeChunk:
        def __init__(self, text: str, source: str):
            self.page_content = text
            self.metadata = {"source": source, "page": 1}

    class FakeDocstore:
        def __init__(self, docs):
            self._dict = {str(idx): doc for idx, doc in enumerate(docs)}

    class FakeVectorStore:
        def __init__(self):
            self.vector_doc = FakeChunk("semantic vector hit", "vector.pdf")
            self.bm25_doc = FakeChunk("exact lexical bm25 hit", "bm25.pdf")
            self.docstore = FakeDocstore([self.vector_doc, self.bm25_doc])

        def similarity_search_with_score(self, query, k):
            return [(self.vector_doc, 0.1)]

        def similarity_search(self, query, k):
            return [self.vector_doc]

    original_store = document_search_module.get_vector_store
    try:
        document_search_module.get_vector_store = lambda chat_id=None: FakeVectorStore()
        result = document_search_module.DocumentSearchTool().search(
            "lexical query",
            chat_id="test",
            top_k=4,
            bm25_enabled=True,
        )
    finally:
        document_search_module.get_vector_store = original_store

    assert len(result.docs) == 2
    assert result.breakdown["parallel"] is True
    assert result.breakdown["counts"]["vector"] == 1
    assert result.breakdown["counts"]["bm25"] == 1


if __name__ == "__main__":
    test_router_uses_llm_planner_routes()
    test_planner_can_return_tasks_and_tools_together()
    test_documents_only_blocks_web_route_and_tool()
    test_clear_file_explanation_repairs_bad_clarify_plan()
    test_arabic_explain_my_file_repairs_bad_clarify_plan()
    test_arabic_explain_fayl_repairs_bad_clarify_plan()
    test_file_request_falls_back_when_planner_llm_fails()
    test_arabic_calculator_repairs_bad_clarify_plan()
    test_web_only_file_explanation_stays_clarify()
    test_documents_plus_web_search_uses_document_context()
    test_documents_plus_web_file_request_forces_document_grounded_web_step()
    test_file_plus_arithmetic_request_does_not_become_quiz()
    test_quiz_grading_tool()
    test_tool_call_request_schema()
    test_function_calling_executes_planned_multiple_tools()
    test_tutor_answer_appends_calculator_result_if_llm_omits_it()
    test_reflection_agent_enabled_updates_answer()
    test_reflection_agent_disabled_leaves_answer()
    test_quality_agents_fast_mode_does_not_call_llm()
    test_critic_agent_disabled_leaves_answer()
    test_critic_agent_improves_medium_risk_answer()
    test_quality_agents_skip_structured_quiz_waiting_state()
    test_non_quiz_graph_result_clears_stale_active_quiz()
    test_arabic_question_count_and_fallback_quiz()
    test_multi_task_quiz_preserves_structured_quiz_message()
    test_web_search_disabled_returns_stub()
    test_graph_no_docs_tutor_path_returns_clear_message()
    test_graph_calculator_uses_llm_tool_selection()
    test_graph_quiz_path_returns_valid_quiz_object()
    test_graph_garbage_path_does_not_retrieve_docs()
    test_document_search_can_merge_vector_and_bm25_parallel_branches()
    print("graph workflow tests passed")

from __future__ import annotations

from functools import lru_cache
import warnings

try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

    warnings.filterwarnings(
        "ignore",
        category=LangChainPendingDeprecationWarning,
        message=".*allowed_objects.*",
    )
except Exception:
    pass

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    END = None
    StateGraph = None

from src.graph.edges import after_retrieve_for_answer, after_retrieve_for_quiz, after_web_search, route_after_router, route_next_task
from src.graph.nodes import (
    arabic_guard_node,
    build_prompt_node,
    citation_checker_node,
    collect_task_output_node,
    critic_node,
    enable_langsmith_if_configured,
    evaluation_node,
    final_composer_node,
    parallel_agents_node,
    quiz_feedback_node,
    quiz_generation_node,
    reflection_node,
    retrieve_docs_node,
    router_node,
    save_trace_node,
    study_plan_node,
    summary_node,
    task_dispatcher_node,
    tool_calling_node,
    tutor_answer_node,
    web_search_node,
)
from src.graph.state import StudyGraphState
from src.llm import resolve_model_profile


def _initial_state(initial_state: StudyGraphState) -> StudyGraphState:
    model_settings = resolve_model_profile(
        profile=initial_state.get("model_profile"),
        provider=initial_state.get("llm_provider"),
        model=initial_state.get("llm_model"),
    )
    return {
        "docs": [],
        "context": "",
        "web_sources": [],
        "bm25_enabled": False,
        "retrieval_breakdown": {},
        "tools_used": [],
        "tool_call": None,
        "tool_result": None,
        "tool_calls": [],
        "tool_results": [],
        "tasks": [],
        "current_task_index": 0,
        "task_outputs": {},
        "task_results": [],
        "final_sections": [],
        "is_multi_task": False,
        "active_task": None,
        "parallel_agent_results": [],
        "needs_documents": False,
        "needs_web": False,
        "answer_style": "direct",
        "planned_tool_calls": [],
        "reflection_enabled": True,
        "critic_enabled": True,
        "reflection_result": None,
        "reflection_checks": {},
        "critic_result": None,
        "answer_before_reflection": None,
        "answer_before_critic": None,
        "external_rag_eval_enabled": False,
        "trace": {},
        "timings_ms": {},
        "error": None,
        "next_action": None,
        "model_profile": model_settings["profile"],
        "llm_provider": model_settings["provider"],
        "llm_model": model_settings["model"],
        **initial_state,
    }


@lru_cache(maxsize=1)
def build_graph():
    if StateGraph is None or END is None:
        raise RuntimeError("LangGraph is not installed. Run: pip install langgraph")

    enable_langsmith_if_configured()
    graph = StateGraph(StudyGraphState)

    graph.add_node("router", router_node)
    graph.add_node("tool_calling", tool_calling_node)
    graph.add_node("task_dispatcher", task_dispatcher_node)
    graph.add_node("collect_task_output", collect_task_output_node)
    graph.add_node("final_composer", final_composer_node)
    graph.add_node("parallel_agents", parallel_agents_node)
    graph.add_node("retrieve_docs", retrieve_docs_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("build_prompt", build_prompt_node)
    graph.add_node("tutor_answer", tutor_answer_node)
    graph.add_node("summary", summary_node)
    graph.add_node("quiz_generation", quiz_generation_node)
    graph.add_node("quiz_feedback", quiz_feedback_node)
    graph.add_node("study_plan", study_plan_node)
    graph.add_node("arabic_guard", arabic_guard_node)
    graph.add_node("reflection", reflection_node)
    graph.add_node("critic", critic_node)
    graph.add_node("citation_checker", citation_checker_node)
    graph.add_node("evaluation", evaluation_node)
    graph.add_node("save_trace", save_trace_node)

    graph.set_entry_point("router")
    graph.add_edge("router", "tool_calling")
    graph.add_conditional_edges(
        "tool_calling",
        route_after_router,
        {
            "multi_task": "task_dispatcher",
            "task_dispatcher": "task_dispatcher",
            "parallel_agents": "parallel_agents",
            "retrieve_docs": "retrieve_docs",
            "build_prompt": "build_prompt",
            "tutor_rag": "retrieve_docs",
            "summary": "retrieve_docs",
            "quiz_generate": "retrieve_docs",
            "quiz_generation": "quiz_generation",
            "feedback": "retrieve_docs",
            "study_plan": "retrieve_docs",
            "study_plan_direct": "study_plan",
            "web_search": "web_search",
            "documents_plus_web": "retrieve_docs",
            "clarify": "save_trace",
        },
    )

    graph.add_edge("parallel_agents", "final_composer")
    graph.add_conditional_edges("task_dispatcher", route_next_task, {
        "build_prompt": "build_prompt",
        "quiz_generation": "quiz_generation",
        "study_plan": "study_plan",
        "web_search": "web_search",
        "quiz_feedback": "quiz_feedback",
        "final_composer": "final_composer",
    })
    graph.add_conditional_edges(
        "retrieve_docs",
        _after_retrieve,
        {
            "web_search": "web_search",
            "task_dispatcher": "task_dispatcher",
            "parallel_agents": "parallel_agents",
            "build_prompt": "build_prompt",
            "quiz_generation": "quiz_generation",
            "study_plan": "study_plan",
            "arabic_guard": "arabic_guard",
        },
    )
    graph.add_conditional_edges(
        "web_search",
        _after_web_search_graph,
        {
            "task_dispatcher": "task_dispatcher",
            "parallel_agents": "parallel_agents",
            "build_prompt": "build_prompt",
            "arabic_guard": "arabic_guard",
            "collect_task_output": "collect_task_output",
        },
    )
    graph.add_conditional_edges("build_prompt", _after_build_prompt, {"summary": "summary", "tutor_answer": "tutor_answer"})
    graph.add_conditional_edges("summary", _after_task_node, {"collect_task_output": "collect_task_output", "arabic_guard": "arabic_guard"})
    graph.add_conditional_edges("tutor_answer", _after_task_node, {"collect_task_output": "collect_task_output", "arabic_guard": "arabic_guard"})
    graph.add_conditional_edges("quiz_generation", _after_task_node, {"collect_task_output": "collect_task_output", "evaluation": "evaluation"})
    graph.add_conditional_edges("quiz_feedback", _after_task_node, {"collect_task_output": "collect_task_output", "arabic_guard": "arabic_guard"})
    graph.add_conditional_edges("study_plan", _after_task_node, {"collect_task_output": "collect_task_output", "arabic_guard": "arabic_guard"})
    graph.add_edge("collect_task_output", "task_dispatcher")
    graph.add_edge("final_composer", "arabic_guard")
    graph.add_conditional_edges("arabic_guard", _after_guard, {"quiz_generation": "quiz_generation", "reflection": "reflection"})
    graph.add_edge("reflection", "critic")
    graph.add_edge("critic", "citation_checker")
    graph.add_edge("citation_checker", "evaluation")
    graph.add_edge("evaluation", "save_trace")
    graph.add_edge("save_trace", END)

    return graph.compile()


def _after_retrieve(state: StudyGraphState) -> str:
    route = state.get("route")
    if route == "multi_task":
        if state.get("next_action") == "final":
            return "arabic_guard"
        tasks = state.get("tasks") or []
        idx = int(state.get("current_task_index") or 0)
        first_pending = (tasks[idx] or {}).get("type") if idx < len(tasks) else None
        if state.get("needs_web") and not state.get("web_sources") and first_pending != "web_search":
            return "web_search"
        if _can_parallelize_tasks(state):
            return "parallel_agents"
        return "task_dispatcher"
    if state.get("next_action") == "final":
        return "arabic_guard"
    if route in {"tutor_rag", "summary", "feedback"} and state.get("needs_web") and not state.get("web_sources"):
        return "web_search"
    if route == "documents_plus_web":
        if state.get("web_sources"):
            return "build_prompt"
        return "web_search"
    if route == "quiz_generate":
        return after_retrieve_for_quiz(state)
    if route == "study_plan":
        return "study_plan"
    return after_retrieve_for_answer(state)


def _can_parallelize_tasks(state: StudyGraphState) -> bool:
    tasks = state.get("tasks") or []
    if len(tasks) <= 1:
        return False
    task_types = {str((task or {}).get("type") or "") for task in tasks}
    return "quiz_feedback" not in task_types


def _after_web_search_graph(state: StudyGraphState) -> str:
    if state.get("route") == "multi_task":
        task = state.get("active_task") or {}
        if task.get("type") == "web_search":
            return "collect_task_output"
        if _can_parallelize_tasks(state):
            return "parallel_agents"
        return "task_dispatcher"
    return after_web_search(state)


def _after_build_prompt(state: StudyGraphState) -> str:
    if state.get("route") == "multi_task":
        tasks = state.get("tasks") or []
        idx = int(state.get("current_task_index") or 0)
        task_type = str((tasks[idx] or {}).get("type") or "") if idx < len(tasks) else ""
        return "summary" if task_type == "summary" else "tutor_answer"
    if state.get("route") == "summary":
        return "summary"
    return "tutor_answer"


def _after_task_node(state: StudyGraphState) -> str:
    if state.get("route") == "multi_task":
        return "collect_task_output"
    if state.get("route") == "quiz_generate":
        return "evaluation"
    return "arabic_guard"


def _after_guard(state: StudyGraphState) -> str:
    return "reflection"


def run_study_graph(initial_state: StudyGraphState) -> StudyGraphState:
    state = _initial_state(initial_state)
    return build_graph().invoke(state)


def evaluate_completed_state(state: StudyGraphState, *, external_rag_eval_enabled: bool = False) -> StudyGraphState:
    evaluation_state = dict(state)
    evaluation_state["external_rag_eval_enabled"] = external_rag_eval_enabled
    evaluated = evaluation_node(evaluation_state)
    return save_trace_node(evaluated)


def stream_study_graph(initial_state: StudyGraphState):
    state = _initial_state(initial_state)
    latest = state
    for update in build_graph().stream(state, stream_mode="updates"):
        if not isinstance(update, dict):
            continue
        for node_name, node_state in update.items():
            if isinstance(node_state, dict):
                latest = {**latest, **node_state}
            yield node_name, latest

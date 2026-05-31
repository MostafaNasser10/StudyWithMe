from __future__ import annotations

from src.graph.state import StudyGraphState


def route_after_router(state: StudyGraphState) -> str:
    if state.get("route") == "multi_task":
        if state.get("needs_documents"):
            return "retrieve_docs"
        tasks = state.get("tasks") or []
        first_task_type = (tasks[0] or {}).get("type") if tasks else None
        if state.get("needs_web") and first_task_type != "web_search":
            return "web_search"
        return "task_dispatcher"
    return state.get("route", "tutor_rag")


def after_retrieve_for_answer(state: StudyGraphState) -> str:
    if state.get("next_action") == "final":
        return "arabic_guard"
    return "build_prompt"


def after_retrieve_for_quiz(state: StudyGraphState) -> str:
    if state.get("next_action") == "final":
        return "save_trace"
    return "quiz_generation"


def after_web_search(state: StudyGraphState) -> str:
    if state.get("next_action") == "final":
        return "arabic_guard"
    return "build_prompt"


def route_next_task(state: StudyGraphState) -> str:
    if state.get("next_action") == "compose_final":
        return "final_composer"
    tasks = state.get("tasks") or []
    idx = int(state.get("current_task_index") or 0)
    if idx >= len(tasks):
        return "final_composer"
    task_type = str((tasks[idx] or {}).get("type") or "explain")
    return {
        "explain": "build_prompt",
        "summary": "build_prompt",
        "quiz_generate": "quiz_generation",
        "study_plan": "study_plan",
        "web_search": "web_search",
        "calculator": "calculator",
        "quiz_feedback": "quiz_feedback",
        "feedback": "build_prompt",
        "clarify": "final_composer",
    }.get(task_type, "build_prompt")

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter

from src.chat.chat_models import now_iso
from src.tracing.trace_models import ComponentStep, PromptTrace


class Tracer:
    def __init__(self, chat_id: str, user_query: str):
        self.trace = PromptTrace.create(chat_id=chat_id, user_query=user_query)

    @contextmanager
    def step(self, name: str, input_summary: str = ""):
        started = perf_counter()
        step = ComponentStep(name=name, input_summary=input_summary)
        try:
            yield step
            step.status = "ok"
        except Exception as exc:
            step.status = "error"
            step.error = str(exc)
            raise
        finally:
            step.end_time = now_iso()
            step.duration_ms = round((perf_counter() - started) * 1000)
            self.trace.component_steps.append(step.__dict__.copy())

    def add_timing(self, name: str, duration_ms: int) -> None:
        self.trace.timings_ms[name] = duration_ms

    def set_agent(self, agent: str) -> None:
        self.trace.selected_agent = agent

    def set_docs(self, docs: list[dict]) -> None:
        self.trace.retrieved_docs = docs

    def add_tool(self, tool: str) -> None:
        if tool not in self.trace.tools_used:
            self.trace.tools_used.append(tool)

    def finish(self, final_answer: str, evaluation_result: dict | None = None) -> dict:
        self.trace.final_answer = final_answer
        self.trace.evaluation_result = evaluation_result
        return self.trace.to_dict()


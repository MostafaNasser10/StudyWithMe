from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from src.agents.base_agent import append_sources_section
from src.agents.feedback_agent import FeedbackAgent
from src.agents.quiz_agent import QuizAgent
from src.agents.study_plan_agent import StudyPlanAgent
from src.agents.summary_agent import SummaryAgent
from src.agents.tutor_agent import TutorAgent
from src.agents.web_search_agent import WebSearchAgent
from src.arabic_guard import enforce_arabic_answer
from src.config import SOURCE_SCOPES
from src.llm import get_llm
from src.tools.calculator_tool import calculation_needed, extract_expression, safe_calculate


@dataclass
class PreparedResponse:
    selected_agent: str
    route: list[str]
    prompt: str
    docs: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    web_sources: list[dict[str, Any]] = field(default_factory=list)
    direct_answer: str | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)


class Supervisor:
    def detect_route(self, query: str, source_scope: str = "Documents only", web_enabled: bool = False) -> str:
        text = query.lower()
        if calculation_needed(text):
            return "Calculator"
        if any(word in text for word in ["quiz", "mcq", "test", "اختبار", "أسئلة", "اسئلة", "امتحان"]):
            return "Quiz"
        if any(word in text for word in ["evaluate", "feedback", "correct", "score", "قيّم", "قيم", "صحح", "درجة"]):
            return "Feedback"
        if any(word in text for word in ["plan", "schedule", "roadmap", "خطة", "جدول", "ذاكر"]):
            return "Study Plan"
        if any(word in text for word in ["summary", "summarize", "تلخيص", "لخص", "ملخص"]):
            return "Summary"
        if source_scope == "Web only" or (web_enabled and any(word in text for word in ["latest", "today", "حديث", "آخر", "ويب"])):
            return "Web Search"
        return "RAG Tutor"

    def _agent_for(self, selected: str):
        return {
            "Quiz": QuizAgent,
            "Feedback": FeedbackAgent,
            "Study Plan": StudyPlanAgent,
            "Summary": SummaryAgent,
            "Web Search": WebSearchAgent,
        }.get(selected, TutorAgent)()

    def _direct_answer(self, body: str, source: str = "من النموذج") -> str:
        return f"""# الإجابة المختصرة
{body}

# الشرح التفصيلي
هذه إجابة مباشرة لا تحتاج إلى استرجاع مقاطع من الملفات.

# مثال توضيحي
إذا احتجت مثالا إضافيا، اكتب المطلوب بشكل محدد.

# المصادر والدليل
- {source}

# ملخص للمذاكرة
- راجع النتيجة أو التعليمات قبل استخدامها.
"""

    def prepare(
        self,
        query: str,
        chat_id: str,
        source_scope: str = "Documents only",
        web_enabled: bool = False,
    ) -> PreparedResponse:
        if source_scope not in SOURCE_SCOPES:
            source_scope = "Documents only"

        started = perf_counter()
        selected = self.detect_route(query, source_scope, web_enabled)
        route = ["Supervisor", selected]
        timings = {"routing_ms": round((perf_counter() - started) * 1000)}

        if selected == "Calculator":
            expression = extract_expression(query)
            if not expression:
                return PreparedResponse(
                    selected_agent="Calculator",
                    route=route,
                    prompt="",
                    tools_used=["calculator"],
                    direct_answer=self._direct_answer(
                        "لم أستطع استخراج عملية حسابية واضحة. اكتب العملية مثل: 12 * (4 + 3).",
                        "أداة الحاسبة",
                    ),
                    timings_ms=timings,
                )
            calc = safe_calculate(expression)
            return PreparedResponse(
                selected_agent="Calculator",
                route=route,
                prompt="",
                tools_used=["calculator"],
                direct_answer=self._direct_answer(
                    f"نتيجة العملية `{calc.expression}` هي: `{calc.result}`.",
                    "أداة الحاسبة",
                ),
                timings_ms=timings,
            )

        agent = self._agent_for(selected)
        docs: list[dict[str, Any]] = []
        context = ""
        web_sources: list[dict[str, Any]] = []

        if source_scope in {"Documents only", "Documents + Web"} and selected != "Web Search":
            started = perf_counter()
            context, docs = agent.retrieve(query, chat_id=chat_id)
            timings["retrieval_ms"] = round((perf_counter() - started) * 1000)
            if source_scope == "Documents only" and not docs:
                return PreparedResponse(
                    selected_agent=selected,
                    route=route,
                    prompt="",
                    docs=[],
                    direct_answer=self._direct_answer(
                        "لا توجد مستندات مفهرسة لهذه المحادثة بعد. ارفع ملفات من اللوحة اليمنى ثم اضغط Build / refresh index.",
                        "حالة قاعدة المعرفة",
                    ),
                    timings_ms=timings,
                )

        if source_scope in {"Web only", "Documents + Web"} and web_enabled:
            started = perf_counter()
            web_agent = WebSearchAgent()
            web_sources = web_agent.search(query)
            route.append("Web Tool")
            timings["web_ms"] = round((perf_counter() - started) * 1000)
            web_context = "\n\n".join(
                f"[ويب {idx}]\nTitle: {item.get('title')}\nURL: {item.get('url')}\nSnippet: {item.get('snippet')}"
                for idx, item in enumerate(web_sources, start=1)
            )
            context = f"{context}\n\nWEB CONTEXT:\n{web_context}".strip()

        prompt = agent.build_prompt(query=query, context=context)
        tools = ["web_search"] if web_sources else []
        return PreparedResponse(selected, route, prompt, docs, tools, web_sources, timings_ms=timings)

    def stream_prepared(self, prepared: PreparedResponse):
        if prepared.direct_answer is not None:
            yield prepared.direct_answer
            return

        llm = get_llm()
        if hasattr(llm, "stream"):
            for chunk in llm.stream(prepared.prompt):
                content = getattr(chunk, "content", str(chunk))
                if content:
                    yield content
        else:
            answer = llm.invoke(prepared.prompt).content
            for idx in range(0, len(answer), 28):
                yield answer[idx : idx + 28]

    def finalize_answer(self, raw_answer: str, query: str, prepared: PreparedResponse) -> str:
        if prepared.direct_answer is not None:
            return raw_answer
        llm = get_llm()
        guarded = enforce_arabic_answer(raw_answer, query, llm)
        return append_sources_section(guarded, prepared.docs, prepared.web_sources)


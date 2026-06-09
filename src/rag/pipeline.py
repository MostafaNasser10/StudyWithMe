from src.agents.base_agent import append_sources_section
from src.agents.tutor_agent import TutorAgent
from src.guardrails.arabic import enforce_arabic_answer
from src.llm import get_llm


def rag_answer(query: str, chat_id: str | None = None):
    agent = TutorAgent()
    context, docs = agent.retrieve(query, chat_id=chat_id)

    if not docs:
        return {
            "answer": "لا توجد مستندات مفهرسة بعد. من فضلك ارفع ملفات لهذه المحادثة ثم ابن الفهرس.",
            "docs": [],
            "confidence": None,
        }

    llm = get_llm()
    response = llm.invoke(agent.build_prompt(query, context))
    answer = enforce_arabic_answer(response.content, query, llm)
    answer = append_sources_section(answer, docs)
    return {"answer": answer, "docs": docs, "confidence": None}


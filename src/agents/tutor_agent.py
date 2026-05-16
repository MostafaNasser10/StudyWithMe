from src.agents.base_agent import BaseAgent
from src.prompts import RAG_SYSTEM_PROMPT


class TutorAgent(BaseAgent):
    name = "RAG Tutor"
    prompt = RAG_SYSTEM_PROMPT


def tutor_agent(query: str, chat_id: str | None = None) -> dict:
    agent = TutorAgent()
    context, docs = agent.retrieve(query, chat_id=chat_id)
    answer = agent.invoke(agent.build_prompt(query, context))
    return {"answer": answer, "docs": docs, "confidence": None, "tools_used": []}


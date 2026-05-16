from src.agents.base_agent import BaseAgent
from src.prompts import FEEDBACK_PROMPT


class FeedbackAgent(BaseAgent):
    name = "Feedback"
    prompt = FEEDBACK_PROMPT


def feedback_agent(query: str, chat_id: str | None = None) -> dict:
    agent = FeedbackAgent()
    context, docs = agent.retrieve(query, chat_id=chat_id)
    answer = agent.invoke(agent.build_prompt(query, context))
    return {"answer": answer, "docs": docs, "confidence": None, "tools_used": []}


from src.agents.base_agent import BaseAgent
from src.prompts import QUIZ_PROMPT


class QuizAgent(BaseAgent):
    name = "Quiz"
    prompt = QUIZ_PROMPT


def quiz_agent(query: str, chat_id: str | None = None) -> dict:
    agent = QuizAgent()
    context, docs = agent.retrieve(query, chat_id=chat_id)
    answer = agent.invoke(agent.build_prompt(query, context, "Generate 5 questions unless the user asks for a specific number."))
    return {"answer": answer, "docs": docs, "confidence": None, "tools_used": []}


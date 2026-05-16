from src.agents.base_agent import BaseAgent
from src.prompts import STUDY_PLAN_PROMPT


class StudyPlanAgent(BaseAgent):
    name = "Study Plan"
    prompt = STUDY_PLAN_PROMPT


def study_plan_agent(query: str, chat_id: str | None = None) -> dict:
    agent = StudyPlanAgent()
    context, docs = agent.retrieve(query, chat_id=chat_id)
    answer = agent.invoke(agent.build_prompt(query, context))
    return {"answer": answer, "docs": docs, "confidence": None, "tools_used": []}


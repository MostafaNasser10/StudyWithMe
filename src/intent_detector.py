from src.agents.supervisor import Supervisor


def detect_intent(user_input: str) -> str:
    return Supervisor().detect_route(user_input)


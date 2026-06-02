from src.llm import get_llm
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

llm = get_llm()

response = llm.invoke("Say hello in Arabic.")

print(response.content)

from src.rag import rag_answer

query = "What is GlobalQA?"

answer = rag_answer(query)

print("\nRAG ANSWER:\n")
print(answer)
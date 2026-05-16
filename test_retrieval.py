from src.retriever import retrieve_chunks

query = "What is GlobalQA?"

results = retrieve_chunks(query)

print(f"\nRetrieved {len(results)} chunks\n")

for i, chunk in enumerate(results):
    print("=" * 80)
    print(f"CHUNK {i+1}")
    print("=" * 80)

    print("\nSOURCE:")
    print(chunk.metadata)

    print("\nCONTENT:")
    print(chunk.page_content[:1000])

    print("\n")
from src.retrieval.document_loader import load_documents

documents = load_documents()

print(f"Loaded {len(documents)} pages")

print("\nFIRST PAGE:\n")
print(documents[0].page_content[:1000])

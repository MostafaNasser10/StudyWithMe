from src.document_loader import load_documents
from src.text_splitter import split_documents

documents = load_documents()

chunks = split_documents(documents)

print(f"\nLoaded pages: {len(documents)}")
print(f"Generated chunks: {len(chunks)}")

print("\nFIRST CHUNK:\n")
print(chunks[0].page_content)

print("\nSECOND CHUNK:\n")
print(chunks[1].page_content)
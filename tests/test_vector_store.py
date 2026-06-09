from src.retrieval.document_loader import load_documents
from src.retrieval.text_splitter import split_documents
from src.retrieval.vector_store import create_vector_store

documents = load_documents()

chunks = split_documents(documents)

vector_store = create_vector_store(chunks)

print("\nVector database created successfully!")

print(f"\nStored chunks: {len(chunks)}")

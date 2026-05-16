from src.document_loader import load_documents
from src.text_splitter import split_documents
from src.vector_store import create_vector_store

documents = load_documents()

chunks = split_documents(documents)

vector_store = create_vector_store(chunks)

print("\nVector database created successfully!")

print(f"\nStored chunks: {len(chunks)}")
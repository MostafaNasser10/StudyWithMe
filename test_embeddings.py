from src.embeddings import get_embedding_model

embedding_model = get_embedding_model()

text = "What is Retrieval-Augmented Generation?"

embedding = embedding_model.embed_query(text)

print(f"Embedding length: {len(embedding)}")

print("\nFirst 10 values:\n")
print(embedding[:10])
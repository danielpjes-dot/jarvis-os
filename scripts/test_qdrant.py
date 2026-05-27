from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

client = QdrantClient("http://127.0.0.1:6333")

collection_name = "jarvis_memory"

collections = client.get_collections().collections
existing = [c.name for c in collections]

if collection_name not in existing:
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=768,
            distance=Distance.COSINE
        )
    )

print("READY")
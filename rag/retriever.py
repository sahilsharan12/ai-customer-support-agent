
import re
from functools import lru_cache

import requests
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.config import (
    OLLAMA_BASE_URL, OLLAMA_EMBEDDING_MODEL, POLICY_RETRIEVAL, PROJECT_ROOT,
    VECTOR_STORE_DIR,
)


# ==========================================
# 1. CONFIGURATION
# ==========================================

COLLECTION_NAME = "customer_support_policies"
DOCUMENTS_DIR = PROJECT_ROOT / "rag" / "documents"
TOP_K = 3


# ==========================================
# 2. INITIALIZE CHROMADB
# ==========================================

@lru_cache(maxsize=1)
def get_collection():
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(VECTOR_STORE_DIR), settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection(name=COLLECTION_NAME)


@lru_cache(maxsize=1)
def build_local_index():
    sections = []
    for path in sorted(DOCUMENTS_DIR.glob("*.md")):
        document = path.read_text(encoding="utf-8").strip()
        if not document:
            continue
        title = document.splitlines()[0]
        chunks = re.split(r"(?m)(?=^## )", document)
        for chunk in chunks[1:] or chunks:
            sections.append({
                "content": f"{title}\n\n{chunk.strip()}",
                "source": path.name,
                "policy_type": path.stem,
            })
    if not sections:
        return None
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    vectors = vectorizer.fit_transform(section["content"] for section in sections)
    return sections, vectorizer, vectors


def retrieve_local_policy(query: str, top_k: int):
    index = build_local_index()
    if index is None:
        return []
    sections, vectorizer, vectors = index
    scores = (vectors @ vectorizer.transform([query]).T).toarray().ravel()
    matches = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)
    return [
        {**sections[idx], "distance": float(1 - scores[idx])}
        for idx in matches[:top_k]
        if scores[idx] >= 0.10
    ]


# ==========================================
# 3. GENERATE QUERY EMBEDDING
# ==========================================

def generate_query_embedding(query: str):

    if not isinstance(query, str) or not query.strip():
        raise ValueError("A valid search query is required.")

    try:

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={
                "model": OLLAMA_EMBEDDING_MODEL,
                "input": query.strip(),
                "keep_alive": 0,
            },
            timeout=120
        )

        response.raise_for_status()

        result = response.json()

        return result["embeddings"][0]

    except requests.exceptions.RequestException as error:

        raise RuntimeError(
            f"Embedding generation failed: {error}"
        )


# ==========================================
# 4. RETRIEVE RELEVANT POLICY DOCUMENTS
# ==========================================

def retrieve_policy(query: str, top_k: int = TOP_K):

    if not isinstance(query, str) or not query.strip():
        raise ValueError("A valid search query is required.")

    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    if POLICY_RETRIEVAL == "local":
        return retrieve_local_policy(query, top_k)
    if POLICY_RETRIEVAL != "vector":
        raise ValueError("POLICY_RETRIEVAL must be local or vector.")

    collection = get_collection()
    total_documents = collection.count()

    if total_documents == 0:
        return []

    query_embedding = generate_query_embedding(query)

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, total_documents),
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    retrieved_documents = []

    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for document, metadata, distance in zip(
        documents,
        metadatas,
        distances
    ):
        # Ollama returns unit vectors and Chroma's default distance is squared L2.
        if distance >= 1.35:
            continue

        retrieved_documents.append({

            "content": document,

            "source": metadata.get("source"),

            "policy_type": metadata.get("policy_type"),

            "distance": distance

        })

    return retrieved_documents


# ==========================================
# 5. BUILD POLICY CONTEXT
# ==========================================

def get_policy_context(query: str):
    return format_policy_context(retrieve_policy(query))


def format_policy_context(results: list[dict]) -> str:
    if not results:
        return "No relevant policy information was found."

    context = []

    for index, result in enumerate(results, start=1):

        context.append(
            f"""
Policy Reference {index}
Source: {result['source']}
Policy Type: {result['policy_type']}

Content:
{result['content']}
"""
        )

    return "\n".join(context)


# ==========================================
# 6. TEST POLICY RETRIEVAL
# ==========================================

if __name__ == "__main__":

    print("=" * 60)
    print("CUSTOMER SUPPORT POLICY RETRIEVER")
    print("=" * 60)

    query = (
        "I received a damaged product. "
        "Can I request a return and refund?"
    )

    print("\nCUSTOMER QUERY:")
    print(query)

    try:

        results = retrieve_policy(query)

        print("\nRETRIEVED POLICY DOCUMENTS:")
        print("=" * 60)

        if not results:

            print("No policy documents found.")

        else:

            for index, result in enumerate(results, start=1):

                print(f"\nRESULT {index}")
                print("-" * 60)

                print("Source:", result["source"])
                print("Policy:", result["policy_type"])
                print("Distance:", result["distance"])

                print("\nContent:")
                print(result["content"])

        # Test context generation
        print("\n" + "=" * 60)
        print("GENERATED POLICY CONTEXT")
        print("=" * 60)

        policy_context = get_policy_context(query)

        print(policy_context)

        print("\n" + "=" * 60)
        print("RETRIEVAL TEST COMPLETED")
        print("=" * 60)

    except Exception as error:

        print("\nERROR:", error)


import requests

from backend.config import OLLAMA_BASE_URL, OLLAMA_EMBEDDING_MODEL, VECTOR_STORE_DIR
from rag.retriever import DOCUMENTS_DIR, get_collection


CHUNK_SIZE = 1000


def split_text(text, chunk_size=CHUNK_SIZE):

    import re

    # Split documents into paragraphs
    paragraphs = re.split(r"\n\s*\n", text.strip())

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        # Add paragraph if it fits
        if len(current_chunk) + len(paragraph) <= chunk_size:

            current_chunk += "\n\n" + paragraph if current_chunk else paragraph

        else:

            if current_chunk:
                chunks.append(current_chunk.strip())

            # Handle paragraphs larger than chunk_size
            if len(paragraph) > chunk_size:

                words = paragraph.split()
                current_chunk = ""

                for word in words:

                    if len(current_chunk) + len(word) + 1 <= chunk_size:
                        current_chunk += " " + word if current_chunk else word

                    else:
                        chunks.append(current_chunk.strip())
                        current_chunk = word

            else:
                current_chunk = paragraph

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


# ==========================================
# 4. GENERATE EMBEDDINGS USING OLLAMA
# ==========================================

def generate_embeddings(texts):

    try:

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={
                "model": OLLAMA_EMBEDDING_MODEL,
                "input": texts,
                "keep_alive": 0,
            },
            timeout=120
        )

        response.raise_for_status()

        result = response.json()

        return result["embeddings"]

    except requests.exceptions.RequestException as error:

        raise RuntimeError(
            f"Ollama embedding request failed: {error}"
        )


# ==========================================
# 5. LOAD POLICY DOCUMENTS
# ==========================================

def load_documents():

    documents = []

    for file_path in sorted(DOCUMENTS_DIR.glob("*.md")):

        print(f"\nReading: {file_path.name}")

        text = file_path.read_text(
            encoding="utf-8"
        )

        chunks = split_text(text)

        for index, chunk in enumerate(chunks):

            documents.append({
                "id": f"{file_path.stem}_{index}",
                "text": chunk,
                "metadata": {
                    "source": file_path.name,
                    "policy_type": file_path.stem,
                    "chunk_index": index
                }
            })

        print(f"Chunks created: {len(chunks)}")

    return documents


# ==========================================
# 6. STORE DOCUMENTS IN CHROMADB
# ==========================================

def store_documents(documents):

    if not documents:
        print("No policy documents found.")
        return

    ids = [document["id"] for document in documents]
    texts = [document["text"] for document in documents]
    embeddings = generate_embeddings(texts)
    collection = get_collection()
    previous_ids = set(collection.get(include=[])["ids"])

    collection.upsert(
        ids=ids,
        documents=texts,
        metadatas=[
            document["metadata"]
            for document in documents
        ],
        embeddings=embeddings
    )

    stale_ids = previous_ids.difference(ids)
    if stale_ids:
        collection.delete(ids=sorted(stale_ids))

    print("\nDocuments successfully stored in ChromaDB.")


# ==========================================
# 7. MAIN EXECUTION
# ==========================================

def main():

    print("=" * 55)
    print("CUSTOMER SUPPORT RAG - DOCUMENT INGESTION")
    print("=" * 55)

    if not DOCUMENTS_DIR.exists():
        raise FileNotFoundError(
            f"Documents folder not found: {DOCUMENTS_DIR}"
        )

    documents = load_documents()

    store_documents(documents)

    print("\n" + "=" * 55)
    print("INGESTION COMPLETED")
    print("=" * 55)

    print("Total chunks:", get_collection().count())

    print("Vector database:", VECTOR_STORE_DIR)


if __name__ == "__main__":
    main()

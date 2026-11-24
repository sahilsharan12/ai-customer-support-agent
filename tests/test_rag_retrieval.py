import pytest

from rag import ingest, retriever


@pytest.mark.parametrize(
    ("query", "policy"),
    [
        ("What is the refund payment method?", "refund_policy.md"),
        ("How many days do I have to send it back?", "return_policy.md"),
        ("My shipment missed its estimated delivery date", "shipping_policy.md"),
    ],
)
def test_relevant_policy_ranks_first(query, policy):
    assert retriever.retrieve_policy(query)[0]["source"] == policy


def test_chroma_ingestion_and_retrieval(tmp_path, monkeypatch):
    retriever.get_collection.cache_clear()
    monkeypatch.setattr(retriever, "VECTOR_STORE_DIR", tmp_path / "chroma")
    monkeypatch.setattr(retriever, "POLICY_RETRIEVAL", "vector")
    monkeypatch.setattr(ingest, "generate_embeddings", lambda texts: [[1, 0], [0, 1]][:len(texts)])
    monkeypatch.setattr(retriever, "generate_query_embedding", lambda query: [1, 0])
    documents = [
        {"id": "return_0", "text": "Return window is seven days.", "metadata": {"source": "returns.md", "policy_type": "return"}},
        {"id": "refund_0", "text": "Refunds use the original payment method.", "metadata": {"source": "refunds.md", "policy_type": "refund"}},
    ]
    try:
        ingest.store_documents(documents)
        assert retriever.get_collection().count() == 2
        assert [item["source"] for item in retriever.retrieve_policy("return window")] == ["returns.md"]
        ingest.store_documents(documents[:1])
        assert retriever.get_collection().count() == 1
    finally:
        retriever.get_collection.cache_clear()

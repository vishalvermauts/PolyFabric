import pytest
from infinite_memory.core.store import VectorStore


def test_store_upsert_and_search(test_store):
    docs = [
        {
            "id": "doc1#L1-L10",
            "text": "def compute_loss(y_true, y_pred):\n    return ((y_true - y_pred) ** 2).mean()",
            "metadata": {"file_path": "model/loss.py", "start_line": 1, "end_line": 10, "project": "ai_demo"}
        },
        {
            "id": "doc2#L1-L10",
            "text": "function calculateScore(examId) {\n    return fetchScoreFromDb(examId);\n}",
            "metadata": {"file_path": "src/exam.ts", "start_line": 1, "end_line": 10, "project": "pte_trainer"}
        }
    ]
    count = test_store.upsert_documents(docs)
    assert count == 2
    assert test_store.count_chunks() == 2

    results = test_store.search("mean squared error loss function", top_k=1)
    assert len(results) > 0
    top = results[0]
    assert "compute_loss" in top["text"]


def test_store_maintenance_vacuum(test_store):
    test_store.upsert_document("doc1", "def foo(): pass", {"file_path": "foo.py"})
    size_before = test_store.get_disk_size_bytes()
    assert size_before > 0

    stats = test_store.maintenance_vacuum(older_than_days=0)
    assert "compacted" in stats
    assert "cleaned_versions" in stats
    assert stats["bytes_after"] > 0

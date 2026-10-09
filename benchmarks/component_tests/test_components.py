import pytest
from infinite_memory.core.store import VectorStore
from infinite_memory.core.router import SystemOneRouter
from infinite_memory.security.secret_masker import SecretMasker

def test_component_router_speed(benchmark):
    router = SystemOneRouter()
    prompt = "pinpoint def parse_ast in tree_sitter_ast.py"
    res = benchmark(router.classify_intent, prompt)
    assert res is not None

def test_component_secret_masker_speed(benchmark):
    masker = SecretMasker()
    text = "Authorization: Bearer sk-1234567890abcdef1234567890abcdef\npassword: secret_password_here"
    res = benchmark(masker.mask_text, text)
    assert "sk-" not in res

def test_component_vector_search_speed(benchmark, tmp_path):
    store = VectorStore(db_path=str(tmp_path / "bench_db"))
    # Seed small data
    chunks = [{"id": f"p:f:{i}", "content": f"function test_{i}() {{ return {i}; }}", "file_path": "test.ts", "symbol_name": f"test_{i}", "chunk_type": "function"} for i in range(10)]
    store.upsert_file_documents("test_proj", "test.ts", chunks)
    
    res = benchmark(store.search, "function test_5", project="test_proj", limit=5)
    assert len(res) > 0

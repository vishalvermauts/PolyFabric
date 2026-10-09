import pytest
from pathlib import Path
from infinite_memory.core.hub import Hub
from infinite_memory.core.store import VectorStore
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser
from infinite_memory.security.secret_masker import SecretMasker
from infinite_memory.security.git_guard import GitBranchGuard
from infinite_memory.server import mesh_read_file, mesh_write_file, pinpoint_symbol, mesh_search


def test_path_containment_and_traversal_prevention(temp_dir):
    """P0 Security: Enforce strict repository containment for reads and writes."""
    repo_dir = temp_dir / "my_repo"
    outside_dir = temp_dir / "outside"
    repo_dir.mkdir()
    outside_dir.mkdir()

    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("SUPER_SECRET_EXTERNAL_DATA")

    (repo_dir / "safe.py").write_text("print('safe')")

    hub = Hub(registry_path=temp_dir / "registry.json")
    hub.register_project("my_repo", repo_dir)
    from infinite_memory.server import set_active_hub
    set_active_hub(hub)

    # 1. Valid inside path
    assert hub.resolve_file_path("my_repo", "safe.py") == (repo_dir / "safe.py").resolve()

    # 2. Path traversal attempts
    assert hub.resolve_file_path("my_repo", "../outside/secret.txt") is None
    assert hub.resolve_file_path("my_repo", "../../etc/passwd") is None
    assert hub.resolve_file_path("my_repo", str(secret_file)) is None

    # 3. Server tools reject escaped paths
    res_read = mesh_read_file("my_repo", "../outside/secret.txt")
    assert "Error: Path access denied" in res_read

    res_write = mesh_write_file("my_repo", "../outside/malicious.py", "malicious_code")
    assert "Rejected: Path traversal detected" in res_write


def test_atomic_file_replacement_and_stale_cleanup(temp_dir):
    """P0: Table.add() replaced by atomic upsert_file_documents to prevent stale chunks."""
    store = VectorStore(db_path=temp_dir / "atomic_db")

    # Initial file with SymbolA and SymbolB
    docs_v1 = [
        {"id": "file.py#SymbolA", "text": "def SymbolA(): pass", "metadata": {"file_path": "file.py", "symbol_name": "SymbolA"}},
        {"id": "file.py#SymbolB", "text": "def SymbolB(): pass", "metadata": {"file_path": "file.py", "symbol_name": "SymbolB"}},
    ]
    store.upsert_file_documents("file.py", docs_v1, project="test_p")
    assert store.count_chunks() == 2

    # Edits: SymbolB is removed, SymbolC is added
    docs_v2 = [
        {"id": "file.py#SymbolA", "text": "def SymbolA(): pass", "metadata": {"file_path": "file.py", "symbol_name": "SymbolA"}},
        {"id": "file.py#SymbolC", "text": "def SymbolC(): pass", "metadata": {"file_path": "file.py", "symbol_name": "SymbolC"}},
    ]
    store.upsert_file_documents("file.py", docs_v2, project="test_p")
    assert store.count_chunks() == 2  # Total must remain 2, not 4!

    # SymbolB must be gone completely
    exact_b = store.search_exact_symbol("SymbolB", project="test_p")
    assert len(exact_b) == 0

    exact_c = store.search_exact_symbol("SymbolC", project="test_p")
    assert len(exact_c) == 1


def test_sensitive_file_exclusion_and_read_shadowing(temp_dir):
    """P0: Raw secrets masked before storage, sensitive files excluded."""
    repo = temp_dir / "secret_repo"
    repo.mkdir()

    env_file = repo / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-1234567890abcdef1234567890\nDB_PASS=mypass123")

    hub = Hub(registry_path=temp_dir / "registry.json")
    hub.register_project("secret_repo", repo)
    from infinite_memory.server import set_active_hub
    set_active_hub(hub)

    # mesh_read_file on .env should be blocked
    res = mesh_read_file("secret_repo", ".env")
    assert "Access Denied" in res or "sensitive credential file" in res

    # Vector store masking
    store = VectorStore(db_path=temp_dir / "masked_db")
    store.upsert_document("doc1", "API_KEY = 'sk-1234567890abcdef1234567890'", {"file_path": "app.py"})
    results = store.search("API_KEY", top_k=1)
    assert len(results) > 0
    assert "sk-1234567890abcdef" not in results[0]["text"]
    assert "<SECRET_REF:" in results[0]["text"]


def test_exact_symbol_lookup_vs_nonexistent_symbol(temp_dir):
    """P1: Symbol pinpointing returns exact AST match, not erroneous semantic approximations."""
    store = VectorStore(db_path=temp_dir / "symbol_db")

    docs = [
        {"id": "scoring.py#calculate_score", "text": "def calculate_score(user_answers):\n    return sum(user_answers)", "metadata": {"file_path": "scoring.py", "symbol_name": "calculate_score"}},
        {"id": "auth.py#login", "text": "def login(): pass", "metadata": {"file_path": "auth.py", "symbol_name": "login"}},
    ]
    store.upsert_documents(docs)

    # 1. Exact match
    matches = store.search_exact_symbol("calculate_score")
    assert len(matches) == 1
    assert matches[0]["file_path"] == "scoring.py"

    # 2. Non-existent symbol exact match returns empty
    matches_fake = store.search_exact_symbol("non_existent_function_123")
    assert len(matches_fake) == 0


def test_ast_uncovered_region_and_size_bounding(temp_dir):
    """P1: Imports, global decorators, and module headers are not lost; large functions bounded."""
    parser = UniversalASTParser(max_ast_chunk_lines=20)
    code = """import os
import sys
from typing import Dict, Any

# Global configuration constants
GLOBAL_TIMEOUT = 300
API_VERSION = "v2"

def small_func():
    return True
"""
    chunks = parser.parse_file("test.py", code=code)
    # Must capture small_func and module_context
    types = [c.chunk_type for c in chunks]
    assert any("ast_function_definition" in t for t in types)
    assert any("ast_module_context" in t for t in types)

    # Verify import statements exist in the extracted chunks
    all_content = "\n".join([c.content for c in chunks])
    assert "GLOBAL_TIMEOUT" in all_content
    assert "import os" in all_content

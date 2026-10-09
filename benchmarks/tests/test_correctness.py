import pytest
import os
import shutil
import tempfile
from pathlib import Path
from infinite_memory.core.store import VectorStore
from infinite_memory.core.watcher import MeshWatcherManager
from infinite_memory.security.secret_masker import SecretMasker, mask_secrets

@pytest.fixture
def temp_workspace():
    tmp = tempfile.mkdtemp(prefix="imp_bench_correctness_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)

def test_hardened_diff_secret_masking():
    diff_lines = [
        "+password: benchmark_fake_password_123",
        "-DB_PASS=benchmark_fake_password_123",
        "+API_KEY=benchmark_fake_password_123",
        "normal line: nothing to mask"
    ]
    raw_diff = "\n".join(diff_lines)
    masked, _ = mask_secrets(raw_diff)
    assert "benchmark_fake_password_123" not in masked
    assert "+password: <SECRET_REF:PASSWORD>" in masked
    assert "-DB_PASS=<SECRET_REF:DB_PASS>" in masked
    assert "+API_KEY=<SECRET_REF:API_KEY>" in masked
    assert "normal line: nothing to mask" in masked

def test_atomic_merge_insert_guarantee(temp_workspace):
    db_path = temp_workspace / "db"
    store = VectorStore(db_path=temp_workspace / "db")
    project = "test_atomic"
    file_path = "services/auth.py"
    
    # Round 1
    chunks_v1 = [
        {"id": f"{project}:{file_path}:1", "text": "def login(): pass", "metadata": {"file_path": file_path, "symbol_name": "login", "chunk_type": "function"}},
        {"id": f"{project}:{file_path}:2", "text": "def logout(): pass", "metadata": {"file_path": file_path, "symbol_name": "logout", "chunk_type": "function"}}
    ]
    store.upsert_file_documents(file_path, chunks_v1, project=project)
    results = store.search("login", project=project, top_k=10)
    assert len(results) > 0
    
    # Round 2: Replace with new symbol, old chunk (logout) must be deleted atomically
    chunks_v2 = [
        {"id": f"{project}:{file_path}:1", "text": "def login(): return True", "metadata": {"file_path": file_path, "symbol_name": "login", "chunk_type": "function"}},
        {"id": f"{project}:{file_path}:3", "text": "def refresh(): pass", "metadata": {"file_path": file_path, "symbol_name": "refresh", "chunk_type": "function"}}
    ]
    store.upsert_file_documents(file_path, chunks_v2, project=project)
    
    # Check that logout is gone
    exact_logout = store.search_exact_symbol("logout", project=project)
    exact_refresh = store.search_exact_symbol("refresh", project=project)
    exact_login = store.search_exact_symbol("login", project=project)
    
    assert len(exact_logout) == 0
    assert len(exact_refresh) == 1
    assert len(exact_login) == 1
    assert store.count_chunks() == 2

def test_offline_deletion_reconciliation(temp_workspace):
    db_path = temp_workspace / "db"
    proj_dir = temp_workspace / "proj"
    proj_dir.mkdir(parents=True)
    f1 = proj_dir / "mod_a.py"
    f2 = proj_dir / "mod_b.py"
    f1.write_text("def a(): pass", encoding="utf-8")
    f2.write_text("def b(): pass", encoding="utf-8")
    
    store = VectorStore(db_path=temp_workspace / "db")
    watcher = MeshWatcherManager(store=store)
    projects = {"proj": {"path": str(proj_dir)}}
    watcher.sync_watchers(projects, reconcile_startup=True)
    
    indexed = store.get_indexed_files_for_project("proj")
    assert any("mod_a.py" in p for p in indexed)
    assert any("mod_b.py" in p for p in indexed)
    
    # Simulate offline deletion of mod_a.py
    f1.unlink()
    watcher.stop_all()
    watcher.sync_watchers(projects, reconcile_startup=True)
    
    indexed_after = store.get_indexed_files_for_project("proj")
    assert not any("mod_a.py" in p for p in indexed_after)
    assert any("mod_b.py" in p for p in indexed_after)

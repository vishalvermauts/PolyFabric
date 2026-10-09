import pytest
import os
import shutil
import tempfile
from pathlib import Path
from infinite_memory.core.store import VectorStore
from infinite_memory.core.watcher import MeshWatcherManager
from infinite_memory.security.secret_masker import SecretMasker
from infinite_memory.server import mesh_read_file, mesh_write_file

@pytest.fixture
def temp_workspace():
    tmp = tempfile.mkdtemp(prefix="imp_bench_correctness_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)

def test_hardened_diff_secret_masking():
    masker = SecretMasker()
    diff_lines = [
        "+password: benchmark_fake_password_123",
        "-DB_PASS=benchmark_fake_password_123",
        "+API_KEY=benchmark_fake_password_123",
        "normal line: nothing to mask"
    ]
    raw_diff = "\n".join(diff_lines)
    masked = masker.mask_text(raw_diff)
    assert "benchmark_fake_password_123" not in masked
    assert "+password: [REDACTED_PASSWORD]" in masked
    assert "-DB_PASS=[REDACTED_DB_PASS]" in masked
    assert "+API_KEY=[REDACTED_API_KEY]" in masked
    assert "normal line: nothing to mask" in masked

def test_atomic_merge_insert_guarantee(temp_workspace):
    db_path = temp_workspace / "db"
    store = VectorStore(db_path=str(db_path))
    project = "test_atomic"
    file_path = "services/auth.py"
    
    # Round 1
    chunks_v1 = [
        {"id": f"{project}:{file_path}:1", "content": "def login(): pass", "file_path": file_path, "symbol_name": "login", "chunk_type": "function"},
        {"id": f"{project}:{file_path}:2", "content": "def logout(): pass", "file_path": file_path, "symbol_name": "logout", "chunk_type": "function"}
    ]
    store.upsert_file_documents(project, file_path, chunks_v1)
    results = store.search("login", project=project, limit=10)
    assert len(results) > 0
    
    # Round 2: Replace with new symbol, old chunk (logout) must be deleted atomically
    chunks_v2 = [
        {"id": f"{project}:{file_path}:1", "content": "def login(): return True", "file_path": file_path, "symbol_name": "login", "chunk_type": "function"},
        {"id": f"{project}:{file_path}:3", "content": "def refresh(): pass", "file_path": file_path, "symbol_name": "refresh", "chunk_type": "function"}
    ]
    store.upsert_file_documents(project, file_path, chunks_v2)
    
    # Check that logout is gone
    table = store.db.open_table(store.table_name)
    rows = table.to_pandas()
    matching_rows = rows[(rows["project"] == project) & (rows["file_path"] == file_path)]
    symbol_names = set(matching_rows["symbol_name"].tolist())
    assert "logout" not in symbol_names
    assert "refresh" in symbol_names
    assert "login" in symbol_names
    assert len(matching_rows) == 2

def test_offline_deletion_reconciliation(temp_workspace):
    db_path = temp_workspace / "db"
    proj_dir = temp_workspace / "proj"
    proj_dir.mkdir(parents=True)
    f1 = proj_dir / "mod_a.py"
    f2 = proj_dir / "mod_b.py"
    f1.write_text("def a(): pass", encoding="utf-8")
    f2.write_text("def b(): pass", encoding="utf-8")
    
    store = VectorStore(db_path=str(db_path))
    watcher = MeshWatcherManager(store)
    watcher._reconcile_project("proj", str(proj_dir))
    
    indexed = store.get_indexed_files_for_project("proj")
    assert "mod_a.py" in indexed
    assert "mod_b.py" in indexed
    
    # Simulate offline deletion of mod_a.py
    f1.unlink()
    watcher._reconcile_project("proj", str(proj_dir))
    
    indexed_after = store.get_indexed_files_for_project("proj")
    assert "mod_a.py" not in indexed_after
    assert "mod_b.py" in indexed_after

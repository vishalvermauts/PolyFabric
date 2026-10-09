import os
import sys
import time
import pytest
import shutil
import tempfile
import multiprocessing
from pathlib import Path

from infinite_memory.core.store import VectorStore
from infinite_memory.core.watcher import MeshWatcherManager
from infinite_memory.server import mesh_write_file, set_active_hub
from infinite_memory.core.hub import Hub
from filelock import FileLock

@pytest.fixture
def temp_env():
    tmp = tempfile.mkdtemp(prefix="imp_bench_failure_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)

def test_offline_watcher_stop_and_join_reconciliation(temp_env):
    """Accurate offline test: Watchers are cleanly stopped and joined before file deletion."""
    db_path = temp_env / "db"
    proj_dir = temp_env / "proj"
    proj_dir.mkdir(parents=True)
    f1 = proj_dir / "mod_a.py"
    f2 = proj_dir / "mod_b.py"
    f1.write_text("def a(): pass", encoding="utf-8")
    f2.write_text("def b(): pass", encoding="utf-8")
    
    store = VectorStore(db_path=db_path)
    watcher = MeshWatcherManager(store=store)
    projects = {"proj": {"path": str(proj_dir)}}
    
    # 1. Startup reconciliation & start watchers
    watcher.sync_watchers(projects, reconcile_startup=True)
    indexed = store.get_indexed_files_for_project("proj")
    assert any("mod_a.py" in p for p in indexed)
    assert any("mod_b.py" in p for p in indexed)
    
    # 2. Stop and cleanly join all background watcher threads
    active_watchers = list(watcher.watchers.values())
    watcher.stop_all()
    # Confirm observers are joined and dead
    for w in active_watchers:
        assert not w.observer.is_alive()
        
    # 3. Simulate true offline deletion while server/watcher is completely dead
    f1.unlink()
    assert not f1.exists()
    
    # 4. Restart server & reconcile on startup
    new_watcher = MeshWatcherManager(store=store)
    new_watcher.sync_watchers(projects, reconcile_startup=True)
    
    indexed_after = store.get_indexed_files_for_project("proj")
    assert not any("mod_a.py" in p for p in indexed_after)
    assert any("mod_b.py" in p for p in indexed_after)
    new_watcher.stop_all()

def _writer_worker(project, file_path, content, lock_path, db_path, result_queue):
    try:
        store = VectorStore(db_path=db_path)
        chunks = [{"id": f"{project}:{file_path}:0", "text": content, "metadata": {"file_path": file_path}}]
        store.upsert_file_documents(file_path, chunks, project=project)
        result_queue.put("SUCCESS")
    except Exception as e:
        result_queue.put(f"ERROR: {e}")

def test_cross_process_concurrent_write_lock(temp_env):
    """Test concurrent writer processes on the same database file."""
    db_path = temp_env / "concurrent_db"
    lock_path = temp_env / "lock"
    project = "concurrency_test"
    file_path = "worker.py"
    
    q = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=_writer_worker, args=(project, file_path, "def run1(): pass", lock_path, db_path, q))
    p2 = multiprocessing.Process(target=_writer_worker, args=(project, file_path, "def run2(): pass", lock_path, db_path, q))
    
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    
    results = [q.get() for _ in range(2)]
    assert "SUCCESS" in results
    
    # Vector store must be consistent with either run1 or run2, never corrupted
    store = VectorStore(db_path=db_path)
    res = store.search("run", project=project, top_k=5)
    assert len(res) > 0
    assert "run1" in res[0]["text"] or "run2" in res[0]["text"]

def test_failure_injection_before_commit(temp_env):
    """If embedding generation fails, old documents must survive untouched."""
    db_path = temp_env / "fail_db"
    store = VectorStore(db_path=db_path)
    project = "fail_test"
    file_path = "critical.py"
    
    # Seed valid state
    initial_chunks = [{"id": "crit:1", "text": "def critical_service(): return 42", "metadata": {"file_path": file_path, "symbol_name": "critical_service"}}]
    store.upsert_file_documents(file_path, initial_chunks, project=project)
    assert store.count_chunks() == 1
    
    # Inject failure during document preparation / embedding
    class BrokenEncoder:
        def embed(self, texts):
            raise RuntimeError("Injected ONNX / Embedding Failure")
            
    original_encoder = store.encoder
    store.encoder = BrokenEncoder()
    
    try:
        bad_chunks = [{"id": "crit:2", "text": "def broken(): pass", "metadata": {"file_path": file_path, "symbol_name": "broken"}}]
        store.upsert_file_documents(file_path, bad_chunks, project=project)
    except RuntimeError:
        pass # Expected injected failure
    finally:
        store.encoder = original_encoder
        
    # Verify that original records are intact and searchable
    survived = store.search_exact_symbol("critical_service", project=project)
    assert len(survived) == 1
    assert "critical_service" in survived[0]["symbol_name"]

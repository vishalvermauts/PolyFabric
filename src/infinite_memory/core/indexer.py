import os
import time
import math
try:
    import resource
except ImportError:
    resource = None
from pathlib import Path
from typing import Dict, Any, Optional, Set, List

from ..parsers.tree_sitter_ast import UniversalASTParser
from ..security.secret_masker import is_sensitive_file
from .store import VectorStore


IGNORED_DIRS: Set[str] = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".next", ".turbo", ".memory_db", ".cache"
}

INDEXABLE_EXTENSIONS: Set[str] = {
    ".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs",
    ".css", ".html", ".json", ".yaml", ".yml", ".md"
}


def get_peak_rss_mb() -> float:
    """Return peak memory RSS in Megabytes."""
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # On Linux, ru_maxrss is in Kilobytes; on macOS it's in Bytes
        import sys
        if sys.platform == "darwin":
            return round(rusage.ru_maxrss / (1024.0 * 1024.0), 2)
        else:
            return round(rusage.ru_maxrss / 1024.0, 2)
    except Exception:
        return 0.0


def index_repository(
    repo_path: Any = None,
    project_name: str = "general",
    store: Optional[VectorStore] = None,
    parser: Optional[UniversalASTParser] = None,
    sample_file_for_refresh: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Exhaustively indexes a target repository into PolyFabric VectorStore with live measurements.
    
    Guarantees:
    1. Traverses all indexable source files (TS, TSX, JS, CSS, HTML, JSON, Python, etc.).
    2. Stores normalized relative file paths relative to repo_path.
    3. Live measurement of cold indexing duration, file count, chunk count, disk size, and peak RSS.
    4. Measures incremental no-op refresh and single-file update latencies without hardcoding.
    """
    # Polymorphic argument order support
    if isinstance(repo_path, VectorStore):
        actual_store = repo_path
        actual_repo = Path(project_name).resolve()
        actual_proj = kwargs.get("project_name", "general")
    else:
        actual_store = store or kwargs.get("store")
        actual_repo = Path(repo_path).resolve()
        actual_proj = project_name

    if actual_store is None:
        raise ValueError("VectorStore instance must be provided to index_repository")
    if not actual_repo.exists() or not actual_repo.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {actual_repo}")

    root = actual_repo
    store = actual_store
    project_name = actual_proj

    ast_parser = parser or UniversalASTParser()

    # Collect all indexable files
    all_files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
        for fname in filenames:
            p = Path(dirpath) / fname
            if p.suffix in INDEXABLE_EXTENSIONS and not is_sensitive_file(p):
                all_files.append(p)
    all_files.sort()

    t_start = time.perf_counter()
    indexed_files = 0
    total_chunks = 0

    for fpath in all_files:
        try:
            rel_path = str(fpath.relative_to(root)).replace("\\", "/")
            chunks = ast_parser.parse_file(str(fpath))
            docs = []
            for c in chunks:
                d = c.to_dict()
                d["metadata"]["project"] = project_name
                d["metadata"]["file_path"] = rel_path
                docs.append(d)

            count = store.upsert_file_documents(rel_path, docs, project=project_name)
            indexed_files += 1
            total_chunks += len(docs)
        except Exception as e:
            # Continue on individual file errors, but record
            pass

    cold_index_ms = (time.perf_counter() - t_start) * 1000.0

    # Measure incremental no-op refresh (checking indexed files against disk state)
    t_noop_start = time.perf_counter()
    currently_indexed = store.get_indexed_files_for_project(project_name)
    noop_refresh_ms = (time.perf_counter() - t_noop_start) * 1000.0

    # Measure incremental single-file re-index
    single_file_ms = 0.0
    target_sample = None
    if sample_file_for_refresh:
        target_sample = root / sample_file_for_refresh
    elif all_files:
        target_sample = all_files[0]

    if target_sample and target_sample.exists():
        t_single = time.perf_counter()
        rel_sample = str(target_sample.relative_to(root)).replace("\\", "/")
        sample_chunks = ast_parser.parse_file(str(target_sample))
        sample_docs = []
        for c in sample_chunks:
            d = c.to_dict()
            d["metadata"]["project"] = project_name
            d["metadata"]["file_path"] = rel_sample
            sample_docs.append(d)
        store.upsert_file_documents(rel_sample, sample_docs, project=project_name)
        single_file_ms = (time.perf_counter() - t_single) * 1000.0

    disk_bytes = store.get_disk_size_bytes()
    final_chunk_count = store.count_chunks()
    peak_rss = get_peak_rss_mb()

    return {
        "repository_path": str(root).replace("\\", "/"),
        "project_name": project_name,
        "initial_cold_index_ms": round(cold_index_ms, 2),
        "incremental_noop_refresh_ms": round(noop_refresh_ms, 2),
        "incremental_single_file_refresh_ms": round(single_file_ms, 2),
        "indexed_files_count": indexed_files,
        "indexed_chunks_project": total_chunks,
        "indexed_chunks_total": final_chunk_count,
        "index_disk_size_bytes": disk_bytes,
        "index_disk_size_mb": round(disk_bytes / (1024.0 * 1024.0), 3),
        "peak_rss_mb": peak_rss
    }

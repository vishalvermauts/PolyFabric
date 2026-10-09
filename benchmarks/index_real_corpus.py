import os
import sys
import time
import json
from pathlib import Path
import psutil

from infinite_memory.core.store import VectorStore
from infinite_memory.parsers.tree_sitter_ast import TreeSitterParser

BASE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BASE_DIR / "corpus"
RESULTS_DIR = BASE_DIR / "results"
MANIFEST_FILE = BASE_DIR / "corpus-manifest.jsonl"

def index_real_corpus():
    out_dir = RESULTS_DIR / "real_corpus_indexing"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "real_lancedb"
    
    print("=== Starting Real Corpus Indexing (Flask, FastAPI, Express, TypeScript) ===")
    store = VectorStore(db_path=db_path)
    parser = TreeSitterParser()
    
    if not MANIFEST_FILE.exists():
        print(f"Error: {MANIFEST_FILE} not found.")
        sys.exit(1)
        
    entries = []
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
                
    print(f"Loaded {len(entries)} files from manifest.")
    
    t0 = time.perf_counter()
    total_chunks = 0
    ast_chunks = 0
    fallback_chunks = 0
    indexed_files = 0
    file_errors = 0
    
    for idx, item in enumerate(entries):
        rel_path = item["path"]
        corpus_name = item["corpus"]
        full_path = CORPUS_DIR / rel_path
        
        if not full_path.exists() or not full_path.is_file():
            continue
            
        try:
            chunks = parser.parse_file(str(full_path))
            if not chunks:
                continue
                
            docs = []
            for c_idx, c in enumerate(chunks):
                is_ast = c.get("chunk_type") in ("class", "function", "method", "class_method")
                if is_ast:
                    ast_chunks += 1
                else:
                    fallback_chunks += 1
                    
                doc = {
                    "id": f"{corpus_name}:{rel_path}:{c_idx}",
                    "text": c.get("content", ""),
                    "metadata": {
                        "file_path": rel_path,
                        "symbol_name": c.get("symbol_name", ""),
                        "chunk_type": c.get("chunk_type", "sliding_window"),
                        "start_line": c.get("start_line", 1),
                        "end_line": c.get("end_line", 1)
                    }
                }
                docs.append(doc)
                
            store.upsert_file_documents(rel_path, docs, project=corpus_name)
            total_chunks += len(docs)
            indexed_files += 1
            
            if (idx + 1) % 100 == 0:
                elapsed = time.perf_counter() - t0
                print(f"Progress: Indexed {indexed_files}/{len(entries)} files ({total_chunks} chunks, {total_chunks/elapsed:.1f} chunks/sec)...")
        except Exception as e:
            file_errors += 1
            
    duration = time.perf_counter() - t0
    throughput = total_chunks / max(0.001, duration)
    
    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "manifest_files": len(entries),
        "indexed_files": indexed_files,
        "file_errors": file_errors,
        "total_chunks": total_chunks,
        "ast_chunks": ast_chunks,
        "fallback_chunks": fallback_chunks,
        "wall_time_sec": duration,
        "throughput_chunks_sec": throughput,
        "average_chunks_per_file": total_chunks / max(1, indexed_files)
    }
    
    print("\n=== Real Corpus Indexing Complete ===")
    print(json.dumps(summary, indent=2))
    
    with open(out_dir / "indexing_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

if __name__ == "__main__":
    index_real_corpus()

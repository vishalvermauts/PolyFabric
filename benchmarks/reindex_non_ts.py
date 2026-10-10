import os
import sys
import time
import json
import shutil
from pathlib import Path
from collections import Counter

from infinite_memory.core.store import VectorStore
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser
import lancedb

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
CORPUS_DIR = BASE_DIR / "corpus"
RESULTS_DIR = BASE_DIR / "results"
MANIFEST_FILE = BASE_DIR / "corpus-manifest.jsonl"
SRC_DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
NEW_DB_DIR = RESULTS_DIR / "real_corpus_indexing_rebuilt"
NEW_DB_PATH = NEW_DB_DIR / "real_lancedb"

def patch_non_ts_and_reindex():
    print("=== Re-indexing Non-TypeScript Files (Flask, FastAPI, Express) with ABI 14 Grammars ===")
    
    if NEW_DB_DIR.exists():
        shutil.rmtree(NEW_DB_DIR)
    NEW_DB_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Step 1: Copying verified TypeScript table data from {SRC_DB_PATH} to {NEW_DB_PATH}...")
    shutil.copytree(SRC_DB_PATH, NEW_DB_PATH)
    
    store = VectorStore(db_path=NEW_DB_PATH)
    parser = UniversalASTParser()
    
    # Step 2: Delete existing non-TS chunks from the table (they were sliding_window fallbacks)
    print("Step 2: Purging old sliding_window chunks for flask, fastapi, express...")
    for proj in ["flask", "fastapi", "express"]:
        deleted = store.delete_by_project(proj)
        print(f"  Purged project: {proj}")
        
    # Step 3: Re-index all non-TS files with full AST parsing
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
        
    non_ts_entries = [e for e in entries if e["corpus"] in ("flask", "fastapi", "express")]
    print(f"\nStep 3: Indexing {len(non_ts_entries)} Python and JavaScript files with AST symbols...")
    
    t0 = time.perf_counter()
    new_chunks_count = 0
    ast_chunks_count = 0
    symbols_count = 0
    
    for idx, item in enumerate(non_ts_entries):
        rel_path = item["path"]
        corpus_name = item["corpus"]
        full_path = CORPUS_DIR / rel_path
        
        if not full_path.exists() or not full_path.is_file():
            continue
            
        chunks = parser.parse_file(str(full_path))
        if not chunks:
            continue
            
        docs = []
        for c in chunks:
            d = c.to_dict()
            chunk_type = d["metadata"].get("chunk_type", "")
            sym_name = d["metadata"].get("symbol_name", "")
            if chunk_type.startswith("ast_"):
                ast_chunks_count += 1
            if sym_name:
                symbols_count += 1
            docs.append(d)
            
        store.upsert_file_documents(rel_path, docs, project=corpus_name)
        new_chunks_count += len(docs)
        if (idx + 1) % 10 == 0 or idx == len(non_ts_entries) - 1:
            print(f"  [{idx+1}/{len(non_ts_entries)}] Indexed {rel_path} -> {len(docs)} chunks (Symbols: {symbols_count})")
            
    duration = time.perf_counter() - t0
    print(f"\nNon-TS indexing completed in {duration:.2f}s ({new_chunks_count} chunks created, {ast_chunks_count} AST chunks, {symbols_count} symbols).")
    
    # Step 4: Verify complete database contents
    db = lancedb.connect(str(NEW_DB_PATH))
    tbl = db.open_table("documents")
    df = tbl.to_pandas()
    print("\n=== Rebuilt Database Verification ===")
    print(f"Total Rows: {len(df)}")
    print(f"By Project: {dict(Counter(df['project']))}")
    
    print("\nSymbols with names by project:")
    for proj, group in df.groupby("project"):
        syms_with_name = (group["symbol_name"] != "").sum()
        print(f"  {proj}: {syms_with_name} symbols (Total chunks: {len(group)})")
        
    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "total_chunks": len(df),
        "by_project": dict(Counter(df["project"])),
        "symbols_by_project": {proj: int((group["symbol_name"] != "").sum()) for proj, group in df.groupby("project")},
        "non_ts_indexing_duration_sec": round(duration, 2)
    }
    
    out_file = NEW_DB_DIR / "indexing_summary.json"
    out_file.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved rebuilt index summary to {out_file}")

if __name__ == "__main__":
    patch_non_ts_and_reindex()

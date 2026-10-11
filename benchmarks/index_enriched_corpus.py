import os
import sys
import json
import time
from pathlib import Path

# Add src to sys.path
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import lancedb
from fastembed import TextEmbedding
from infinite_memory.core.store import DOCUMENTS_SCHEMA
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser

def main():
    base_dir = Path("C:/AI/Polyfabric/benchmarks")
    manifest_file = base_dir / "corpus-manifest.jsonl"
    corpus_dir = base_dir / "corpus"
    out_dir = base_dir / "results" / "enriched_corpus_indexing"
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "enriched_lancedb"

    print(f"=== Starting Enriched Corpus Indexing to {db_path} ===")
    sys.stdout.flush()

    db = lancedb.connect(str(db_path))
    tbl = db.create_table("documents", schema=DOCUMENTS_SCHEMA, mode="overwrite")

    parser = UniversalASTParser()
    encoder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    entries = [json.loads(line) for line in manifest_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Loaded {len(entries)} files from manifest.")
    sys.stdout.flush()

    t0 = time.perf_counter()
    batch_records = []
    indexed_files = 0
    total_chunks = 0
    ast_chunks = 0
    fallback_chunks = 0
    BATCH_SIZE = 250

    for idx, item in enumerate(entries):
        rel_path = item["path"]
        corpus_name = item["corpus"]
        full_path = corpus_dir / rel_path
        if not full_path.exists() or not full_path.is_file():
            continue

        try:
            chunks = parser.parse_file(str(full_path))
            if not chunks:
                continue

            # Embed chunks
            texts = [c.content for c in chunks]
            embeddings = [e.tolist() for e in encoder.embed(texts)]

            for c, emb in zip(chunks, embeddings):
                norm_file_path = rel_path.replace("\\", "/")
                rec = {
                    "id": c.chunk_id,
                    "text": c.content,
                    "file_path": norm_file_path,
                    "project": corpus_name,
                    "symbol_name": c.symbol_name or "",
                    "chunk_type": c.chunk_type,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "vector": emb,
                }
                if c.chunk_type.startswith("ast_"):
                    ast_chunks += 1
                else:
                    fallback_chunks += 1
                batch_records.append(rec)

            indexed_files += 1

            if len(batch_records) >= BATCH_SIZE:
                tbl.add(batch_records)
                total_chunks += len(batch_records)
                batch_records.clear()
                elapsed = time.perf_counter() - t0
                print(f"Progress: {indexed_files}/{len(entries)} files ({total_chunks} chunks, {total_chunks/max(0.001, elapsed):.1f} chunks/sec)...")
                sys.stdout.flush()

        except Exception as e:
            print(f"Error on {rel_path}: {e}")
            sys.stdout.flush()

    if batch_records:
        tbl.add(batch_records)
        total_chunks += len(batch_records)
        batch_records.clear()

    print("Building FTS index for BM25 search...")
    sys.stdout.flush()
    try:
        tbl.create_fts_index("text", replace=True)
        print("FTS index created successfully.")
    except Exception as e:
        print(f"FTS index creation warning: {e}")
    sys.stdout.flush()

    duration = time.perf_counter() - t0
    print(f"Indexing complete in {duration:.2f}s! Total files: {indexed_files}, chunks: {total_chunks} (ast: {ast_chunks}, fallback: {fallback_chunks}).")
    sys.stdout.flush()

if __name__ == "__main__":
    main()

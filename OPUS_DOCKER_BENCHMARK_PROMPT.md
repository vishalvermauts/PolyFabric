# OPUS DOCKER MISSION BRIEF: REINDEXING & FAIR EVALUATION

> **Repository**: `https://github.com/vishalvermauts/PolyFabric.git`  
> **Dedicated Branch**: `feat/opus-optimizations`  
> **Target LanceDB**: `/workspace/PolyFabric/benchmarks/results/real_corpus_indexing/real_lancedb` (Baseline) and `/workspace/PolyFabric/benchmarks/results/enriched_corpus_indexing/enriched_lancedb` (New Enriched)  
> **Test Queries**: `benchmarks/query_ground_truth_manifest.json` (150 ground-truth queries)

---

## 1. Context & What Has Already Been Implemented

The code fixes and regression tests are **already committed and pushed** to `origin/feat/opus-optimizations` (commit `de0f4b3`):
1. **Multiline Signature Extraction**: `_extract_signature` in `src/infinite_memory/core/system1.py` accurately tracks delimiter balance `( ... )`, `[ ... ]`, `{ ... }` across multiple lines, preserving multiline parameter signatures, complex type annotations, and trailing docstrings without premature truncation.
2. **Repository Diversity Preservation**: `_prune_candidates` in `src/infinite_memory/core/system1.py` guarantees every repository in the initial candidate pool retains representation before score-gap or budget truncation.
3. **AST Context Enrichment**: `UniversalASTParser` in `src/infinite_memory/parsers/tree_sitter_ast.py` prepends `# File: ...`, `# Enclosing: ...`, and module/class docstring headers to AST chunks.
4. **Regression Tests**: Added regression tests in `tests/test_system1.py` (`test_multiline_complex_signature_regression`, `test_preserves_minority_repo_diversity_regression`). All **92 unit tests pass**.

---

## 2. Your Mission Inside Your Docker VM

Your task is to perform the heavy indexing and evaluation inside your Docker container (offloading CPU/RAM from the host machine):

1. **Reindex the real corpus with AST context enrichment into a separate directory**:
   - Target database: `benchmarks/results/enriched_corpus_indexing/enriched_lancedb`.
   - Build the Tantivy BM25 FTS index on the new table.
   - Keep the original database `benchmarks/results/real_corpus_indexing/real_lancedb` untouched for baseline comparison.

2. **Run the fair comparative evaluation on identical queries and Top-5 budgets (`top_k=5`)**:
   - Compare the baseline (`real_lancedb`) against the new enriched implementation (`enriched_lancedb`).
   - Run across all 150 manifest queries from `benchmarks/query_ground_truth_manifest.json`.
   - Report the following metrics separately:
     - **Exact symbol lookup**: Hit@1, Hit@5, MRR@10, candidate coverage, and p50/p95 latency.
     - **Concept semantic search**: Hit@1, Hit@5, MRR@10, candidate coverage, and p50/p95 latency.
     - **Candidate coverage**: % of ground-truth files present in the retrieved candidate pool.
     - **Absent controls**: Clean abstention rate and false positive count.
     - **Cross-repository routing**: Intent detection accuracy reported **strictly separately** from full multi-repository evidence retrieval success.

---

## 3. Step-by-Step Commands to Run in Your Docker VM

### Step 3.1: Pull Latest Branch & Start Container
```bash
git clone https://github.com/vishalvermauts/PolyFabric.git /workspace/PolyFabric
cd /workspace/PolyFabric
git checkout feat/opus-optimizations
git pull origin feat/opus-optimizations

# Start the sandbox container
docker compose up --build -d
```

### Step 3.2: Verify Unit Tests Pass
```bash
docker compose exec app pytest tests/ -v
# Output should show: 92 passed, 0 failures
```

### Step 3.3: Run Enriched Corpus Indexing
Run the indexing script inside the container using the 8-vCPU container resources:
```bash
docker compose exec app python -u -c "
import os, sys, json, time
from pathlib import Path

sys.path.insert(0, '/app/src')
import lancedb
from fastembed import TextEmbedding
from infinite_memory.core.store import DOCUMENTS_SCHEMA
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser

base_dir = Path('/app/benchmarks')
manifest_file = base_dir / 'corpus-manifest.jsonl'
corpus_dir = base_dir / 'corpus'
out_dir = base_dir / 'results' / 'enriched_corpus_indexing'
out_dir.mkdir(parents=True, exist_ok=True)
db_path = out_dir / 'enriched_lancedb'

print(f'Starting indexing to {db_path}...')
db = lancedb.connect(str(db_path))
tbl = db.create_table('documents', schema=DOCUMENTS_SCHEMA, mode='overwrite')

parser = UniversalASTParser()
encoder = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')

entries = [json.loads(line) for line in manifest_file.read_text(encoding='utf-8').splitlines() if line.strip()]
print(f'Loaded {len(entries)} files from manifest.')

t0 = time.perf_counter()
batch_records = []
total_chunks = 0
indexed_files = 0

for idx, item in enumerate(entries):
    rel_path = item['path']
    corpus_name = item['corpus']
    full_path = corpus_dir / rel_path
    if not full_path.exists() or not full_path.is_file():
        continue
    try:
        chunks = parser.parse_file(str(full_path))
        if not chunks:
            continue
        texts = [c.content for c in chunks]
        embeddings = [e.tolist() for e in encoder.embed(texts)]
        for c, emb in zip(chunks, embeddings):
            rec = {
                'id': c.chunk_id,
                'text': c.content,
                'file_path': rel_path.replace('\\\\', '/'),
                'project': corpus_name,
                'symbol_name': c.symbol_name or '',
                'chunk_type': c.chunk_type,
                'start_line': c.start_line,
                'end_line': c.end_line,
                'vector': emb,
            }
            batch_records.append(rec)
        indexed_files += 1
        if len(batch_records) >= 250:
            tbl.add(batch_records)
            total_chunks += len(batch_records)
            batch_records.clear()
            elapsed = time.perf_counter() - t0
            print(f'Progress: {indexed_files}/{len(entries)} files ({total_chunks} chunks, {total_chunks/max(0.001, elapsed):.1f} chunks/sec)...')
    except Exception as e:
        print(f'Error on {rel_path}: {e}')

if batch_records:
    tbl.add(batch_records)
    total_chunks += len(batch_records)
    batch_records.clear()

print('Building Tantivy BM25 FTS index...')
tbl.create_fts_index('text', replace=True)
print(f'Indexing complete in {time.perf_counter()-t0:.2f}s! Total files: {indexed_files}, total chunks: {total_chunks}.')
"
```

### Step 3.4: Run the Fair Comparison Evaluation Matrix
Run the fair comparison script `benchmarks/run_enriched_fair_comparison.py`:
```bash
docker compose exec app python -u benchmarks/run_enriched_fair_comparison.py
```

### Step 3.5: Push Results
Save the JSON summary report and push:
```bash
git add benchmarks/results/
git commit -m "docs(eval): publish enriched corpus fair comparison benchmark results"
git push origin feat/opus-optimizations
```

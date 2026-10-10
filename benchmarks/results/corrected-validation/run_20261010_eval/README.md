# Corrected Validation Run Package: `run_20261010_eval`

## 1. Provenance & Environment
- **Date & Hardware**: 2026-10-10, Docker Large (8 vCPU AMD EPYC, 16 GB RAM, 28 GiB disk, linux/amd64).
- **Application Baseline Commit**: `5661842a4f8d3fa564f954a90c69acc25f4f3ae7`
- **Benchmark Branch**: `bench/corrected-validation`
- **Corpus**: 800 frozen real-world source files across 4 repositories (`typescript`, `fastapi`, `flask`, `express`).
- **Database**: LanceDB flat table (`documents`) with **47,644 total chunks** (46,376 TypeScript, 731 FastAPI, 371 Flask, 166 Express). Zero vector indexing (pure flat scan).

## 2. Included Evidence Artifacts
- `retrieval_quality_summary.json`: Independent evaluation metrics for Mode A (Exact AST symbol lookup) and Mode B (Semantic search) across 150 ground-truth queries.
- `retrieval_detailed_queries.json`: Complete record of all 150 queries, target definitions, line-range matches, candidates returned, cosine distances, and latencies.
- `mcp_isolated_performance_summary.json`: Summary of 1,000 isolated MCP stdio queries over the frozen real-corpus database.
- `mcp_isolated_requests.jsonl`: Raw streaming event logs for all 1,000 requests.
- `mcp_concurrency_summary.json`: Controlled concurrency scaling (1, 2, 4, 8 in-flight requests) on a single MCP server instance.
- `component_breakdown_profile.json`: Micro-benchmarks isolating FastEmbed ONNX runtime, LanceDB table scan, symbol lookup, and secret masking.
- `preliminary_soak_summary.json`: Historical soak summary preserved from baseline run, explicitly labeled as preliminary.
- `installed_dependencies.txt`: Pinned package lock from `uv pip freeze`.
- `tested_files_manifest.json`: Cryptographic SHA-256 hashes of all application and benchmark source files.
- `query_ground_truth_manifest.json`: Ground-truth specification for all 150 queries.

## 3. Reproduction Commands
To replicate these exact evaluations from scratch:

```bash
# 1. Verify tested files provenance
python benchmarks/recompute_metrics.py

# 2. Run independent retrieval quality evaluation (150 queries)
python benchmarks/run_corrected_retrieval.py

# 3. Run isolated MCP warm performance benchmark (1,000 requests)
python benchmarks/run_isolated_mcp_performance.py

# 4. Run controlled concurrency stress test (1, 2, 4, 8 in-flight)
python benchmarks/run_mcp_concurrency.py
```

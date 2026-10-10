# MISSION BRIEF & SYSTEM PROMPT FOR AI CODING AGENTS (OPUS 4.6 AUDIT EDITION)

> **Target Repository**: `https://github.com/vishalvermauts/PolyFabric`  
> **Target Working Directory**: `C:\AI\Polyfabric`  
> **Base Branch**: `feat/edge-reranker-federated` (contains the OPUS 4.6 diversity merge commit `446a645`)  
> **Components Under Audit & Optimization**:
>   - Core Retrieval Engine: `src/infinite_memory/core/system1.py`
>   - Unified Vector Store: `src/infinite_memory/core/store.py`
>   - Investigation & Grounding Engine: `src/infinite_memory/core/system2.py`
>   - Production MCP Server: `src/infinite_memory/server.py` (`mesh_fast_search`)
>   - Tree-sitter AST Parsers: `src/infinite_memory/parsers/`
> **Local Database Corpus**: 13,393 indexed LanceDB records from 4 real-world repositories (`typescript`, `flask`, `fastapi`, `express`) at `benchmarks/results/real_corpus_indexing/real_lancedb`  
> **Evaluation Datasets**:
>   - Regression Suite: `benchmarks/query_ground_truth_manifest.json` (150 frozen ground-truth queries)
>   - Holdout Generalization Suite: 20 fresh untouched queries across all 4 repositories

---

## 1. Executive Summary & Objective

You are assigned as a **Principal AI Systems Engineer and Information Retrieval Architect**. Your mission is to inspect the latest **PolyFabric** codebase on `feat/edge-reranker-federated`, analyze the newly merged diversity scheduler, identify remaining performance/accuracy bottlenecks, and implement architectural optimizations that beat the current production baselines.

### Hard Engineering Constraints
1. **100% Local Execution**: Must run completely offline on local CPU. Zero dependencies on paid cloud LLM APIs (OpenAI, Anthropic) or mandatory GPUs.
2. **Resource Footprint**:
   - Total model weights: $\le 150\text{ MB}$ (FastEmbed ONNX models).
   - In-memory process footprint: $< 250\text{ MB}$ RAM.
   - P50 scalar lookup latency: $\le 15\text{ ms}$.
   - P50 semantic vector + rerank latency: $\le 100\text{ ms}$ (Current bottleneck: ~1.2s when evaluating large candidate pools on single-thread CPU).
3. **Evidence Budget**: All competitive comparisons must evaluate a strict **Top-5 evidence budget** (`top_k=5`). Top-8 ablation may be recorded separately but must never be conflated with the 5-result target.
4. **Zero-Mock Policy in Production**: Unit tests may use mocks, but production MCP tools (`mesh_fast_search`, `mesh_investigate`) must strictly enforce circuit breakers, input bounds, and relationship grounding.

---

## 2. Current Baseline Benchmark State

Following the OPUS 4.6 Model commit (`446a645`), the system state across the 150 frozen queries and 20 holdout queries is:

| Benchmark Route / Gate | Previous Baseline | OPUS 4.6 Current Baseline | Target Threshold | Current Status | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Exact Symbol Hit@1** | 60.0% | **100.0% (50/50)** | $\ge 95.0\%$ | **PASS** | Case-insensitive fallback + scalar LanceDB lookup |
| **Concept Hit@5 (RRF + Rerank)** | 20.0% | **45.0% (18/40)** | $\ge 50.0\%$ | **NEAR PASS** | Bi-encoder struggles on raw code without docstring prepending |
| **Typo Retrieval Hit@5** | 20.0% | **40.0% (8/20)** | $\ge 20.0\%$ | **PASS** | Levenshtein edit-distance filter |
| **Cross-Repo Multi-Evidence** | 5.0% | **100.0% (20/20)** | $\ge 50.0\%$ | **PASS** | Solved by `_diversity_merge()` round-robin scheduler |
| **Absent Controls (Negative Filter)**| 0% (False Pos) | **100.0% (Clean Abstain)**| Reject 100% | **PASS** | Thresholding on cross-encoder logit scores (`score > -0.5`) |
| **Scalar Lookup P50 Latency** | 8.7 ms | **10.7 ms** | $\le 15\text{ ms}$ | **PASS** | 0 ONNX embedding model invocations |
| **Cross-Encoder P50 Latency** | 45 ms (No rerank)| **~1,200 ms** (15 docs) | $\le 100\text{ ms}$ | **OPEN BOTTLENECK** | Cross-encoder CPU overhead on 15+ candidate chunks |

---

## 3. Key Challenges & Flaws You Must Fix

While cross-repository discovery and exact-symbol lookups now pass, the following major challenges remain open for you to solve better:

### Flaw 1: Cross-Encoder CPU Latency Bottleneck (~1.2s vs <100ms Target)
- **Problem**: When `use_reranker=True`, the engine passes 15–20 full code snippets (often 30–50 lines of code each) through `jinaai/jina-reranker-v1-tiny-en` on single-threaded CPU.
- **Your Task**:
  - Implement **adaptive candidate pruning** (e.g., only rerank top 6–8 candidates if vector/BM25 scores have high confidence).
  - Benchmark quantized INT8 ONNX cross-encoders or test truncated representation headers (reranking on function signatures + docstrings rather than full 50-line bodies).

### Flaw 2: Semantic Concept Search Ceiling (45% vs $\ge 50\%$ Target)
- **Problem**: In `fastapi` and `typescript`, functions like `@router.get(...)` or `createProgram` lack natural language keywords like *"request validation"* or *"AST visitor pattern"* inside the raw code chunk.
- **Your Task**:
  - Enhance `UniversalASTParser` in `src/infinite_memory/parsers/` to extract parent docstrings and module-level summaries, prepending them to child AST chunks during indexing.

### Flaw 3: Unified MCP Tool Parity (`mesh_fast_search`)
- **Problem**: `mesh_fast_search` in `src/infinite_memory/server.py` defaults to `route="hybrid"`. If a developer asks a pure cross-repository question, the server must automatically detect multi-repo intent and route through `route="stratified"`.
- **Your Task**:
  - Improve `SystemOneRouter` or query intent detection in `server.py` to seamlessly auto-switch to `stratified` when comparative or multi-framework phrasing is detected.

---

## 4. Environment & Reproduction Setup

```powershell
# 1. Clone repository into the target directory
cd C:\AI
git clone https://github.com/vishalvermauts/PolyFabric.git Polyfabric
cd C:\AI\Polyfabric

# 2. Checkout the active development branch
git checkout feat/edge-reranker-federated
git pull origin feat/edge-reranker-federated

# 3. Virtual environment setup
# Use an existing Python 3.11 - 3.14 environment
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install fastembed lancedb pytest filelock

# 4. Set Python path and database environment variable
$env:PYTHONPATH="C:\AI\Polyfabric\src"
$env:INFINITE_MEMORY_DB_PATH="benchmarks/results/real_corpus_indexing/real_lancedb"

# 5. Run full test suite
pytest tests/ -v

# 6. Run fair 5-way benchmark comparison
python benchmarks/run_fair_comparison.py

# 7. Run production MCP tool verification
python -c "from infinite_memory.server import mesh_fast_search; print(mesh_fast_search('createProgram', route='exact_symbol'))"
```

---

## 5. Expected Deliverables from the AI Agent

1. **Architectural Critique**: Identify any remaining edge cases in `_diversity_merge` (e.g. handling missing repositories, tie-breaking, or score normalization).
2. **Latency Optimization**: Implement candidate pruning or fast signature reranking to bring P50 CPU latency down from ~1,200 ms to $< 100\text{ ms}$.
3. **Concept Search Boost**: Propose and implement docstring/AST signature enhancements that elevate Concept Hit@5 past $50.0\%$.
4. **Full Test & Benchmark Proof**: Provide exact reproduction logs with zero regressions on the 68 existing unit tests and the 150 ground-truth queries.

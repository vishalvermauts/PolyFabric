# MISSION BRIEF: POLYFABRIC OPTIMIZATIONS (OPUS ONLINE DOCKER EDITION)

> **Target Repository**: `https://github.com/vishalvermauts/PolyFabric`  
> **Dedicated Branch**: `feat/opus-optimizations`  
> **Container Runtime**: Pre-configured Docker Sandbox (`Dockerfile` + `docker-compose.yml`)  
> **Target Corpus**: 13,393 indexed LanceDB records from 4 real-world repositories (`typescript`, `flask`, `fastapi`, `express`)  
> **Benchmark Dataset**: `benchmarks/query_ground_truth_manifest.json` (150 frozen ground-truth queries)

---

## 1. Executive Summary & Objective

You are assigned as a **Principal AI Systems Engineer and Information Retrieval Architect**. Your mission is to work inside your **online Docker environment** on the dedicated branch `feat/opus-optimizations` to audit PolyFabric, optimize the cross-encoder latency bottleneck, boost concept semantic search, and verify all improvements inside the container.

### Hard Engineering Constraints
1. **100% Local Execution**: Must run completely inside the local/container environment. Zero paid cloud LLM keys (OpenAI, Anthropic) or mandatory GPUs.
2. **Resource Footprint**:
   - Model weights: $\le 150\text{ MB}$ (FastEmbed ONNX models).
   - In-memory process footprint: $< 250\text{ MB}$ RAM.
   - P50 scalar lookup latency: $\le 15\text{ ms}$.
   - P50 vector + rerank latency: $\le 100\text{ ms}$ (Current bottleneck: ~1,200 ms).
3. **Evidence Budget**: All competitive comparisons must evaluate a strict **Top-5 evidence budget** (`top_k=5`).

---

## 2. Current Baseline State (Already Solved on This Branch)

The base branch includes the recent OPUS 4.6 Model improvements:
* **Exact Symbol Lookup**: **100.0% (50/50 PASS)** at 10.7 ms latency using LanceDB scalar SQL with case-insensitive fallback.
* **Cross-Repository Discovery**: **100.0% (20/20 PASS)** using the round-robin diversity scheduler `_diversity_merge()` in `src/infinite_memory/core/system1.py`.
* **Absent Controls / Anti-Hallucination**: **100.0% (Clean Abstain PASS)** using cross-encoder logit thresholding (`score > -0.5`).
* **Existing Unit Test Suite**: **68 / 68 PASS** in 4.44s.

---

## 3. The 3 Exact Challenges for You to Solve

### Challenge 1: Cross-Encoder CPU Latency Bottleneck (~1,200 ms vs < 100 ms Target)
* **Location**: `src/infinite_memory/core/system1.py`
* **The Flaw**: When `use_reranker=True`, the engine passes 15 full code snippets (each 30–50 lines of code) through `jinaai/jina-reranker-v1-tiny-en` on single-threaded CPU. This takes ~1.2s, which is too slow for interactive coding agents.
* **Your Solution**:
  1. Implement **adaptive candidate pruning**: If the top candidates from reciprocal rank fusion (RRF) show strong confidence, prune the candidate pool down to top 6 before calling the cross-encoder.
  2. Implement **signature/header-only reranking**: Extract function signatures, interfaces, and docstrings rather than passing 2,000 characters of function bodies, reducing transformer inference token length by ~70%.

### Challenge 2: Concept Semantic Search Accuracy (45% vs ≥ 50% Target)
* **Location**: `src/infinite_memory/parsers/tree_sitter_ast.py`
* **The Flaw**: Abstract queries (e.g., *"how flask loads environment configuration files"*) rank lower because raw functions (e.g. `from_envvar`) lack natural language keywords like *"environment configuration"* in their isolated chunk text.
* **Your Solution**:
  - Update AST chunking to attach enclosing class/module docstrings and structural context headers into chunk text so bi-encoder embeddings capture conceptual meaning.

### Challenge 3: MCP Server Auto-Routing in `server.py`
* **Location**: `src/infinite_memory/server.py`
* **The Flaw**: `mesh_fast_search()` defaults to `route="hybrid"`. If a developer asks a comparative multi-repo question, single-repo hybrid search runs unless the caller manually specifies `route="stratified"`.
* **Your Solution**:
  - Add intent detection in `mesh_fast_search()` to automatically switch to `route="stratified"` when comparative multi-framework phrasing is detected.

---

## 4. Step-by-Step Online Docker Environment Instructions

Follow these exact commands inside your online Docker environment:

### Step 4.1: Clone and Checkout Dedicated Branch
```bash
git clone https://github.com/vishalvermauts/PolyFabric.git /workspace/PolyFabric
cd /workspace/PolyFabric
git checkout feat/opus-optimizations
```

### Step 4.2: Build and Start the Sandbox Container
The repository already contains a production `Dockerfile` and `docker-compose.yml`. Start the container:
```bash
docker compose up --build -d
```
Verify the container is active:
```bash
docker ps
# You will see: polyfabric-dev-sandbox (Python 3.11 environment)
```

### Step 4.3: Verify Existing Test Suite Inside Docker
Before making changes, verify that the 68 tests pass:
```bash
docker exec -it polyfabric-dev-sandbox pytest tests/ -v
# Output should show: 68 passed
```

### Step 4.4: Implement Your Changes
Modify the files directly in `/workspace/PolyFabric`:
* `src/infinite_memory/core/system1.py`
* `src/infinite_memory/parsers/tree_sitter_ast.py`
* `src/infinite_memory/server.py`
* Add corresponding tests to `tests/test_system1.py`

### Step 4.5: Verify and Benchmark Your Fixes
Run tests and measure retrieval latency inside the container:
```bash
# 1. Ensure all unit tests pass with zero regressions
docker exec -it polyfabric-dev-sandbox pytest tests/ -v

# 2. Measure retrieval and latency
docker exec -it polyfabric-dev-sandbox python -c "
from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever
store = VectorStore('/app/benchmarks/results/real_corpus_indexing/real_lancedb')
retriever = System1Retriever(store)
res = retriever.search('how flask and fastapi handle route decorators', route='hybrid', apply_reranker=True)
print('Retrieved evidence count:', len(res.evidence))
print('Latency:', res.latency_ms, 'ms')
print('Stage timings:', res.stage_timings_ms)
"
```

### Step 4.6: Commit and Push Your Work
```bash
git add src/ tests/
git commit -m "feat(system1): optimize cross-encoder latency and enhance AST concept retrieval (Opus Online Docker)"
git push origin feat/opus-optimizations
```

---

## 5. Expected Deliverables
1. **Source Code Implementation**: Clean, commented code resolving the latency bottleneck and boosting concept search.
2. **Container Verification Log**: Output showing `pytest tests/ -v` passing with zero errors.
3. **Pushed Git Commit**: Changes pushed directly to `origin/feat/opus-optimizations` so they can be merged.

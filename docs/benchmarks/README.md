# PolyFabric Benchmark History & Empirical Validation Suite

> **Release Version**: `v0.2.0`  
> **Target Commit**: `06d28dae442e39b7d66bf58c867d6a982d3c13a0`  
> **Released Retrieval Configuration**: Pure Asymmetric Reciprocal Rank Fusion ($k_{\text{lex}}=65, k_{\text{vec}}=38$) with Dual-Stage Lexical Verification Guard and Proportional Repository Diversity Merging (Restored from `88d66fac8f4dd3f1fca580fbff2c3071dd8667e2`).

---

## 1. Executive Summary & Audit Methodology

This document tracks all empirical benchmark evaluations, stress tests, ablation studies, and fresh query evaluations conducted for PolyFabric across its development lifecycle.

### Core Audit Principles & Honest Disclosure
1. **Separation of Retrospective Splits from Unseen Tests**: The 150-query manifest (`benchmarks/query_ground_truth_manifest.json`) was used repeatedly during iterative prompt engineering and heuristic tuning. The 75-query split derived from it is documented herein as a **Retrospective Benchmark Split**, not an untouched generalization test.
2. **Reconciliation of Conflicting Historical Reports**:
   - Run `RUN-20261011-083216-TASK8463` (commit `88d66fac8f4dd3f1fca580fbff2c3071dd8667e2`) produced **Concept Hit@5 = 52.5%** and **Cross-Repo Candidate Coverage = 45.0%**.
   - Run `task-8665` (commit `7742706248d39b75e83fb834a5dd65cff091c717`) produced **Concept Hit@5 = 45.0%** and **Cross-Repo Candidate Coverage = 25.0%** because intermediate token overlap multipliers introduced an empirical regression.
   - Earlier working summaries conflated the high coverage from `88d66fa` with the commit hash `7742706`. Controlled ablation proved that token-overlap multipliers demoted semantic vectors; hence, the clean `88d66fa` logic was frozen and released at commit `06d28dae442e39b7d66bf58c867d6a982d3c13a0`.
3. **Decoupled Cross-Repository Metrics**: Routing intent accuracy, candidate file coverage, and verified line-level multi-evidence retrieval are evaluated and reported as separate dimensions.
4. **Controlled Evaluation Scope**: Clean abstention on fabricated queries verifies threshold behavior against known absent symbols, not an absolute guarantee against generative hallucinations in external downstream LLMs.

---

## 2. Complete Historical Run Ledger

| Run ID | Timestamp (UTC) | Git Commit / Branch | Target Corpus / DB Snapshot | Total Chunks | Environment & Hardware | Reranker Enabled | Evaluation Dataset | Key Metrics Recorded | Artifact Location / Log |
| :--- | :--- | :--- | :--- | :---: | :--- | :---: | :--- | :--- | :--- |
| **`RUN-PRE-ENRICH`** | 2026-10-10 | `ca8624d`<br>`feat/system1-system2-retrieval` | `real_lancedb`<br>(4 repos) | 12,592 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 150-query Manifest v1 | • Exact Hit@5: 100.0% (P50: 84.7ms)<br>• Concept Hit@5: 37.5%<br>• Clean Abstain: 0.0% (20 FP) | `benchmarks/results/real_corpus_indexing_summary.json` |
| **`RUN-TASK8463`** | 2026-10-11 03:02 | `88d66fac8f4dd3f1`<br>`feat/autonomous-loop` | `enriched_lancedb`<br>(4 repos) | 48,348 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 150-query Manifest v2 | • Exact Hit@5: 100.0% (P50: 14.34ms)<br>• Concept Hit@5: 52.5%<br>• Cross-Repo Cov: 45.0%<br>• Clean Abstain: 100.0% (0 FP) | `benchmarks/results/historical_runs/raw_run_RUN-20261011-083216-TASK8463.json` |
| **`RUN-TASK8665`** | 2026-10-11 08:58 | `7742706248d39b75`<br>`feat/loop-iter-5` | `enriched_lancedb`<br>(4 repos) | 48,348 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 150-query Manifest v2 | • Exact Hit@5: 100.0% (P50: 14.39ms)<br>• Concept Hit@5: 45.0% (Regression)<br>• Cross-Repo Cov: 25.0%<br>• Clean Abstain: 100.0% (0 FP) | `benchmarks/results/enriched_fair_comparison_report.json` |
| **`RUN-ABLATION`** | 2026-10-11 09:10 | `06d28dae442e39b7`<br>`feat/loop-iter-5` | `enriched_lancedb`<br>(4 repos) | 48,348 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 75-query Validation Split | • 6-arm Ablation Study identifying token symbol boost regression | `benchmarks/results/ablation_validation_results.json` |
| **`RUN-RETRO-SPLIT`** | 2026-10-11 09:10 | `06d28dae442e39b7`<br>`feat/loop-iter-5` | `enriched_lancedb`<br>(4 repos) | 48,348 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 75-query Retrospective Split | • Exact Hit@5: 100.0% (P50: 13.59ms)<br>• Concept Hit@5: 50.0%<br>• Clean Abstain: 100.0% (0 FP) | `benchmarks/results/retrospective_benchmark_split_report.json` |
| **`RUN-FRESH-EVAL`** | 2026-10-11 10:07 | `06d28dae442e39b7`<br>`feat/loop-iter-5` | `enriched_lancedb`<br>(4 repos) | 48,348 | Docker 8 vCPU, 16 GB RAM (AMD EPYC) | False | 26 Genuinely New Queries | • Exact Hit@5: 100.0% (P50: 15.08ms)<br>• Concept Hit@5: 75.0%<br>• Clean Abstain: 100.0% (0 FP)<br>• Cross-Repo Multi-Ev: 25.0% | `benchmarks/results/genuinely_new_queries_evaluation_report.json` |

---

## 3. Detailed Per-Repository Database Snapshot

All benchmark runs on `enriched_lancedb` evaluated against an identical, frozen LanceDB database containing **48,348 chunks** extracted via Tree-sitter from real GitHub repositories:

```
Total Database Records: 48,348 chunks
Vector Dimensions: 384 (FastEmbed BAAI/bge-small-en-v1.5)
Columnar Engine: LanceDB (Rust Arrow Core) + Tantivy Full-Text Search
```

| Cloned Repository | Tracked File Count | Total Code Chunks | Proportion of Database | Primary Source Types |
| :--- | :---: | :---: | :---: | :--- |
| **`microsoft/TypeScript`** | 720 | 46,376 | 95.92% | `.ts`, `.tsx`, `.js` |
| **`fastapi/fastapi`** | 42 | 1,239 | 2.56% | `.py` |
| **`pallets/flask`** | 25 | 663 | 1.37% | `.py` |
| **`expressjs/express`** | 11 | 70 | 0.15% | `.js` |
| **Total Corpus** | **798** | **48,348** | **100.00%** | Multi-Language Corpus |

---

## 4. Controlled Optimization Ablation Study

Evaluated across the 75-query validation split to isolate the impact of individual retrieval flags:

| Configuration / Toggled Flag | Concept Hit@1 | Concept Hit@5 | Cross-Repo Coverage | Clean Abstention | Empirical Finding & Regression Analysis |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **1. Released Baseline (`v_88d66fa`)**<br>Asymmetric RRF ($k_{\text{lex}}=65, k_{\text{vec}}=38$) + Round-robin diversity | 15.0% | **55.0%** | **60.0%** | **100.0%** | **Optimal Configuration.** Vector semantic signal retains top ranks. |
| **2. `+ Path Token Boost Only`** | **20.0%** | **55.0%** | **60.0%** | **100.0%** | Slight Hit@1 improvement without degrading Top-5 recall. |
| **3. `+ Symbol Token Boost Only`** | 20.0% | **40.0% (-15.0%)** | **40.0% (-20.0%)** | **100.0%** | **Severe Regression.** Lexical symbol substrings overpower dense semantic embeddings. |
| **4. `+ Both Token Overlap Boosts`** | 20.0% | **40.0% (-15.0%)** | **40.0% (-20.0%)** | **100.0%** | Regression sustained. |
| **5. `+ Score-Ordered Diversity Merge`** | 15.0% | **55.0%** | **60.0%** | **100.0%** | Score sorting yielded neutral difference to alphabetical round-robin. |
| **6. Cumulative Iteration (`v_7742706`)** | 20.0% | **40.0% (-15.0%)** | **40.0% (-20.0%)** | **100.0%** | Replicated the lower numbers found in commit `7742706`. |

---

## 5. Single Execution on Genuinely New Queries

A fresh set of 26 queries was authored to evaluate the frozen model on queries never seen during tuning (`benchmarks/genuinely_new_queries_manifest.json`):

### Category Metrics (Strict $\text{Top-K} = 5$ Budget)
* **Exact Symbol Search (10 queries)**:
  - Hit@1: **90.0%** (9 / 10)
  - Hit@5: **100.0%** (10 / 10)
  - Candidate Coverage: **100.0%** (10 / 10)
  - Latency: $P_{50} = 15.08\text{ ms}$, $P_{95} = 22.36\text{ ms}$
* **Concept Semantic Search (8 queries)**:
  - Hit@1: **62.5%** (5 / 8)
  - Hit@5: **75.0%** (6 / 8)
  - Candidate Coverage: **75.0%** (6 / 8)
  - Latency: $P_{50} = 89.83\text{ ms}$, $P_{95} = 385.09\text{ ms}$
* **Absent Control / Anti-Hallucination (4 queries)**:
  - Clean Abstention Rate: **100.0%** (4 / 4)
  - False Positives: **0 / 4**
  - Latency: $P_{50} = 79.89\text{ ms}$

### Decoupled Cross-Repository Analysis (4 queries)
1. **Routing Intent Detection**: **100.0%** (4 / 4). The router detected multi-framework comparative intents and dispatched to `route="stratified"`.
2. **File Candidate Coverage**: **25.0%** (1 / 4). In 3 queries, the dominant framework occupied 4 of 5 Top-5 slots, failing to surface files from both projects.
3. **Verified Multi-Evidence Retrieval**: **25.0%** (1 / 4). Line-level evidence from both required repositories was successfully retrieved in 1 query.

---

## 6. How to Re-Run Benchmarks Locally or in Docker

```bash
# 1. Run the test suite (92 tests)
pytest tests/ -v

# 2. Run the frozen evaluation on genuinely new queries
python benchmarks/run_genuinely_new_evaluation.py

# 3. Run the ablation comparison on the validation split
python benchmarks/run_ablation_and_held_out.py
```

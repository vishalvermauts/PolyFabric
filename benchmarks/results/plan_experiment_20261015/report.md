# PolyFabric improvement-plan experiment

Executed on 14 October 2026 UTC in the ChatGPT Linux execution container. The run directory and branch suffix `20261015` are identifiers, not the execution date. This was not executed in the earlier Docker cloud sandbox.

Baseline: upstream commit `b09f41ba8281869c89ddccd2657ba7ecb03ea61f`. Changed implementation: `396dfb2a1e6742cf4c6bab1b86d3ff8ad9d6794d`. Source hashes and dependency versions are recorded in `run_metadata.json`. `main` was not modified.

## What this test establishes

Both arms searched the same complete four-repository corpus, with identical stored BGE vectors and query manifests. Three isolated subprocess trials used randomized arm order and four fixed route warmups outside measurements. No coding LLM, paid API, LiteLLM key, or gateway was used. These results measure retrieval, not code-edit acceptance, token savings, dollar savings, or production readiness.

Important: the fresh corpus uses the baseline parser and explicit 128-token passage truncation with `BAAI/bge-small-en-v1.5`. Full original chunk text remains available for lexical search. This bounds CPU indexing cost and isolates retrieval changes. It is a new controlled experiment, not a reproduction of the historical 48,348-row/full-length embedding database. Parser changes are regression-tested separately; their semantic uplift and real cross-encoder quality/latency remain unmeasured.

## Actual corpus

| Repository | Files scanned | Stored chunks |
|---|---:|---:|
| express | 11 | 70 |
| fastapi | 44 | 1239 |
| flask | 24 | 662 |
| typescript | 698 | 45995 |

Total stored chunks: **47,966**. Counts come from complete file inventory and database count, with source file hashes in `corpus_manifest.json`. Scopes and commits match `corpus.lock.json`.

## Retrieval quality and latency

Hit@5 means the labelled file and symbol or line range appeared among five returned chunks. Cross-project success requires every labelled file/range in the same five-result budget. Absent-control percentage means clean abstention on that finite sample. These are historical query sets already seen by earlier optimization work, including the file named `genuinely_new_queries_manifest.json`; neither is claimed to be an untouched holdout. Line-range labels were not revised after observing results.

Latency below is median end-to-end retrieval wall time over three trials and queries in each category. It includes scalar scan, lexical search, embedding, vector search and ranking. Model loading and fixed warmups are excluded. Embedding, vector query execution and remaining retrieval work are recorded separately per query. Vector DB timing includes result materialization; lexical/scalar/ranking work is included in `other_retrieval_ms`.

### query_ground_truth_manifest.json

| Category | Queries | Baseline Hit@1 | Changed Hit@1 | Baseline success@5 | Changed success@5 | Baseline P50 ms | Changed P50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| absent_control | 20 | — | — | 5.0% | 100.0% | 173.02 | 275.07 |
| concept | 40 | 12.5% | 12.5% | 25.0% | 30.0% | 230.77 | 103.85 |
| cross_project | 20 | — | — | 0.0% | 0.0% | 511.92 | 1230.76 |
| exact_symbol | 50 | 30.0% | 92.0% | 34.0% | 98.0% | 109.40 | 1.93 |
| typo | 20 | 5.0% | 5.0% | 15.0% | 15.0% | 213.05 | 177.53 |
### genuinely_new_queries_manifest.json

| Category | Queries | Baseline Hit@1 | Changed Hit@1 | Baseline success@5 | Changed success@5 | Baseline P50 ms | Changed P50 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| absent_control | 4 | — | — | 0.0% | 100.0% | 174.72 | 302.70 |
| concept | 8 | 37.5% | 50.0% | 75.0% | 75.0% | 222.03 | 164.79 |
| cross_project | 4 | — | — | 0.0% | 25.0% | 510.39 | 276.64 |
| exact_symbol | 10 | 60.0% | 80.0% | 80.0% | 100.0% | 112.23 | 2.04 |

## Resource and timing limits

Peak query-process RSS: baseline 863.2 MiB; changed 1047.9 MiB. This includes Python, ONNX and LanceDB; it is not total system memory and excludes a coding LLM. The plan's under-250-MB claim is not supported.

Query embedding encoders used two threads each; indexing used four worker processes. Production default encoder thread settings were not changed. A shared-container background indexing attempt remained active during observations; its process snapshot and aborted-run log are preserved. Absolute timings are not a dedicated-host SLA. No 4x–6x production indexing speedup is claimed.


## IVF_PQ versus exhaustive flat neighbors

IVF_PQ was created only after the flat two-arm comparison. Index and bypass physical plans are saved in `ann_recall.json`. Thirty fixed queries (six per category), identical L2 vectors, three warmup queries per configuration and five randomized configuration/query-order trials were used. Neighbor Recall@k is overlap with exhaustive neighbor IDs, separate from the task Hit@5 tables above. Cutoff ties are not specially credited.

| nprobes | Refine factor | Neighbor Recall@5 | Neighbor Recall@10 | DB P50 ms | DB P95 ms |
|---|---:|---:|---:|---:|---:|
| exhaustive | 1 | 100.0% | 100.0% | 31.03 | 50.00 |
| 1 | 1 | 40.0% | 33.0% | 6.42 | 14.04 |
| 10 | 1 | 69.3% | 55.0% | 6.82 | 8.87 |
| 20 | 1 | 70.7% | 55.7% | 7.15 | 9.50 |
| 64 | 1 | 71.3% | 56.3% | 9.14 | 13.40 |
| 20 | 2 | 79.3% | 70.3% | 6.96 | 9.62 |

Audit trail: the first ANN attempt retained a stale pre-index table handle and actually ran flat search. It is preserved as `ann_invalid_stale_handle.json`, explicitly excluded. The final attempt reopens the table and asserts `ANNSubIndex` is present only in the indexed plan.

ANN is explicit opt-in; this sample cannot certify zero recall loss on future workloads. Warm DB latency excludes embeddings and application ranking.

## Implementation scope and limits

| Plan item | Implemented and checked | Remaining limitation |
|---|---|---|
| IMP-01 | Complete scalar scans, version-aware cache, declaration dictionary; regression beyond 10,000 rows and external writer deletion | Full text snapshot still consumes memory; no 250 MB guarantee |
| IMP-02 | Explicit lexical-only search and bounded query-vector cache | Cache invalidates when encoder instance changes; mutable in-place model configuration is not supported |
| IMP-03 | Exact registered-project inference; target-restricted stratification; score-ordered diversity merge | No hardcoded language-to-framework map; explicit names can be ambiguous |
| IMP-04 | Preceding comments and Python decorators retained | No semantic uplift claim: shared benchmark database intentionally uses baseline chunks; path multipliers deferred |
| IMP-05 | Larger pre-rerank pool; optional MCP reranker flag; regression verifies candidate beyond final k can reach reranker | Real reranker model performance not measured |
| IMP-06 | Direct dictionary fuzzy-symbol search; exact single-project inference | Natural-language typo expansion/fuzzy project scoping deferred pending independent quality test |
| IMP-07 | Context-expansion argument/return contract fixed | No new end-to-end coding acceptance benchmark |
| IMP-08 | Bare conjunction no longer forces cross-repo routing; unknown lexical distance stays unknown | No blanket abstention guarantee; lexical confidence calibration remains open |
| IMP-09 | Empty-project bulk write; relative watcher paths; persisted content hashes; change/delete/skip tests; indexing errors reported | Bulk throughput not benchmarked against baseline; watcher concurrency/failure recovery needs broader soak tests |
| IMP-10 | Optional IVF_PQ builder; physical plans and exact neighbor comparison | Not auto-enabled by corpus size; workload recall must be accepted first |

## Regression tests

Baseline: **92 passed**. Changed implementation: **103 passed**, including 11 added regressions. Logs are retained. Synthetic vectors/encoders are used only in deterministic regression tests, never for the retrieval quality or ANN measurements.

## Reproduce

Install dependencies from `pyproject.toml`, retain the recorded dependency versions, clone the four repositories at the commits/scopes in `corpus.lock.json` under `/tmp/polyfabric-corpus`, and place the upstream baseline source under `/tmp/polyfabric-baseline`.

```bash
export EXPERIMENT_OUT="$PWD/benchmarks/results/plan_experiment_20261015"
PYTHONPATH=/tmp/polyfabric-baseline/src .venv/bin/python benchmarks/experiment_build_corpus.py
.venv/bin/python benchmarks/experiment_run_comparison.py
RAYON_NUM_THREADS=4 .venv/bin/python benchmarks/experiment_ann_recall.py
.venv/bin/python benchmarks/experiment_summarize.py
```

The builder refuses to overwrite a nonempty `/tmp/polyfabric-comparison-db-v2`. Use a fresh path/environment for reproduction; do not run both builders concurrently. Model weights require a first download; subsequent inference is local. The abandoned initial full-length indexing attempt is preserved only in `indexing.log` and contributed no final comparison rows.

Raw per-query results, timings, complete corpus inventory, dependency versions, source hashes and physical query plans are preserved in `raw_artifacts.tar.xz` alongside this report (extract to inspect the named JSON files). They do not constitute independent certification. Earlier unreconciled LiteLLM billing remains unresolved and is not reused here.

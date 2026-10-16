# PolyFabric Evidence Guide

This guide separates recorded coding-task outcomes, retrieval experiments, and unresolved audit questions. It supports the primary [README](../README.md) and [PILOT_QUICKSTART.md](../PILOT_QUICKSTART.md). These are internal records available for inspection, not independent certification. This documentation update did not execute tests, models, indexing, or benchmarks.

---

## 1. Published Head-to-Head Benchmark (Baseline vs. Improved PolyFabric)

The primary empirical evidence for PolyFabric's release candidate is the completed head-to-head evaluation:

- **Run ID:** `RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED`
- **Full Run Directory:** [`benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/)
- **Inventory & Checksums:** [`inventory.json`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/inventory.json) (493 verified files) and [`checksums.sha256`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/checksums.sha256)
- **Target Repository:** [`FarmWatch`](https://github.com/vishalvermauts/FarmWatch) pinned to commit `201321eb045f9b5170007fc26def90e4d13bf564` (clean worktree).
- **Tested Models:** `gemini-2.5-flash` via Helix Gateway (`https://router.helixengine.app`).
- **Policy:** Temperature `0.0`, `max_tokens=8192`, at most 1 repair per attempt, live `npm run build` per attempt (no build cache).
- **Matrix:** 26 tasks $\times$ 3 trials $\times$ 2 arms = **156 evaluated attempts**.

### Tested Versions and Provenance

- **Baseline Arm (`baseline_polyfabric`):** Commit [`eda7e0e`](https://github.com/vishalvermauts/PolyFabric/commit/eda7e0e).
- **Improved Arm (`improved_polyfabric`):** Commit [`2ce529e`](https://github.com/vishalvermauts/PolyFabric/commit/2ce529e) on branch `experiment/frontier-model-optimizations`.
- **Subsequent Hardened Pilot Candidate:** Commit [`9ca5287`](https://github.com/vishalvermauts/PolyFabric/commit/9ca5287f717670941330b4202f0fb6ba606f797e) added read-only enforcement and CLI path normalization, verified in [`PILOT_VERIFICATION_9CA5287`](../benchmarks/results/PILOT_VERIFICATION_9CA5287/). Later documentation/handover commits were not benchmarked.

### Recomputed Headline Results (From Published Records)

All numbers below were independently recomputed directly from [`per_attempt_results.jsonl`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/per_attempt_results.jsonl), [`client_request_ledger.jsonl`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/client_request_ledger.jsonl), and [`summary.json`](../benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/summary.json):

| Metric | Baseline PolyFabric (`eda7e0e`) | Improved PolyFabric (`2ce529e`) | Improvement / Delta |
| :--- | :---: | :---: | :---: |
| **Total Evaluated Attempts** | 78 | 78 | Identical denominator (26 tasks $\times$ 3 trials) |
| **Accepted Attempts (incl. repairs)** | 75 / 78 (96.15%) | **78 / 78 (100.0%)** | **+3.85% (+3 accepted attempts)** |
| **First-Pass Accepted Attempts** | 65 / 78 (83.33%) | **71 / 78 (91.03%)** | **+7.70% (+6 first-pass passes)** |
| **Repairs Attempted / Successful** | 13 attempted / 10 passed | **7 attempted / 7 passed** | **-46.2% fewer repair invocations** |
| **Failed Attempts** | 3 / 78 (3.85%, all UI-02) | **0 / 78 (0.00%)** | **Zero failures on improved arm** |
| **Negative Tasks First-Pass Repairs** | 6 repair calls (hallucinations) | **0 repair calls (clean abstention)** | **100% first-pass clean abstention** |
| **Prompt / Input Tokens** | 255,968 | **253,527** | **-0.95%** |
| **Completion / Output Tokens** | 71,682 | **49,292** | **-31.23%** (less repair waste) |
| **Total Tokens Consumed** | 327,650 | **302,819** | **-7.58% token reduction** |
| **Indexed Project Chunks** | 924 chunks | **642 chunks** | **-30.5% chunk reduction** (AST unwrapping) |
| **Cold Initial Indexing Time** | 57,884 ms (57.9 s) | **37,605 ms (37.6 s)** | **-35.0% faster initial indexing** |
| **Peak Indexing RAM (RSS)** | 3,803.5 MB | **1,542.9 MB** | **-59.4% memory footprint reduction** |
| **Median Warm Retrieval Latency** | 32.26 ms | **23.32 ms** | **-27.7% faster warm search** |
| **Client Calculated Spend** | $0.0814 | **$0.0676** | **-17.0% client calculated cost** |
| **Server Reported Spend** | $0.2346 | **$0.1869** | **-20.3% server spend** |
| **Spend Reconciliation Status** | **UNRESOLVED** | **UNRESOLVED** | Server pricing delta persists |

### Known Limitations and Evidence Gaps

1. **Unreconciled Server Spend:** A discrepancy between client formula accounting ($0.0676) and LiteLLM gateway reported spend ($0.1869) remains **UNRESOLVED** because the gateway does not export per-request itemized token billing logs. Token reductions **must not be equated with guaranteed dollar savings**.
2. **Single-Repository Scope:** Evaluated on FarmWatch (27 files, 642 chunks). This does not demonstrate identical behavior on massive 10,000-file mono-repos or multi-tenant clouds.
3. **Repeated Tasks:** 78 attempts per arm represent 26 distinct tasks evaluated over 3 trials, not 78 independent engineering tasks.
4. **Targeted Pilot Checks (`9ca5287`):** The subsequent candidate checks verified that `POLYFABRIC_READ_ONLY=1` rejects writes while reads succeed, and CLI paths are stored relatively. These checks were environment safety verifications, not a full coding benchmark rerun.

---

## 2. Historical Comparison: Search Baselines (`RUN_20261013_FARMWATCH_3KEY_CORRECTED`)

> [!NOTE]
> **Historical Run with Audit Qualifications:** The figures below describe the older `RUN_20261013_FARMWATCH_3KEY_CORRECTED` run comparing early PolyFabric (`4b32c9b`) against ripgrep (`rg`) and whole-file context. Subsequent audits identified shared-worktree contamination and overwritten supporting artifacts. These records are retained for historical provenance, not as release certification or an uncontested comparison.

### Protocol and Matrix

- **Run ID:** `RUN_20261013_FARMWATCH_3KEY_CORRECTED`
- **Target Repository:** FarmWatch at [`201321eb045f9b5170007fc26def90e4d13bf564`](https://github.com/vishalvermauts/FarmWatch/commit/201321eb045f9b5170007fc26def90e4d13bf564).
- **Recorded PolyFabric Source:** [`4b32c9b1421b0c3d9aa9ed439cf3b90b44350ea4`](https://github.com/vishalvermauts/PolyFabric/commit/4b32c9b1421b0c3d9aa9ed439cf3b90b44350ea4).
- **Matrix:** 26 tasks $\times$ 3 trials $\times$ 3 approaches = **234 evaluated attempts** (298 model requests).

### Full Historical Comparison Table

| Recorded Measurement | PolyFabric (`4b32c9b`) | Targeted `rg` Search | Whole-File Context |
| :--- | :---: | :---: | :---: |
| **Prompt / Input Tokens** | **252,957** | 534,309 | 9,658,300 |
| **Completion / Output Tokens** | 81,150 | 95,488 | 88,280 |
| **Total Input + Output Tokens** | **334,107** | 629,797 | 9,746,580 |
| **Accepted Attempts (incl. repairs)** | **74 / 78 (94.87%)** | 64 / 78 (82.05%) | 62 / 78 (79.49%) |
| **Accepted Before Repair** | 59 / 78 | 54 / 78 | 57 / 78 |
| **Model Requests (incl. repairs)** | 97 | 102 | 99 |
| **Median End-to-End Wall Time** | 6.86 s | **4.58 s** | 8.03 s |

| PolyFabric Token Reduction | Versus Targeted `rg` Search | Versus Whole-File Context |
| :--- | :---: | :---: |
| **Prompt / Input Tokens** | **52.66%** | **97.38%** |
| **Total Input + Output Tokens** | **46.95%** | **96.57%** |

### Historical Verification Artifacts

- [Summary](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/summary.json)
- [Client Request Ledger](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/client_request_ledger.jsonl) (298 calls)
- [Attempt Outcomes](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/per_attempt_results.jsonl) (234 attempts)
- [Task Manifest](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/task_manifest.json)
- [Billing Reconciliation](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/reconciliation_report.json)
- [Run Provenance](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/run_provenance_and_metadata.json)

---

## 3. Retrieval, Ablation and Engineering Evidence

These tests evaluate code discovery, parsing, and engineering behavior. They do not measure downstream agent token savings by themselves:

| Evidence Asset | Scope and Verification |
| :--- | :--- |
| [Preserved Plan Experiment (`plan_experiment_20261015`)](../benchmarks/results/plan_experiment_20261015/) | 176 retrieval queries over 47,966 chunks; includes [report](../benchmarks/results/plan_experiment_20261015/report.md), [summary](../benchmarks/results/plan_experiment_20261015/summary.json), and [raw archive](../benchmarks/results/plan_experiment_20261015/raw_artifacts.tar.xz) preserved on `main` at commit `c3a1015`. |
| [Pilot Verification 9ca5287](../benchmarks/results/PILOT_VERIFICATION_9CA5287/) | Verification summary and raw execution logs for MCP read-only denial, file immutability, and relative CLI paths. |
| [Retrieval Run Ledger](benchmarks/README.md) | Earlier four-repository runs, corpus snapshots, retrospective splits, and ablations. |
| [Ablation Results](../benchmarks/results/ablation_validation_results.json) | Configuration comparisons and regressions on historical validation split. |
| [MCP Protocol Record](../benchmarks/results/mcp_protocol_test.json) | Recorded MCP protocol compliance checks. |
| [Concurrency Benchmark](../benchmarks/results/mcp_concurrency_benchmark_summary.json) | Concurrency performance under multi-client loads. |
| [Release Readiness Report](POLYFABRIC_RELEASE_READINESS_REPORT.md) | Comprehensive audit report covering provenance, comparability, and release readiness. |

---

## 4. Planned StructZero Integration Status

[StructZero](https://www.structzero.app/) is a multi-agent orchestration framework. PolyFabric's intended role is to serve as StructZero's shared code-context layer, retrieving bounded evidence packs before calling language models.

- **Status:** **Planned integration.**
- **Current Support:** PolyFabric integrates with StructZero or any other agent framework via the standard Model Context Protocol (MCP) JSON-RPC stdio interface.
- **Unverified:** FarmWatch benchmark results are standalone engine evaluations and do not measure or certify a deployed StructZero integration. Production StructZero rollout requires tenant isolation, commit-aware context caching, and per-agent spend attribution.

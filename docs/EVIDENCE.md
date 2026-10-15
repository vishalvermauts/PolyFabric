# PolyFabric evidence guide

This guide separates recorded coding-task outcomes, retrieval experiments and unresolved audit questions. It supports the [shorter README](../README.md). These are internal records available for inspection, not independent certification. This documentation update did not execute tests, models, indexing or benchmarks.

## 1. The coding benchmark used in the README

**Run:** `RUN_20261013_FARMWATCH_3KEY_CORRECTED`  
**Project:** FarmWatch, a TypeScript/React/Express application.  
**Target source:** [`201321eb045f9b5170007fc26def90e4d13bf564`](https://github.com/vishalvermauts/FarmWatch/commit/201321eb045f9b5170007fc26def90e4d13bf564).  
**Recorded PolyFabric source:** [`4b32c9b1421b0c3d9aa9ed439cf3b90b44350ea4`](https://github.com/vishalvermauts/PolyFabric/commit/4b32c9b1421b0c3d9aa9ed439cf3b90b44350ea4).  
**Model and policy:** `gemini-2.5-flash`; the runner specifies temperature 0, output budget 8,192 and at most one repair per attempt.  
**Matrix:** 26 tasks, three trials per approach, three approaches; 234 evaluated attempts and 298 benchmark model requests. Tasks cover UI, logic, refactoring, dependency tracing and difficult/negative cases, including additional generalization-labelled tasks.

Three distinct LiteLLM key aliases identify the approaches. This establishes client attribution; it does not by itself reconcile provider billing. No credentials are needed to inspect the committed records.

### Source records and how to inspect them

| Record | What it lets a reviewer check |
|---|---|
| [Summary](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/summary.json) | Published totals and current reconciliation status |
| [Client request ledger](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/client_request_ledger.jsonl) | 298 benchmark calls; approach, task, trial, initial/repair stage, IDs, returned usage and latency |
| [Attempt outcomes](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/per_attempt_results.jsonl) | 234 attempts; acceptance, repair flags, evidence recall, token totals and wall time |
| [Task manifest](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/task_manifest.json) | Task definitions and categories |
| [Full run directory](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/) | Available acceptance criteria, patches, verification records and other supporting artifacts |
| [Runner](../benchmarks/run_3key_full_eval.py) | Context-gathering policies, worktree handling, model calls and acceptance logic |
| [Provenance disclosure](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/run_provenance_and_metadata.json) | Recorded source references and missing launch metadata |
| [Preflight records](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/preflight_attribution_records.json) | Initial attribution checks, separate from benchmark consumption |
| [Excluded duplicate launch](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/excluded_duplicate_launch_records.jsonl) | 65 quarantined calls, excluded from benchmark comparison totals |
| [Billing reconciliation](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/reconciliation_report.json) | Server/client differences and why verified dollar savings are withheld |

For this README edit, the stored client request ledger was summed by approach and matched against the stored attempt outcomes and summary:

| Approach | Requests | Attempts | Accepted | Prompt tokens | Output tokens | Total tokens |
|---|---:|---:|---:|---:|---:|---:|
| PolyFabric | 97 | 78 | 74 | 252,957 | 81,150 | 334,107 |
| Targeted search | 102 | 78 | 64 | 534,309 | 95,488 | 629,797 |
| Whole-file context | 99 | 78 | 62 | 9,658,300 | 88,280 | 9,746,580 |

The request totals also match each approach's summed `model_calls` in the attempt records. This is a consistency check of saved data, not a rerun or independent confirmation of every acceptance decision. Review the runner's criteria and actual patches when assessing coding quality.

### Calculations

`reduction = 100 × (1 − PolyFabric tokens / baseline tokens)`

- Prompt reduction versus targeted search: `1 − 252957 / 534309` = **52.66%**.
- Prompt reduction versus whole-file context: `1 − 252957 / 9658300` = **97.38%**.
- Total-token reduction versus targeted search: `1 − 334107 / 629797` = **46.95%**.
- Total-token reduction versus whole-file context: `1 − 334107 / 9746580` = **96.57%**.

Token totals include initial and repair calls, including failed attempts. Cached prompt tokens are a subset of prompt tokens; they must not be added again. Reasoning-token fields can overlap provider completion accounting and must not be added blindly. Each arm has 78 repeated-task attempts, not 78 unique tasks.

README median wall times are calculated from the 78 `total_wall_ms` values for each approach: PolyFabric **6,855.07 ms**, targeted search **4,583.415 ms**, whole-file context **8,026.72 ms**. These include more than model generation and are observational timings from the saved run.

### Read-only verification example

A reviewer can run the following from a checkout to recompute stored totals. It only reads JSONL files; it does not import PolyFabric or call a model. It was not executed as a new benchmark during this edit.

```python
import json
from collections import defaultdict
from pathlib import Path

root = Path("benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED")
totals = defaultdict(lambda: {"requests": 0, "prompt": 0, "output": 0, "total": 0})
for line in (root / "client_request_ledger.jsonl").read_text().splitlines():
    row = json.loads(line)
    total = totals[row["approach"]]
    total["requests"] += 1
    total["prompt"] += row["prompt_tokens"]
    total["output"] += row["completion_tokens"]
    total["total"] += row["total_tokens"]
print(dict(totals))
```

### Limits that matter for diligence

- The experiment covers one application and the runner's particular context-gathering and repair policies. It does not establish the same gain across languages, large repositories, model providers or commercial coding products.
- Whole-file context is a useful reference baseline, not a claim that every competing tool sends whole files. The targeted-search comparison is the closer efficiency baseline here.
- Acceptance follows the saved automated checks. Repeated trials share tasks; they are not independent evidence of market-wide reliability.
- Working-tree status, exact launch environment/runtime and live benchmark indexing telemetry were not fully captured. The [provenance file](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/run_provenance_and_metadata.json) distinguishes recorded facts from unknowns.
- Server spend remains **unresolved**. The saved key-level aggregates include traffic outside the benchmark, and residual differences persist after known exclusions. Proposed explanations for pricing differences are hypotheses until transaction-level records establish the cause.
- The [offline indexing verification](../benchmarks/results/offline_retrieval_verification/offline_retrieval_verification_report.json) is a separate measurement. Its 924 chunks, approximately 97.3-second initial indexing and approximately 3.77-GB peak RSS must not be presented as captured telemetry from the full coding benchmark.
- These records do not establish production readiness, universal absence of hallucinations, or measured StructZero savings.

## 2. Historical coding runs — kept separate

| Run | Interpretation and evidence |
|---|---|
| Initial bounded evaluation | [Report](../benchmarks/results/RUN_20261013_FARMWATCH_BOUNDED_EVAL/report.md) and [artifacts](../benchmarks/results/RUN_20261013_FARMWATCH_BOUNDED_EVAL/). Earlier results exposed refactoring and dependency-context weaknesses; do not combine their parameters with later runs. |
| Post-fix evaluation | [Report](../benchmarks/results/RUN_20261013_FARMWATCH_POSTFIX_EVAL/report.md) and [artifacts](../benchmarks/results/RUN_20261013_FARMWATCH_POSTFIX_EVAL/). Shared-key attribution and excluded/orphaned records have their own disclosures. |
| Initial three-key evaluation | [Artifacts and audit](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_EVAL/). **Invalid retrieval setup:** incomplete indexing and path resolution discarded the retrieved context. Its low token count is not evidence of useful compression. |
| Corrected three-key evaluation | [Artifacts](../benchmarks/results/RUN_20261013_FARMWATCH_3KEY_CORRECTED/). This is the run used for the README table, subject to the provenance and billing limits above. |

The [previous README snapshot](README_ARCHIVE_20261015.md) retains the earlier narratives and corrections. It is historical documentation; its old installation/API examples are superseded by the current README.

## 3. Retrieval, ablation and engineering evidence

These tests evaluate code discovery and engineering behaviour. They do not measure downstream API-token savings by themselves.

| Evidence | Scope |
|---|---|
| [Retrieval run ledger](benchmarks/README.md) | Earlier four-repository runs, corpus snapshots, retrospective splits and ablations |
| [Ablation results](../benchmarks/results/ablation_validation_results.json) | Configuration comparisons and regressions on the historical validation split |
| [Retrospective split](../benchmarks/results/retrospective_benchmark_split_report.json) | A split from previously used questions; not an untouched holdout |
| [Additional query report](../benchmarks/results/genuinely_new_queries_evaluation_report.json) | Questions described as new for that historical run; later reuse does not make them fresh again |
| [MCP protocol record](../benchmarks/results/mcp_protocol_test.json) | Recorded protocol checks, distinct from search or coding quality |
| [Concurrency results](../benchmarks/results/mcp_concurrency_benchmark_summary.json) | Recorded concurrent MCP measurements |
| [Soak summary](../benchmarks/results/soak_final_summary.json) | Recorded engineering exercise; inspect its parameters before generalizing |
| [Test source](../tests/) and [CI definition](../.github/workflows/test.yml) | Test cases and configured workflow; existence is not evidence of a newly completed passing run |
| [Complete artifact directory](../benchmarks/results/) | All remaining recorded reports, profiles and detailed query results |

### Separate improvement-plan experiment

The experiment at [`732f529`](https://github.com/vishalvermauts/PolyFabric/commit/732f529da33aa60e214067ae473e65ee66c45dbf) remains on a separate branch. Its [report](https://github.com/vishalvermauts/PolyFabric/blob/732f529da33aa60e214067ae473e65ee66c45dbf/benchmarks/results/plan_experiment_20261015/report.md), [summary](https://github.com/vishalvermauts/PolyFabric/blob/732f529da33aa60e214067ae473e65ee66c45dbf/benchmarks/results/plan_experiment_20261015/summary.json) and [raw evidence archive](https://github.com/vishalvermauts/PolyFabric/blob/732f529da33aa60e214067ae473e65ee66c45dbf/benchmarks/results/plan_experiment_20261015/raw_artifacts.tar.xz) contain 176 historical retrieval queries over a fresh 47,966-chunk database with 128-token passage embeddings.

It recorded 103 passing regression tests, large symbol-retrieval gains, limited semantic gains and persistent cross-project problems. It also identified and excluded an ANN attempt that used a stale table handle and was actually flat search. The corrected physical plan used IVF_PQ; 20 probes/refine factor 2 gave 70.3% neighbour Recall@10 on 30 sampled queries. That is a speed/recall tradeoff, not zero-loss ANN.

Its source changes are not merged into `main`. Its corpus, embedding policy, timings and metrics differ from the coding benchmark; combining them into one headline would be misleading. No paid coding-model calls were made in that experiment.

## 4. What remains to validate in StructZero

The proposed integration is a shared, project-scoped evidence layer before model calls. StructZero-specific claims require an integration evaluation with the existing workflow as baseline, versioned context, independently checked patches and per-agent token attribution. Billing claims additionally require request-level gateway reconciliation. Project isolation, stale-index behaviour and complete-reference fallback must be validated before broad rollout.

No StructZero token-saving percentage or production deployment result is claimed by the present README.

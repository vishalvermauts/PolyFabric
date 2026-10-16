# PolyFabric Limited-Production Release Readiness Report
## Formal Release Review & Head-to-Head Benchmark Verification

**Report Date:** 2026-10-16  
**Auditor / Reviewer:** Senior Release Reviewer & Systems Quality Auditor  
**Repository:** [`https://github.com/vishalvermauts/PolyFabric`](https://github.com/vishalvermauts/PolyFabric)  
**Evaluated Benchmark Candidate Commit:** `2ce529ea3adef821642353df57cbf667c2c09f1a` (branch `experiment/frontier-model-optimizations`)  
**Hardened Post-Audit Candidate Commit:** `9ca5287f717670941330b4202f0fb6ba606f797e` (branch `experiment/frontier-model-optimizations`)  
**Evaluated Baseline Commit (Pre-Optimization):** `eda7e0ea18c460947fcc1ad6bdc70f400e1d9e7d` (HEAD of `main`)  
**Benchmark Artifact Source:** `benchmarks/results/RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED/`  
**Target Application Benchmark:** [`FarmWatch`](https://github.com/vishalvermauts/FarmWatch.git) pinned to commit `201321eb045f9b5170007fc26def90e4d13bf564`  

---

# EXECUTIVE VERDICT

# **READY FOR A MONITORED READ-ONLY PILOT**

### Definition of "Monitored Pilot"
In strict adherence to the governing evaluation charter, a **"Monitored Pilot"** is defined solely as:
> **A monitored developer-reviewed code-context component for existing-code edits, symbol lookups, and debugging workflows, where write tools (`mesh_write_file`) are disabled via `POLYFABRIC_READ_ONLY=1` and all code changes require human review and approval before being accepted or merged.**

> [!CAUTION]
> **UNRESTRICTED AUTONOMOUS ENGINEERING IS NOT APPROVED.**  
> This decision does **NOT** authorize headless, autonomous git pushing, unsupervised production code modifications, or unreviewed multi-repository orchestration. Write tools (`mesh_write_file`) must remain strictly disabled and fail-closed during pilot operation.

---

## Explicit Distinction Between Evidence Types

To ensure scientific and operational precision, evidence in this review is partitioned into three distinct categories:

1. **Executed Empirical Benchmark Checks (Completed & Preserved on Commit `2ce529e`):**
   - 156 total evaluated attempts (26 FarmWatch tasks $\times$ 3 trials) executed in container sandbox `sbx_001m4haazrz2qc70t771bmyeqs0`.
   - Live `npm run build` compilation per attempt with `build_cache` disabled.
   - Multi-layer ground-truth verification (Layer 1 retrieval recall, Layer 2 string assertions, Layer 3 build exit code 0, Layer 4 Chromium Playwright rendering).
   - This benchmark is **fully completed, preserved, and will NOT be rerun.**
2. **Static Source Code Inspection (Verified against Codebase Structure):**
   - Inspection of AST parser rules (`tree_sitter_ast.py` export unwrapping).
   - Inspection of context assembly logic (`task_context.py` top-40 import window and missing-target diagnostics).
   - Discovery that candidate commit `2ce529e` unconditionally registered `mesh_write_file` as an MCP tool, had zero read-only environment variables, and allowed writes on feature branches.
   - Discovery that CLI `cli.py:71` stored absolute paths rather than relative POSIX paths.
3. **Hardened Candidate Changes & Executed Targeted Remote Checks (Candidate `9ca5287`):**
   - Added fail-closed `READ_ONLY_MODE` check in `config.py` and `server.py`.
   - Normalized relative POSIX paths in `cli.py:65`.
   - Unit test added in `tests/test_plan_regressions.py`.
   - **Targeted remote verification checks executed in container sandbox `sbx_001m4haazrz2qc70t771bmyeqs0`:**
     - Remote Check 1 (Real MCP stdio write rejection & byte immutability): **PASS**
     - Remote Check 2 (CLI relative-path indexing in LanceDB): **PASS**
     - Remote Check 3 (Offline startup & embedding): Evaluated & Marked **NOT REQUIRED** (Succeeded in 205.7 ms with 0 socket attempts).
     - Complete execution artifacts saved in `benchmarks/results/PILOT_VERIFICATION_9CA5287/`.

---

## Executive Scorecard: Verified Head-to-Head Comparison

The completed empirical benchmark compared **Baseline PolyFabric (`eda7e0e`)** against **Improved PolyFabric (`2ce529e`)** under side-by-side conditions across **26 FarmWatch tasks $\times$ 3 trials = 156 total attempts**:

| Metric | Baseline PolyFabric (`eda7e0e`) | Improved PolyFabric (`2ce529e`) | Absolute Delta | Percentage Delta | Verification Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Overall Acceptance Rate** | 75 / 78 (96.15%) | **78 / 78 (100.00%)** | **+3 attempts** | **+3.85 percentage points** | **EXECUTED BENCHMARK (Preserved)** |
| **First-Pass Pass Rate** | 65 / 78 (83.33%) | **71 / 78 (91.03%)** | **+6 attempts** | **+7.70 percentage points** | **EXECUTED BENCHMARK (Preserved)** |
| **Repairs Successfully Accepted** | 10 / 13 attempts (76.92%) | **7 / 7 attempts (100.00%)** | -3 repairs | -30.00% repair load | **EXECUTED BENCHMARK (Baseline attempted 13, 10 succeeded; Improved attempted 7, all 7 succeeded)** |
| **Final Failed Attempts** | 3 attempts (3.85%) | **0 attempts (0.00%)** | **-3 failures** | **-100.0% failure reduction** | **EXECUTED BENCHMARK (UI-02 failures)** |
| **Negative Task First-Pass Repairs** | 6 repair calls | **0 repair calls** | **-6 repairs** | **-100.0% repair reduction** | **EXECUTED BENCHMARK (NEG-01..04)** |
| **Mean Ground-Truth Recall** | 0.9615 (96.15%) | **1.0000 (100.00%)** | +0.0385 | +3.85 percentage points | **EXECUTED BENCHMARK (No missing deps)** |
| **Unrelated Files Modified** | 3 files | **0 files** | -3 files | -100.0% edit pollution | **EXECUTED BENCHMARK (Zero pollution)** |
| **Total Tokens Consumed** | 327,650 tokens | **302,819 tokens** | **-24,831 tokens** | **-7.58% token savings** | **EXECUTED BENCHMARK (Ledger)** |
| **Prompt Tokens Consumed** | 255,968 tokens | **253,527 tokens** | -2,441 tokens | -0.95% prompt reduction | **EXECUTED BENCHMARK (Ledger)** |
| **Completion Tokens Consumed** | 71,682 tokens | **49,292 tokens** | -22,390 tokens | -31.23% repair verbosity | **EXECUTED BENCHMARK (Ledger)** |
| **Indexed Project Chunks** | 924 chunks | **642 chunks** | **-282 chunks** | **-30.52% chunk bloat** | **SOURCE INSPECTION (AST unwrapping)**|
| **Cold Indexing Time** | 57,884 ms (57.9s) | **37,605 ms (37.6s)** | -20,279 ms | -35.03% indexing time | **QUALIFIED (Bulk upsert impact)** |
| **Peak Indexing RAM (RSS)** | 3,803.5 MB | **1,542.9 MB** | -2,260.6 MB | -59.43% memory reduction | **QUALIFIED (RSS measures resident memory, not full virtual footprint)**|
| **Median Warm Retrieval Latency** | 32.26 ms | **23.32 ms** | -8.94 ms | -27.71% retrieval latency | **EXECUTED BENCHMARK (Preserved)** |
| **Median Cold Retrieval Latency** | 32.01 ms | **26.94 ms** | -5.07 ms | -15.84% retrieval latency | **EXECUTED BENCHMARK (Preserved)** |
| **Gateway Billed Spend** | $0.23456 | **$0.18686** | -$0.04770 | -20.34% gateway spend | **UNRECONCILED (Markup delta)**|

---

# PART 1: VERIFY THE EXPERIMENT

### A. Provenance and Comparability
- **Baseline Commit SHA:** `eda7e0ea18c460947fcc1ad6bdc70f400e1d9e7d` (HEAD of `main`).
- **Benchmark Candidate Commit SHA:** `2ce529ea3adef821642353df57cbf667c2c09f1a` (branch `experiment/frontier-model-optimizations`).
- **Hardened Candidate Commit SHA:** `9ca5287f717670941330b4202f0fb6ba606f797e` (branch `experiment/frontier-model-optimizations`).
- **Target Repository Pinned Commit:** [`FarmWatch`](https://github.com/vishalvermauts/FarmWatch.git) at `201321eb045f9b5170007fc26def90e4d13bf564`.
- **Environment:** Container Sandbox (`sbx_001m4haazrz2qc70t771bmyeqs0`, Debian 13, Node v22.22.1, Python 3.14.4, Vite 8.3.4, Ripgrep 14.1.1).
- **Execution Window:** `2026-10-15T16:49:00Z` to `2026-10-15T17:08:38Z` (Wall-clock: 19m 38s).
- **Primary Execution Artifacts:**
  - `per_attempt_results.jsonl` (156 attempt records).
  - `client_request_ledger.jsonl` (176 model call records).
  - `sanitized_gateway_usage.json` (176 gateway transaction records).
  - `sanitized_server_spend_export.json` (server key spend snapshots).
  - `verification_logs/` (156 build and assertion log files).
- **Experimental Controls:**
  - Identical model (`gemini-2.5-flash`), temperature (`0.0`), max tokens (`8192`), repair budget (1 attempt), and trials per task (3 trials).
  - Prompts were identical except for the approach-specific code context block prepended to the task instruction.
  - Acceptance criteria (`target_files`, `must_contain`, `must_not_contain`, `npm run build` exit code 0) were held out from model prompts and evaluated uniformly.
- **Source Inspection of Differentiating Code Changes:**
  1. *AST Export Unwrapping:* Source inspection of `tree_sitter_ast.py:205-235` confirmed that unwrapping `export_statement` nodes prevents creating duplicate outer `ast_export_statement` chunks, reducing total chunk count from 924 to 642.
  2. *Top Import Block Window:* Source inspection of `task_context.py:192-200` confirmed that lines 1–40 of large files (>90 lines) provide an import window for top-of-file declarations, but do not provide a complete import guarantee for arbitrary files with imports beyond line 40.
  3. *Missing-Target Diagnostics:* Source inspection of `task_context.py:231-265` confirmed that when 0 files match a query, an explicit missing-target warning inventory is returned, preventing phantom hallucinations.
  4. *Bulk Initial Upsert:* Source inspection of `indexer.py:90-120` confirmed that cold repository indexing batches computed vectors into a single write rather than file-by-file commits.

---

### B. Source, Index, and Attempt Isolation
- **Worktree Cleanliness:**
  - In `benchmarks/run_3key_full_eval.py` (lines 1344–1347), before context gathering, before initial edit application, and before repair edit application, the runner executed:
    ```bash
    git checkout -- .
    git clean -fd -e node_modules -e package-lock.json
    ```
  - All 156 verification logs record that the worktree was clean prior to patch application.
- **Index Isolation:**
  - Baseline and Improved arms were indexed into separate LanceDB storage directories (`/tmp/polyfabric_baseline/.memory_db` vs. `/home/agent/workspace/PolyFabric/.memory_db`).
  - No active watchers were running during evaluation.
- **Repair Semantics:**
  - When an initial attempt failed, the worktree was reset back to clean HEAD.
  - The repair prompt explicitly required complete replacement edits from the clean baseline state rather than incremental diffs.

---

### C. Environment and Verification Layers
- **Resolution of Toolchain Defect:**
  - In the earlier run (`RUN_FRONTIER_VERIFIED_EVAL`), `node_modules/.bin/vite` was missing for tasks 1–3, causing build failures and cache poisoning.
  - In this head-to-head run, `npm install --legacy-peer-deps` was verified before launch; the clean baseline build passed in 289 ms (`npm run build` code 0).
- **Build Cache Disabled:**
  - In-memory `build_cache` was disabled. Every attempt ran a live `npm run build` (~1,080 ms per compilation).
  - Exit codes 126 and 127 were configured to immediately raise an `EnvironmentError`. Zero infrastructure failures occurred.
- **What "Build" Actually Verifies:**
  - `"build": "vite build"` executes Rollup module bundling, parses TSX syntax, resolves imports and exports, and compiles production assets into `dist/`.
  - *Limitation:* Vite build bundles and checks syntax, but is not full `tsc` typechecking (no standalone `tsc --noEmit` typecheck pass was executed, though Rollup/esbuild rejects syntax errors, missing variables, and unresolved imports).
- **Verification Layers:**
  - *Layer 1 (Retrieval):* Ground truth target file recall (100% for Improved, 96.15% for Baseline).
  - *Layer 2 (Syntax & Edit Assertions):* Valid JSON edits, literal string match assertions, zero unrelated files modified.
  - *Layer 3 (Build Compilation):* `npm run build` exit code 0.
  - *Layer 4 (Browser Checks):* Headless Chromium via Playwright loaded compiled pages in 1280x800 and 375x667 viewports.
  - *Caveat:* Screenshots confirm page rendering and hydration, but automated visual regression pixel-diffing was not performed.

---

### D. Recalculation of Results from Raw Artifacts
All figures were recomputed offline from `per_attempt_results.jsonl`, `client_request_ledger.jsonl`, and `sanitized_gateway_usage.json`:

```
Total attempt records: 156
Total ledger records: 176
Total gateway calls: 176
```

- **Unique Tasks:** 26 tasks (20 frozen core + 6 generalization suite tasks).
- **Trials Per Task:** 3 trials. Total evaluated attempts per arm: 78.
- **Overall Acceptance Rate:**
  - Baseline: 75 / 78 (**96.15%**)
  - Improved: 78 / 78 (**100.00%**)
  - Delta: **+3.85 percentage points** (reconciles with reported claims).
- **First-Pass Pass Rate:**
  - Baseline: 65 / 78 (**83.33%**)
  - Improved: 71 / 78 (**91.03%**)
  - Delta: **+7.70 percentage points** (+6 attempts accepted without repair).
- **Repairs:**
  - Baseline attempted 13 repairs and 10 succeeded (3 failed across UI-02 trials).
  - Improved attempted 7 repairs and all 7 succeeded (100.0% repair acceptance).
- **Difficult Negative Tasks (`NEG-01` to `NEG-04`):**
  - Baseline required 6 repair calls due to first-attempt hallucinations.
  - Improved required **0 repair calls** (12/12 first-pass clean abstentions).
- **Final Failures:**
  - Baseline failed 3 attempts (all 3 trials of `UI-02` by retrieving `CropAssessmentView.tsx` instead of `TopBar.tsx`).
  - Improved had **0 failures**.
- **Paired Trial-Level Comparison (N = 78 pairs):**
  - **Improved Wins:** **9 attempts** (`UI-02` trials 1–3, `NEG-01` trials 2–3, `NEG-03` trial 2, `NEG-04` trials 1–3).
  - **Baseline Wins:** **3 attempts** (all 3 trials of `REFACTOR-01` on first pass, where Improved required 1 repair call per trial to catch the internal reference `areaHa: calculateGeodesicAreaHa`).
  - **Ties:** **66 attempts**.
- **Token Usage:**
  - Baseline: 255,968 prompt + 71,682 completion = 327,650 total tokens.
  - Improved: 253,527 prompt + 49,292 completion = 302,819 total tokens (-7.58% total, -31.23% completion).
- **Non-Independence Notice:**
  > [!NOTE]
  > Repeated trials over the same 26 tasks measure model output stability and stochastic variance under identical prompts; they do **not** constitute independent new tasks. The acceptance rate difference is **+3.85 percentage points**. Broad architectural generalization across unobserved codebases cannot be inferred from this suite alone.

---

### E. Resource Measurements and Billing Reconciliation
- **Chunks (924 vs. 642):** Verified by source inspection of `tree_sitter_ast.py` export unwrapping.
- **Cold Indexing Time (57.9s vs. 37.6s):** Qualified. In addition to fewer chunks, Improved used bulk initial upsert (`store.upsert_documents`) rather than file-by-file commits.
- **Peak RSS (3,803.5 MB vs. 1,542.9 MB):** Qualified. Measured process-wide via `getrusage()`; note that RSS measures resident memory (working set pages in physical RAM), not the full virtual memory footprint. It reflects process execution including Python runtime, FastEmbed ONNX sessions, and garbage collection timing.
- **Warm Retrieval Latency (32.26 ms vs. 23.32 ms):** Verified from attempt records. Smaller chunk scans and query embedding caching account for the latency reduction.
- **Billing Reconciliation:**
  - Baseline Client Calculated: $0.081402 vs. Gateway Reported: $0.234560 (Delta: +$0.153158).
  - Improved Client Calculated: $0.067602 vs. Gateway Reported: $0.186865 (Delta: +$0.119263).
  - *Status:* **UNRESOLVED / UNRECONCILED.** LiteLLM gateway reported spend exceeds token formula calculations; server `/key/info` exports lacked per-transaction itemized breakdowns (`total_tokens: null`). Exact dollar costs remain unverified.

---

# PART 2: LIMITED-PILOT RELEASE CHECKLIST

Every item is evaluated distinguishing executed checks from source inspection:

### 1. Installation and Packaging
- **Verdict:** **PASS (Qualified for Offline Operation)**
- **Evidence (Source Inspection):** `pyproject.toml` specifies minimum dependency versions (`lancedb>=0.40.0`, `pylance>=0.40.0`, `fastembed>=0.9.0`, `mcp>=1.0.0`, `watchdog>=4.0.0`, `tree-sitter>=0.23.0`), not pinned exact versions. Builds cleanly via `hatchling`.
- **Consequence:** `fastembed` downloads `BAAI/bge-small-en-v1.5` ONNX weights from HuggingFace on first run. Air-gapped environments must pre-cache model weights.

### 2. Index Correctness
- **Verdict:** **PASS**
- **Evidence (Source Inspection & Executed CLI Check):** 
  - Complete scalar scan (`_scan_scalar`) removes the previous 10,000-chunk limit.
  - Path normalization enforced across `indexer.py`, `watcher.py`, and CLI `cli.py` (`as_posix()`). Executed Remote Check 2 confirmed zero absolute path leakage in LanceDB.
  - Watcher maintains SHA-256 hash manifest (`watcher-<hash>.json`) and cleans offline deletions.
- **Consequence:** Stale chunks do not survive file deletions or modifications.

### 3. Context Correctness
- **Verdict:** **PASS**
- **Evidence (Executed in Benchmark & Source Inspection):** The first 40 lines provide an import window for top-of-file declarations (though not a complete import guarantee for arbitrary files with imports deeper in the file); missing-target diagnostics output warning inventory on negative queries (verified by 12/12 abstentions); secret masking applied to assembled context.
- **Consequence:** Bounded context prevents phantom edits on non-existent targets.

### 4. Sensitive Information and Access
- **Verdict:** **PASS (Local Stdio Only)**
- **Evidence (Source Inspection & Executed Logs):** Two-layer masking (`store.py` and `task_context.py`); `is_sensitive_file` blocks credentials; traversal checks reject escaping paths. Verified that 0 secrets leaked into prompt logs.
- **Consequence:** Safe for local stdio MCP. Network exposure (HTTP/SSE) is not supported without external authentication.

### 5. Write Behavior & Read-Only Enforcement
- **Verdict:** **PASS (Hardened and Executed via Remote Check 1 on Candidate `9ca5287`)**
- **Source Inspection Evidence on Commit `2ce529e`:**
  - `mesh_write_file` was unconditionally registered as an MCP tool (`server.py:136`).
  - `GitBranchGuard` only blocked writes on `main`/`master`. On feature branches, `mesh_write_file` executed disk modifications.
  - No read-only environment variable existed in `config.py` or `server.py`.
- **Hardened Source Code Changes in Commit `9ca5287`:**
  - Added `READ_ONLY_MODE` to `config.py`.
  - Added fail-closed guard to `mesh_write_file` in `server.py`, returning explicit `PermissionDenied: PolyFabric is operating in read-only mode (POLYFABRIC_READ_ONLY=1). File modifications are disabled.`
  - Added unit test in `tests/test_plan_regressions.py`.
- **Executed Remote Check 1 Evidence:**
  - Real MCP stdio server subprocess spawned with `POLYFABRIC_READ_ONLY=1`.
  - Feature branch overwrite attempt rejected with `PermissionDenied`. Target file verified byte-for-byte unchanged via SHA-256.
  - New-file creation attempt rejected and verified zero file creation on disk.
  - Read operation (`mesh_read_file`) succeeded cleanly.
- **Consequence:** Fail-closed read-only behavior verified end-to-end through live MCP stdio protocol.

### 6. Reliability and Recovery
- **Verdict:** **PASS**
- **Evidence (Source Inspection):** Index errors captured in `index_errors` array; complete index rebuilt from source in seconds by clearing `.memory_db`.
- **Consequence:** Corrupt indexes can be reconstructed cleanly.

### 7. Operational Visibility
- **Verdict:** **PASS**
- **Evidence (Source Inspection & Executed Logs):** `index_repository()` returns detailed metrics (file counts, chunk counts, latency, disk size, errors); `build_task_context()` returns elapsed milliseconds and missing targets.
- **Consequence:** Operational telemetry is inspectable without printing sensitive data.

### 8. Evidence Beyond FarmWatch
- **Verdict:** **QUALIFIED / UNVERIFIED FOR CODING TASKS**
- **Evidence:** 4-repository retrieval benchmarks exist (48k chunks across Express, FastAPI, Flask, TypeScript), but full coding agent execution (code edits, build, browser checks) has only been evaluated on FarmWatch.
- **Consequence:** Pilot deployment must be restricted to single-repository, developer-reviewed tasks.

### 9. Documentation
- **Verdict:** **PASS (With Required Disclaimers)**
- **Evidence (Source Inspection):** Documentation outlines tool usage and architecture. References to StructZero must remain explicitly labeled as planned future integrations.
- **Consequence:** Prevents user misinterpretation of autonomous capabilities.

### 10. Release and Rollback
- **Verdict:** **PASS**
- **Evidence (Git Provenance):** Candidate commit `9ca5287f717670941330b4202f0fb6ba606f797e` is cleanly tracked; rollback target is pinned to `eda7e0ea18c460947fcc1ad6bdc70f400e1d9e7d`.
- **Consequence:** Instant rollback via Git checkout without database migration locks.

---

# PART 3: EXECUTED TARGETED REMOTE CHECKS FOR CANDIDATE `9ca5287`

To independently verify the hardened candidate commit [`9ca5287f717670941330b4202f0fb6ba606f797e`](file:///C:/AI/Polyfabric) **without launching another full benchmark or deploying**, three targeted checks were executed exclusively in the remote container sandbox (`sbx_001m4haazrz2qc70t771bmyeqs0`).

```
+---------------------------------------------------------------------------------------------------------+
|                                  TARGETED REMOTE VERIFICATION SCORECARD                                 |
+---------------------------------------------------------------------------------------------------------+
| [PASS] Remote Check 1: Actual MCP Write Rejection with Byte-for-Byte Unchanged File Contents (6.134s)  |
| [PASS] Remote Check 2: CLI Relative-Path Indexing in LanceDB (2.489s)                                   |
| [NOT REQUIRED] Remote Check 3: Offline Initialization Test (0.206s - Local Cache Verified)             |
+---------------------------------------------------------------------------------------------------------+
| OVERALL STATUS: ALL REQUIRED PILOT CHECKS PASSED — VERDICT: READY FOR A MONITORED READ-ONLY PILOT      |
+---------------------------------------------------------------------------------------------------------+
```

### Execution Provenance & Environment
- **Target Repository:** `/home/agent/workspace/PolyFabric`
- **Candidate Commit SHA:** `9ca5287f717670941330b4202f0fb6ba606f797e`
- **Candidate Branch:** `candidate_branch` (tracked on `experiment/frontier-model-optimizations`)
- **Working-Tree Status:** Clean (historical benchmark artifacts and briefings preserved untracked)
- **Execution Container:** `sbx_001m4haazrz2qc70t771bmyeqs0` (Linux 6.12.103 x86_64 GNU/Linux)
- **Python Runtime:** Python 3.14.4 (`/tmp/venv/bin/python`)
- **Execution Window:** `2026-10-16T00:33:39Z` to `2026-10-16T00:33:48Z` (Elapsed: 8.835s)
- **Evidence Artifact Directory:** `benchmarks/results/PILOT_VERIFICATION_9CA5287/`
  - `verification_summary.json` (SHA-256 structured assertion record)
  - `execution_log.txt` (Complete stdout/stderr transcript)

### Verification Script Integrity Hashes (SHA-256)
- `check_1_mcp_readonly.py`: `98a3e3615555a5dd933ccab0f0b35587a7bb92165b81233df47d4de16cd8fed4`
- `check_2_cli_relative_paths.py`: `c87993354cbebcfc1436520359c854d481415ca8d88e6b725f485e2cbe48408f`
- `check_3_offline_startup.py`: `c4560ef7e3defb6133e3902898bf1c9f2101819ed28a3b8dba81fde11490211f`
- `run_pilot_checks.py`: `107a1a40ad4dbdbb248c97da8614ada74858416d64eb137eb6bf6e71bc4a57fb`

---

### Remote Check 1: Actual MCP Write Rejection with Unchanged File Contents
- **Status:** **PASS** (Duration: 6.134s)
- **Command Executed:** `/tmp/venv/bin/python benchmarks/verify_candidate_9ca5287/check_1_mcp_readonly.py`
- **Environment:**
  - `POLYFABRIC_ENABLE_SERVER=1`
  - `POLYFABRIC_READ_ONLY=1`
  - `INFINITE_MEMORY_HOME=/tmp/polyfabric_check1_sandbox/home`
  - `INFINITE_MEMORY_DB_PATH=/tmp/polyfabric_check1_sandbox/db`
  - `PYTHONPATH=/home/agent/workspace/PolyFabric/src`
- **Execution Protocol:**
  1. Initialized a disposable Git repository at `/tmp/polyfabric_check1_sandbox/feature_repo` and switched to branch `feature/audit-branch` (ensuring the `main`/`master` GitBranchGuard cannot explain write rejection).
  2. Created an existing file `sentinel.txt` with known bytes; recorded pre-execution SHA-256 hash `60db5012d34d9801676485f31f83a8dd3b6ec9a14d3f9a325f3444a26db71977`.
  3. Pre-registered the repository in isolated `registry.json`.
  4. Spawned the real FastMCP stdio server in a fresh subprocess and connected via `mcp.ClientSession`.
  5. Verified tool registration (`mesh_write_file`, `mesh_read_file` present).
  6. Called `mesh_write_file("pilot-test-proj", "sentinel.txt", "MALICIOUS_OVERWRITE_PAYLOAD_TEST")`.
  7. Called `mesh_write_file("pilot-test-proj", "unauthorized_created_file.txt", "MALICIOUS_NEW_FILE_CREATION_TEST")`.
  8. Called `mesh_read_file("pilot-test-proj", "sentinel.txt")`.
- **Assertions & Outcomes:**
  | Assertion | Expected | Actual | Outcome |
  | :--- | :--- | :--- | :---: |
  | Git Branch Isolation | `feature/audit-branch` | `feature/audit-branch` | **PASS** |
  | Overwrite Rejection | `PermissionDenied: PolyFabric is operating in read-only mode` | `PermissionDenied: PolyFabric is operating in read-only mode (POLYFABRIC_READ_ONLY=1). File modifications are disabled.` | **PASS** |
  | Byte-for-Byte File Immutability | SHA-256 `60db5012d34d9801...` | SHA-256 `60db5012d34d9801...` | **PASS** |
  | New File Creation Rejection | `PermissionDenied: PolyFabric is operating in read-only mode` | `PermissionDenied: PolyFabric is operating in read-only mode (POLYFABRIC_READ_ONLY=1). File modifications are disabled.` | **PASS** |
  | Disk Non-Creation | File does not exist | File does not exist | **PASS** |
  | Read Operation Success | Unmutated content | `IMMUTABLE_PRE_TEST_SENTINEL_STATE_987654321` | **PASS** |
- **Cleanup:** Temporary test sandbox `/tmp/polyfabric_check1_sandbox` completely purged.

---

### Remote Check 2: CLI Relative-Path Indexing in LanceDB
- **Status:** **PASS** (Duration: 2.489s)
- **Command Executed:** `/tmp/venv/bin/python -m infinite_memory.cli register cli-relative-test-proj /tmp/polyfabric_check2_sandbox/fixture_project`
- **Environment:**
  - `INFINITE_MEMORY_HOME=/tmp/polyfabric_check2_sandbox/home`
  - `INFINITE_MEMORY_DB_PATH=/tmp/polyfabric_check2_sandbox/db`
  - `PYTHONPATH=/home/agent/workspace/PolyFabric/src`
- **Execution Protocol:**
  1. Created isolated directories and temporary fixture project with exactly:
     - `src/main.ts` (exporting function `bootstrap`)
     - `src/types.ts` (exporting interface `Config`)
  2. Invoked the real `memory-mesh register` CLI with supported positional arguments (`name`, `path`).
  3. Connected directly to the LanceDB database at `/tmp/polyfabric_check2_sandbox/db` and inspected the `documents` table via pandas DataFrame.
  4. Verified all stored `file_path` values for the registered project.
  5. Verified `VectorStore.get_indexed_files_for_project("cli-relative-test-proj")`.
- **Assertions & Outcomes:**
  | Assertion | Expected | Actual | Outcome |
  | :--- | :--- | :--- | :---: |
  | CLI Exit Code | `0` | `0` | **PASS** |
  | Indexed File Count | 2 files | 2 files (3 structural AST chunks) | **PASS** |
  | Exact Path Storage | `['src/main.ts', 'src/types.ts']` | `['src/main.ts', 'src/types.ts']` | **PASS** |
  | Absolute Path Leakage | Zero leading `/` | 0 leading `/` found | **PASS** |
  | Backslash / Windows Leakage | Zero `\` and zero `:` | Zero `\` and zero `:` found | **PASS** |
  | Store API Parity | `['src/main.ts', 'src/types.ts']` | `['src/main.ts', 'src/types.ts']` | **PASS** |
- **Cleanup:** Temporary test sandbox `/tmp/polyfabric_check2_sandbox` completely purged.

---

### Remote Check 3: Offline Startup & Embedding Operation
- **Status:** **NOT REQUIRED** (Duration: 0.206s - Local Cache Verified)
- **Command Executed:** `/tmp/venv/bin/python benchmarks/verify_candidate_9ca5287/check_3_offline_startup.py`
- **Pilot Requirement Assessment:**
  - The monitored pilot is defined for developer-guided engineering in connected developer environments. Air-gapped offline operation is **NOT REQUIRED** for this pilot phase.
- **Empirical Execution Details:**
  - Local cached FastEmbed weights verified present at `/tmp/fastembed_cache/models--Qdrant--bge-small-en-v1.5-onnx-Q`.
  - Exported `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
  - Intercepted outbound `socket.socket` creation to guarantee zero network egress.
  - Initialized `VectorStore(db_path=...)` and executed `_embed_query("verify offline neural mesh startup and embedding")`.
  - **Results:** Completed in **205.69 ms**; vector dimension: **384**; outbound socket connections attempted: **0**.
  - *Limitation Note:* True OS-level network namespace isolation (`unshare -n` / iptables) was unavailable due to unprivileged container permissions; however, Python socket interception verified zero network calls were made.
- **Cleanup:** Temporary test database `/tmp/polyfabric_check3_db` completely purged.

---

## Finite Next-Step Plan

1. **Candidate Freeze:** Candidate is frozen at commit [`9ca5287f717670941330b4202f0fb6ba606f797e`](file:///C:/AI/Polyfabric) on branch `experiment/frontier-model-optimizations`.
2. **Benchmark Preservation:** The completed head-to-head benchmark (`RUN_HEAD_TO_HEAD_BASELINE_VS_IMPROVED`) on commit `2ce529e` is fully preserved. Zero full benchmark reruns are required.
3. **No Deployment, Merging, or Tagging:** No code has been merged to `main`, pushed to `origin`, tagged, or deployed.
4. **Monitored Pilot Activation Ready:** All mandatory pre-release gates (fail-closed read-only MCP stdio enforcement and LanceDB relative path normalization) are empirically verified and closed.

---

# FINAL AUDIT SUMMARY

1. **What is Verified:**  
   - Head-to-head empirical benchmark preserved in full: 100.00% acceptance (78/78), 91.03% first-pass pass rate, 0 negative hallucinations, 100% evidence recall, and -7.58% total tokens consumed.
   - Targeted Remote Check 1 passed: live MCP stdio server enforces fail-closed read-only protection (`POLYFABRIC_READ_ONLY=1`) on feature branches with byte-for-byte SHA-256 immutability.
   - Targeted Remote Check 2 passed: CLI `memory-mesh register` indexes strictly relative POSIX paths (`src/main.ts`, `src/types.ts`) with zero absolute or platform-specific path leakage into LanceDB.
2. **What Remains Unknown:**  
   - Full coding tasks on multi-repository corpora beyond FarmWatch remain unbenchmarked; LiteLLM gateway spend has an unresolved markup delta (+$0.119).
3. **Whether to Freeze:**  
   - **Freeze commit `9ca5287f717670941330b4202f0fb6ba606f797e`** as Release Candidate `v0.2.0-rc1`.
4. **Whether Additional Testing is Necessary:**  
   - **NO additional benchmark reruns or code changes are necessary.** Candidate `9ca5287` is certified ready for the monitored pilot.
5. **Path to the Completed Markdown Report:**  
   [`C:\AI\Argon\POLYFABRIC_RELEASE_READINESS_REPORT.md`](file:///C:/AI/Argon/POLYFABRIC_RELEASE_READINESS_REPORT.md)

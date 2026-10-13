# Bounded Coding Task Evaluation: PolyFabric vs. Targeted Search (`rg`) vs. Whole-File Context

- **Run ID:** `RUN_20261013_FARMWATCH_BOUNDED_EVAL`
- **Target Repository:** [`vishalvermauts/FarmWatch`](https://github.com/vishalvermauts/FarmWatch) (Commit: `201321eb045f9b5170007fc26def90e4d13bf564`)
- **Execution Environment:** Isolated Cloud Sandbox (`sbx_001m4haazrz2qc70t771bmyeqs0`, Debian 13 Linux, Node.js `v22.22.1`, Vite `8.3.4`, ripgrep `14.1.1`, Python `3.14.4`)
- **Coding Model:** `gemini-2.5-flash` via LiteLLM Gateway (`temperature=0.0`, `max_tokens=8192`, repair budget = `1` retry per failed attempt)
- **Protocol Status:** Frozen implementation (`infinite-memory-protocol` AST + LanceDB hybrid vector/FTS index, zero tuning during evaluation)
- **Trial Design:** 20 tasks across 5 categories (4 tasks/category) $\times$ 3 approaches $\times$ 3 randomized trials = **180 evaluated attempts** (225 total gateway model calls including repairs).

---

## 1. Executive Summary & Overall Comparison

Previous evaluations compared PolyFabric retrieval exclusively against a naive whole-file context baseline across 5 simple single-file tasks. To establish a realistic engineering boundary, this evaluation introduces a strong **Targeted Search (`rg` + file listing + selective line reads)** competitor across 20 tasks spanning UI, Logic, Multi-Caller Refactoring, Full-Stack Dependency Tracing, and Difficult/Negative Abstention cases. Every edit was verified on a clean git worktree against file-coverage assertions, negative-diff checks, `npm run build` (Vite + TypeScript bundle compilation), and headless Playwright screenshots (`1280x800` and `375x667`) for UI tasks.

### Table 1: Overall Performance Across All 20 Tasks (60 Attempts per Approach)

| Metric | Approach A: `polyfabric_retrieval` | Approach B: `targeted_search` (`rg` + slices) | Approach C: `whole_file_context` |
| :--- | :---: | :---: | :---: |
| **Accepted Tasks (Trial 1, $N=20$)** | **14 / 20 (70.0%)** | **17 / 20 (85.0%)** | **18 / 20 (90.0%)** |
| **First-Attempt Accepted (Trial 1)** | 13 / 20 (65.0%) | **17 / 20 (85.0%)** | 15 / 20 (75.0%) |
| **Post-Repair Accepted (Trial 1)** | 1 / 20 (+5.0%) | 0 / 20 (0.0%) | 3 / 20 (+15.0%) |
| **Accepted Attempts (All 3 Trials, $N=60$)** | 44 / 60 (73.33%) | **52 / 60 (86.67%)** | 51 / 60 (85.00%) |
| **Mean File-Level Evidence Recall** | 93.50% | 98.33% | **100.00%** |
| **Prompt Tokens (Median / Attempt)** | 7,075.0 | **3,789.5** | 97,309.0 |
| **Prompt Tokens (Mean $\pm$ SD)** | $6,719.7 \pm 2,366.2$ | $5,310.1 \pm 4,026.2$ | $110,389.2 \pm 33,592.2$ |
| **Total Prompt Tokens (Trial 1 / All 3 Trials)** | 129,700 / 403,182 | **98,923 / 318,606** | 2,241,212 / 6,623,351 |
| **Token Reduction vs. Whole-File (Median)** | **-92.73%** | **-96.11%** | Baseline (0.0%) |
| **Completion Tokens (Median / Total 3 Trials)** | 338.0 / 64,080 | 339.0 / 33,252 | **335.0** / 69,923 |
| **Retrieval Latency — Cold / Warm Median** | 195.88 ms / 184.69 ms | 28.98 ms / 24.26 ms | **1.40 ms / 1.19 ms** |
| **Total Wall Time (Median / IQR)** | 5,653.21 ms (IQR: 11,116.5 ms) | **4,605.90 ms (IQR: 3,779.7 ms)** | 7,575.32 ms (IQR: 9,870.9 ms) |
| **Total Tool Calls (Trial 1)** | **179** | 180 | 440 |
| **Total Model Calls (All 3 Trials)** | 80 | **70** | 75 |
| **Total Gateway Cost (Trial 1 / All 3 Trials)** | \$0.029684 / \$0.098921 | **\$0.021334 / \$0.067743** | \$0.351269 / \$1.035457 |
| **Cost per Accepted Task (Trial 1)** | \$0.002120 (**-89.1% vs. C**) | **\$0.001255 (-93.6% vs. C)** | \$0.019515 |
| **Cost per Accepted Attempt (All Trials)** | \$0.002248 | **\$0.001303** | \$0.020303 |
| **False Abstentions (Positive Tasks)** | 3 / 48 | **0 / 48** | **0 / 48** |
| **False-Positive Edits (Negative Tasks)** | **0 / 12** | **0 / 12** | 3 / 12 (Failed `NEG-03`) |
| **Unrelated Files Modified** | **0** | **0** | 6 |

---

## 2. Category-Level Breakdown

### Table 2: Accepted Tasks and Attempts by Category

| Category (4 Tasks / 12 Trials per Category) | `polyfabric_retrieval` (Trial 1 / All Trials) | `targeted_search` (`rg`) (Trial 1 / All Trials) | `whole_file_context` (Trial 1 / All Trials) | Category Winner & Technical Takeaway |
| :--- | :---: | :---: | :---: | :--- |
| **1. UI** (`UI-01`..`UI-04`) | **4/4** (12/12, **100%**) | 3/4 (9/12, 75.0%) | **4/4** (12/12, **100%**) | **`polyfabric_retrieval` wins on quality + cost.** PolyFabric found all 3 files in `UI-01` (`i18n.ts`, `index.html`, `metadata.json`) where `rg --fixed-strings` missed multiline `en.brand`. |
| **2. Logic** (`LOGIC-01`..`LOGIC-04`) | **4/4** (12/12, **100%**) | **4/4** (12/12, **100%**) | **4/4** (12/12, **100%**) | **Tie (`polyfabric_retrieval` & `targeted_search`).** Both achieved 100% first-attempt accuracy at 92%–97% lower token cost and 35%–45% lower latency than `whole_file_context`. |
| **3. Refactoring** (`REFACTOR-01`..`REFACTOR-04`) | 0/4 (2/12, 16.7%) | **2/4 (7/12, 58.3%)** | **3/4** (6/12, 50.0%) | **`targeted_search` & `whole_file_context` win.** PolyFabric's bounded chunk windows missed top-of-file `import` lines (`REFACTOR-02`) and 3rd/4th call sites in 1,350-line files (`REFACTOR-01`). |
| **4. Dependency Tracing** (`DEP-01`..`DEP-04`) | 2/4 (6/12, 50.0%) | **4/4 (12/12, 100%)** | **4/4** (12/12, **100%**) | **`targeted_search` wins.** Exact URL string matching (`rg -n '/api/geo/geocode'`) deterministically located both Express route definitions and frontend `fetch()` callers. |
| **5. Difficult / Negative** (`NEG-01`..`NEG-04`) | **4/4** (12/12, **100%**) | **4/4** (12/12, **100%**) | 3/4 (9/12, 75.0%) | **`targeted_search` & `polyfabric_retrieval` win.** Both abstained cleanly on all 4 negative tasks; `whole_file_context` hallucinated a speculative edit on `NEG-03` (`194k` tokens). |

---

## 3. Where PolyFabric Helped vs. Where Targeted Search Matched or Beat It

### Where PolyFabric Helped
1. **92.7% Prompt Token Savings & 89.1% Cost Reduction over Whole-File Context with 100% Quality on Localized UI & Logic Edits:**
   - On all 8 UI and Logic tasks (`UI-01`..`UI-04`, `LOGIC-01`..`LOGIC-04`), `polyfabric_retrieval` achieved **24 / 24 (100%)** accepted attempts on the first try using a median of **6,542 prompt tokens** (`~$0.00118`/task) vs. **97,309 prompt tokens** (`~$0.01480`/task) for `whole_file_context`.
2. **Semantic + FTS Resilience on Cross-Format Branding (`UI-01`) where Literal `rg` Missed:**
   - In `UI-01`, the instruction referenced `en.brand: 'FarmWatch'`. Because `src/utils/i18n.ts` formats this across nested lines (`en: {\n  brand: 'FarmWatch'`), autonomous `rg --fixed-strings` failed to match `en.brand: 'FarmWatch'` (`recall = 0.6667`, missing `i18n.ts`), whereas PolyFabric's hybrid semantic + FTS query retrieved `src/utils/i18n.ts`, `index.html`, and `metadata.json` (`recall = 1.0`, **3/3 trials accepted**).
3. **Preventing Context-Induced Hallucination on Ambiguous Prompts (`NEG-03`):**
   - When given an intentionally underspecified instruction (*"Change the threshold from 15 to 25 in the component"*), `whole_file_context` failed all 3 trials (`0/3`, burning `194,679` tokens and `$0.03588` per attempt) because having all 20 source files in context tempted the model into guessing and editing an arbitrary threshold. Both `polyfabric_retrieval` (`3/3` accepted) and `targeted_search` (`3/3` accepted) abstained safely.

### Where Targeted Search (`rg` + Selective Reads) Matched or Beat PolyFabric
1. **Multi-Call-Site Symbol Renames (`REFACTOR-01`, `REFACTOR-02`):**
   - `targeted_search` achieved **3/3 first-attempt successes** on `REFACTOR-01` (`3,088` prompt tokens, `$0.00099`) and **2/3 successes** on `REFACTOR-02` (`1,939` prompt tokens, `$0.00059`), whereas `polyfabric_retrieval` scored `0/3` on both. Exhaustive lexical search (`rg -n`) returns every single line number where an identifier occurs (both top-of-file `import` statements and multiple call sites across a 1,350-line component), whereas top-$k$ chunk retrieval drops secondary call sites and file headers.
2. **Cross-Stack Literal Route Tracing (`DEP-01`, `DEP-02`):**
   - When migrating `/api/geo/geocode` (`DEP-01`) and `/api/satellite/simulate-observations` (`DEP-02`) across `server.ts` and React components, `targeted_search` achieved **6/6 first-attempt successes** (`8,360–9,178` tokens) compared to `0/6` for `polyfabric_retrieval`.
3. **Lower Retrieval Latency and Zero-Match Negative Prompt Overhead (`NEG-01`..`NEG-04`):**
   - `targeted_search` ran in a median of **28.98 ms (cold) / 24.26 ms (warm)** with zero index build overhead, compared to **195.88 ms (cold) / 184.69 ms (warm)** for `polyfabric_retrieval` (which embeds the query via ONNX `BAAI/bge-small-en-v1.5` and executes LanceDB vector + FTS queries).
   - On negative tasks where a symbol did not exist (`NEG-01`, `NEG-02`, `NEG-04`), `rg` returned zero matches and sent only the compact repository file list (**532–544 prompt tokens**, `$0.00017`), whereas `polyfabric_retrieval` still injected its top-$k$ nearest-neighbor chunks (**5,441–7,142 prompt tokens**, `$0.00120`).

---

## 4. Concrete Failure Examples & Root-Cause Analysis

1. **Failure Case 1 — Omitted Top-of-File Import Statements During Chunk Slicing (`REFACTOR-02`, `DEP-02`):**
   - **Observed Behavior:** In `REFACTOR-02` (`sortPolygonClockwise` $\rightarrow$ `orderPolygonClockwise`), `polyfabric_retrieval` achieved `1.0` file-level recall (`src/utils/geo.ts` and `src/components/FieldGisView.tsx` were both discovered). It correctly renamed `export function orderPolygonClockwise` in `geo.ts` and updated `const sorted = orderPolygonClockwise(drawnCoords);` at line 545 of `FieldGisView.tsx`. However, `npm run build` failed because line 9 of `FieldGisView.tsx` (`import { ..., sortPolygonClockwise } from '../utils/geo'`) was not updated.
   - **Root Cause:** For files $>90$ lines, `polyfabric_retrieval` extracted $\pm 15$-line windows around retrieved AST chunks (lines `530–560` of `FieldGisView.tsx`) without including lines `1–20` where ES module imports reside.
2. **Failure Case 2 — Incomplete Call-Site Coverage Under Fixed `top_k` (`REFACTOR-01`, `REFACTOR-04`):**
   - **Observed Behavior:** In `REFACTOR-01`, `calculateGeodesicAreaHa` is called 4 times in `FieldGisView.tsx` (lines 5, 243, 620, 640). `polyfabric_retrieval` updated the declaration in `geo.ts` and the first call site in `FieldGisView.tsx`, but missed lines 620 and 640 (`verification_logs/REFACTOR-01_polyfabric_retrieval.log`). In `REFACTOR-04` (`formatDate` across 5 files), `polyfabric_retrieval` only retrieved `src/utils/i18n.ts` (`recall = 0.2`), missing the 4 UI components that import `formatDate`.
   - **Root Cause:** `search_exact_symbol` indexes symbol definitions (`symbol_name` column on AST function/class nodes), not cross-file identifier references, and `search_fts(..., top_k=5)` is capped at 5 chunks globally.
3. **Failure Case 3 — Multi-Project Index Contamination if `project` Filter is Omitted:**
   - **Observed Behavior:** During pre-run inspection of `/home/agent/.unified_memory/vector_db`, we observed that when multiple worktrees (`farmwatch-1` and `farmwatch-2`) are indexed into the shared LanceDB table (`1,568` total chunks = `784` per worktree) alongside lockfiles (`bun.lock`), unscoped vector queries return duplicate chunks from sibling worktrees and noisy lockfile fragments unless explicitly filtered by `project="farmwatch-1"`.

---

## 5. Indexing, Refresh & Memory Overhead

Unlike `targeted_search` (`rg`), which operates directly on the working tree with zero precomputation, `polyfabric_retrieval` requires maintaining a local LanceDB + Tantivy FTS + ONNX embedding index:

| Operational Metric | Measured Value (`sbx_001m4haazrz2qc70t771bmyeqs0`) |
| :--- | :--- |
| **Initial Cold Indexing Time (`784` chunks, `FarmWatch`)** | `2,140.00 ms` (`2.14 s`) |
| **Incremental No-Op Check (`get_indexed_files_for_project`)** | `26.02 ms` |
| **Incremental Single-File Re-Index (`src/utils/geo.ts` AST + ONNX + LanceDB upsert)** | `2,426.86 ms` (`2.43 s`) |
| **Vector + FTS Index Disk Size (`~/.unified_memory/vector_db`)** | `4.23 MB` (`4,432,561 bytes`) |
| **Peak Process RSS Memory (Python + ONNX Runtime + LanceDB + Playwright)** | `1,119.99 MB` |

---

## 6. Per-Task Acceptance Matrix (Trial 1 + All 3 Trials)

| Task ID | Category | Target Files | `polyfabric_retrieval` (T1 / 3 Trials) | `targeted_search` (T1 / 3 Trials) | `whole_file_context` (T1 / 3 Trials) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **`UI-01`** | UI (Branding) | `i18n.ts`, `index.html`, `metadata.json` | PASS (3/3) | FAIL (0/3) | PASS (3/3) |
| **`UI-02`** | UI (Font Size) | `src/components/TopBar.tsx` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`UI-03`** | UI (Responsive Spacing) | `src/components/DashboardView.tsx` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`UI-04`** | UI (Shared Styles) | `src/index.css` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`LOGIC-01`** | Logic (Defaults/Bounds) | `src/utils/geo.ts` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`LOGIC-02`** | Logic (Circle Threshold) | `src/utils/geo.ts` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`LOGIC-03`** | Logic (Zoom Clamping) | `src/utils/geo.ts` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`LOGIC-04`** | Logic (Fallback Box) | `src/utils/geo.ts` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`REFACTOR-01`** | Refactoring (All Callers) | `geo.ts`, `FieldGisView.tsx` | FAIL (0/3) | PASS (3/3) | PASS* (1/3) |
| **`REFACTOR-02`** | Refactoring (Exports/Imports) | `geo.ts`, `FieldGisView.tsx` | FAIL (0/3) | PASS (2/3) | PASS* (3/3) |
| **`REFACTOR-03`** | Refactoring (Shared Type) | `farmwatch.ts`, `NewFieldModal.tsx` | FAIL (2/3) | FAIL (2/3) | FAIL (1/3) |
| **`REFACTOR-04`** | Refactoring (5-File Rename) | `i18n.ts` + 4 views | FAIL (0/3) | FAIL (0/3) | PASS* (1/3) |
| **`DEP-01`** | Dependency (`/api/geo/geocode`) | `server.ts`, `NewFieldModal.tsx` | FAIL (0/3) | PASS (3/3) | PASS (3/3) |
| **`DEP-02`** | Dependency (`/api/satellite/...`) | `server.ts`, `src/App.tsx` | FAIL (0/3) | PASS (3/3) | PASS (3/3) |
| **`DEP-03`** | Dependency (`/api/weather`) | `server.ts`, `src/App.tsx` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`DEP-04`** | Dependency (`/api/health`) | `server.ts` | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`NEG-01`** | Negative (Nonexistent Symbol) | *(Abstain Required)* | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`NEG-02`** | Negative (Misspelled File/Sym) | *(Abstain Required)* | PASS (3/3) | PASS (3/3) | PASS (3/3) |
| **`NEG-03`** | Negative (Ambiguous Prompt) | *(Abstain Required)* | PASS* (3/3) | PASS (3/3) | FAIL (0/3) |
| **`NEG-04`** | Negative (Stale/Removed File) | *(Abstain Required)* | PASS (3/3) | PASS (3/3) | PASS (3/3) |

*(Note: `PASS*` indicates Trial 1 succeeded using the 1-step repair budget after initial verification failure.)*

---

## 7. Reproducible Artifact Manifest

All sanitized artifacts for this run are stored in `benchmarks/results/RUN_20261013_FARMWATCH_BOUNDED_EVAL/`:
- [`run_metadata.json`](./run_metadata.json) — Sandbox hardware, software versions, commit hashes, and indexing/memory overhead.
- [`task_manifest.json`](./task_manifest.json) — All 20 task prompts and metadata.
- [`acceptance_criteria/`](./acceptance_criteria/) — Separate deterministic ground-truth file and snippet assertions for `UI-01`..`NEG-04`.
- [`per_attempt_results.jsonl`](./per_attempt_results.jsonl) — Raw line-delimited JSON records for all 180 attempts (3 trials $\times$ 20 tasks $\times$ 3 approaches).
- [`summary.json`](./summary.json) — Aggregated metrics, medians, IQRs, token counts, and gateway costs.
- [`sanitized_gateway_usage.json`](./sanitized_gateway_usage.json) — Sanitized LiteLLM call ledger (`225` calls, `$1.202124` run spend, zero raw keys).
- [`patches/`](./patches/) — Unified git diff patches (`<TASK_ID>_<approach>.patch`) for Trial 1.
- [`verification_logs/`](./verification_logs/) — Build (`npm run build`) and assertion verification logs (`<TASK_ID>_<approach>.log`).
- [`sanitized_prompts_and_responses/`](./sanitized_prompts_and_responses/) — Sanitized model inputs, discovered file lists, and outputs.
- [`screenshots/`](./screenshots/) — Before and after headless Chromium screenshots (`1280x800` and `375x667`) for UI tasks (`UI-01`..`UI-04`).

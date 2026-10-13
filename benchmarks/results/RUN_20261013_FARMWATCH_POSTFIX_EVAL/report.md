# Post-Fix Bounded Evaluation & Generalization Report: PolyFabric on FarmWatch

- **Run ID:** `RUN_20261013_FARMWATCH_POSTFIX_EVAL`
- **Baseline Run ID (Pre-Fix):** `RUN_20261013_FARMWATCH_BOUNDED_EVAL`
- **Target Repository:** `https://github.com/vishalvermauts/FarmWatch.git` (clean commit `201321eb045f9b5170007fc26def90e4d13bf564`)
- **Cloud Sandbox:** `sbx_001m4haazrz2qc70t771bmyeqs0` (Linux Debian 13, Node `v22.22.1`, Python `3.13.5`, `ripgrep 14.1.1`)
- **Model & Gateway:** `gemini-2.5-flash` via LiteLLM (`temperature=0.0`, `max_tokens=8192`, `repair_budget=1`, `trials_per_task=3`)

---

## 1. Root Causes Diagnosed & General Retrieval Fixes Applied

In the initial bounded evaluation (`RUN_20261013_FARMWATCH_BOUNDED_EVAL`), `polyfabric_retrieval` achieved `15 / 20` (`75.0%`) on Trial 1 (`44 / 60` across all 3 trials) because of three specific retrieval defects that affected **Refactoring** (`1 / 4` Trial 1: failed `REFACTOR-01`, `REFACTOR-02`, `REFACTOR-04`) and **Dependency Tracing** (`2 / 4` Trial 1: failed `DEP-01`, `DEP-02`):

1. **Declaration-Only Exact Symbol Lookup (`VectorStore.search_exact_symbol` in `src/infinite_memory/core/store.py`):**
   - *Defect:* `search_exact_symbol(sym)` previously executed `WHERE symbol_name = '<sym>'`, returning only the AST declaration chunk (e.g., `src/utils/geo.ts` for `calculatePolygonStats` or `src/utils/i18n.ts` for `getTranslations`) while omitting every file that imported or called the symbol (`FieldGisView.tsx`, `DashboardView.tsx`, `SoilAndWeatherView.tsx`, `SatelliteTimelineView.tsx`, `ActionHistoryView.tsx`).
   - *General Fix:* Upgraded `search_exact_symbol` to scan deduplicated project chunks (cached in memory per project and invalidated on index upsert), returning AST declaration chunks (`symbol_name == sym`) first, followed by all chunks containing word-bounded occurrences (`\b<sym>\b`) across `text`.

2. **Delimiter Splitting & Dense Fallback Noise on Route/Literal Queries (`VectorStore.search_fts` in `src/infinite_memory/core/store.py`):**
   - *Defect:* Tantivy's default tokenizer split URL paths and hyphenated literals (`/api/geo/geocode`, `/api/satellite/simulate-observations`, `satellite-ndvi-v2`), causing `search_fts` to fall back to dense vector search and rank unrelated mock files above `server.ts`, or match replacement targets in `"Rename X to Y"` prompts.
   - *General Fix:* Upgraded `search_fts` to perform exact and case-insensitive substring containment over deduplicated project chunks before Tantivy FTS, and added `exact_only=True` support so non-existent target names in rename instructions do not trigger noisy dense vector fallbacks.

3. **IDF-Weighted File Ranking & Intra-File Call-Site Pinpointing (`gather_context_polyfabric` in `benchmarks/run_postfix_eval.py`):**
   - *Defect:* Ranking discovered files purely by raw chunk count allowed files with many generic term matches to crowd out backend route handlers (`server.ts`), and slicing only a single `[-15, +15]` window around the first AST chunk in `>90`-line files omitted top-of-file `import` statements or secondary call sites in the same file.
   - *General Fix:* Scored candidate files by Inverse Document Frequency ($\text{IDF}(t) = \frac{2 \ln(1 + |t|)}{\text{df}(t)}$) across extracted search terms plus a $+1.5$ AST declaration bonus, pruned low-specificity tail files (`< 0.15 \times \max\text{Score}` with `< 2` term hits), and merged AST chunk windows with $\pm 12$-line windows around all intra-file occurrences of the search terms.

---

## 2. Frozen 20-Task Evaluation Results (Before Fix vs. After Fix vs. Baselines)

All 20 frozen tasks (`UI-01..04`, `LOGIC-01..04`, `REFACTOR-01..04`, `DEP-01..04`, `NEG-01..04`) were re-evaluated using the exact same acceptance criteria, `npm run build` verification, and 3-trial protocol:

| Metric | `polyfabric_retrieval` (Before Fix) | `polyfabric_retrieval` (After Fix) | `targeted_search` (`rg` + slices) | `whole_file_context` (Full Repo) |
| :--- | :---: | :---: | :---: | :---: |
| **Accepted Tasks (Trial 1)** | 15 / 20 (75.00%) | **20 / 20 (100.00%)** | 17 / 20 (85.00%) | 18 / 20 (90.00%) |
| **First-Attempt Accepted (Trial 1)** | 14 / 20 (70.00%) | **15 / 20 (75.00%)** | 17 / 20 (85.00%) | 15 / 20 (75.00%) |
| **Repaired Accepted (Trial 1)** | 1 / 20 | **5 / 20** | 0 / 20 | 3 / 20 |
| **Accepted Attempts (All 3 Trials)** | 44 / 60 (73.33%) | **58 / 60 (96.67%)** | 52 / 60 (86.67%) | 51 / 60 (85.00%) |
| **Mean Evidence Recall** | 79.17% | **100.00%** | 98.33% | 100.00% |
| **Missed Dependencies (All Trials)** | 34 | **1** | 21 | 4 |
| **Unrelated File Edits (All Trials)** | 0 | **0** | 0 | 6 |
| **False-Positive Edits on Negative** | 0 | **1** | 0 | 3 |
| **Prompt Tokens (Median / Attempt)** | 2,226.5 | **2,401.0** | 3,789.5 | 97,309.0 |
| **Prompt Tokens (Mean ± SD)** | 3,721.6 ± 4,132.1 | **3,759.3 ± 3,314.6** | 5,310.1 ± 4,026.2 | 110,389.2 ± 33,592.2 |
| **Total Prompt Tokens (Trial 1)** | 65,127 | **81,947** | 98,923 | 2,241,212 |
| **Total Prompt Tokens (All 3 Trials)** | 223,296 | **225,560** | 318,606 | 6,623,351 |
| **Completion Tokens (Median)** | 364.0 | **370.0** | 339.0 | 335.0 |
| **Retrieval Latency Cold / Warm (Median)** | 14.70 ms / 12.66 ms | **15.28 ms / 13.73 ms** | 28.98 ms / 24.26 ms | 1.40 ms / 1.19 ms |
| **Total Wall Time (Median ± IQR)** | 4,884.19 ± 2,844.57 ms | **4,659.44 ± 3,274.64 ms** | 4,605.90 ± 3,779.71 ms | 7,575.32 ± 9,870.89 ms |
| **Total Gateway Cost (Trial 1)** | $0.015678 | **$0.022693** | $0.021334 | $0.351269 |
| **Cost per Accepted Task (Trial 1)** | $0.001045 | **$0.001135** | $0.001255 | $0.019515 |
| **Total Gateway Cost (All 3 Trials)** | $0.056893 | **$0.068216** | $0.067743 | $1.035457 |
| **Cost per Accepted Attempt (All Trials)** | $0.001293 | **$0.001176** | $0.001303 | $0.020303 |

### Category Breakdown on Frozen 20-Task Suite (Trial 1 Tasks | All 3 Trials Attempts)

| Category (4 Tasks / 12 Attempts) | `polyfabric_retrieval` (Before Fix) | `polyfabric_retrieval` (After Fix) | `targeted_search` (`rg` + slices) | `whole_file_context` (Full Repo) |
| :--- | :---: | :---: | :---: | :---: |
| **UI** (`UI-01..04`) | 4/4 \| 12/12 (100%) | **4/4 \| 12/12 (100%)** | 3/4 \| 9/12 (75%) | 4/4 \| 12/12 (100%) |
| **Logic** (`LOGIC-01..04`) | 4/4 \| 12/12 (100%) | **4/4 \| 12/12 (100%)** | 4/4 \| 12/12 (100%) | 4/4 \| 12/12 (100%) |
| **Refactoring** (`REFACTOR-01..04`) | 1/4 \| 2/12 (16.7%) | **4/4 \| 11/12 (91.7%)** | 2/4 \| 7/12 (58.3%) | 3/4 \| 6/12 (50.0%) |
| **Dependency Tracing** (`DEP-01..04`) | 2/4 \| 6/12 (50.0%) | **4/4 \| 12/12 (100%)** | 4/4 \| 12/12 (100%) | 4/4 \| 12/12 (100%) |
| **Difficult / Negative** (`NEG-01..04`) | 4/4 \| 12/12 (100%) | **4/4 \| 11/12 (91.7%)** | 4/4 \| 12/12 (100%) | 3/4 \| 9/12 (75.0%) |

---

## 3. Unseen Generalization Suite (`6 Tasks / 18 Attempts per Approach`)

To verify that the retrieval fixes generalize beyond the original 5 failed tasks, we evaluated 6 newly authored, unseen tasks (3 multi-file symbol/type renames and 3 full-stack API endpoint/contract migrations):
- `GEN-REFACTOR-01`: Rename `generatePresetPolygon` $\rightarrow$ `createPresetBoundaryPolygon` across `src/utils/geo.ts` and `src/components/FieldGisView.tsx`.
- `GEN-REFACTOR-02`: Rename `format Area` $\rightarrow$ `formatFieldAreaDisplay` across `src/utils/geo.ts`, `src/components/DashboardView.tsx`, and `src/components/FieldGisView.tsx`.
- `GEN-REFACTOR-03`: Rename `AiAssessmentPayload` $\rightarrow$ `CropHealthAssessmentResult` across `src/types/farmwatch.ts`, `src/utils/mockData.ts`, and `src/components/CropAssessmentView.tsx` (4 call sites across lines 1–169).
- `GEN-DEP-01`: Migrate weather forecast endpoint `/api/weather/forecast` $\rightarrow$ `/api/v2/weather/forecast` across `server.ts` and `src/components/SoilAndWeatherView.tsx`.
- `GEN-DEP-02`: Migrate privacy export endpoint `/api/privacy/export` $\rightarrow$ `/api/v2/privacy/export-archive` and add `exportFormat: 'json-v2'` across `server.ts` and `src/components/PrivacyCenterView.tsx`.
- `GEN-DEP-03`: Migrate AI advisor chat endpoint `/api/ai/chat` $\rightarrow$ `/api/v2/ai/advisor-chat` across `server.ts` and `src/components/CropAssessmentView.tsx`.

| Metric (Unseen Generalization Suite) | `polyfabric_retrieval` (After Fix) | `targeted_search` (`rg` + slices) | `whole_file_context` (Full Repo) |
| :--- | :---: | :---: | :---: |
| **Accepted Tasks (Trial 1)** | **6 / 6 (100.00%)** | 5 / 6 (83.33%) | 6 / 6 (100.00%) |
| **Accepted Attempts (All 3 Trials)** | **17 / 18 (94.44%)** | 17 / 18 (94.44%) | 16 / 18 (88.89%) |
| **Generalization Refactoring (`GEN-REFACTOR-01..03`)** | **3/3 Trial 1 \| 8/9 All Trials** | 3/3 Trial 1 \| 9/9 All Trials | 3/3 Trial 1 \| 7/9 All Trials |
| **Generalization Dependency (`GEN-DEP-01..03`)** | **3/3 Trial 1 \| 9/9 All Trials** | 2/3 Trial 1 \| 8/9 All Trials | 3/3 Trial 1 \| 9/9 All Trials |
| **Mean Evidence Recall** | **100.00%** | 100.00% | 100.00% |
| **Prompt Tokens (Median / Attempt)** | **2,503.0** | 5,960.5 | 97,276.0 |
| **Total Prompt Tokens (Trial 1 / All 3 Trials)** | **19,545 / 54,305** | 45,322 / 118,748 | 682,126 / 2,046,378 |
| **Retrieval Latency Cold / Warm (Median)** | **10.64 ms / 8.79 ms** | 15.66 ms / 16.32 ms | 1.61 ms / 0.91 ms |
| **Total Wall Time (Median ± IQR)** | **5,073.20 ± 3,604.03 ms** | 5,128.32 ± 1,997.22 ms | 8,030.89 ± 4,433.05 ms |
| **Total Gateway Cost (Trial 1 / All 3 Trials)** | **$0.005955 / $0.019149** | $0.010505 / $0.026036 | $0.105516 / $0.320122 |
| **Cost per Accepted Task (Trial 1)** | **$0.000993** | $0.002101 | $0.017586 |

---

## 4. Combined 26-Task Summary (`20 Frozen + 6 Generalization`, 78 Attempts per Approach)

| Metric (Combined 26 Tasks) | `polyfabric_retrieval` (After Fix) | `targeted_search` (`rg` + slices) | `whole_file_context` (Full Repo) |
| :--- | :---: | :---: | :---: |
| **Accepted Tasks (Trial 1)** | **26 / 26 (100.00%)** | 22 / 26 (84.62%) | 24 / 26 (92.31%) |
| **Accepted Attempts (All 3 Trials)** | **75 / 78 (96.15%)** | 69 / 78 (88.46%) | 67 / 78 (85.90%) |
| **Mean Evidence Recall** | **100.00%** | 98.72% | 100.00% |
| **Prompt Tokens (Median / Attempt)** | **2,401.0** | 3,789.5 | 97,305.0 |
| **Total Prompt Tokens (Trial 1 / All 3 Trials)** | **101,492 / 279,865** | 144,245 / 437,354 | 2,923,338 / 8,669,729 |
| **Retrieval Latency Cold / Warm (Median)** | **14.29 ms / 13.55 ms** | 26.73 ms / 18.71 ms | 1.40 ms / 1.18 ms |
| **Total Wall Time (Median)** | **4,904.55 ms** | 4,650.42 ms | 7,901.26 ms |
| **Total Gateway Cost (Trial 1 / All 3 Trials)** | **$0.028648 / $0.087365** | $0.031839 / $0.093779 | $0.456785 / $1.355579 |
| **Cost per Accepted Task (Trial 1)** | **$0.001102** | $0.001447 | $0.019033 |
| **Cost per Accepted Attempt (All 3 Trials)** | **$0.001165** | $0.001359 | $0.020233 |

"""
Comprehensive Offline Retrieval Verification Suite.

Guarantees:
1. Operates completely offline with ZERO paid model calls ($0 spend).
2. Creates an explicit, isolated LanceDB database.
3. Indexes the complete pinned FarmWatch repository and records live telemetry (files, chunks, disk size, RSS, latency).
4. Verifies:
   - Known function definitions and callers are returned (e.g. generatePresetPolygon in geo.ts, NewFieldModal.tsx, FieldGisView.tsx).
   - Imports, backend routes, and frontend fetch calls are returned (e.g. /api/satellite/gee-tiles in server.ts and FieldGisView.tsx).
   - TypeScript, HTML, CSS, and JSON files are searchable.
   - Returned files exist on disk, and code snippets match the source lines exactly.
   - Relocates repository to a new directory and verifies path resolution still succeeds without re-indexing.
5. Saves all verification checks, metrics, and snippets as verifiable artifacts.
"""

import os
import sys
import json
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, List

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.infinite_memory.core.store import VectorStore
from src.infinite_memory.core.indexer import index_repository
from src.infinite_memory.core.task_context import build_task_context
from src.infinite_memory.utils.path_utils import normalize_and_resolve_repo_path


def run_offline_verification(
    repo_path: Path,
    output_dir: Path,
    project_name: str = "farmwatch_verified"
) -> Dict[str, Any]:
    print("=" * 70)
    print("STARTING OFFLINE RETRIEVAL VERIFICATION (ZERO PAID CALLS)")
    print("=" * 70)

    repo_path = repo_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo_path": str(repo_path),
        "checks_passed": 0,
        "checks_total": 0,
        "details": {}
    }

    # 1. Create Isolated Test Database
    isolated_db_dir = output_dir / "isolated_lancedb"
    if isolated_db_dir.exists():
        shutil.rmtree(isolated_db_dir)
    isolated_db_dir.mkdir(parents=True)

    print(f"\n[Step 1] Initializing isolated VectorStore at: {isolated_db_dir}")
    store = VectorStore(db_path=str(isolated_db_dir))

    # 2. Complete Repository Indexing with Live Telemetry
    print(f"[Step 2] Exhaustively indexing pinned FarmWatch repository: {repo_path}")
    t0 = time.perf_counter()
    index_stats = index_repository(
        repo_path=repo_path,
        project_name=project_name,
        store=store,
        sample_file_for_refresh="src/utils/geo.ts"
    )
    indexing_duration = (time.perf_counter() - t0) * 1000.0
    print(f"  Indexed files : {index_stats['indexed_files_count']}")
    print(f"  Indexed chunks: {index_stats['indexed_chunks_project']}")
    print(f"  Disk size     : {index_stats['index_disk_size_mb']} MB")
    print(f"  Peak RSS      : {index_stats['peak_rss_mb']} MB")
    print(f"  Cold index ms : {index_stats['initial_cold_index_ms']} ms")
    print(f"  No-op refresh : {index_stats['incremental_noop_refresh_ms']} ms")
    print(f"  1-file refresh: {index_stats['incremental_single_file_refresh_ms']} ms")

    results["indexing_telemetry"] = index_stats

    # Assert non-trivial indexing
    assert index_stats["indexed_files_count"] >= 20, f"Expected >= 20 files, got {index_stats['indexed_files_count']}"
    assert index_stats["indexed_chunks_project"] >= 200, f"Expected >= 200 chunks, got {index_stats['indexed_chunks_project']}"

    # 3. Check 1: Known Function Definition & Callers (generatePresetPolygon)
    print("\n[Step 3] Checking known function definitions and callers...")
    results["checks_total"] += 1
    chk1_instruction = (
        "Rename generatePresetPolygon to createPresetBoundaryPolygon across utility and all importing components"
    )
    ctx1 = build_task_context(store, chk1_instruction, repo_path, project_name=project_name)
    disc1 = set(ctx1["discovered_files"])
    print(f"  Query: '{chk1_instruction}'")
    print(f"  Discovered files ({len(disc1)}): {sorted(list(disc1))}")

    has_def = "src/utils/geo.ts" in disc1
    has_caller = any(c in disc1 for c in ["src/components/NewFieldModal.tsx", "src/components/FieldGisView.tsx"])
    chk1_passed = has_def and has_caller
    results["details"]["check_1_function_def_and_callers"] = {
        "passed": chk1_passed,
        "has_definition": has_def,
        "has_caller": has_caller,
        "discovered_files": sorted(list(disc1)),
        "path_errors": ctx1.get("path_errors", [])
    }
    if chk1_passed:
        results["checks_passed"] += 1
        print("  ✓ PASS: Found definition in geo.ts and caller components.")
    else:
        print("  ✗ FAIL: Missing definition or caller in discovered files.")

    # 4. Check 2: Imports, Backend Route, and Frontend Fetch (/api/satellite/gee-tiles)
    print("\n[Step 4] Checking backend routes and frontend fetch calls...")
    results["checks_total"] += 1
    chk2_instruction = (
        "Migrate /api/satellite/gee-tiles to /api/v2/satellite/gee-tiles across server and frontend"
    )
    ctx2 = build_task_context(store, chk2_instruction, repo_path, project_name=project_name)
    disc2 = set(ctx2["discovered_files"])
    print(f"  Query: '{chk2_instruction}'")
    print(f"  Discovered files ({len(disc2)}): {sorted(list(disc2))}")

    has_backend = "server.ts" in disc2
    has_frontend = "src/components/FieldGisView.tsx" in disc2
    chk2_passed = has_backend and has_frontend
    results["details"]["check_2_backend_route_and_fetch"] = {
        "passed": chk2_passed,
        "has_backend": has_backend,
        "has_frontend": has_frontend,
        "discovered_files": sorted(list(disc2)),
        "path_errors": ctx2.get("path_errors", [])
    }
    if chk2_passed:
        results["checks_passed"] += 1
        print("  ✓ PASS: Found server.ts route and FieldGisView.tsx fetch caller.")
    else:
        print("  ✗ FAIL: Missing backend route or frontend caller.")

    # 5. Check 3: Multi-Format Searchability (TS, HTML, CSS, JSON)
    print("\n[Step 5] Checking multi-format searchability (HTML, CSS, JSON, TS)...")
    results["checks_total"] += 1
    # 5a. CSS search
    css_res = build_task_context(store, "Refine custom scrollbar styling in `::-webkit-scrollbar`", repo_path, project_name=project_name)
    has_css = any(f.endswith(".css") for f in css_res["discovered_files"])

    # 5b. HTML search
    html_res = build_task_context(store, "Update HTML title or root element in `index.html`", repo_path, project_name=project_name)
    has_html = "index.html" in html_res["discovered_files"]

    # 5c. JSON search
    json_res = build_task_context(store, "Check application metadata in `metadata.json`", repo_path, project_name=project_name)
    has_json = "metadata.json" in json_res["discovered_files"]

    # 5d. TS search
    ts_res = build_task_context(store, "Update algorithm in `sortPolygonClockwise`", repo_path, project_name=project_name)
    has_ts = any(f.endswith(".ts") or f.endswith(".tsx") for f in ts_res["discovered_files"])

    chk3_passed = has_css and has_html and has_json and has_ts
    results["details"]["check_3_multiformat_searchability"] = {
        "passed": chk3_passed,
        "css_found": has_css,
        "html_found": has_html,
        "json_found": has_json,
        "ts_found": has_ts
    }
    if chk3_passed:
        results["checks_passed"] += 1
        print("  ✓ PASS: Successfully searched CSS, HTML, JSON, and TS files.")
    else:
        print(f"  ✗ FAIL: Missing format: CSS={has_css}, HTML={has_html}, JSON={has_json}, TS={has_ts}")

    # 6. Check 4: Returned Files Exist and Snippets Match Source on Disk
    print("\n[Step 6] Validating returned snippets against disk files byte-for-byte...")
    results["checks_total"] += 1
    snippet_failures = []
    snippet_samples = []

    # Test snippets from ctx1 and ctx2
    for ctx_item, label in [(ctx1, "generatePresetPolygon"), (ctx2, "/api/satellite/gee-tiles")]:
        context_text = ctx_item["context_text"]
        lines_ctx = context_text.splitlines()
        current_file = None
        current_range = None
        current_snip_lines = []

        def _validate_block(c_file, c_range, snip_lines):
            resolved_p, _ = normalize_and_resolve_repo_path(c_file, repo_path, must_exist=True)
            if not resolved_p:
                snippet_failures.append(f"{label}: Could not resolve '{c_file}'")
                return
            file_lines = resolved_p.read_text(encoding="utf-8", errors="replace").splitlines()
            s, e = c_range
            expected = file_lines[s - 1:e]
            if snip_lines != expected:
                diff_hint = f"len(got)={len(snip_lines)} vs len(expected)={len(expected)}"
                if len(snip_lines) > 0 and len(expected) > 0:
                    diff_hint += f" | got[0]={repr(snip_lines[0])} vs exp[0]={repr(expected[0])}"
                snippet_failures.append(f"{label}: Snippet in {c_file} (L{s}-L{e}) mismatch ({diff_hint})")
            else:
                snippet_samples.append({
                    "file": c_file,
                    "range": f"L{s}-L{e}",
                    "snippet_preview": "\n".join(snip_lines[:5])
                })

        for line in lines_ctx:
            if line.startswith("--- FILE:"):
                if current_file and current_range and current_snip_lines:
                    _validate_block(current_file, current_range, current_snip_lines)
                parts = line.split("--- FILE: ")[1].split(" (Lines ")
                current_file = parts[0]
                range_str = parts[1].split(" of ")[0]
                s_str, e_str = range_str.split("-")
                current_range = (int(s_str), int(e_str))
                current_snip_lines = []
            elif line.startswith("==="):
                continue
            else:
                if current_file:
                    current_snip_lines.append(line)

        # Flush last block
        if current_file and current_range and current_snip_lines:
            _validate_block(current_file, current_range, current_snip_lines)

    chk4_passed = (len(snippet_failures) == 0 and len(snippet_samples) > 0)
    results["details"]["check_4_snippet_fidelity"] = {
        "passed": chk4_passed,
        "validated_snippets_count": len(snippet_samples),
        "failures": snippet_failures,
        "samples": snippet_samples[:3]
    }
    if chk4_passed:
        results["checks_passed"] += 1
        print(f"  ✓ PASS: All {len(snippet_samples)} extracted snippets match source files on disk.")
    else:
        print(f"  ✗ FAIL: Snippet mismatches: {snippet_failures}")

    # 7. Check 5: Relocation Resilience
    print("\n[Step 7] Testing relocation resilience (relocating repo to new path)...")
    results["checks_total"] += 1
    relocated_dir = Path(tempfile.mkdtemp(prefix="FarmWatch_Relocated_"))
    try:
        shutil.copytree(repo_path, relocated_dir, dirs_exist_ok=True)
        # Query with relocated directory
        reloc_ctx = build_task_context(store, chk1_instruction, relocated_dir, project_name=project_name)
        reloc_disc = set(reloc_ctx["discovered_files"])
        reloc_passed = ("src/utils/geo.ts" in reloc_disc and len(reloc_ctx.get("path_errors", [])) == 0)
        # Verify resolved file is actually under relocated_dir
        if reloc_passed:
            sample_resolved, _ = normalize_and_resolve_repo_path("src/utils/geo.ts", relocated_dir, must_exist=True)
            if not sample_resolved or not sample_resolved.is_relative_to(relocated_dir):
                reloc_passed = False

        results["details"]["check_5_relocation_resilience"] = {
            "passed": reloc_passed,
            "relocated_dir": str(relocated_dir),
            "discovered_files": sorted(list(reloc_disc)),
            "path_errors": reloc_ctx.get("path_errors", [])
        }
        if reloc_passed:
            results["checks_passed"] += 1
            print("  ✓ PASS: Path resolution succeeded under relocated directory without re-indexing.")
        else:
            print("  ✗ FAIL: Relocation check failed.")
    finally:
        shutil.rmtree(relocated_dir, ignore_errors=True)

    # Summary
    all_passed = (results["checks_passed"] == results["checks_total"])
    results["overall_success"] = all_passed
    print("\n" + "=" * 70)
    print(f"VERIFICATION RESULTS: {results['checks_passed']} / {results['checks_total']} CHECKS PASSED")
    print("=" * 70)

    # Save verification artifacts
    rep_path = output_dir / "offline_retrieval_verification_report.json"
    rep_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved verification report to: {rep_path}")

    # Save snippet samples to markdown
    snip_md = output_dir / "retrieved_snippets_sample.md"
    md_lines = ["# Verified PolyFabric Retrieved Snippets Sample\n"]
    for s in snippet_samples:
        md_lines.append(f"### File: `{s['file']}` ({s['range']})\n```typescript\n{s['snippet_preview']}\n```\n")
    snip_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Saved snippet samples to: {snip_md}")

    return results


if __name__ == "__main__":
    repo_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/FarmWatch")
    out_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/retrieval_verification")
    res = run_offline_verification(repo_arg, out_arg)
    sys.exit(0 if res["overall_success"] else 1)

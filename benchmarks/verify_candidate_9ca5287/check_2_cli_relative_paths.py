#!/usr/bin/env python3
"""Targeted Remote Check 2: CLI Relative-Path Indexing in LanceDB.

Verifies that running `memory-mesh register` CLI on a project containing:
  - src/main.ts
  - src/types.ts
stores strictly normalized relative POSIX paths in LanceDB:
1. Registration exits with returncode 0.
2. Both fixture files are indexed in the LanceDB documents table.
3. Stored paths are exactly 'src/main.ts' and 'src/types.ts'.
4. Zero absolute paths, Windows drive prefixes, or backslashes appear.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import lancedb


def run_check_2() -> dict:
    t_start = time.time()
    results = {
        "check": "Check 2: CLI relative-path indexing",
        "timestamp_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "assertions": [],
        "status": "FAIL",
    }

    # 1. Setup isolated directories
    test_root = Path("/tmp/polyfabric_check2_sandbox").resolve()
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True, exist_ok=True)

    isolated_home = test_root / "home"
    isolated_db = test_root / "db"
    project_dir = test_root / "fixture_project"
    isolated_home.mkdir(parents=True, exist_ok=True)
    isolated_db.mkdir(parents=True, exist_ok=True)
    (project_dir / "src").mkdir(parents=True, exist_ok=True)

    # 2. Create the exact fixture files
    main_ts = project_dir / "src" / "main.ts"
    types_ts = project_dir / "src" / "types.ts"

    main_ts.write_text(
        "import { Config } from './types';\n"
        "export function bootstrap(cfg: Config): number {\n"
        "  return cfg.port + 1;\n"
        "}\n",
        encoding="utf-8"
    )

    types_ts.write_text(
        "export interface Config {\n"
        "  host: string;\n"
        "  port: number;\n"
        "}\n",
        encoding="utf-8"
    )

    print(f"Created fixture project at {project_dir}")
    print(f"  {main_ts.relative_to(project_dir)}")
    print(f"  {types_ts.relative_to(project_dir)}")

    # 3. Environment variables isolated BEFORE starting CLI
    cli_env = {
        **os.environ,
        "INFINITE_MEMORY_HOME": str(isolated_home),
        "INFINITE_MEMORY_DB_PATH": str(isolated_db),
        "PYTHONPATH": "/home/agent/workspace/PolyFabric/src",
    }

    # 4. Execute the actual CLI command via memory-mesh / python -m infinite_memory.cli
    # Supported signature: memory-mesh register <name> <path>
    cmd = [
        "/tmp/venv/bin/python",
        "-m", "infinite_memory.cli",
        "register",
        "cli-relative-test-proj",
        str(project_dir),
    ]

    print(f"Executing CLI command: {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=cli_env, capture_output=True, text=True)
    print(f"CLI stdout:\n{proc.stdout}")
    if proc.stderr:
        print(f"CLI stderr:\n{proc.stderr}")

    reg_success = (proc.returncode == 0)
    results["assertions"].append({
        "assertion": "CLI register exits with code 0",
        "expected": 0,
        "actual": proc.returncode,
        "passed": reg_success,
    })
    assert reg_success, f"CLI registration failed with code {proc.returncode}"

    # 5. Direct inspection of the exact LanceDB database
    print(f"Connecting directly to LanceDB at {isolated_db}...")
    db = lancedb.connect(str(isolated_db))
    table_names = db.table_names()
    print(f"LanceDB tables present: {table_names}")
    assert "documents" in table_names, f"documents table missing from {table_names}"

    table = db.open_table("documents")
    df = table.to_pandas()
    print(f"Total rows in documents table: {len(df)}")

    proj_df = df[df["project"] == "cli-relative-test-proj"]
    indexed_paths = sorted(proj_df["file_path"].unique().tolist())
    print(f"Stored file_path values for project: {indexed_paths}")

    # Assertion A: Both fixture files are indexed
    count_match = (len(indexed_paths) == 2)
    results["assertions"].append({
        "assertion": "Both fixture files indexed in LanceDB",
        "expected": ["src/main.ts", "src/types.ts"],
        "actual": indexed_paths,
        "passed": count_match,
    })
    assert count_match, f"Expected 2 indexed files, got {len(indexed_paths)}: {indexed_paths}"

    # Assertion B: Stored paths are exactly 'src/main.ts' and 'src/types.ts'
    exact_match = (indexed_paths == ["src/main.ts", "src/types.ts"])
    results["assertions"].append({
        "assertion": "Stored file paths are exactly ['src/main.ts', 'src/types.ts']",
        "expected": ["src/main.ts", "src/types.ts"],
        "actual": indexed_paths,
        "passed": exact_match,
    })
    assert exact_match, f"Exact path match failed: {indexed_paths}"

    # Assertion C: No absolute paths, drive prefixes, or backslashes
    clean_paths = True
    path_defects = []
    for fp in indexed_paths:
        if fp.startswith("/"):
            clean_paths = False
            path_defects.append(f"Leading slash found: {fp}")
        if fp.startswith("\\"):
            clean_paths = False
            path_defects.append(f"Leading backslash found: {fp}")
        if ":" in fp:
            clean_paths = False
            path_defects.append(f"Drive letter found: {fp}")
        if "\\" in fp:
            clean_paths = False
            path_defects.append(f"Unnormalized backslash found: {fp}")

    results["assertions"].append({
        "assertion": "Paths contain zero absolute paths, drive prefixes, or backslashes",
        "expected": "Zero path formatting defects",
        "actual": path_defects if path_defects else "Clean relative POSIX paths",
        "passed": clean_paths,
    })
    assert clean_paths, f"Path format defects: {path_defects}"
    print(f"Path format validation passed: All paths are clean relative POSIX paths.")

    # 6. Also check via VectorStore method get_indexed_files_for_project
    from infinite_memory.core.store import VectorStore
    store = VectorStore(db_path=isolated_db)
    store_files = sorted(store.get_indexed_files_for_project("cli-relative-test-proj"))
    store_match = (store_files == ["src/main.ts", "src/types.ts"])
    results["assertions"].append({
        "assertion": "VectorStore.get_indexed_files_for_project returns identical relative paths",
        "expected": ["src/main.ts", "src/types.ts"],
        "actual": store_files,
        "passed": store_match,
    })
    assert store_match, f"Store API mismatch: {store_files}"

    # Cleanup
    shutil.rmtree(test_root, ignore_errors=True)
    results["cleanup"] = f"Removed temporary test directory {test_root}"

    t_end = time.time()
    results["timestamp_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_end))
    results["elapsed_seconds"] = round(t_end - t_start, 3)
    results["status"] = "PASS"
    print(f"\n>>> CHECK 2 VERDICT: PASS ({results['elapsed_seconds']}s) <<<\n")
    return results


if __name__ == "__main__":
    out = run_check_2()
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["status"] == "PASS" else 1)

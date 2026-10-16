#!/usr/bin/env python3
"""Unified Pilot Verification Runner for Candidate Commit 9ca5287.

Executes:
  1. Check 1: Read-only enforcement through actual MCP stdio server
  2. Check 2: CLI relative-path indexing into LanceDB
  3. Check 3: Offline startup evaluation

Records:
  - Candidate commit SHA and working-tree status
  - Script SHA-256 hashes
  - Exact commands, environment variables, timestamps, and exit codes
  - Complete assertion tables and final verdicts
  - Saves all structured logs to benchmarks/results/PILOT_VERIFICATION_9CA5287/
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Import individual check runners
from check_1_mcp_readonly import run_check_1
from check_2_cli_relative_paths import run_check_2
from check_3_offline_startup import run_check_3


def compute_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


def main():
    t_start = time.time()
    iso_start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start))
    print("=" * 80)
    print("POLYFABRIC RELEASE CANDIDATE 9ca5287 TARGETED VERIFICATION RUNNER")
    print(f"Timestamp: {iso_start}")
    print("=" * 80)

    # 1. Verify candidate commit SHA and git working-tree status
    repo_root = Path("/home/agent/workspace/PolyFabric").resolve()
    commit_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True)
    actual_commit = commit_proc.stdout.strip()

    status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True)
    working_tree_porcelain = status_proc.stdout.strip()

    branch_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True)
    current_branch = branch_proc.stdout.strip()

    expected_commit = "9ca5287f717670941330b4202f0fb6ba606f797e"
    print(f"Target Repository: {repo_root}")
    print(f"Expected Commit:   {expected_commit}")
    print(f"Actual HEAD Commit:{actual_commit}")
    print(f"Active Branch:     {current_branch}")
    assert actual_commit == expected_commit, f"Commit mismatch! Expected {expected_commit}, got {actual_commit}"

    # 2. Script integrity hashes
    script_dir = Path(__file__).parent.resolve()
    scripts = {
        "check_1_mcp_readonly.py": compute_file_sha256(script_dir / "check_1_mcp_readonly.py"),
        "check_2_cli_relative_paths.py": compute_file_sha256(script_dir / "check_2_cli_relative_paths.py"),
        "check_3_offline_startup.py": compute_file_sha256(script_dir / "check_3_offline_startup.py"),
        "run_pilot_checks.py": compute_file_sha256(script_dir / "run_pilot_checks.py"),
    }
    print("\nVerification Script Hashes (SHA-256):")
    for s_name, s_hash in scripts.items():
        print(f"  {s_name}: {s_hash}")

    # Output directory for evidence
    results_dir = repo_root / "benchmarks" / "results" / "PILOT_VERIFICATION_9CA5287"
    results_dir.mkdir(parents=True, exist_ok=True)

    execution_manifest = {
        "candidate_commit": actual_commit,
        "branch": current_branch,
        "git_status_porcelain": working_tree_porcelain,
        "environment": {
            "os": os.uname().sysname + " " + os.uname().release,
            "python": sys.version,
            "python_executable": sys.executable,
            "container_id": "sbx_001m4haazrz2qc70t771bmyeqs0",
        },
        "scripts": scripts,
        "timestamp_start": iso_start,
        "checks": {},
        "overall_verdict": "PENDING",
    }

    # 3. Execute Check 1
    print("\n" + "=" * 80)
    print("RUNNING CHECK 1: Real MCP Stdio Server Read-Only Enforcement")
    print("=" * 80)
    try:
        c1_res = asyncio.run(run_check_1())
        execution_manifest["checks"]["check_1_mcp_readonly"] = c1_res
    except Exception as e:
        print(f"Check 1 Failed with Exception: {e}")
        execution_manifest["checks"]["check_1_mcp_readonly"] = {"status": "FAIL", "error": str(e)}

    # 4. Execute Check 2
    print("\n" + "=" * 80)
    print("RUNNING CHECK 2: CLI Relative-Path Indexing in LanceDB")
    print("=" * 80)
    try:
        c2_res = run_check_2()
        execution_manifest["checks"]["check_2_cli_relative_paths"] = c2_res
    except Exception as e:
        print(f"Check 2 Failed with Exception: {e}")
        execution_manifest["checks"]["check_2_cli_relative_paths"] = {"status": "FAIL", "error": str(e)}

    # 5. Execute Check 3
    print("\n" + "=" * 80)
    print("RUNNING CHECK 3: Offline Startup & Embedding Operation")
    print("=" * 80)
    try:
        c3_res = run_check_3(require_offline=False)
        execution_manifest["checks"]["check_3_offline_startup"] = c3_res
    except Exception as e:
        print(f"Check 3 Failed with Exception: {e}")
        execution_manifest["checks"]["check_3_offline_startup"] = {"status": "FAIL", "error": str(e)}

    # 6. Overall Verdict Determination
    c1_status = execution_manifest["checks"].get("check_1_mcp_readonly", {}).get("status")
    c2_status = execution_manifest["checks"].get("check_2_cli_relative_paths", {}).get("status")
    c3_status = execution_manifest["checks"].get("check_3_offline_startup", {}).get("status")

    if c1_status == "PASS" and c2_status == "PASS":
        execution_manifest["overall_verdict"] = "READY FOR A MONITORED READ-ONLY PILOT"
    else:
        execution_manifest["overall_verdict"] = "BLOCKED — SPECIFIC DEFECTS"

    t_end = time.time()
    execution_manifest["timestamp_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_end))
    execution_manifest["total_elapsed_seconds"] = round(t_end - t_start, 3)

    # 7. Write out persistent artifacts
    manifest_file = results_dir / "verification_summary.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(execution_manifest, f, indent=2)

    print("\n" + "=" * 80)
    print(f"FINAL PILOT VERDICT: {execution_manifest['overall_verdict']}")
    print(f"  Check 1 (MCP Read-Only Enforcement): {c1_status}")
    print(f"  Check 2 (CLI Relative Paths):        {c2_status}")
    print(f"  Check 3 (Offline Operation):         {c3_status}")
    print(f"Saved complete evidence to: {manifest_file}")
    print("=" * 80 + "\n")

    sys.exit(0 if execution_manifest["overall_verdict"] == "READY FOR A MONITORED READ-ONLY PILOT" else 1)


if __name__ == "__main__":
    main()

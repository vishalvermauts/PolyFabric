#!/usr/bin/env python3
"""Targeted Remote Check 1: Real MCP Server Read-Only Enforcement.

Verifies that when POLYFABRIC_READ_ONLY=1 is set:
1. The real MCP server starts via stdio and initializes an MCP ClientSession.
2. An attempted overwrite of an existing file via `mesh_write_file` on a feature branch
   returns explicit PermissionDenied.
3. The existing file remains byte-for-byte identical on disk (verified by SHA-256).
4. An attempted write to a non-existent path returns explicit PermissionDenied and creates no file.
5. A normal read operation via `mesh_read_file` succeeds and returns unmutated contents.
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_check_1() -> dict:
    t_start = time.time()
    results = {
        "check": "Check 1: Read-only enforcement through actual MCP",
        "timestamp_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "assertions": [],
        "status": "FAIL",
    }

    # 1. Isolated workspace setup
    test_root = Path("/tmp/polyfabric_check1_sandbox").resolve()
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True, exist_ok=True)

    isolated_home = test_root / "home"
    isolated_db = test_root / "db"
    repo_dir = test_root / "feature_repo"
    isolated_home.mkdir(parents=True, exist_ok=True)
    isolated_db.mkdir(parents=True, exist_ok=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    # 2. Git setup on a FEATURE branch (so main branch guard cannot explain the rejection)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "pilot@polyfabric.local"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Pilot Verifier"], cwd=repo_dir, check=True)

    # Initial commit on default branch
    base_file = repo_dir / "README.md"
    base_file.write_text("# Feature Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    # Switch to feature branch explicitly
    subprocess.run(["git", "checkout", "-b", "feature/audit-branch"], cwd=repo_dir, check=True, capture_output=True)
    branch_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True)
    current_branch = branch_proc.stdout.strip()
    assert current_branch == "feature/audit-branch", f"Expected feature branch, got {current_branch}"
    results["assertions"].append({
        "assertion": "Git feature branch configured",
        "expected": "feature/audit-branch",
        "actual": current_branch,
        "passed": True,
    })

    # 3. Create existing test file with known payload and SHA-256
    sentinel_file = repo_dir / "sentinel.txt"
    original_bytes = b"IMMUTABLE_PRE_TEST_SENTINEL_STATE_987654321\n"
    sentinel_file.write_bytes(original_bytes)
    pre_sha256 = hashlib.sha256(original_bytes).hexdigest()
    results["assertions"].append({
        "assertion": "Sentinel file pre-hash computed",
        "expected": pre_sha256,
        "actual": pre_sha256,
        "passed": True,
    })

    # 4. Pre-register project in isolated registry.json
    registry_file = isolated_home / "registry.json"
    registry_data = {
        "pilot-test-proj": {
            "path": str(repo_dir),
            "type": "general",
            "metadata": {"test": "true"}
        }
    }
    registry_file.write_text(json.dumps(registry_data, indent=2), encoding="utf-8")

    # 5. Start real MCP stdio server subprocess with POLYFABRIC_ENABLE_SERVER=1 and POLYFABRIC_READ_ONLY=1
    server_env = {
        **os.environ,
        "POLYFABRIC_ENABLE_SERVER": "1",
        "POLYFABRIC_READ_ONLY": "1",
        "INFINITE_MEMORY_HOME": str(isolated_home),
        "INFINITE_MEMORY_DB_PATH": str(isolated_db),
        "PYTHONPATH": "/home/agent/workspace/PolyFabric/src",
    }

    server_params = StdioServerParameters(
        command="/tmp/venv/bin/python",
        args=["-m", "infinite_memory.server"],
        env=server_env,
    )

    print("Spawning real MCP server subprocess via stdio...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("MCP session initialized.")

            tools_resp = await session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            print(f"Server exposed tools: {tool_names}")
            assert "mesh_write_file" in tool_names
            assert "mesh_read_file" in tool_names

            # Test A: Overwrite attempt on existing file
            call_overwrite = await session.call_tool(
                "mesh_write_file",
                arguments={
                    "project_name": "pilot-test-proj",
                    "path": "sentinel.txt",
                    "content": "MALICIOUS_OVERWRITE_PAYLOAD_TEST"
                }
            )
            overwrite_text = call_overwrite.content[0].text if call_overwrite.content else ""
            print(f"mesh_write_file (overwrite) response:\n  {overwrite_text}")
            denied_overwrite = "PermissionDenied: PolyFabric is operating in read-only mode" in overwrite_text
            results["assertions"].append({
                "assertion": "Attempted overwrite returns read-only PermissionDenied",
                "expected": "PermissionDenied: PolyFabric is operating in read-only mode",
                "actual": overwrite_text,
                "passed": denied_overwrite,
            })
            assert denied_overwrite, f"Write rejection failed: {overwrite_text}"

            # Test B: Byte-for-byte immutability verification
            post_bytes = sentinel_file.read_bytes()
            post_sha256 = hashlib.sha256(post_bytes).hexdigest()
            byte_match = (post_bytes == original_bytes)
            hash_match = (post_sha256 == pre_sha256)
            results["assertions"].append({
                "assertion": "Existing file remains byte-for-byte unchanged",
                "expected": pre_sha256,
                "actual": post_sha256,
                "passed": byte_match and hash_match,
            })
            assert byte_match and hash_match, f"File mutated! SHA changed from {pre_sha256} to {post_sha256}"
            print(f"Byte immutability confirmed: SHA256 {post_sha256}")

            # Test C: New file creation attempt
            ghost_file = repo_dir / "unauthorized_created_file.txt"
            call_create = await session.call_tool(
                "mesh_write_file",
                arguments={
                    "project_name": "pilot-test-proj",
                    "path": "unauthorized_created_file.txt",
                    "content": "MALICIOUS_NEW_FILE_CREATION_TEST"
                }
            )
            create_text = call_create.content[0].text if call_create.content else ""
            print(f"mesh_write_file (create) response:\n  {create_text}")
            denied_create = "PermissionDenied: PolyFabric is operating in read-only mode" in create_text
            file_not_created = not ghost_file.exists()
            results["assertions"].append({
                "assertion": "Attempted new file write returns read-only PermissionDenied",
                "expected": "PermissionDenied: PolyFabric is operating in read-only mode",
                "actual": create_text,
                "passed": denied_create,
            })
            results["assertions"].append({
                "assertion": "Non-existent file was NOT created on disk",
                "expected": "File does not exist",
                "actual": "File exists" if ghost_file.exists() else "File does not exist",
                "passed": file_not_created,
            })
            assert denied_create, f"New file write rejection failed: {create_text}"
            assert file_not_created, "DEFECT: File was created on disk despite read-only mode!"
            print("New file non-creation confirmed: unauthorized_created_file.txt absent.")

            # Test D: Read operation succeeds
            call_read = await session.call_tool(
                "mesh_read_file",
                arguments={
                    "project_name": "pilot-test-proj",
                    "path": "sentinel.txt",
                }
            )
            read_text = call_read.content[0].text if call_read.content else ""
            print(f"mesh_read_file response:\n  {read_text.strip()}")
            read_success = "IMMUTABLE_PRE_TEST_SENTINEL_STATE_987654321" in read_text
            results["assertions"].append({
                "assertion": "Normal read operation via mesh_read_file succeeds",
                "expected": "IMMUTABLE_PRE_TEST_SENTINEL_STATE_987654321",
                "actual": read_text.strip(),
                "passed": read_success,
            })
            assert read_success, f"Read operation failed: {read_text}"
            print("Read operation confirmed: contents retrieved accurately.")

    # Cleanup
    shutil.rmtree(test_root, ignore_errors=True)
    results["cleanup"] = f"Removed temporary test directory {test_root}"

    t_end = time.time()
    results["timestamp_end"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_end))
    results["elapsed_seconds"] = round(t_end - t_start, 3)
    results["status"] = "PASS"
    print(f"\n>>> CHECK 1 VERDICT: PASS ({results['elapsed_seconds']}s) <<<\n")
    return results


if __name__ == "__main__":
    out = asyncio.run(run_check_1())
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["status"] == "PASS" else 1)

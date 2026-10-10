import os
import sys
import time
import json
import asyncio
import statistics
from pathlib import Path
from typing import List, Dict, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

async def benchmark_mcp_performance(num_requests: int = 1000):
    print("=== Running Isolated Full-Corpus MCP Performance Benchmark ===")
    print(f"Target Database: {DB_PATH}")
    print(f"Total Measured Calls: {num_requests}")

    manifest_queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    query_pool = [q["query"] for q in manifest_queries]

    server_params = StdioServerParameters(
        command="/home/agent/bench/.venv/bin/python",
        args=["-m", "infinite_memory.server"],
        env={**os.environ, "MEMORY_MESH_DB_PATH": str(DB_PATH)}
    )

    startup_ms = 0.0
    first_query_ms = 0.0
    warm_latencies_ms = []
    transport_errors = 0
    application_errors = 0
    empty_responses = 0
    valid_responses = 0

    per_request_records = []

    print("Spawning FastMCP stdio server...")
    t_start_all = time.perf_counter()

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            t0 = time.perf_counter()
            init_res = await session.initialize()
            startup_ms = (time.perf_counter() - t0) * 1000.0
            print(f"MCP Initialize completed in {startup_ms:.2f} ms")

            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"Verified tools: {tool_names}")

            # First query timing (Cold execution / model loading)
            t_first = time.perf_counter()
            first_res = await session.call_tool("mesh_search", {"query": query_pool[0], "top_k": 5})
            first_query_ms = (time.perf_counter() - t_first) * 1000.0
            print(f"First Query Latency (cold cache): {first_query_ms:.2f} ms")

            # 1,000 Measured MCP Calls across representative randomized queries
            print(f"Executing {num_requests} measured client calls over MCP stdio...")
            t_bench_start = time.perf_counter()

            for idx in range(num_requests):
                q = query_pool[idx % len(query_pool)]
                t_req = time.perf_counter()
                
                try:
                    res = await session.call_tool("mesh_search", {"query": q, "top_k": 5})
                    req_lat = (time.perf_counter() - t_req) * 1000.0
                    warm_latencies_ms.append(req_lat)

                    # Strict response validation
                    is_err = getattr(res, "isError", False)
                    content_text = "".join(getattr(c, "text", "") for c in res.content) if res and res.content else ""

                    if is_err:
                        transport_errors += 1
                        status = "mcp_error"
                    elif content_text.startswith("Operational Error:") or content_text.startswith("Traceback (most recent call last):"):
                        application_errors += 1
                        status = "application_error"
                    elif not content_text.strip():
                        empty_responses += 1
                        status = "empty"
                    else:
                        valid_responses += 1
                        status = "success"

                    rec = {
                        "request_idx": idx,
                        "query": q,
                        "latency_ms": round(req_lat, 2),
                        "status": status,
                        "response_length": len(content_text)
                    }
                except Exception as exc:
                    req_lat = (time.perf_counter() - t_req) * 1000.0
                    warm_latencies_ms.append(req_lat)
                    transport_errors += 1
                    rec = {
                        "request_idx": idx,
                        "query": q,
                        "latency_ms": round(req_lat, 2),
                        "status": "exception",
                        "error": str(exc)
                    }

                per_request_records.append(rec)

                if (idx + 1) % 200 == 0:
                    med = statistics.median(warm_latencies_ms)
                    print(f"Progress: {idx+1}/{num_requests} calls (P50: {med:.2f} ms)...")

    bench_duration = time.perf_counter() - t_bench_start
    qps = len(warm_latencies_ms) / max(0.001, bench_duration)

    p50 = float(statistics.median(warm_latencies_ms))
    p90 = float(statistics.quantiles(warm_latencies_ms, n=10)[8]) if len(warm_latencies_ms) >= 10 else p50
    p95 = float(statistics.quantiles(warm_latencies_ms, n=20)[18]) if len(warm_latencies_ms) >= 20 else p90
    p99 = float(statistics.quantiles(warm_latencies_ms, n=100)[98]) if len(warm_latencies_ms) >= 100 else p95
    max_lat = float(max(warm_latencies_ms))
    min_lat = float(min(warm_latencies_ms))

    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "protocol": "Model Context Protocol (MCP) Stdio JSON-RPC 2.0",
        "database": str(DB_PATH),
        "total_measured_requests": len(warm_latencies_ms),
        "bench_duration_sec": round(bench_duration, 2),
        "completed_qps": round(qps, 2),
        "startup_init_ms": round(startup_ms, 2),
        "first_query_ms": round(first_query_ms, 2),
        "outcomes": {
            "valid_responses": valid_responses,
            "transport_errors": transport_errors,
            "application_errors": application_errors,
            "empty_responses": empty_responses,
            "error_rate": round((transport_errors + application_errors) / max(1, len(warm_latencies_ms)), 4)
        },
        "latencies_ms": {
            "min": round(min_lat, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max_lat, 2)
        }
    }

    out_summary = RESULTS_DIR / "mcp_isolated_performance_summary.json"
    out_summary.write_text(json.dumps(summary, indent=2))
    
    out_requests = RESULTS_DIR / "mcp_isolated_requests.jsonl"
    with open(out_requests, "w", encoding="utf-8") as f:
        for r in per_request_records:
            f.write(json.dumps(r) + "\n")

    print("\n=== MCP Performance Benchmark Complete ===")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    asyncio.run(benchmark_mcp_performance(num_requests=1000))

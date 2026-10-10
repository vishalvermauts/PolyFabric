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

async def worker(worker_id: int, session: ClientSession, query_queue: asyncio.Queue, results_list: list):
    while not query_queue.empty():
        try:
            q = query_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
            
        t0 = time.perf_counter()
        try:
            res = await session.call_tool("mesh_search", {"query": q, "top_k": 5})
            lat = (time.perf_counter() - t0) * 1000.0
            results_list.append({"latency_ms": lat, "status": "success"})
        except Exception as e:
            lat = (time.perf_counter() - t0) * 1000.0
            results_list.append({"latency_ms": lat, "status": "error", "error": str(e)})

async def run_concurrency_test():
    print("=== Running Controlled MCP Concurrency Benchmark (1, 2, 4, 8 In-Flight) ===")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    query_pool = [q["query"] for q in manifest]

    server_params = StdioServerParameters(
        command="/home/agent/bench/.venv/bin/python",
        args=["-m", "infinite_memory.server"],
        env={**os.environ, "MEMORY_MESH_DB_PATH": str(DB_PATH)}
    )

    concurrency_levels = [1, 2, 4, 8]
    test_results = {}

    for c in concurrency_levels:
        print(f"\n--- Testing Concurrency Level: {c} In-Flight Requests ---")
        num_queries = 200
        q_queue = asyncio.Queue()
        for i in range(num_queries):
            q_queue.put_nowait(query_pool[i % len(query_pool)])

        results = []
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                
                t_start = time.perf_counter()
                tasks = [asyncio.create_task(worker(i, session, q_queue, results)) for i in range(c)]
                await asyncio.gather(*tasks)
                t_total = time.perf_counter() - t_start

        latencies = [r["latency_ms"] for r in results]
        p50 = float(statistics.median(latencies))
        p90 = float(statistics.quantiles(latencies, n=10)[8]) if len(latencies) >= 10 else p50
        p95 = float(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else p90
        p99 = float(statistics.quantiles(latencies, n=100)[98]) if len(latencies) >= 100 else p95
        qps = len(latencies) / max(0.001, t_total)

        res_entry = {
            "concurrency_in_flight": c,
            "architecture": "Single MCP Server instance, shared async session",
            "total_requests": len(latencies),
            "duration_sec": round(t_total, 2),
            "throughput_qps": round(qps, 2),
            "latencies_ms": {
                "min": round(min(latencies), 2),
                "p50": round(p50, 2),
                "p90": round(p90, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2),
                "max": round(max(latencies), 2)
            }
        }
        print(json.dumps(res_entry, indent=2))
        test_results[f"concurrency_{c}"] = res_entry

    out_file = RESULTS_DIR / "mcp_concurrency_benchmark_summary.json"
    out_file.write_text(json.dumps(test_results, indent=2))
    print(f"\nSaved concurrency benchmark summary to {out_file}")

if __name__ == "__main__":
    asyncio.run(run_concurrency_test())

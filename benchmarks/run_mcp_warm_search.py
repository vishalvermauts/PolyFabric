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
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"

SAMPLE_QUERIES = [
    "class Flask application WSGI dispatch",
    "def route endpoint handler decorator",
    "class Request context header parsing",
    "FastAPI APIRouter prefix include_router",
    "Depends security OAuth2PasswordBearer",
    "express Router route layer stack",
    "res.send json response status code",
    "createProgram compiler host options",
    "createScanner syntax kind scan token",
    "createTypeChecker getSymbolAtLocation checkSourceFile",
    "HTTP 404 exception response json",
    "middleware next function error handling",
    "websocket route connection accept",
    "AST traversal visitor child nodes",
    "configuration environment variable default",
]

async def run_mcp_warm_search(num_queries=500):
    print("=== Starting Real MCP Stdio Warm Search Benchmark ===")
    out_dir = RESULTS_DIR / "mcp_warm_searches"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "infinite_memory.server"],
        env={**os.environ, "MEMORY_MESH_DB_PATH": str(DB_PATH)}
    )
    
    latencies_ms = []
    errors = 0
    empty_responses = 0
    correct_responses = 0
    
    print(f"Connecting to MCP server subprocess...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            t0 = time.perf_counter()
            init_res = await session.initialize()
            init_ms = (time.perf_counter() - t0) * 1000.0
            print(f"MCP Initialize completed in {init_ms:.2f} ms")
            
            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"Available MCP tools ({len(tool_names)}): {tool_names}")
            
            # 20 warmup calls
            print("Executing 20 warmup calls through stdio...")
            for i in range(20):
                q = SAMPLE_QUERIES[i % len(SAMPLE_QUERIES)]
                await session.call_tool("mesh_search", {"query": q, "top_k": 5})
                
            print(f"Executing {num_queries} repeated warm searches through MCP stdio...")
            start_bench = time.perf_counter()
            for idx in range(num_queries):
                q = SAMPLE_QUERIES[idx % len(SAMPLE_QUERIES)]
                t_call = time.perf_counter()
                try:
                    res = await session.call_tool("mesh_search", {"query": q, "top_k": 5})
                    call_ms = (time.perf_counter() - t_call) * 1000.0
                    latencies_ms.append(call_ms)
                    
                    if not res or not res.content:
                        empty_responses += 1
                    else:
                        # Inspect content correctness
                        content_text = "".join(getattr(c, "text", "") for c in res.content)
                        if len(content_text.strip()) > 0:
                            correct_responses += 1
                        else:
                            empty_responses += 1
                except Exception as e:
                    call_ms = (time.perf_counter() - t_call) * 1000.0
                    latencies_ms.append(call_ms)
                    errors += 1
                    
                if (idx + 1) % 100 == 0:
                    med = statistics.median(latencies_ms)
                    print(f"Progress: {idx+1}/{num_queries} calls (P50: {med:.2f} ms)...")

    duration = time.perf_counter() - start_bench
    p50 = float(statistics.median(latencies_ms))
    p90 = float(statistics.quantiles(latencies_ms, n=10)[8]) if len(latencies_ms) >= 10 else p50
    p95 = float(statistics.quantiles(latencies_ms, n=20)[18]) if len(latencies_ms) >= 20 else p90
    p99 = float(statistics.quantiles(latencies_ms, n=100)[98]) if len(latencies_ms) >= 100 else p95
    min_lat = float(min(latencies_ms))
    max_lat = float(max(latencies_ms))
    
    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "protocol": "Model Context Protocol (MCP) Stdio JSON-RPC 2.0",
        "total_requests": num_queries,
        "wall_time_sec": duration,
        "throughput_req_per_sec": num_queries / max(0.001, duration),
        "errors": errors,
        "error_rate": errors / max(1, num_queries),
        "empty_responses": empty_responses,
        "empty_rate": empty_responses / max(1, num_queries),
        "correct_responses": correct_responses,
        "correctness_rate": correct_responses / max(1, num_queries),
        "latencies_ms": {
            "min": min_lat,
            "p50": p50,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "max": max_lat
        }
    }
    
    print("\n=== Real MCP Stdio Warm Search Results ===")
    print(json.dumps(summary, indent=2))
    
    with open(out_dir / "mcp_warm_search_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    return summary

def main():
    num = 500
    if len(sys.argv) > 1:
        num = int(sys.argv[1])
    asyncio.run(run_mcp_warm_search(num))

if __name__ == "__main__":
    main()

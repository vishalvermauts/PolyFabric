import os
import sys
import time
import json
import statistics
import asyncio
from pathlib import Path
from typing import List, Dict, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

async def run_context_expansion_eval():
    print("=== Step 5: Evaluating End-to-End Context Expansion & MCP Impact ===")
    print(f"Target DB: {DB_PATH}")
    print(f"Query Manifest: {MANIFEST_PATH}")

    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    
    server_params = StdioServerParameters(
        command="/home/agent/bench/.venv/bin/python",
        args=["-m", "infinite_memory.server"],
        env={**os.environ, "MEMORY_MESH_DB_PATH": str(DB_PATH)}
    )

    token_estimates = []
    char_lengths = []
    latencies_ms = []
    header_inclusions = 0
    total_chunks_inspected = 0
    bounded_conformance = 0

    print("Spawning FastMCP stdio server with Context Expansion enabled...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_res = await session.list_tools()
            print(f"Tools confirmed: {[t.name for t in tools_res.tools]}")

            # Warm-up call
            await session.call_tool("mesh_search", {"query": "warmup test", "top_k": 2})

            print(f"Executing search with context expansion across {len(queries)} ground truth queries...")
            for idx, q in enumerate(queries):
                qtext = q["query"]
                t0 = time.perf_counter()
                res = await session.call_tool("mesh_search", {"query": qtext, "top_k": 5})
                lat = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(lat)

                content_text = "".join(getattr(c, "text", "") for c in res.content) if res and res.content else ""
                
                # Split chunks
                chunks = [c for c in content_text.split("--- ") if c.strip()]
                for ch in chunks:
                    total_chunks_inspected += 1
                    # Approximate token count: chars / 4
                    approx_tokens = len(ch) / 4.0
                    token_estimates.append(approx_tokens)
                    char_lengths.append(len(ch))

                    # Check bounded envelope: default envelope max_tokens is 350 (~1400 chars)
                    # including header, allowing small margin for metadata banner
                    if approx_tokens <= 450:
                        bounded_conformance += 1

                    # Check if file header / context lines were prepended
                    if "# Context from file header:" in ch or "import " in ch or "export " in ch:
                        header_inclusions += 1

                if (idx + 1) % 50 == 0:
                    print(f"Processed {idx + 1}/{len(queries)} queries. Current P50 Latency: {statistics.median(latencies_ms):.2f} ms")

    avg_tokens = statistics.mean(token_estimates) if token_estimates else 0
    p50_tokens = statistics.median(token_estimates) if token_estimates else 0
    p90_tokens = statistics.quantiles(token_estimates, n=10)[8] if len(token_estimates) >= 10 else 0
    max_tokens = max(token_estimates) if token_estimates else 0

    p50_lat = statistics.median(latencies_ms)
    p90_lat = statistics.quantiles(latencies_ms, n=10)[8] if len(latencies_ms) >= 10 else p50_lat
    p95_lat = statistics.quantiles(latencies_ms, n=20)[18] if len(latencies_ms) >= 20 else p90_lat

    conformance_pct = (bounded_conformance / max(1, total_chunks_inspected)) * 100.0
    header_pct = (header_inclusions / max(1, total_chunks_inspected)) * 100.0

    eval_summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "total_queries_evaluated": len(queries),
        "total_chunks_retrieved": total_chunks_inspected,
        "token_envelope_metrics": {
            "avg_tokens_per_chunk": round(avg_tokens, 1),
            "p50_tokens_per_chunk": round(p50_tokens, 1),
            "p90_tokens_per_chunk": round(p90_tokens, 1),
            "max_tokens_per_chunk": round(max_tokens, 1),
            "envelope_bound_conformance_pct": round(conformance_pct, 2),
            "header_context_enrichment_pct": round(header_pct, 2)
        },
        "mcp_stdio_latency_with_expansion_ms": {
            "p50_ms": round(p50_lat, 2),
            "p90_ms": round(p90_lat, 2),
            "p95_ms": round(p95_lat, 2)
        }
    }

    print("\n================ CONTEXT EXPANSION EVALUATION SUMMARY ================")
    print(json.dumps(eval_summary, indent=2))
    
    out_file = RESULTS_DIR / "context_expansion_eval_summary.json"
    out_file.write_text(json.dumps(eval_summary, indent=2), encoding="utf-8")
    print(f"Saved evaluation results to {out_file}")

if __name__ == "__main__":
    asyncio.run(run_context_expansion_eval())

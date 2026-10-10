import asyncio
import os
import sys
import time
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_protocol():
    print("=== Testing Real Stdio MCP Server Protocol ===")
    
    server_params = StdioServerParameters(
        command="/home/agent/bench/.venv/bin/python",
        args=["-m", "infinite_memory.server"],
        env=dict(os.environ)
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. Initialize session
            t0 = time.perf_counter()
            init_res = await session.initialize()
            init_lat_ms = (time.perf_counter() - t0) * 1000.0
            print(f"MCP Initialize succeeded in {init_lat_ms:.2f} ms")
            
            # 2. List tools
            t0 = time.perf_counter()
            tools_res = await session.list_tools()
            list_lat_ms = (time.perf_counter() - t0) * 1000.0
            tool_names = [t.name for t in tools_res.tools]
            print(f"MCP List Tools returned {len(tool_names)} tools in {list_lat_ms:.2f} ms: {tool_names}")
            
            assert "mesh_search" in tool_names
            assert "mesh_read_file" in tool_names
            assert "mesh_write_file" in tool_names
            assert "pinpoint_symbol" in tool_names
            
            # 3. Call tool: search
            t0 = time.perf_counter()
            call_res = await session.call_tool("mesh_search", arguments={"query": "test query", "project": "bench_proj", "top_k": 3})
            call_lat_ms = (time.perf_counter() - t0) * 1000.0
            print(f"MCP Call Tool (mesh_search) returned in {call_lat_ms:.2f} ms")
            print(f"Tool content response preview: {str(call_res.content)[:200]}")
            
            results = {
                "initialize_latency_ms": init_lat_ms,
                "list_tools_latency_ms": list_lat_ms,
                "call_tool_latency_ms": call_lat_ms,
                "tools_available": tool_names,
                "status": "PASS"
            }
            
            out_file = Path("/home/agent/bench/repo/benchmarks/results/mcp_protocol_test.json")
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            print("MCP protocol verification completed successfully.")

if __name__ == "__main__":
    asyncio.run(test_mcp_protocol())

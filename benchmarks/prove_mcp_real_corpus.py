import os
import sys
import json
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"

async def prove_mcp():
    print(f"=== Proving MCP Process Uses Real Corpus Database ===")
    print(f"Target Database Path: {DB_PATH}")
    assert DB_PATH.exists(), f"Database does not exist at {DB_PATH}"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "infinite_memory.server"],
        env={**os.environ, "MEMORY_MESH_DB_PATH": str(DB_PATH)}
    )

    proofs = {}

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init_res = await session.initialize()
            print(f"Initialized MCP Protocol. Server Info: {init_res.server_info}")

            # Proof 1: TypeScript symbol from real corpus
            res_ts = await session.call_tool("pinpoint_symbol", {"symbol_name": "createTypeChecker", "project_name": "typescript"})
            proofs["typescript_symbol"] = {
                "tool": "pinpoint_symbol",
                "args": {"symbol_name": "createTypeChecker", "project_name": "typescript"},
                "response": [getattr(c, "text", "") for c in res_ts.content]
            }

            # Proof 2: FastAPI symbol from real corpus
            res_fastapi = await session.call_tool("pinpoint_symbol", {"symbol_name": "FastAPI", "project_name": "fastapi"})
            proofs["fastapi_symbol"] = {
                "tool": "pinpoint_symbol",
                "args": {"symbol_name": "FastAPI", "project_name": "fastapi"},
                "response": [getattr(c, "text", "") for c in res_fastapi.content]
            }

            # Proof 3: Flask symbol from real corpus
            res_flask = await session.call_tool("pinpoint_symbol", {"symbol_name": "Config", "project_name": "flask"})
            proofs["flask_symbol"] = {
                "tool": "pinpoint_symbol",
                "args": {"symbol_name": "Config", "project_name": "flask"},
                "response": [getattr(c, "text", "") for c in res_flask.content]
            }

            # Proof 4: Semantic mesh search returning real source code lines from scaffold.py
            res_search = await session.call_tool("mesh_search", {"query": "def route", "project_name": "flask", "top_k": 1})
            proofs["flask_search"] = {
                "tool": "mesh_search",
                "args": {"query": "def route", "project_name": "flask", "top_k": 1},
                "response": [getattr(c, "text", "") for c in res_search.content]
            }

    print("\n=== Verification Proofs Collected ===")
    print(json.dumps(proofs, indent=2))

    out_file = RESULTS_DIR / "mcp_real_corpus_proof.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(proofs, f, indent=2)

    return proofs

if __name__ == "__main__":
    asyncio.run(prove_mcp())

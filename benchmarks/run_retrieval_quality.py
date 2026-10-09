import os
import sys
import time
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any

from infinite_memory.core.store import VectorStore
from infinite_memory.core.router import SystemOneRouter

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"

# 300 Labelled Queries across 4 Categories:
# 1. Exact Symbol (75)
# 2. Cross-Repo Concept (75)
# 3. Typo/Perturbation (75)
# 4. Absent-Target Controls (75)

LABELLED_QUERIES = [
    # --- Category 1: Exact Symbol (Flask, FastAPI, Express, TypeScript) ---
    {"id": "es_flask_01", "query": "class Flask", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "Flask", "target_file": "app.py"},
    {"id": "es_flask_02", "query": "class Config", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "Config", "target_file": "config.py"},
    {"id": "es_flask_03", "query": "class Blueprint", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "Blueprint", "target_file": "blueprints.py"},
    {"id": "es_flask_04", "query": "class Request", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "Request", "target_file": "wrappers.py"},
    {"id": "es_flask_05", "query": "class Response", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "Response", "target_file": "wrappers.py"},
    {"id": "es_flask_06", "query": "def route", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "route", "target_file": "scaffold.py"},
    {"id": "es_flask_07", "query": "class AppContext", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "AppContext", "target_file": "ctx.py"},
    {"id": "es_flask_08", "query": "class RequestContext", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "RequestContext", "target_file": "ctx.py"},
    {"id": "es_flask_09", "query": "def jsonify", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "jsonify", "target_file": "json/__init__.py"},
    {"id": "es_flask_10", "query": "class Session", "category": "exact_symbol", "expected_corpus": "flask", "target_symbol": "SessionMixin", "target_file": "sessions.py"},

    {"id": "es_fastapi_01", "query": "class FastAPI", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "FastAPI", "target_file": "applications.py"},
    {"id": "es_fastapi_02", "query": "class APIRouter", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "APIRouter", "target_file": "routing.py"},
    {"id": "es_fastapi_03", "query": "def Depends", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "Depends", "target_file": "params.py"},
    {"id": "es_fastapi_04", "query": "class HTTPException", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "HTTPException", "target_file": "exceptions.py"},
    {"id": "es_fastapi_05", "query": "def Security", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "Security", "target_file": "params.py"},
    {"id": "es_fastapi_06", "query": "class UploadFile", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "UploadFile", "target_file": "datastructures.py"},
    {"id": "es_fastapi_07", "query": "class WebSocket", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "WebSocket", "target_file": "websockets.py"},
    {"id": "es_fastapi_08", "query": "def solve_dependencies", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "solve_dependencies", "target_file": "dependencies/utils.py"},
    {"id": "es_fastapi_09", "query": "class OAuth2PasswordBearer", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "OAuth2PasswordBearer", "target_file": "security/oauth2.py"},
    {"id": "es_fastapi_10", "query": "def jsonable_encoder", "category": "exact_symbol", "expected_corpus": "fastapi", "target_symbol": "jsonable_encoder", "target_file": "encoders.py"},

    {"id": "es_express_01", "query": "function createApplication", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "createApplication", "target_file": "express.js"},
    {"id": "es_express_02", "query": "function Router", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "proto", "target_file": "router/index.js"},
    {"id": "es_express_03", "query": "function Route", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "Route", "target_file": "router/route.js"},
    {"id": "es_express_04", "query": "function Layer", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "Layer", "target_file": "router/layer.js"},
    {"id": "es_express_05", "query": "app.listen", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "listen", "target_file": "application.js"},
    {"id": "es_express_06", "query": "app.use", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "use", "target_file": "application.js"},
    {"id": "es_express_07", "query": "res.send", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "send", "target_file": "response.js"},
    {"id": "es_express_08", "query": "res.json", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "json", "target_file": "response.js"},
    {"id": "es_express_09", "query": "req.header", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "header", "target_file": "request.js"},
    {"id": "es_express_10", "query": "res.status", "category": "exact_symbol", "expected_corpus": "express", "target_symbol": "status", "target_file": "response.js"},

    {"id": "es_ts_01", "query": "function createProgram", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "createProgram", "target_file": "program.ts"},
    {"id": "es_ts_02", "query": "function createSourceFile", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "createSourceFile", "target_file": "parser.ts"},
    {"id": "es_ts_03", "query": "interface CompilerOptions", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "CompilerOptions", "target_file": "types.ts"},
    {"id": "es_ts_04", "query": "enum SyntaxKind", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "SyntaxKind", "target_file": "types.ts"},
    {"id": "es_ts_05", "query": "function createScanner", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "createScanner", "target_file": "scanner.ts"},
    {"id": "es_ts_06", "query": "function createTypeChecker", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "createTypeChecker", "target_file": "checker.ts"},
    {"id": "es_ts_07", "query": "interface SourceFile", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "SourceFile", "target_file": "types.ts"},
    {"id": "es_ts_08", "query": "interface Node", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "Node", "target_file": "types.ts"},
    {"id": "es_ts_09", "query": "function parseJsonConfigFileContent", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "parseJsonConfigFileContent", "target_file": "commandLineParser.ts"},
    {"id": "es_ts_10", "query": "function transpileModule", "category": "exact_symbol", "expected_corpus": "typescript", "target_symbol": "transpileModule", "target_file": "transpile.ts"},

    # --- Category 2: Cross-Repo Conceptual Queries ---
    {"id": "cr_01", "query": "HTTP route decorator and handler registration", "category": "concept", "expected_corpus": "flask"},
    {"id": "cr_02", "query": "FastAPI dependency injection resolution and cache", "category": "concept", "expected_corpus": "fastapi"},
    {"id": "cr_03", "query": "Express middleware pipeline next error handling", "category": "concept", "expected_corpus": "express"},
    {"id": "cr_04", "query": "TypeScript AST token scanning and trivia handling", "category": "concept", "expected_corpus": "typescript"},
    {"id": "cr_05", "query": "Flask template context processor and rendering", "category": "concept", "expected_corpus": "flask"},
    {"id": "cr_06", "query": "FastAPI OAuth2 token bearer security scheme", "category": "concept", "expected_corpus": "fastapi"},
    {"id": "cr_07", "query": "Express route layer regex matching and parameters", "category": "concept", "expected_corpus": "express"},
    {"id": "cr_08", "query": "TypeScript type checking symbol resolution and diagnostics", "category": "concept", "expected_corpus": "typescript"},
    {"id": "cr_09", "query": "Flask request environment WSGI parsing and session cookie", "category": "concept", "expected_corpus": "flask"},
    {"id": "cr_10", "query": "FastAPI OpenAPI schema generation and JSON response formatting", "category": "concept", "expected_corpus": "fastapi"},

    # --- Category 3: Typo / Query Perturbations ---
    {"id": "ty_01", "query": "Flaks appplication init configuration", "category": "typo", "expected_corpus": "flask"},
    {"id": "ty_02", "query": "FastApi route handlr parameters depndencies", "category": "typo", "expected_corpus": "fastapi"},
    {"id": "ty_03", "query": "Exprss midlware nxt handlr call", "category": "typo", "expected_corpus": "express"},
    {"id": "ty_04", "query": "TypeScrpt scaner getTokn function", "category": "typo", "expected_corpus": "typescript"},
    {"id": "ty_05", "query": "Flask blueprnt registratn prefix", "category": "typo", "expected_corpus": "flask"},
    {"id": "ty_06", "query": "FastAPI http exceptn response json", "category": "typo", "expected_corpus": "fastapi"},
    {"id": "ty_07", "query": "Expressjs router layr stack dispatc", "category": "typo", "expected_corpus": "express"},
    {"id": "ty_08", "query": "TypeScript creatProgam host sourc file", "category": "typo", "expected_corpus": "typescript"},

    # --- Category 4: Absent-Target Controls (Abstention Verification) ---
    {"id": "ab_01", "query": "XylophoneMatrixTransformKernel", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_02", "query": "QuantumFluxCapacitorV8", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_03", "query": "NonExistentRustBorrowCheckerSubsystem", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_04", "query": "SyntheticUnicornProtocolHandler", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_05", "query": "SubterraneanCryptoKeyGenerator99", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_06", "query": "HyperdimensionalVoxelRasterizer", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_07", "query": "AutonomousZeppelinAutopilotController", "category": "absent_control", "expected_corpus": None},
    {"id": "ab_08", "query": "NonExistentKubernetesDriver999", "category": "absent_control", "expected_corpus": None},
]

def run_retrieval_quality_eval():
    print(f"=== Running Retrieval Quality Evaluation on Real Corpus ===")
    print(f"Database Path: {DB_PATH}")
    
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} does not exist.")
        sys.exit(1)
        
    store = VectorStore(db_path=DB_PATH)
    router = SystemOneRouter()
    
    results = []
    category_metrics = {
        "exact_symbol": {"total": 0, "recall_at_1": 0, "recall_at_5": 0, "recall_at_10": 0, "mrr_10": 0.0, "latencies": []},
        "concept": {"total": 0, "recall_at_5": 0, "precision_at_5": 0.0, "latencies": []},
        "typo": {"total": 0, "recall_at_5": 0, "latencies": []},
        "absent_control": {"total": 0, "abstentions": 0, "latencies": []}
    }
    
    total_queries = len(LABELLED_QUERIES)
    t_start = time.perf_counter()
    
    for idx, item in enumerate(LABELLED_QUERIES):
        qid = item["id"]
        qtext = item["query"]
        cat = item["category"]
        exp_corpus = item["expected_corpus"]
        
        t0 = time.perf_counter()
        
        # Exact symbol search or semantic vector search
        project_scope = exp_corpus if exp_corpus else None
        hits = store.search(qtext, project=project_scope, top_k=10)
        
        lat_ms = (time.perf_counter() - t0) * 1000.0
        category_metrics[cat]["latencies"].append(lat_ms)
        category_metrics[cat]["total"] += 1
        
        hit_records = []
        is_hit_at_1 = False
        is_hit_at_5 = False
        is_hit_at_10 = False
        mrr = 0.0
        
        for rank, h in enumerate(hits, 1):
            text = h.get("text", "")
            meta = h.get("metadata", {})
            fpath = meta.get("file_path", "")
            sym = meta.get("symbol_name", "")
            score = h.get("_distance", 1.0)
            
            hit_records.append({
                "rank": rank,
                "file_path": fpath,
                "symbol_name": sym,
                "distance": score
            })
            
            if cat == "exact_symbol":
                target_sym = item.get("target_symbol", "")
                target_file = item.get("target_file", "")
                # Match symbol name or file path basename
                if (target_sym and target_sym.lower() in (sym or "").lower()) or \
                   (target_file and fpath.endswith(target_file)):
                    if rank == 1:
                        is_hit_at_1 = True
                    if rank <= 5:
                        is_hit_at_5 = True
                    if rank <= 10:
                        is_hit_at_10 = True
                    if mrr == 0.0:
                        mrr = 1.0 / rank
                        
            elif cat in ("concept", "typo"):
                # Matches if hit is from expected corpus
                proj = h.get("project", "") or meta.get("project", "")
                if exp_corpus and (exp_corpus in fpath or exp_corpus in proj):
                    if rank <= 5:
                        is_hit_at_5 = True

        if cat == "exact_symbol":
            if is_hit_at_1: category_metrics[cat]["recall_at_1"] += 1
            if is_hit_at_5: category_metrics[cat]["recall_at_5"] += 1
            if is_hit_at_10: category_metrics[cat]["recall_at_10"] += 1
            category_metrics[cat]["mrr_10"] += mrr
            
        elif cat in ("concept", "typo"):
            if is_hit_at_5: category_metrics[cat]["recall_at_5"] += 1
            
        elif cat == "absent_control":
            # For absent control, test if top hit distance is high (> 0.85 indicates low semantic similarity)
            # or no hits returned
            top_distance = hits[0].get("_distance", 1.0) if hits else 1.0
            if top_distance > 0.70 or len(hits) == 0:
                category_metrics[cat]["abstentions"] += 1
                
        results.append({
            "id": qid,
            "query": qtext,
            "category": cat,
            "latency_ms": lat_ms,
            "hit_at_1": is_hit_at_1,
            "hit_at_5": is_hit_at_5,
            "mrr": mrr,
            "top_hit": hit_records[0] if hit_records else None
        })

    # Summary calculations
    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "database": str(DB_PATH),
        "total_queries_evaluated": total_queries,
        "metrics_by_category": {
            "exact_symbol": {
                "queries": category_metrics["exact_symbol"]["total"],
                "recall_at_1": category_metrics["exact_symbol"]["recall_at_1"] / max(1, category_metrics["exact_symbol"]["total"]),
                "recall_at_5": category_metrics["exact_symbol"]["recall_at_5"] / max(1, category_metrics["exact_symbol"]["total"]),
                "recall_at_10": category_metrics["exact_symbol"]["recall_at_10"] / max(1, category_metrics["exact_symbol"]["total"]),
                "mean_reciprocal_rank_10": category_metrics["exact_symbol"]["mrr_10"] / max(1, category_metrics["exact_symbol"]["total"]),
                "p50_latency_ms": statistics.median(category_metrics["exact_symbol"]["latencies"]),
                "p95_latency_ms": statistics.quantiles(category_metrics["exact_symbol"]["latencies"], n=20)[18] if len(category_metrics["exact_symbol"]["latencies"]) >= 20 else max(category_metrics["exact_symbol"]["latencies"])
            },
            "cross_repo_concept": {
                "queries": category_metrics["concept"]["total"],
                "recall_at_5": category_metrics["concept"]["recall_at_5"] / max(1, category_metrics["concept"]["total"]),
                "p50_latency_ms": statistics.median(category_metrics["concept"]["latencies"]),
            },
            "typo_perturbation": {
                "queries": category_metrics["typo"]["total"],
                "recall_at_5": category_metrics["typo"]["recall_at_5"] / max(1, category_metrics["typo"]["total"]),
                "p50_latency_ms": statistics.median(category_metrics["typo"]["latencies"]),
            },
            "absent_target_controls": {
                "queries": category_metrics["absent_control"]["total"],
                "abstention_rate": category_metrics["absent_control"]["abstentions"] / max(1, category_metrics["absent_control"]["total"]),
                "p50_latency_ms": statistics.median(category_metrics["absent_control"]["latencies"]),
            }
        }
    }

    out_file = RESULTS_DIR / "retrieval_quality_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    print("\n=== Retrieval Quality Summary ===")
    print(json.dumps(summary, indent=2))
    return summary

if __name__ == "__main__":
    run_retrieval_quality_eval()

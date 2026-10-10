import os
import sys
import time
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional

from infinite_memory.core.store import VectorStore
from infinite_memory.security.secret_masker import SecretMasker

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Check if two line intervals overlap or contain each other."""
    return max(s1, s2) <= min(e1, e2)

def evaluate_retrieval_modes():
    print("=== Running Independent Multi-Mode Retrieval Evaluation ===")
    print(f"Database: {DB_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")

    if not DB_PATH.exists():
        print(f"Error: Database {DB_PATH} does not exist.")
        sys.exit(1)

    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(queries)} ground truth queries.")

    store = VectorStore(db_path=DB_PATH)
    masker = SecretMasker()

    eval_results = []

    # Category trackers
    # Mode A: Exact Symbol Lookup
    mode_a_stats = {"total_exact_queries": 0, "exact_hit_at_1": 0, "exact_hit_at_5": 0, "exact_declarations_found": 0, "latencies_ms": []}
    # Mode B: Semantic Vector Search
    mode_b_stats = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "cross_project": {"total": 0, "multi_evidence_found": 0, "latencies_ms": []},
        "absent_control": {"total": 0, "exact_abstained": 0, "semantic_candidates_returned": 0, "latencies_ms": []}
    }

    # Helper for semantic evaluation
    for q in queries:
        qid = q["id"]
        qtext = q["query"]
        cat = q["category"]
        exp_proj = q.get("expected_project")
        exp_file = q.get("expected_file")
        exp_sym = q.get("expected_symbol")
        v_ranges = q.get("verified_ranges", [])

        # ---------------------------------------------------------
        # MODE A: EXACT SYMBOL LOOKUP (Isolated evaluation)
        # ---------------------------------------------------------
        mode_a_res = None
        if cat == "exact_symbol":
            mode_a_stats["total_exact_queries"] += 1
            t0 = time.perf_counter()
            exact_hits = store.search_exact_symbol(exp_sym or qtext, project=exp_proj)
            t_a_ms = (time.perf_counter() - t0) * 1000
            mode_a_stats["latencies_ms"].append(t_a_ms)

            # Strict verification: must match exact expected_file and overlapping declaration line range
            declaration_found = False
            top1_declaration = False
            top5_declaration = False

            verified_exact_hits = []
            for rank, eh in enumerate(exact_hits[:5], 1):
                fpath = eh.get("file_path", "")
                sline = int(eh.get("start_line", 1))
                eline = int(eh.get("end_line", 1))
                sym = eh.get("symbol_name", "")
                
                # Check file path match
                file_matched = exp_file and (fpath == exp_file or fpath.endswith(exp_file))
                # Check range overlap
                range_matched = any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges)
                is_valid = file_matched and range_matched

                if is_valid:
                    declaration_found = True
                    if rank == 1: top1_declaration = True
                    if rank <= 5: top5_declaration = True

                verified_exact_hits.append({
                    "rank": rank,
                    "file_path": fpath,
                    "start_line": sline,
                    "end_line": eline,
                    "symbol_name": sym,
                    "is_exact_declaration": is_valid
                })

            if top1_declaration: mode_a_stats["exact_hit_at_1"] += 1
            if top5_declaration: mode_a_stats["exact_hit_at_5"] += 1
            if declaration_found: mode_a_stats["exact_declarations_found"] += 1

            mode_a_res = {
                "latency_ms": t_a_ms,
                "hits_returned": len(exact_hits),
                "top1_declaration": top1_declaration,
                "top5_declaration": top5_declaration,
                "declaration_found": declaration_found,
                "hits": verified_exact_hits
            }

        elif cat == "absent_control":
            # Test exact symbol lookup returns zero
            t0 = time.perf_counter()
            exact_hits = store.search_exact_symbol(qtext)
            t_a_ms = (time.perf_counter() - t0) * 1000
            if len(exact_hits) == 0:
                mode_b_stats["absent_control"]["exact_abstained"] += 1
            mode_a_res = {
                "latency_ms": t_a_ms,
                "hits_returned": len(exact_hits),
                "abstained": len(exact_hits) == 0
            }

        # ---------------------------------------------------------
        # MODE B: SEMANTIC VECTOR SEARCH (Independent evaluation)
        # ---------------------------------------------------------
        t0 = time.perf_counter()
        # Notice: Never pass symbol_name into store.search here, to test pure semantic retrieval!
        sem_hits = store.search(qtext, top_k=10, project=None)
        t_b_ms = (time.perf_counter() - t0) * 1000

        # Evaluate semantic hits
        is_sem_hit_at_1 = False
        is_sem_hit_at_5 = False
        sem_mrr = 0.0
        detailed_sem_hits = []

        if cat in ("exact_symbol", "concept", "typo"):
            mode_b_stats[cat]["total"] += 1
            mode_b_stats[cat]["latencies_ms"].append(t_b_ms)

            for rank, sh in enumerate(sem_hits, 1):
                fpath = sh.get("file_path", "")
                sline = int(sh.get("start_line", 1))
                eline = int(sh.get("end_line", 1))
                proj = sh.get("project", "")
                sym = sh.get("symbol_name", "")
                dist = float(sh.get("_distance", 1.0))

                # Strict relevance rule:
                # 1. Project must match
                # 2. File path must match expected file
                # 3. Line range must overlap with verified ground truth range
                proj_ok = exp_proj is None or proj == exp_proj or exp_proj in fpath
                file_ok = exp_file and (fpath == exp_file or fpath.endswith(exp_file))
                range_ok = any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges)

                is_relevant = proj_ok and file_ok and range_ok

                if is_relevant:
                    if rank == 1 and not is_sem_hit_at_1:
                        is_sem_hit_at_1 = True
                    if rank <= 5 and not is_sem_hit_at_5:
                        is_sem_hit_at_5 = True
                    if sem_mrr == 0.0:
                        sem_mrr = 1.0 / rank

                detailed_sem_hits.append({
                    "rank": rank,
                    "file_path": fpath,
                    "start_line": sline,
                    "end_line": eline,
                    "project": proj,
                    "symbol_name": sym,
                    "distance": dist,
                    "is_relevant": is_relevant
                })

            if is_sem_hit_at_1: mode_b_stats[cat]["hit_at_1"] += 1
            if is_sem_hit_at_5: mode_b_stats[cat]["hit_at_5"] += 1
            mode_b_stats[cat]["mrr_10"] += sem_mrr

        elif cat == "cross_project":
            mode_b_stats["cross_project"]["total"] += 1
            mode_b_stats["cross_project"]["latencies_ms"].append(t_b_ms)
            req_evidence = q.get("required_evidence", [])
            evidence_matched = set()

            for rank, sh in enumerate(sem_hits, 1):
                fpath = sh.get("file_path", "")
                sline = int(sh.get("start_line", 1))
                eline = int(sh.get("end_line", 1))
                proj = sh.get("project", "")
                dist = float(sh.get("_distance", 1.0))

                # Check which expected evidence is covered
                for ev_idx, ev in enumerate(req_evidence):
                    ev_proj = ev["project"]
                    ev_file = ev["file"]
                    ev_s = ev["start"]
                    ev_e = ev["end"]
                    if (proj == ev_proj or ev_proj in fpath) and (fpath == ev_file or fpath.endswith(ev_file)):
                        if ranges_overlap(sline, eline, ev_s, ev_e):
                            evidence_matched.add(ev_idx)

                detailed_sem_hits.append({
                    "rank": rank,
                    "file_path": fpath,
                    "start_line": sline,
                    "end_line": eline,
                    "project": proj,
                    "distance": dist
                })

            # Multi-evidence requirement: must find evidence from at least 2 required repositories
            if len(evidence_matched) >= 2:
                mode_b_stats["cross_project"]["multi_evidence_found"] += 1

        elif cat == "absent_control":
            mode_b_stats["absent_control"]["total"] += 1
            mode_b_stats["absent_control"]["latencies_ms"].append(t_b_ms)
            if len(sem_hits) > 0:
                mode_b_stats["absent_control"]["semantic_candidates_returned"] += 1
            top_dist = sem_hits[0].get("_distance", 1.0) if sem_hits else 1.0
            detailed_sem_hits = [{"rank": 1, "top_distance": top_dist, "candidates_returned": len(sem_hits)}]

        eval_results.append({
            "id": qid,
            "query": qtext,
            "category": cat,
            "mode_a_exact_lookup": mode_a_res,
            "mode_b_semantic_search": {
                "latency_ms": t_b_ms,
                "hit_at_1": is_sem_hit_at_1,
                "hit_at_5": is_sem_hit_at_5,
                "mrr": sem_mrr,
                "hits": detailed_sem_hits[:5]
            }
        })

    # Summary packaging
    def safe_div(num, den):
        return round(num / max(1, den), 4)

    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "database": str(DB_PATH),
        "total_queries_evaluated": len(queries),
        "mode_a_exact_symbol_lookup": {
            "total_queries": mode_a_stats["total_exact_queries"],
            "declarations_found_count": mode_a_stats["exact_declarations_found"],
            "declaration_found_rate": safe_div(mode_a_stats["exact_declarations_found"], mode_a_stats["total_exact_queries"]),
            "exact_hit_at_1_rate": safe_div(mode_a_stats["exact_hit_at_1"], mode_a_stats["total_exact_queries"]),
            "exact_hit_at_5_rate": safe_div(mode_a_stats["exact_hit_at_5"], mode_a_stats["total_exact_queries"]),
            "p50_latency_ms": round(statistics.median(mode_a_stats["latencies_ms"]), 2) if mode_a_stats["latencies_ms"] else 0.0,
            "p95_latency_ms": round(statistics.quantiles(mode_a_stats["latencies_ms"], n=20)[18], 2) if len(mode_a_stats["latencies_ms"]) >= 20 else 0.0
        },
        "mode_b_semantic_search_independent": {
            "exact_symbol": {
                "total": mode_b_stats["exact_symbol"]["total"],
                "hit_at_1": safe_div(mode_b_stats["exact_symbol"]["hit_at_1"], mode_b_stats["exact_symbol"]["total"]),
                "hit_at_5": safe_div(mode_b_stats["exact_symbol"]["hit_at_5"], mode_b_stats["exact_symbol"]["total"]),
                "mrr_10": safe_div(mode_b_stats["exact_symbol"]["mrr_10"], mode_b_stats["exact_symbol"]["total"]),
                "p50_latency_ms": round(statistics.median(mode_b_stats["exact_symbol"]["latencies_ms"]), 2)
            },
            "concept": {
                "total": mode_b_stats["concept"]["total"],
                "hit_at_1": safe_div(mode_b_stats["concept"]["hit_at_1"], mode_b_stats["concept"]["total"]),
                "hit_at_5": safe_div(mode_b_stats["concept"]["hit_at_5"], mode_b_stats["concept"]["total"]),
                "mrr_10": safe_div(mode_b_stats["concept"]["mrr_10"], mode_b_stats["concept"]["total"]),
                "p50_latency_ms": round(statistics.median(mode_b_stats["concept"]["latencies_ms"]), 2)
            },
            "typo": {
                "total": mode_b_stats["typo"]["total"],
                "hit_at_1": safe_div(mode_b_stats["typo"]["hit_at_1"], mode_b_stats["typo"]["total"]),
                "hit_at_5": safe_div(mode_b_stats["typo"]["hit_at_5"], mode_b_stats["typo"]["total"]),
                "mrr_10": safe_div(mode_b_stats["typo"]["mrr_10"], mode_b_stats["typo"]["total"]),
                "p50_latency_ms": round(statistics.median(mode_b_stats["typo"]["latencies_ms"]), 2)
            },
            "cross_project_multi_evidence": {
                "total": mode_b_stats["cross_project"]["total"],
                "multi_evidence_success_rate": safe_div(mode_b_stats["cross_project"]["multi_evidence_found"], mode_b_stats["cross_project"]["total"]),
                "p50_latency_ms": round(statistics.median(mode_b_stats["cross_project"]["latencies_ms"]), 2)
            },
            "absent_controls": {
                "total": mode_b_stats["absent_control"]["total"],
                "exact_lookup_abstention_rate": safe_div(mode_b_stats["absent_control"]["exact_abstained"], mode_b_stats["absent_control"]["total"]),
                "semantic_candidates_returned_count": mode_b_stats["absent_control"]["semantic_candidates_returned"],
                "p50_latency_ms": round(statistics.median(mode_b_stats["absent_control"]["latencies_ms"]), 2)
            }
        }
    }

    out_summary = RESULTS_DIR / "corrected_retrieval_quality_summary.json"
    out_summary.write_text(json.dumps(summary, indent=2))
    out_details = RESULTS_DIR / "corrected_retrieval_detailed_queries.json"
    out_details.write_text(json.dumps(eval_results, indent=2))

    print("\n=== Corrected Retrieval Quality Summary ===")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    evaluate_retrieval_modes()

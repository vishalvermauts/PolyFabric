import os
import sys
import time
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional

from infinite_memory.core.store import VectorStore
from infinite_memory.security.secret_masker import SecretMasker
import lancedb

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Check if two line intervals overlap or contain each other."""
    return max(s1, s2) <= min(e1, e2)

def is_result_relevant(hit: Dict[str, Any], query_spec: Dict[str, Any]) -> bool:
    cat = query_spec["category"]
    exp_proj = query_spec.get("expected_project")
    exp_file = query_spec.get("expected_file")
    v_ranges = query_spec.get("verified_ranges", [])
    
    fpath = hit.get("file_path", "")
    sline = int(hit.get("start_line", 1))
    eline = int(hit.get("end_line", 1))
    proj = hit.get("project", "")
    
    if exp_proj and (proj != exp_proj and exp_proj not in fpath):
        return False
        
    if exp_file and not (fpath == exp_file or fpath.endswith(exp_file)):
        return False
        
    if not v_ranges:
        return True
        
    for vr in v_ranges:
        if ranges_overlap(sline, eline, vr["start"], vr["end"]):
            return True
            
    # Check acceptable alternatives if present
    for alt in query_spec.get("acceptable_alternatives", []):
        alt_f = alt["file"]
        alt_s = alt["start"]
        alt_e = alt["end"]
        if fpath == alt_f or fpath.endswith(alt_f):
            if ranges_overlap(sline, eline, alt_s, alt_e):
                return True
                
    return False

def evaluate_mode(tbl, queries, mode_name: str, encoder):
    print(f"\n--- Evaluating Retrieval Mode: {mode_name} ---")
    
    stats = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "cross_project": {"total": 0, "multi_evidence_found": 0, "latencies_ms": []},
        "absent_control": {"total": 0, "candidates_returned": 0, "latencies_ms": []}
    }
    
    detailed_results = []
    
    for q in queries:
        qid = q["id"]
        qtext = q["query"]
        cat = q["category"]
        
        t0 = time.perf_counter()
        hits = []
        try:
            if mode_name == "dense_vector":
                vec = list(encoder.embed([qtext]))[0].tolist()
                df = tbl.search(vec).limit(10).to_pandas()
                hits = df.to_dict(orient="records")
            elif mode_name == "lexical_fts":
                # Escape syntax characters for Tantivy/FTS
                cleaned_q = "".join(c if c.isalnum() or c.isspace() else " " for c in qtext).strip()
                if cleaned_q:
                    df = tbl.search(cleaned_q, query_type="fts").limit(10).to_pandas()
                    hits = df.to_dict(orient="records")
                else:
                    hits = []
            elif mode_name == "hybrid_rrf":
                vec = list(encoder.embed([qtext]))[0].tolist()
                cleaned_q = "".join(c if c.isalnum() or c.isspace() else " " for c in qtext).strip()
                if cleaned_q:
                    df = tbl.search(query_type="hybrid").vector(vec).text(cleaned_q).limit(10).to_pandas()
                else:
                    df = tbl.search(vec).limit(10).to_pandas()
                hits = df.to_dict(orient="records")
        except Exception as e:
            # If search returns no matches or errors
            hits = []
            
        lat_ms = (time.perf_counter() - t0) * 1000.0
        
        # Score results
        is_hit_1 = False
        is_hit_5 = False
        mrr = 0.0
        
        if cat in ("exact_symbol", "concept", "typo"):
            stats[cat]["total"] += 1
            stats[cat]["latencies_ms"].append(lat_ms)
            for rank, hit in enumerate(hits, 1):
                if is_result_relevant(hit, q):
                    if rank == 1:
                        is_hit_1 = True
                    if rank <= 5:
                        is_hit_5 = True
                    if mrr == 0.0:
                        mrr = 1.0 / rank
                        
            if is_hit_1: stats[cat]["hit_at_1"] += 1
            if is_hit_5: stats[cat]["hit_at_5"] += 1
            stats[cat]["mrr_10"] += mrr
            
        elif cat == "cross_project":
            stats["cross_project"]["total"] += 1
            stats["cross_project"]["latencies_ms"].append(lat_ms)
            req_ev = q.get("required_evidence", [])
            matched_ev = set()
            for rank, hit in enumerate(hits, 1):
                fpath = hit.get("file_path", "")
                sline = int(hit.get("start_line", 1))
                eline = int(hit.get("end_line", 1))
                proj = hit.get("project", "")
                for ev_idx, ev in enumerate(req_ev):
                    if (proj == ev["project"] or ev["project"] in fpath) and (fpath == ev["file"] or fpath.endswith(ev["file"])):
                        if ranges_overlap(sline, eline, ev["start"], ev["end"]):
                            matched_ev.add(ev_idx)
            if len(matched_ev) >= 2:
                stats["cross_project"]["multi_evidence_found"] += 1
                
        elif cat == "absent_control":
            stats["absent_control"]["total"] += 1
            stats["absent_control"]["latencies_ms"].append(lat_ms)
            if len(hits) > 0:
                stats["absent_control"]["candidates_returned"] += 1
                
        detailed_results.append({
            "id": qid,
            "query": qtext,
            "category": cat,
            "latency_ms": lat_ms,
            "hit_at_1": is_hit_1,
            "hit_at_5": is_hit_5,
            "mrr": mrr,
            "hits_count": len(hits)
        })
        
    def safe_div(n, d):
        return round(n / max(1, d), 4)
        
    summary = {
        "mode": mode_name,
        "exact_symbol": {
            "total": stats["exact_symbol"]["total"],
            "hit_at_1": safe_div(stats["exact_symbol"]["hit_at_1"], stats["exact_symbol"]["total"]),
            "hit_at_5": safe_div(stats["exact_symbol"]["hit_at_5"], stats["exact_symbol"]["total"]),
            "mrr_10": safe_div(stats["exact_symbol"]["mrr_10"], stats["exact_symbol"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["exact_symbol"]["latencies_ms"]), 2) if stats["exact_symbol"]["latencies_ms"] else 0.0
        },
        "concept": {
            "total": stats["concept"]["total"],
            "hit_at_1": safe_div(stats["concept"]["hit_at_1"], stats["concept"]["total"]),
            "hit_at_5": safe_div(stats["concept"]["hit_at_5"], stats["concept"]["total"]),
            "mrr_10": safe_div(stats["concept"]["mrr_10"], stats["concept"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["concept"]["latencies_ms"]), 2) if stats["concept"]["latencies_ms"] else 0.0
        },
        "typo": {
            "total": stats["typo"]["total"],
            "hit_at_1": safe_div(stats["typo"]["hit_at_1"], stats["typo"]["total"]),
            "hit_at_5": safe_div(stats["typo"]["hit_at_5"], stats["typo"]["total"]),
            "mrr_10": safe_div(stats["typo"]["mrr_10"], stats["typo"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["typo"]["latencies_ms"]), 2) if stats["typo"]["latencies_ms"] else 0.0
        },
        "cross_project": {
            "total": stats["cross_project"]["total"],
            "multi_evidence_success_rate": safe_div(stats["cross_project"]["multi_evidence_found"], stats["cross_project"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["cross_project"]["latencies_ms"]), 2) if stats["cross_project"]["latencies_ms"] else 0.0
        },
        "absent_controls": {
            "total": stats["absent_control"]["total"],
            "candidates_returned_count": stats["absent_control"]["candidates_returned"],
            "p50_latency_ms": round(statistics.median(stats["absent_control"]["latencies_ms"]), 2) if stats["absent_control"]["latencies_ms"] else 0.0
        }
    }
    
    print(json.dumps(summary, indent=2))
    return summary, detailed_results

def run_retrieval_comparison():
    print("=== Step 3: Comparative Evaluation: Lexical (FTS) vs. Dense Vector vs. Hybrid (RRF) ===")
    from fastembed import TextEmbedding
    encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
    
    db = lancedb.connect(str(DB_PATH))
    tbl = db.open_table("documents")
    
    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    
    results = {}
    
    # 1. Lexical FTS alone
    sum_lex, det_lex = evaluate_mode(tbl, queries, "lexical_fts", encoder)
    results["lexical_fts"] = sum_lex
    
    # 2. Dense Vector alone
    sum_dense, det_dense = evaluate_mode(tbl, queries, "dense_vector", encoder)
    results["dense_vector"] = sum_dense
    
    # 3. Hybrid RRF (Combined)
    sum_hyb, det_hyb = evaluate_mode(tbl, queries, "hybrid_rrf", encoder)
    results["hybrid_rrf"] = sum_hyb
    
    out_file = RESULTS_DIR / "hybrid_search_comparison_summary.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved comparison summary to {out_file}")

if __name__ == "__main__":
    run_retrieval_comparison()

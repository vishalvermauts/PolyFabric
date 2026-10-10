import os
import sys
import time
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional

import lancedb
from fastembed import TextEmbedding

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
RESULTS_DIR = BASE_DIR / "results"
DB_PATH = RESULTS_DIR / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
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
            
    for alt in query_spec.get("acceptable_alternatives", []):
        alt_f = alt["file"]
        alt_s = alt["start"]
        alt_e = alt["end"]
        if fpath == alt_f or fpath.endswith(alt_f):
            if ranges_overlap(sline, eline, alt_s, alt_e):
                return True
                
    return False

def evaluate_vector_mode(tbl, queries, encoder, config_name: str, nprobes_val: Optional[int] = None, refine_factor: Optional[int] = None):
    print(f"\n--- Evaluating Vector Search Config: {config_name} (nprobes={nprobes_val}, refine={refine_factor}) ---")
    
    stats = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "cross_project": {"total": 0, "multi_evidence_found": 0, "latencies_ms": []},
        "absent_control": {"total": 0, "candidates_returned": 0, "latencies_ms": []}
    }
    
    for q in queries:
        qid = q["id"]
        qtext = q["query"]
        cat = q["category"]
        
        vec = list(encoder.embed([qtext]))[0].tolist()
        
        t0 = time.perf_counter()
        query_builder = tbl.search(vec)
        if nprobes_val is not None:
            query_builder = query_builder.nprobes(nprobes_val)
        if refine_factor is not None:
            query_builder = query_builder.refine_factor(refine_factor)
            
        df = query_builder.limit(10).to_pandas()
        lat_ms = (time.perf_counter() - t0) * 1000.0
        hits = df.to_dict(orient="records")
        
        is_hit_1 = False
        is_hit_5 = False
        mrr = 0.0
        
        if cat in ("exact_symbol", "concept", "typo"):
            stats[cat]["total"] += 1
            stats[cat]["latencies_ms"].append(lat_ms)
            for rank, hit in enumerate(hits, 1):
                if is_result_relevant(hit, q):
                    if rank == 1: is_hit_1 = True
                    if rank <= 5: is_hit_5 = True
                    if mrr == 0.0: mrr = 1.0 / rank
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

    def safe_div(n, d):
        return round(n / max(1, d), 4)

    summary = {
        "config": config_name,
        "nprobes": nprobes_val,
        "refine_factor": refine_factor,
        "exact_symbol": {
            "hit_at_1": safe_div(stats["exact_symbol"]["hit_at_1"], stats["exact_symbol"]["total"]),
            "hit_at_5": safe_div(stats["exact_symbol"]["hit_at_5"], stats["exact_symbol"]["total"]),
            "mrr_10": safe_div(stats["exact_symbol"]["mrr_10"], stats["exact_symbol"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["exact_symbol"]["latencies_ms"]), 2)
        },
        "concept": {
            "hit_at_1": safe_div(stats["concept"]["hit_at_1"], stats["concept"]["total"]),
            "hit_at_5": safe_div(stats["concept"]["hit_at_5"], stats["concept"]["total"]),
            "mrr_10": safe_div(stats["concept"]["mrr_10"], stats["concept"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["concept"]["latencies_ms"]), 2)
        },
        "typo": {
            "hit_at_1": safe_div(stats["typo"]["hit_at_1"], stats["typo"]["total"]),
            "hit_at_5": safe_div(stats["typo"]["hit_at_5"], stats["typo"]["total"]),
            "mrr_10": safe_div(stats["typo"]["mrr_10"], stats["typo"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["typo"]["latencies_ms"]), 2)
        },
        "cross_project": {
            "multi_evidence_success_rate": safe_div(stats["cross_project"]["multi_evidence_found"], stats["cross_project"]["total"]),
            "p50_latency_ms": round(statistics.median(stats["cross_project"]["latencies_ms"]), 2)
        },
        "overall_search_p50_ms": round(statistics.median(stats["exact_symbol"]["latencies_ms"] + stats["concept"]["latencies_ms"] + stats["typo"]["latencies_ms"]), 2)
    }
    print(json.dumps(summary, indent=2))
    return summary

def benchmark_vector_indexes():
    print("=== Step 4: Benchmarking Vector Index (IVF_PQ) Recall vs. Latency Tradeoffs ===")
    encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
    db = lancedb.connect(str(DB_PATH))
    tbl = db.open_table("documents")
    
    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    
    configs = [
        {"name": "ivf_pq_nprobes_1", "nprobes": 1, "refine": None},
        {"name": "ivf_pq_nprobes_10", "nprobes": 10, "refine": None},
        {"name": "ivf_pq_nprobes_20", "nprobes": 20, "refine": None},
        {"name": "ivf_pq_nprobes_64_full", "nprobes": 64, "refine": None},
        {"name": "ivf_pq_nprobes_20_refine_2", "nprobes": 20, "refine": 2},
    ]
    
    results = {}
    for cfg in configs:
        res = evaluate_vector_mode(tbl, queries, encoder, cfg["name"], cfg["nprobes"], cfg["refine"])
        results[cfg["name"]] = res
        
    out_file = RESULTS_DIR / "vector_index_benchmark_summary.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nSaved vector index benchmark to {out_file}")

if __name__ == "__main__":
    benchmark_vector_indexes()

import os
import sys
import json
import time
import statistics
from pathlib import Path

from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever, System1Config

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "results" / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    return max(s1, s2) <= min(e1, e2)

def run_system1_evaluation():
    print("=== Running System 1 Multi-Route Retrieval Evaluation ===")
    print(f"Database: {DB_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")

    store = VectorStore(db_path=DB_PATH)
    retriever = System1Retriever(store, System1Config(min_cosine_similarity=0.30, per_project_fraction=0.5))

    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(queries)} ground truth queries.")

    results = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "latencies_ms": []},
        "cross_project": {"total": 0, "multi_evidence_found": 0, "latencies_ms": []},
        "absent_control": {"total": 0, "abstained_correctly": 0, "false_positives": 0, "latencies_ms": []}
    }

    for idx, q in enumerate(queries):
        qid = q["id"]
        qtext = q["query"]
        cat = q["category"]
        exp_proj = q.get("expected_project")
        exp_file = q.get("expected_file")
        exp_sym = q.get("expected_symbol")
        v_ranges = q.get("verified_ranges", [])

        if cat == "exact_symbol":
            res = retriever.search(qtext, route="exact_symbol", symbol=qtext, top_k=5)
            results["exact_symbol"]["total"] += 1
            results["exact_symbol"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                sym = ev.symbol_name

                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges) or (exp_sym and sym == exp_sym):
                        hit_rank = rank
                        break

            if hit_rank == 1:
                results["exact_symbol"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["exact_symbol"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["exact_symbol"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "concept":
            # Test System 1 hybrid retrieval (RRF)
            res = retriever.search(qtext, route="hybrid", top_k=5)
            results["concept"]["total"] += 1
            results["concept"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
                        hit_rank = rank
                        break

            if hit_rank == 1:
                results["concept"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["concept"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["concept"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "typo":
            # Typo queries are conceptual queries with typos -> test hybrid search
            res = retriever.search(qtext, route="hybrid", top_k=5)
            results["typo"]["total"] += 1
            results["typo"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
                        hit_rank = rank
                        break

            if hit_rank == 1:
                results["typo"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["typo"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["typo"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "cross_project":
            # Test System 1 stratified retrieval across all repositories
            res = retriever.search(qtext, route="stratified", top_k=5)
            results["cross_project"]["total"] += 1
            results["cross_project"]["latencies_ms"].append(res.latency_ms)

            req_ev = q.get("required_evidence", [])
            matched_ev = set()
            for ev in res.evidence:
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                proj = ev.repo
                for req_idx, req in enumerate(req_ev):
                    if (proj == req["project"] or req["project"] in fpath) and (fpath == req["file"] or fpath.endswith(req["file"])):
                        if ranges_overlap(sline, eline, req["start"], req["end"]):
                            matched_ev.add(req_idx)

            if len(matched_ev) >= 2:
                results["cross_project"]["multi_evidence_found"] += 1

        elif cat == "absent_control":
            # Test System 1 distance thresholding / clean abstention
            res = retriever.search(qtext, route="dense", top_k=5)
            results["absent_control"]["total"] += 1
            results["absent_control"]["latencies_ms"].append(res.latency_ms)

            if res.abstained or len(res.evidence) == 0:
                results["absent_control"]["abstained_correctly"] += 1
            else:
                results["absent_control"]["false_positives"] += 1

    def safe_div(n, d):
        return round(n / max(1, d), 4)

    summary = {
        "exact_symbol": {
            "total": results["exact_symbol"]["total"],
            "hit_at_1": safe_div(results["exact_symbol"]["hit_at_1"], results["exact_symbol"]["total"]),
            "hit_at_5": safe_div(results["exact_symbol"]["hit_at_5"], results["exact_symbol"]["total"]),
            "mrr_10": safe_div(results["exact_symbol"]["mrr_10"], results["exact_symbol"]["total"]),
            "p50_latency_ms": round(statistics.median(results["exact_symbol"]["latencies_ms"]), 2)
        },
        "concept": {
            "total": results["concept"]["total"],
            "hit_at_1": safe_div(results["concept"]["hit_at_1"], results["concept"]["total"]),
            "hit_at_5": safe_div(results["concept"]["hit_at_5"], results["concept"]["total"]),
            "mrr_10": safe_div(results["concept"]["mrr_10"], results["concept"]["total"]),
            "p50_latency_ms": round(statistics.median(results["concept"]["latencies_ms"]), 2)
        },
        "typo": {
            "total": results["typo"]["total"],
            "hit_at_1": safe_div(results["typo"]["hit_at_1"], results["typo"]["total"]),
            "hit_at_5": safe_div(results["typo"]["hit_at_5"], results["typo"]["total"]),
            "mrr_10": safe_div(results["typo"]["mrr_10"], results["typo"]["total"]),
            "p50_latency_ms": round(statistics.median(results["typo"]["latencies_ms"]), 2)
        },
        "cross_project": {
            "total": results["cross_project"]["total"],
            "multi_evidence_found": results["cross_project"]["multi_evidence_found"],
            "multi_evidence_rate": safe_div(results["cross_project"]["multi_evidence_found"], results["cross_project"]["total"]),
            "p50_latency_ms": round(statistics.median(results["cross_project"]["latencies_ms"]), 2)
        },
        "absent_control": {
            "total": results["absent_control"]["total"],
            "abstained_correctly": results["absent_control"]["abstained_correctly"],
            "abstention_rate": safe_div(results["absent_control"]["abstained_correctly"], results["absent_control"]["total"]),
            "false_positives": results["absent_control"]["false_positives"],
            "p50_latency_ms": round(statistics.median(results["absent_control"]["latencies_ms"]), 2)
        }
    }

    out_file = BASE_DIR / "results" / "system1_evaluation_summary.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n=== System 1 Evaluation Summary ===")
    print(json.dumps(summary, indent=2))
    return summary

if __name__ == "__main__":
    run_system1_evaluation()

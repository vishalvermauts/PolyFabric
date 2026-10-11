import os
import sys
import json
import time
import statistics
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever, System1Config
from infinite_memory.server import _detect_cross_repo_intent

BASE_DIR = Path(__file__).resolve().parent
BASELINE_DB_PATH = BASE_DIR / "results" / "real_corpus_indexing" / "real_lancedb"
ENRICHED_DB_PATH = BASE_DIR / "results" / "enriched_corpus_indexing" / "enriched_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    return max(s1, s2) <= min(e1, e2)

def evaluate_configuration(db_path: Path, config_name: str, enable_reranker: bool = False):
    print(f"\n=======================================================")
    print(f"Evaluating: {config_name}")
    print(f"Database: {db_path}")
    print(f"Reranker: {enable_reranker}")
    print(f"=======================================================")

    store = VectorStore(db_path=db_path)
    cfg = System1Config(min_cosine_similarity=0.30, per_project_fraction=0.5)
    retriever = System1Retriever(store, cfg)

    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    results = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "candidate_coverage": 0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "candidate_coverage": 0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "mrr_10": 0.0, "candidate_coverage": 0, "latencies_ms": []},
        "cross_project": {"total": 0, "routing_intent_detected": 0, "multi_evidence_found": 0, "candidate_coverage": 0, "latencies_ms": []},
        "absent_control": {"total": 0, "abstained_correctly": 0, "false_positives": 0, "latencies_ms": []}
    }

    for q in queries:
        qid = q["id"]
        qtext = q["query"]
        cat = q["category"]
        exp_proj = q.get("expected_project")
        exp_file = q.get("expected_file")
        exp_sym = q.get("expected_symbol")
        v_ranges = q.get("verified_ranges", [])

        if cat == "exact_symbol":
            res = retriever.search(qtext, route="exact_symbol", symbol=qtext, top_k=5, apply_reranker=enable_reranker)
            results["exact_symbol"]["total"] += 1
            results["exact_symbol"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            found_in_candidates = False
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                sym = ev.symbol_name

                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    found_in_candidates = True
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges) or (exp_sym and sym == exp_sym):
                        if hit_rank is None:
                            hit_rank = rank

            if found_in_candidates:
                results["exact_symbol"]["candidate_coverage"] += 1
            if hit_rank == 1:
                results["exact_symbol"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["exact_symbol"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["exact_symbol"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "concept":
            res = retriever.search(qtext, route="hybrid", top_k=5, apply_reranker=enable_reranker)
            results["concept"]["total"] += 1
            results["concept"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            found_in_candidates = False
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    found_in_candidates = True
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
                        if hit_rank is None:
                            hit_rank = rank

            if found_in_candidates:
                results["concept"]["candidate_coverage"] += 1
            if hit_rank == 1:
                results["concept"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["concept"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["concept"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "typo":
            res = retriever.search(qtext, route="hybrid", top_k=5, apply_reranker=enable_reranker)
            results["typo"]["total"] += 1
            results["typo"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            found_in_candidates = False
            for rank, ev in enumerate(res.evidence, 1):
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    found_in_candidates = True
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
                        if hit_rank is None:
                            hit_rank = rank

            if found_in_candidates:
                results["typo"]["candidate_coverage"] += 1
            if hit_rank == 1:
                results["typo"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                results["typo"]["hit_at_5"] += 1
            if hit_rank is not None and hit_rank <= 10:
                results["typo"]["mrr_10"] += 1.0 / hit_rank

        elif cat == "cross_project":
            # 1. Routing Intent Detection evaluated independently
            intent_detected = _detect_cross_repo_intent(qtext)
            results["cross_project"]["total"] += 1
            if intent_detected:
                results["cross_project"]["routing_intent_detected"] += 1

            # 2. Stratified retrieval on top-5 budget
            res = retriever.search(qtext, route="stratified", top_k=5, apply_reranker=enable_reranker)
            results["cross_project"]["latencies_ms"].append(res.latency_ms)

            req_ev = q.get("required_evidence", [])
            matched_ev = set()
            files_covered = set()
            for ev in res.evidence:
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                proj = ev.repo
                for req_idx, req in enumerate(req_ev):
                    if (proj == req["project"] or req["project"] in fpath) and (fpath == req["file"] or fpath.endswith(req["file"])):
                        files_covered.add(req_idx)
                        if ranges_overlap(sline, eline, req["start"], req["end"]):
                            matched_ev.add(req_idx)

            if len(files_covered) >= 2:
                results["cross_project"]["candidate_coverage"] += 1
            if len(matched_ev) >= 2:
                results["cross_project"]["multi_evidence_found"] += 1

        elif cat == "absent_control":
            res = retriever.search(qtext, route="dense", top_k=5, apply_reranker=enable_reranker)
            results["absent_control"]["total"] += 1
            results["absent_control"]["latencies_ms"].append(res.latency_ms)

            if res.abstained or len(res.evidence) == 0:
                results["absent_control"]["abstained_correctly"] += 1
            else:
                results["absent_control"]["false_positives"] += 1

    def safe_div(n, d):
        return round(n / max(1, d), 4)

    def calc_percentile(data, p):
        if not data:
            return 0.0
        sorted_d = sorted(data)
        k = (len(sorted_d) - 1) * (p / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_d) - 1)
        return round(sorted_d[f] + (sorted_d[c] - sorted_d[f]) * (k - f), 2)

    summary = {
        "config_name": config_name,
        "exact_symbol": {
            "total": results["exact_symbol"]["total"],
            "hit_at_1": safe_div(results["exact_symbol"]["hit_at_1"], results["exact_symbol"]["total"]),
            "hit_at_5": safe_div(results["exact_symbol"]["hit_at_5"], results["exact_symbol"]["total"]),
            "candidate_coverage": safe_div(results["exact_symbol"]["candidate_coverage"], results["exact_symbol"]["total"]),
            "p50_latency_ms": calc_percentile(results["exact_symbol"]["latencies_ms"], 50),
            "p95_latency_ms": calc_percentile(results["exact_symbol"]["latencies_ms"], 95),
        },
        "concept": {
            "total": results["concept"]["total"],
            "hit_at_1": safe_div(results["concept"]["hit_at_1"], results["concept"]["total"]),
            "hit_at_5": safe_div(results["concept"]["hit_at_5"], results["concept"]["total"]),
            "candidate_coverage": safe_div(results["concept"]["candidate_coverage"], results["concept"]["total"]),
            "p50_latency_ms": calc_percentile(results["concept"]["latencies_ms"], 50),
            "p95_latency_ms": calc_percentile(results["concept"]["latencies_ms"], 95),
        },
        "typo": {
            "total": results["typo"]["total"],
            "hit_at_1": safe_div(results["typo"]["hit_at_1"], results["typo"]["total"]),
            "hit_at_5": safe_div(results["typo"]["hit_at_5"], results["typo"]["total"]),
            "candidate_coverage": safe_div(results["typo"]["candidate_coverage"], results["typo"]["total"]),
            "p50_latency_ms": calc_percentile(results["typo"]["latencies_ms"], 50),
            "p95_latency_ms": calc_percentile(results["typo"]["latencies_ms"], 95),
        },
        "cross_project": {
            "total": results["cross_project"]["total"],
            "routing_intent_accuracy": safe_div(results["cross_project"]["routing_intent_detected"], results["cross_project"]["total"]),
            "multi_evidence_hit_at_5": safe_div(results["cross_project"]["multi_evidence_found"], results["cross_project"]["total"]),
            "candidate_coverage": safe_div(results["cross_project"]["candidate_coverage"], results["cross_project"]["total"]),
            "p50_latency_ms": calc_percentile(results["cross_project"]["latencies_ms"], 50),
            "p95_latency_ms": calc_percentile(results["cross_project"]["latencies_ms"], 95),
        },
        "absent_control": {
            "total": results["absent_control"]["total"],
            "abstained_correctly": results["absent_control"]["abstained_correctly"],
            "clean_abstention_rate": safe_div(results["absent_control"]["abstained_correctly"], results["absent_control"]["total"]),
            "false_positives": results["absent_control"]["false_positives"],
            "p50_latency_ms": calc_percentile(results["absent_control"]["latencies_ms"], 50),
            "p95_latency_ms": calc_percentile(results["absent_control"]["latencies_ms"], 95),
        }
    }
    return summary

def main():
    print("Running baseline evaluation on real_lancedb...")
    baseline_summary = evaluate_configuration(BASELINE_DB_PATH, "Baseline (Pre-Enrichment)", enable_reranker=False)

    print("\nRunning enriched evaluation on enriched_lancedb...")
    enriched_summary = evaluate_configuration(ENRICHED_DB_PATH, "New (Enriched Corpus + Optimizations)", enable_reranker=False)

    comparison = {
        "baseline": baseline_summary,
        "enriched_new": enriched_summary
    }

    out_file = BASE_DIR / "results" / "enriched_fair_comparison_report.json"
    out_file.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print("\n=== FAIR COMPARISON COMPLETED ===")
    print(json.dumps(comparison, indent=2))
    os._exit(0)

if __name__ == "__main__":
    main()

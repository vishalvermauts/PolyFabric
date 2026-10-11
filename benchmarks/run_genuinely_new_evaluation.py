import os
import sys
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever, System1Config
from infinite_memory.server import _detect_cross_repo_intent

ENRICHED_DB_PATH = BASE_DIR / "results" / "enriched_corpus_indexing" / "enriched_lancedb"
MANIFEST_PATH = BASE_DIR / "genuinely_new_queries_manifest.json"
OUTPUT_PATH = BASE_DIR / "results" / "genuinely_new_queries_evaluation_report.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    return max(s1, s2) <= min(e1, e2)

def evaluate_new_queries():
    print(f"\n=======================================================")
    print(f"EVALUATING FROZEN POLYFABRIC ON GENUINELY NEW QUERIES")
    print(f"Corpus: {ENRICHED_DB_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Top-K Evidence Budget: 5")
    print(f"=======================================================\n")

    store = VectorStore(db_path=ENRICHED_DB_PATH)
    cfg = System1Config(
        min_cosine_similarity=0.30,
        per_project_fraction=0.5,
        rrf_k=60,
        rrf_k_lex=65,
        rrf_k_vec=38
    )
    retriever = System1Retriever(store, cfg)
    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    per_query_results = []
    category_summary = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "candidate_coverage": 0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "candidate_coverage": 0, "latencies_ms": []},
        "cross_project": {
            "total": 0,
            "routing_intent_detected": 0,
            "file_candidate_coverage": 0,
            "successful_multi_evidence_hit_at_5": 0,
            "latencies_ms": []
        },
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

        query_record = {
            "id": qid,
            "query": qtext,
            "category": cat,
            "expected_project": exp_proj,
            "expected_file": exp_file,
            "expected_symbol": exp_sym,
        }

        if cat == "exact_symbol":
            res = retriever.search(qtext, route="exact_symbol", symbol=qtext, top_k=5, apply_reranker=False)
            category_summary["exact_symbol"]["total"] += 1
            category_summary["exact_symbol"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            found_in_candidates = False
            retrieved_items = []

            for rank, ev in enumerate(res.evidence, 1):
                retrieved_items.append({
                    "rank": rank,
                    "repo": ev.repo,
                    "file_path": ev.file_path,
                    "symbol_name": ev.symbol_name,
                    "lines": [ev.start_line, ev.end_line],
                    "score": round(ev.score, 4)
                })
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
                category_summary["exact_symbol"]["candidate_coverage"] += 1
            if hit_rank == 1:
                category_summary["exact_symbol"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                category_summary["exact_symbol"]["hit_at_5"] += 1

            query_record.update({
                "latency_ms": res.latency_ms,
                "hit_rank": hit_rank,
                "hit_at_1": hit_rank == 1,
                "hit_at_5": hit_rank is not None and hit_rank <= 5,
                "candidate_coverage": found_in_candidates,
                "retrieved_evidence": retrieved_items
            })

        elif cat == "concept":
            res = retriever.search(qtext, route="hybrid", top_k=5, apply_reranker=False)
            category_summary["concept"]["total"] += 1
            category_summary["concept"]["latencies_ms"].append(res.latency_ms)

            hit_rank = None
            found_in_candidates = False
            retrieved_items = []

            for rank, ev in enumerate(res.evidence, 1):
                retrieved_items.append({
                    "rank": rank,
                    "repo": ev.repo,
                    "file_path": ev.file_path,
                    "symbol_name": ev.symbol_name,
                    "lines": [ev.start_line, ev.end_line],
                    "score": round(ev.score, 4)
                })
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line

                if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
                    found_in_candidates = True
                    if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
                        if hit_rank is None:
                            hit_rank = rank

            if found_in_candidates:
                category_summary["concept"]["candidate_coverage"] += 1
            if hit_rank == 1:
                category_summary["concept"]["hit_at_1"] += 1
            if hit_rank is not None and hit_rank <= 5:
                category_summary["concept"]["hit_at_5"] += 1

            query_record.update({
                "latency_ms": res.latency_ms,
                "hit_rank": hit_rank,
                "hit_at_1": hit_rank == 1,
                "hit_at_5": hit_rank is not None and hit_rank <= 5,
                "candidate_coverage": found_in_candidates,
                "retrieved_evidence": retrieved_items
            })

        elif cat == "cross_project":
            # 1. Routing Intent Detection evaluated independently
            intent_detected = _detect_cross_repo_intent(qtext)
            category_summary["cross_project"]["total"] += 1
            if intent_detected:
                category_summary["cross_project"]["routing_intent_detected"] += 1

            # 2. Stratified retrieval on strict top-5 budget
            res = retriever.search(qtext, route="stratified", top_k=5, apply_reranker=False)
            category_summary["cross_project"]["latencies_ms"].append(res.latency_ms)

            req_ev = q.get("required_evidence", [])
            matched_evidence_indices = set()
            covered_file_indices = set()
            retrieved_items = []

            for rank, ev in enumerate(res.evidence, 1):
                retrieved_items.append({
                    "rank": rank,
                    "repo": ev.repo,
                    "file_path": ev.file_path,
                    "symbol_name": ev.symbol_name,
                    "lines": [ev.start_line, ev.end_line],
                    "score": round(ev.score, 4)
                })
                fpath = ev.file_path
                sline = ev.start_line
                eline = ev.end_line
                proj = ev.repo

                for req_idx, req in enumerate(req_ev):
                    if (proj == req["project"] or req["project"] in fpath) and (fpath == req["file"] or fpath.endswith(req["file"])):
                        covered_file_indices.add(req_idx)
                        if ranges_overlap(sline, eline, req["start"], req["end"]):
                            matched_evidence_indices.add(req_idx)

            file_cov = len(covered_file_indices) >= len(req_ev)
            multi_ev = len(matched_evidence_indices) >= len(req_ev)

            if file_cov:
                category_summary["cross_project"]["file_candidate_coverage"] += 1
            if multi_ev:
                category_summary["cross_project"]["successful_multi_evidence_hit_at_5"] += 1

            query_record.update({
                "latency_ms": res.latency_ms,
                "routing_intent_detected": intent_detected,
                "file_coverage_achieved": file_cov,
                "successful_multi_evidence_hit_at_5": multi_ev,
                "covered_projects": list({ev.repo for ev in res.evidence}),
                "retrieved_evidence": retrieved_items
            })

        elif cat == "absent_control":
            res = retriever.search(qtext, route="dense", top_k=5, apply_reranker=False)
            category_summary["absent_control"]["total"] += 1
            category_summary["absent_control"]["latencies_ms"].append(res.latency_ms)

            abstained = res.abstained or len(res.evidence) == 0
            if abstained:
                category_summary["absent_control"]["abstained_correctly"] += 1
            else:
                category_summary["absent_control"]["false_positives"] += 1

            query_record.update({
                "latency_ms": res.latency_ms,
                "abstained_correctly": abstained,
                "evidence_count": len(res.evidence)
            })

        per_query_results.append(query_record)

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

    final_report = {
        "metadata": {
            "evaluation_title": "Frozen PolyFabric Evaluation on Genuinely New Queries",
            "execution_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_commit": "7742706248d39b75e83fb834a5dd65cff091c717",
            "frozen_implementation": "src/infinite_memory/core/system1.py (commit 88d66fa verified)",
            "selection_criteria_frozen": "Validation selection based on highest Concept Hit@5 & Clean Abstention without regression",
            "corpus_path": str(ENRICHED_DB_PATH),
            "manifest_path": str(MANIFEST_PATH),
            "total_new_queries": len(queries)
        },
        "summary": {
            "exact_symbol": {
                "total": category_summary["exact_symbol"]["total"],
                "hit_at_1": safe_div(category_summary["exact_symbol"]["hit_at_1"], category_summary["exact_symbol"]["total"]),
                "hit_at_5": safe_div(category_summary["exact_symbol"]["hit_at_5"], category_summary["exact_symbol"]["total"]),
                "candidate_coverage": safe_div(category_summary["exact_symbol"]["candidate_coverage"], category_summary["exact_symbol"]["total"]),
                "p50_latency_ms": calc_percentile(category_summary["exact_symbol"]["latencies_ms"], 50),
                "p95_latency_ms": calc_percentile(category_summary["exact_symbol"]["latencies_ms"], 95),
            },
            "concept": {
                "total": category_summary["concept"]["total"],
                "hit_at_1": safe_div(category_summary["concept"]["hit_at_1"], category_summary["concept"]["total"]),
                "hit_at_5": safe_div(category_summary["concept"]["hit_at_5"], category_summary["concept"]["total"]),
                "candidate_coverage": safe_div(category_summary["concept"]["candidate_coverage"], category_summary["concept"]["total"]),
                "p50_latency_ms": calc_percentile(category_summary["concept"]["latencies_ms"], 50),
                "p95_latency_ms": calc_percentile(category_summary["concept"]["latencies_ms"], 95),
            },
            "cross_project": {
                "total": category_summary["cross_project"]["total"],
                "routing_intent_accuracy": safe_div(category_summary["cross_project"]["routing_intent_detected"], category_summary["cross_project"]["total"]),
                "file_candidate_coverage": safe_div(category_summary["cross_project"]["file_candidate_coverage"], category_summary["cross_project"]["total"]),
                "successful_multi_evidence_hit_at_5": safe_div(category_summary["cross_project"]["successful_multi_evidence_hit_at_5"], category_summary["cross_project"]["total"]),
                "p50_latency_ms": calc_percentile(category_summary["cross_project"]["latencies_ms"], 50),
                "p95_latency_ms": calc_percentile(category_summary["cross_project"]["latencies_ms"], 95),
            },
            "absent_control": {
                "total": category_summary["absent_control"]["total"],
                "clean_abstention_rate": safe_div(category_summary["absent_control"]["abstained_correctly"], category_summary["absent_control"]["total"]),
                "false_positives": category_summary["absent_control"]["false_positives"],
                "p50_latency_ms": calc_percentile(category_summary["absent_control"]["latencies_ms"], 50),
                "p95_latency_ms": calc_percentile(category_summary["absent_control"]["latencies_ms"], 95),
            }
        },
        "per_query_results": per_query_results
    }

    OUTPUT_PATH.write_text(json.dumps(final_report, indent=2), encoding="utf-8")
    print(f"\nFinal report saved to: {OUTPUT_PATH}")
    print("\nSUMMARY METRICS:")
    print(json.dumps(final_report["summary"], indent=2))

if __name__ == "__main__":
    evaluate_new_queries()

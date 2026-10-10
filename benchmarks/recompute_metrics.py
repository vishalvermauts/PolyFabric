import sys
import json
from pathlib import Path
import statistics

def recompute_metrics(queries_file: Path, summary_file: Path = None):
    data = json.loads(queries_file.read_text(encoding="utf-8"))
    
    # 1. Exact Symbol Mode A & Mode B
    exact_queries = [q for q in data if q.get("category") == "exact_symbol"]
    mode_a_found = sum(1 for q in exact_queries if q.get("mode_a_exact_lookup", {}).get("declaration_found"))
    mode_a_hit1 = sum(1 for q in exact_queries if q.get("mode_a_exact_lookup", {}).get("top1_declaration"))
    mode_a_hit5 = sum(1 for q in exact_queries if q.get("mode_a_exact_lookup", {}).get("top5_declaration"))
    mode_a_lats = [q["mode_a_exact_lookup"]["latency_ms"] for q in exact_queries if "latency_ms" in q.get("mode_a_exact_lookup", {})]
    
    mode_b_exact_hit1 = sum(1 for q in exact_queries if q.get("mode_b_semantic_search", {}).get("hit_at_1"))
    mode_b_exact_hit5 = sum(1 for q in exact_queries if q.get("mode_b_semantic_search", {}).get("hit_at_5"))
    mode_b_exact_mrrs = [q.get("mode_b_semantic_search", {}).get("mrr", 0.0) for q in exact_queries]
    mode_b_exact_lats = [q["mode_b_semantic_search"]["latency_ms"] for q in exact_queries]
    
    # 2. Concept Queries
    concept_queries = [q for q in data if q.get("category") == "concept"]
    concept_hit1 = sum(1 for q in concept_queries if q.get("mode_b_semantic_search", {}).get("hit_at_1"))
    concept_hit5 = sum(1 for q in concept_queries if q.get("mode_b_semantic_search", {}).get("hit_at_5"))
    concept_mrrs = [q.get("mode_b_semantic_search", {}).get("mrr", 0.0) for q in concept_queries]
    concept_lats = [q["mode_b_semantic_search"]["latency_ms"] for q in concept_queries]
    
    # 3. Typo Queries
    typo_queries = [q for q in data if q.get("category") == "typo"]
    typo_hit1 = sum(1 for q in typo_queries if q.get("mode_b_semantic_search", {}).get("hit_at_1"))
    typo_hit5 = sum(1 for q in typo_queries if q.get("mode_b_semantic_search", {}).get("hit_at_5"))
    typo_mrrs = [q.get("mode_b_semantic_search", {}).get("mrr", 0.0) for q in typo_queries]
    typo_lats = [q["mode_b_semantic_search"]["latency_ms"] for q in typo_queries]
    
    # 4. Absent Controls
    absent_queries = [q for q in data if q.get("category") == "absent_control"]
    absent_abstained = sum(1 for q in absent_queries if q.get("mode_a_exact_lookup", {}).get("abstained"))
    absent_sem_returned = sum(1 for q in absent_queries if q.get("mode_b_semantic_search", {}).get("hits", [{}])[0].get("candidates_returned", 0) > 0)
    absent_lats = [q["mode_b_semantic_search"]["latency_ms"] for q in absent_queries]
    
    def safe_div(num, den):
        return round(num / max(1, den), 4)

    summary = {
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "database": "/home/agent/bench/repo/benchmarks/results/real_corpus_indexing/real_lancedb",
        "total_queries_evaluated": len(data),
        "mode_a_exact_symbol_lookup": {
            "total_queries": len(exact_queries),
            "declarations_found_count": mode_a_found,
            "declaration_found_rate": safe_div(mode_a_found, len(exact_queries)),
            "exact_hit_at_1_rate": safe_div(mode_a_hit1, len(exact_queries)),
            "exact_hit_at_5_rate": safe_div(mode_a_hit5, len(exact_queries)),
            "p50_latency_ms": round(statistics.median(mode_a_lats), 2) if mode_a_lats else 0.0,
            "p95_latency_ms": round(statistics.quantiles(mode_a_lats, n=20)[18], 2) if len(mode_a_lats) >= 20 else 0.0
        },
        "mode_b_semantic_search_independent": {
            "exact_symbol": {
                "total": len(exact_queries),
                "hit_at_1": safe_div(mode_b_exact_hit1, len(exact_queries)),
                "hit_at_5": safe_div(mode_b_exact_hit5, len(exact_queries)),
                "mrr_10": safe_div(sum(mode_b_exact_mrrs), len(exact_queries)),
                "p50_latency_ms": round(statistics.median(mode_b_exact_lats), 2)
            },
            "concept": {
                "total": len(concept_queries),
                "hit_at_1": safe_div(concept_hit1, len(concept_queries)),
                "hit_at_5": safe_div(concept_hit5, len(concept_queries)),
                "mrr_10": safe_div(sum(concept_mrrs), len(concept_queries)),
                "p50_latency_ms": round(statistics.median(concept_lats), 2)
            },
            "typo": {
                "total": len(typo_queries),
                "hit_at_1": safe_div(typo_hit1, len(typo_queries)),
                "hit_at_5": safe_div(typo_hit5, len(typo_queries)),
                "mrr_10": safe_div(sum(typo_mrrs), len(typo_queries)),
                "p50_latency_ms": round(statistics.median(typo_lats), 2)
            },
            "absent_controls": {
                "total": len(absent_queries),
                "exact_lookup_abstention_rate": safe_div(absent_abstained, len(absent_queries)),
                "semantic_candidates_returned_count": absent_sem_returned,
                "p50_latency_ms": round(statistics.median(absent_lats), 2)
            }
        }
    }
    
    print("=== Recomputed Evaluation Metrics from Raw Queries ===")
    print(json.dumps(summary, indent=2))
    
    if summary_file and summary_file.exists():
        expected = json.loads(summary_file.read_text(encoding="utf-8"))
        print("\nVerifying against summary.json...")
        assert summary["mode_a_exact_symbol_lookup"]["declaration_found_rate"] == expected["mode_a_exact_symbol_lookup"]["declaration_found_rate"], "Mode A mismatch"
        assert summary["mode_b_semantic_search_independent"]["concept"]["hit_at_5"] == expected["mode_b_semantic_search_independent"]["concept"]["hit_at_5"], "Concept hit@5 mismatch"
        assert summary["mode_b_semantic_search_independent"]["exact_symbol"]["mrr_10"] == expected["mode_b_semantic_search_independent"]["exact_symbol"]["mrr_10"], "Exact MRR mismatch"
        assert summary["mode_b_semantic_search_independent"]["absent_controls"]["exact_lookup_abstention_rate"] == expected["mode_b_semantic_search_independent"]["absent_controls"]["exact_lookup_abstention_rate"], "Absent control abstention mismatch"
        print("[SUCCESS] Verification passed: Recomputed metrics mathematically match summary JSON.")

if __name__ == "__main__":
    queries_p = Path("benchmarks/results/corrected_retrieval_detailed_queries.json")
    summary_p = Path("benchmarks/results/corrected_retrieval_quality_summary.json")
    recompute_metrics(queries_p, summary_p)

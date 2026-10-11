import os
import sys
import json
import time
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from infinite_memory.core.store import VectorStore
import infinite_memory.core.system1 as sys1
from infinite_memory.core.system1 import System1Retriever, System1Config, Evidence
from infinite_memory.server import _detect_cross_repo_intent

ENRICHED_DB_PATH = BASE_DIR / "results" / "enriched_corpus_indexing" / "enriched_lancedb"
VAL_MANIFEST_PATH = BASE_DIR / "val_split_manifest.json"
HELD_OUT_MANIFEST_PATH = BASE_DIR / "held_out_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    return max(s1, s2) <= min(e1, e2)

def make_evaluator(
    enable_path_token_boost: bool,
    enable_symbol_token_boost: bool,
    diversity_sort_by_score: bool,
    enable_context_headers: bool,
):
    """
    Patches functions in system1 to toggle each optimization independently.
    """
    # 1. Custom _rrf_fuse with flags
    def custom_rrf_fuse(lexical_hits, vector_hits, k=60, top_k=5, k_lex=None, k_vec=None, query=None):
        scores = sys1.defaultdict(float)
        records = {}
        actual_k_lex = k_lex if k_lex is not None else k
        actual_k_vec = k_vec if k_vec is not None else k

        for rank, rec in enumerate(lexical_hits, 1):
            rid = rec.get("id", str(rank))
            scores[rid] += 1.0 / (actual_k_lex + rank)
            records[rid] = rec

        for rank, rec in enumerate(vector_hits, 1):
            rid = rec.get("id", str(rank))
            scores[rid] += 1.0 / (actual_k_vec + rank)
            records[rid] = rec

        if query and (enable_path_token_boost or enable_symbol_token_boost):
            q_tokens = {w for w in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(w) > 2}
            for rid, rec in records.items():
                if enable_path_token_boost:
                    fpath_tokens = set(re.findall(r"[a-zA-Z0-9]+", rec.get("file_path", "").lower()))
                    path_overlap = len(q_tokens.intersection(fpath_tokens))
                    if path_overlap > 0:
                        scores[rid] += path_overlap * 0.004
                if enable_symbol_token_boost:
                    sym_tokens = set(re.findall(r"[a-zA-Z0-9]+", str(rec.get("symbol_name", "")).lower()))
                    sym_overlap = len(q_tokens.intersection(sym_tokens))
                    if sym_overlap > 0:
                        scores[rid] += sym_overlap * 0.006

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        result = []
        for rid in sorted_ids[:top_k]:
            rec = dict(records[rid])
            rec["_rrf_score"] = scores[rid]
            result.append(rec)
        return result

    # 2. Custom _diversity_merge with flag
    def custom_diversity_merge(evidence, top_k: int):
        by_repo = sys1.defaultdict(list)
        for ev in evidence:
            by_repo[ev.repo].append(ev)

        for repo in by_repo:
            by_repo[repo].sort(key=lambda e: e.score, reverse=True)

        result = []
        seen_ids = set()

        if diversity_sort_by_score:
            sorted_repos = sorted(by_repo.keys(), key=lambda r: (by_repo[r][0].score if by_repo[r] else 0.0), reverse=True)
        else:
            sorted_repos = sorted(by_repo.keys())

        max_depth = max((len(cands) for cands in by_repo.values()), default=0)
        for depth in range(min(2, max_depth)):
            for repo in sorted_repos:
                candidates = by_repo[repo]
                if len(candidates) > depth:
                    cand = candidates[depth]
                    if cand.id not in seen_ids and len(result) < top_k:
                        result.append(cand)
                        seen_ids.add(cand.id)

        if len(result) < top_k:
            remaining = []
            for repo in by_repo:
                for cand in by_repo[repo]:
                    if cand.id not in seen_ids:
                        remaining.append(cand)
            remaining.sort(key=lambda e: e.score, reverse=True)
            for cand in remaining:
                if len(result) < top_k:
                    result.append(cand)
                    seen_ids.add(cand.id)
                else:
                    break

        return result

    # 3. Custom _apply_reranker with flag
    def custom_apply_reranker(evidence, query, reranker, top_k=5):
        if not evidence or reranker is None:
            return evidence
        t0 = time.perf_counter()
        pruned = sys1._prune_candidates(evidence)
        if enable_context_headers:
            pairs = [
                (query, f"# File: {ev.file_path}\n# Symbol: {ev.symbol_name}\n" + sys1._extract_signature(ev.text))
                for ev in pruned
            ]
        else:
            pairs = [(query, sys1._extract_signature(ev.text)) for ev in pruned]
        scores = list(reranker.rerank(query, [p[1] for p in pairs]))
        scored = []
        for ev, score in zip(pruned, scores):
            ev.score = float(score)
            scored.append(ev)
        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:top_k]

    sys1._rrf_fuse = custom_rrf_fuse
    sys1._diversity_merge = custom_diversity_merge
    sys1._apply_reranker = custom_apply_reranker

def run_evaluation(manifest_path: Path, store: VectorStore, top_k: int = 5):
    cfg = System1Config(min_cosine_similarity=0.30, per_project_fraction=0.5)
    retriever = System1Retriever(store, cfg)
    queries = json.loads(manifest_path.read_text(encoding="utf-8"))

    results = {
        "exact_symbol": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "candidate_coverage": 0, "latencies_ms": []},
        "concept": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "candidate_coverage": 0, "latencies_ms": []},
        "typo": {"total": 0, "hit_at_1": 0, "hit_at_5": 0, "candidate_coverage": 0, "latencies_ms": []},
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
            res = retriever.search(qtext, route="exact_symbol", symbol=qtext, top_k=top_k, apply_reranker=False)
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
            if hit_rank is not None and hit_rank <= top_k:
                results["exact_symbol"]["hit_at_5"] += 1

        elif cat == "concept":
            res = retriever.search(qtext, route="hybrid", top_k=top_k, apply_reranker=False)
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
            if hit_rank is not None and hit_rank <= top_k:
                results["concept"]["hit_at_5"] += 1

        elif cat == "typo":
            res = retriever.search(qtext, route="hybrid", top_k=top_k, apply_reranker=False)
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
            if hit_rank is not None and hit_rank <= top_k:
                results["typo"]["hit_at_5"] += 1

        elif cat == "cross_project":
            intent_detected = _detect_cross_repo_intent(qtext)
            results["cross_project"]["total"] += 1
            if intent_detected:
                results["cross_project"]["routing_intent_detected"] += 1

            res = retriever.search(qtext, route="stratified", top_k=top_k, apply_reranker=False)
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
            res = retriever.search(qtext, route="dense", top_k=top_k, apply_reranker=False)
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

    return {
        "exact_symbol": {
            "total": results["exact_symbol"]["total"],
            "hit_at_1": safe_div(results["exact_symbol"]["hit_at_1"], results["exact_symbol"]["total"]),
            "hit_at_5": safe_div(results["exact_symbol"]["hit_at_5"], results["exact_symbol"]["total"]),
            "candidate_coverage": safe_div(results["exact_symbol"]["candidate_coverage"], results["exact_symbol"]["total"]),
            "p50_latency_ms": calc_percentile(results["exact_symbol"]["latencies_ms"], 50),
        },
        "concept": {
            "total": results["concept"]["total"],
            "hit_at_1": safe_div(results["concept"]["hit_at_1"], results["concept"]["total"]),
            "hit_at_5": safe_div(results["concept"]["hit_at_5"], results["concept"]["total"]),
            "candidate_coverage": safe_div(results["concept"]["candidate_coverage"], results["concept"]["total"]),
            "p50_latency_ms": calc_percentile(results["concept"]["latencies_ms"], 50),
        },
        "typo": {
            "total": results["typo"]["total"],
            "hit_at_1": safe_div(results["typo"]["hit_at_1"], results["typo"]["total"]),
            "hit_at_5": safe_div(results["typo"]["hit_at_5"], results["typo"]["total"]),
            "candidate_coverage": safe_div(results["typo"]["candidate_coverage"], results["typo"]["total"]),
            "p50_latency_ms": calc_percentile(results["typo"]["latencies_ms"], 50),
        },
        "cross_project": {
            "total": results["cross_project"]["total"],
            "routing_intent_accuracy": safe_div(results["cross_project"]["routing_intent_detected"], results["cross_project"]["total"]),
            "multi_evidence_hit_at_5": safe_div(results["cross_project"]["multi_evidence_found"], results["cross_project"]["total"]),
            "candidate_coverage": safe_div(results["cross_project"]["candidate_coverage"], results["cross_project"]["total"]),
            "p50_latency_ms": calc_percentile(results["cross_project"]["latencies_ms"], 50),
        },
        "absent_control": {
            "total": results["absent_control"]["total"],
            "clean_abstention_rate": safe_div(results["absent_control"]["abstained_correctly"], results["absent_control"]["total"]),
            "false_positives": results["absent_control"]["false_positives"],
            "p50_latency_ms": calc_percentile(results["absent_control"]["latencies_ms"], 50),
        }
    }

def main():
    store = VectorStore(db_path=ENRICHED_DB_PATH)

    # Ablation matrix on Validation Set
    configurations = {
        "v_88d66fa (pure asymmetric RRF, alpha order diversity)": {
            "enable_path_token_boost": False,
            "enable_symbol_token_boost": False,
            "diversity_sort_by_score": False,
            "enable_context_headers": False,
        },
        "opt1_path_token_only (+path token boost)": {
            "enable_path_token_boost": True,
            "enable_symbol_token_boost": False,
            "diversity_sort_by_score": False,
            "enable_context_headers": False,
        },
        "opt2_sym_token_only (+symbol token boost)": {
            "enable_path_token_boost": False,
            "enable_symbol_token_boost": True,
            "diversity_sort_by_score": False,
            "enable_context_headers": False,
        },
        "opt3_both_tokens (+path & symbol token boost)": {
            "enable_path_token_boost": True,
            "enable_symbol_token_boost": True,
            "diversity_sort_by_score": False,
            "enable_context_headers": False,
        },
        "opt4_score_diversity_only (+score ordered diversity)": {
            "enable_path_token_boost": False,
            "enable_symbol_token_boost": False,
            "diversity_sort_by_score": True,
            "enable_context_headers": False,
        },
        "v_7742706 (all opts: tokens + score diversity + headers)": {
            "enable_path_token_boost": True,
            "enable_symbol_token_boost": True,
            "diversity_sort_by_score": True,
            "enable_context_headers": True,
        },
    }

    ablation_results = {}
    print("=== STARTING OPTIMIZATION ABLATION ON VALIDATION SPLIT (75 QUERIES) ===")
    for name, flags in configurations.items():
        print(f"Running config: {name} ...")
        make_evaluator(**flags)
        summary = run_evaluation(VAL_MANIFEST_PATH, store)
        ablation_results[name] = summary
        print(f" -> Concept Hit@5: {summary['concept']['hit_at_5']:.1%}, Concept Hit@1: {summary['concept']['hit_at_1']:.1%}, Cross-repo Cov: {summary['cross_project']['candidate_coverage']:.1%}, Clean Abstain: {summary['absent_control']['clean_abstention_rate']:.1%}")

    # Save ablation validation results
    val_out = BASE_DIR / "results" / "ablation_validation_results.json"
    val_out.write_text(json.dumps(ablation_results, indent=2), encoding="utf-8")
    print(f"Validation ablation saved to {val_out}")

    # Determine best configuration based on validation metrics
    # We choose the configuration with the highest Concept Hit@5 and balanced Cross-repo coverage while maintaining 100% clean abstention
    best_config_name = max(
        ablation_results.keys(),
        key=lambda k: (
            ablation_results[k]["absent_control"]["clean_abstention_rate"],
            ablation_results[k]["concept"]["hit_at_5"],
            ablation_results[k]["cross_project"]["candidate_coverage"],
            ablation_results[k]["exact_symbol"]["hit_at_5"]
        )
    )
    print(f"\n=======================================================")
    print(f"BEST CONFIGURATION SELECTED: {best_config_name}")
    print(f"=======================================================")

    # Run ONE final evaluation of the best configuration on the UNTOUCHED HELD-OUT SET
    print("\n=== RUNNING FINAL EVALUATION ON UNTOUCHED HELD-OUT SET (75 QUERIES) ===")
    best_flags = configurations[best_config_name]
    make_evaluator(**best_flags)
    held_out_summary = run_evaluation(HELD_OUT_MANIFEST_PATH, store)

    final_report = {
        "selected_configuration": best_config_name,
        "selected_flags": best_flags,
        "validation_metrics": ablation_results[best_config_name],
        "held_out_final_evaluation": held_out_summary,
        "full_ablation_matrix": ablation_results
    }

    held_out_out = BASE_DIR / "results" / "held_out_final_evaluation_report.json"
    held_out_out.write_text(json.dumps(final_report, indent=2), encoding="utf-8")
    print(f"Held-out final evaluation saved to {held_out_out}")
    print("\nHELD-OUT EVALUATION SUMMARY:")
    print(json.dumps(held_out_summary, indent=2))

if __name__ == "__main__":
    main()

"""
Validation Script:
1. Verifies exact repository counts via full table scan.
2. Confirms IVF_PQ index presence and execution plan.
3. Compares indexed ANN results against exhaustive flat search baseline on identical queries:
   - Measures neighbor Recall@k (ground truth = flat k-NN)
   - Measures task Hit@k
4. Conducts latency trials with warm-up, randomized configuration ordering, and timing decomposition:
   - embedding_time_ms
   - db_search_time_ms
   - total_retrieval_time_ms
5. Evaluates System 1 exact-symbol retrieval on both the original benchmark and a held-out query set.
"""

import time
import json
import random
import statistics
from pathlib import Path
from typing import List, Dict, Any, Set

import lancedb
from fastembed import TextEmbedding

from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever, System1Config

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "results" / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

def ranges_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    return max(s1, s2) <= min(e1, e2)

def is_task_hit(hit: Dict[str, Any], q: Dict[str, Any]) -> bool:
    exp_file = q.get("expected_file")
    v_ranges = q.get("verified_ranges", [])
    exp_sym = q.get("expected_symbol")

    fpath = hit.get("file_path", "")
    sline = int(hit.get("start_line", 1))
    eline = int(hit.get("end_line", 1))
    sym = hit.get("symbol_name", "")

    if exp_file and (fpath == exp_file or fpath.endswith(exp_file)):
        if any(ranges_overlap(sline, eline, vr["start"], vr["end"]) for vr in v_ranges):
            return True
        if exp_sym and sym == exp_sym:
            return True
    return False

def run_comprehensive_validation():
    print("=====================================================================")
    print("      COMPREHENSIVE IVF_PQ, FLAT BASELINE & RECALL@K AUDIT           ")
    print("=====================================================================")

    # 1. Full Scan Repository Counts
    print("\n--- 1. Complete Scan: Repository Record Counts ---")
    db = lancedb.connect(str(DB_PATH))
    tbl = db.open_table("documents")
    full_df = tbl.to_pandas()
    total_records = len(full_df)
    repo_counts = full_df["project"].value_counts().to_dict()
    print(f"Total scan record count: {total_records}")
    print(f"Repository distribution: {repo_counts}")

    # 2. Confirm IVF_PQ Existence and Plan
    print("\n--- 2. Vector Index Inspection & Query Plan ---")
    indices = tbl.list_indices()
    has_ivf_pq = any(idx.index_type == "IvfPq" for idx in indices)
    print(f"Indices configured on table: {[idx.name + ' (' + idx.index_type + ')' for idx in indices]}")
    print(f"IVF_PQ index confirmed active: {has_ivf_pq}")
    
    plan_indexed = tbl.search([0.0]*384).nprobes(1).explain_plan()
    plan_flat = tbl.search([0.0]*384).bypass_vector_index().explain_plan()
    print("Indexed search plan contains ANNSubIndex:", "ANNSubIndex" in plan_indexed)
    print("Flat search plan contains bypass/KNNVectorDistance:", "KNNVectorDistance" in plan_flat or "bypass" in plan_flat)

    # 3. Load queries and pre-compute embeddings to separate embedding vs search latency
    print("\n--- 3. Pre-computing Query Embeddings for Controlled Latency Decomposition ---")
    queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    encoder = TextEmbedding("BAAI/bge-small-en-v1.5")
    
    query_vectors = {}
    for q in queries:
        t_emb_0 = time.perf_counter()
        vec = list(encoder.embed([q["query"]]))[0].tolist()
        t_emb_ms = (time.perf_counter() - t_emb_0) * 1000.0
        query_vectors[q["id"]] = {
            "query": q["query"],
            "category": q["category"],
            "vector": vec,
            "spec": q,
            "emb_time_ms": t_emb_ms
        }
    print(f"Embedded {len(query_vectors)} queries successfully.")

    # 4. Compute Exhaustive Flat Baseline (True k-NN) for All Queries
    print("\n--- 4. Computing Exhaustive Flat Search Ground-Truth Neighbors ---")
    flat_ground_truth: Dict[str, List[str]] = {}
    flat_task_hits: Dict[str, bool] = {}
    flat_latencies: List[float] = []

    for qid, qdata in query_vectors.items():
        t0 = time.perf_counter()
        flat_res = tbl.search(qdata["vector"]).bypass_vector_index().limit(10).to_pandas()
        flat_lat_ms = (time.perf_counter() - t0) * 1000.0
        flat_latencies.append(flat_lat_ms)

        flat_ids = flat_res["id"].tolist()
        flat_ground_truth[qid] = flat_ids
        flat_task_hits[qid] = any(is_task_hit(r, qdata["spec"]) for r in flat_res.to_dict(orient="records")[:5])

    # 5. Randomized Configurations with Warm-up Trials
    print("\n--- 5. Randomized Benchmark Configurations (with Warm-up) ---")
    configs = [
        {"name": "ivf_pq_nprobe_1", "nprobes": 1, "refine": None},
        {"name": "ivf_pq_nprobe_5", "nprobes": 5, "refine": None},
        {"name": "ivf_pq_nprobe_20", "nprobes": 20, "refine": None},
        {"name": "ivf_pq_nprobe_20_refine_2", "nprobes": 20, "refine": 2},
    ]

    # Warm-up runs
    for _ in range(5):
        sample_q = query_vectors[queries[0]["id"]]["vector"]
        tbl.search(sample_q).nprobes(5).limit(10).to_pandas()
        tbl.search(sample_q).bypass_vector_index().limit(10).to_pandas()

    # Shuffle evaluation order
    eval_order = list(configs)
    random.seed(42)
    random.shuffle(eval_order)

    comparison_results = {}

    for cfg in eval_order:
        cfg_name = cfg["name"]
        nprobe = cfg["nprobes"]
        refine = cfg["refine"]

        db_latencies = []
        total_latencies = []
        neighbor_recalls_at_5 = []
        neighbor_recalls_at_10 = []
        task_hits_at_5 = []

        for qid, qdata in query_vectors.items():
            true_neighbors_5 = set(flat_ground_truth[qid][:5])
            true_neighbors_10 = set(flat_ground_truth[qid][:10])

            builder = tbl.search(qdata["vector"]).nprobes(nprobe)
            if refine:
                builder = builder.refine_factor(refine)

            t0_db = time.perf_counter()
            df_ann = builder.limit(10).to_pandas()
            t_db_ms = (time.perf_counter() - t0_db) * 1000.0
            
            db_latencies.append(t_db_ms)
            total_latencies.append(t_db_ms + qdata["emb_time_ms"])

            ann_ids = df_ann["id"].tolist()
            ann_5 = set(ann_ids[:5])
            ann_10 = set(ann_ids[:10])

            rec_5 = len(true_neighbors_5.intersection(ann_5)) / max(1, len(true_neighbors_5))
            rec_10 = len(true_neighbors_10.intersection(ann_10)) / max(1, len(true_neighbors_10))
            neighbor_recalls_at_5.append(rec_5)
            neighbor_recalls_at_10.append(rec_10)

            hit_5 = any(is_task_hit(r, qdata["spec"]) for r in df_ann.to_dict(orient="records")[:5])
            task_hits_at_5.append(1 if hit_5 else 0)

        comparison_results[cfg_name] = {
            "nprobes": nprobe,
            "refine": refine,
            "neighbor_recall_at_5": round(statistics.mean(neighbor_recalls_at_5), 4),
            "neighbor_recall_at_10": round(statistics.mean(neighbor_recalls_at_10), 4),
            "task_hit_at_5_rate": round(statistics.mean(task_hits_at_5), 4),
            "p50_db_search_ms": round(statistics.median(db_latencies), 2),
            "p95_db_search_ms": round(statistics.quantiles(db_latencies, n=20)[18], 2),
            "p50_total_retrieval_ms": round(statistics.median(total_latencies), 2),
            "p95_total_retrieval_ms": round(statistics.quantiles(total_latencies, n=20)[18], 2),
        }

    # Add Flat Baseline metrics
    comparison_results["exhaustive_flat_baseline"] = {
        "nprobes": "FLAT",
        "refine": None,
        "neighbor_recall_at_5": 1.0,
        "neighbor_recall_at_10": 1.0,
        "task_hit_at_5_rate": round(statistics.mean([1 if h else 0 for h in flat_task_hits.values()]), 4),
        "p50_db_search_ms": round(statistics.median(flat_latencies), 2),
        "p95_db_search_ms": round(statistics.quantiles(flat_latencies, n=20)[18], 2),
        "p50_total_retrieval_ms": round(statistics.median([l + query_vectors[qid]["emb_time_ms"] for qid, l in zip(query_vectors.keys(), flat_latencies)]), 2),
        "p95_total_retrieval_ms": round(statistics.quantiles([l + query_vectors[qid]["emb_time_ms"] for qid, l in zip(query_vectors.keys(), flat_latencies)], n=20)[18], 2),
    }

    # 6. Verify System 1 on Both Original Benchmark and Held-out Query Set
    print("\n--- 6. System 1 Exact-Symbol Verification: Original vs Held-Out Query Set ---")
    store = VectorStore(db_path=DB_PATH)
    sys1 = System1Retriever(store)

    # 6a. Original 50 Exact-Symbol Queries
    orig_exact_queries = [q for q in queries if q["category"] == "exact_symbol"]
    orig_hits = 0
    orig_total = len(orig_exact_queries)
    orig_latencies = []

    for q in orig_exact_queries:
        t0 = time.perf_counter()
        res = sys1.search(q["query"], route="exact_symbol", symbol=q["query"], top_k=5)
        orig_latencies.append((time.perf_counter() - t0) * 1000.0)
        if any(is_task_hit(ev.to_dict(), q) for ev in res.evidence[:1]):
            orig_hits += 1

    # 6b. Held-out Symbol Queries (distinct symbols present in corpus but NOT in query manifest)
    existing_queries_symbols = set(q["query"] for q in orig_exact_queries)
    corpus_symbols_df = full_df[full_df["symbol_name"] != ""][["symbol_name", "project", "file_path", "start_line", "end_line"]].drop_duplicates(subset=["symbol_name"])
    
    held_out_candidates = [
        r for r in corpus_symbols_df.to_dict(orient="records")
        if r["symbol_name"] not in existing_queries_symbols and len(r["symbol_name"]) > 3
    ]
    random.seed(123)
    held_out_sample = random.sample(held_out_candidates, min(50, len(held_out_candidates)))

    held_out_hits = 0
    held_out_latencies = []

    for item in held_out_sample:
        sym = item["symbol_name"]
        q_held = {
            "expected_file": item["file_path"],
            "expected_symbol": sym,
            "verified_ranges": [{"start": item["start_line"], "end": item["end_line"]}],
        }
        t0 = time.perf_counter()
        res = sys1.search(sym, route="exact_symbol", symbol=sym, top_k=5)
        held_out_latencies.append((time.perf_counter() - t0) * 1000.0)
        if any(is_task_hit(ev.to_dict(), q_held) for ev in res.evidence[:1]):
            held_out_hits += 1

    sys1_summary = {
        "original_benchmark_50_queries": {
            "total": orig_total,
            "hit_at_1": round(orig_hits / orig_total, 4),
            "p50_latency_ms": round(statistics.median(orig_latencies), 2),
        },
        "held_out_50_distinct_symbols": {
            "total": len(held_out_sample),
            "hit_at_1": round(held_out_hits / len(held_out_sample), 4),
            "p50_latency_ms": round(statistics.median(held_out_latencies), 2),
        }
    }

    final_report = {
        "complete_scan_record_count": total_records,
        "repository_distribution": repo_counts,
        "ivf_pq_active": has_ivf_pq,
        "index_configurations_comparison": comparison_results,
        "system1_exact_symbol_verification": sys1_summary,
    }

    report_path = BASE_DIR / "results" / "vector_index_rigorous_validation.json"
    report_path.write_text(json.dumps(final_report, indent=2), encoding="utf-8")
    print("\n=== Validation Results Summary ===")
    print(json.dumps(final_report, indent=2))

if __name__ == "__main__":
    run_comprehensive_validation()

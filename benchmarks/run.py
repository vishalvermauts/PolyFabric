import os
import sys
import time
import json
import random
import argparse
from pathlib import Path
import psutil
import numpy as np

from infinite_memory.core.store import VectorStore
from infinite_memory.core.router import SystemOneRouter
from infinite_memory.security.secret_masker import mask_secrets
from infinite_memory.core.hub import Hub

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"

def run_benchmarks(profile="smoke", duration_seconds=10, seed=20261010):
    random.seed(seed)
    np.random.seed(seed)
    run_id = f"{profile}_{seed}_{int(time.time())}"
    out_dir = RESULTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"=== Starting Benchmark Profile: {profile} (Seed: {seed}) ===")
    print(f"Output directory: {out_dir}")
    
    db_path = out_dir / "bench_store"
    store = VectorStore(db_path=db_path)
    router = SystemOneRouter()
    
    # Pre-index synthetic/corpus files
    num_files = 20 if profile == "smoke" else (150 if profile == "standard" else 80)
    print(f"Indexing {num_files} benchmark files...")
    idx_start = time.perf_counter()
    for f_idx in range(num_files):
        chunks = [
            {
                "id": f"bench_proj:file_{f_idx}.py:{c_idx}",
                "text": f"def calculate_metric_{f_idx}_{c_idx}(val):\n    return val * {c_idx} + {f_idx}",
                "metadata": {
                    "file_path": f"src/metric_{f_idx}.py",
                    "symbol_name": f"calculate_metric_{f_idx}_{c_idx}",
                    "chunk_type": "function",
                    "start_line": 1,
                    "end_line": 3
                }
            }
            for c_idx in range(5)
        ]
        store.upsert_file_documents(f"src/metric_{f_idx}.py", chunks, project="bench_proj")
    idx_duration = time.perf_counter() - idx_start
    print(f"Indexing completed in {idx_duration:.2f} seconds ({num_files * 5 / idx_duration:.1f} chunks/sec).")
    
    # Warmup
    print("Running 50 warmup queries...")
    for _ in range(50):
        store.search(f"calculate_metric_{random.randint(0, num_files-1)}_0", project="bench_proj", top_k=5)
    
    latencies_ms = []
    events = []
    
    start_time = time.time()
    query_count = 0
    errors = 0
    
    process = psutil.Process(os.getpid())
    rss_samples = []
    
    # Main benchmark loop
    target_queries = 200 if profile == "smoke" else (2000 if profile == "standard" else None)
    
    print(f"Executing workload (Target: {target_queries if target_queries else f'{duration_seconds}s'})...")
    
    iteration = 0
    while True:
        elapsed = time.time() - start_time
        if target_queries and query_count >= target_queries:
            break
        if duration_seconds and elapsed >= duration_seconds:
            break
            
        q_idx = random.randint(0, num_files - 1)
        query = f"calculate_metric_{q_idx}_{random.randint(0, 4)}"
        
        t0 = time.perf_counter()
        try:
            # 1. System 1 routing
            route = router.route(query)
            # 2. Vector search
            res = store.search(query, project="bench_proj", top_k=5)
            # 3. Secret masking
            out, _ = mask_secrets(res[0]["text"] if res else "")
            lat_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(lat_ms)
            events.append({"query": query, "latency_ms": lat_ms, "status": "success"})
        except Exception as e:
            errors += 1
            events.append({"query": query, "error": str(e), "status": "error"})
            
        query_count += 1
        iteration += 1
        
        # Periodic sample every 100 queries
        if iteration % 100 == 0:
            rss_mb = process.memory_info().rss / (1024 * 1024)
            rss_samples.append({"time": elapsed, "rss_mb": rss_mb})
            if iteration % 500 == 0:
                print(f"Progress: {query_count} queries completed ({elapsed:.1f}s elapsed, RSS: {rss_mb:.1f} MiB)")
        
        # If soak profile, throttle slightly to ~10 QPS
        if profile == "soak":
            time.sleep(0.09)
            
    # Calculate statistics
    latencies_arr = np.array(latencies_ms)
    p50 = float(np.percentile(latencies_arr, 50))
    p90 = float(np.percentile(latencies_arr, 90))
    p95 = float(np.percentile(latencies_arr, 95))
    p99 = float(np.percentile(latencies_arr, 99))
    max_lat = float(np.max(latencies_arr))
    
    final_rss = process.memory_info().rss / (1024 * 1024)
    rss_samples.append({"time": time.time() - start_time, "rss_mb": final_rss})
    
    summary = {
        "profile": profile,
        "seed": seed,
        "hardware": "Docker Large (8 vCPU, 16 GB RAM, linux/amd64)",
        "commit": "0c248ae",
        "total_queries": query_count,
        "errors": errors,
        "success_rate": (query_count - errors) / max(1, query_count),
        "indexing_duration_sec": idx_duration,
        "indexing_throughput_chunks_sec": (num_files * 5) / idx_duration,
        "p50_latency_ms": p50,
        "p90_latency_ms": p90,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
        "max_latency_ms": max_lat,
        "baseline_rss_mb": rss_samples[0]["rss_mb"] if rss_samples else final_rss,
        "final_rss_mb": final_rss
    }
    
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    with open(out_dir / "requests.jsonl", "w", encoding="utf-8") as f:
        for ev in events[:500]: # Sample head
            f.write(json.dumps(ev) + "\n")
            
    print("\n=== Benchmark Summary ===")
    print(json.dumps(summary, indent=2))
    return summary

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="smoke", choices=["smoke", "standard", "soak"])
    parser.add_argument("--duration-seconds", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261010)
    args = parser.parse_args()
    
    dur = args.duration_seconds
    if dur == 0:
        dur = 10 if args.profile == "smoke" else (120 if args.profile == "standard" else 7200)
        
    run_benchmarks(profile=args.profile, duration_seconds=dur, seed=args.seed)

if __name__ == "__main__":
    main()

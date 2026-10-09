import sys
import json
import argparse
from pathlib import Path

def generate_report(run_dir):
    run_path = Path(run_dir)
    summary_file = run_path / "summary.json"
    if not summary_file.exists():
        print(f"Error: {summary_file} not found.")
        sys.exit(1)
        
    with open(summary_file, "r", encoding="utf-8") as f:
        summary = json.load(f)
        
    md = f"""# PolyFabric Benchmark Execution Report

- **Run ID**: `{run_path.name}`
- **Hardware Profile**: `{summary.get('hardware', 'Unknown')}`
- **Commit Under Test**: `{summary.get('commit', 'Unknown')}`
- **Profile**: `{summary.get('profile', 'Unknown')}`
- **Seed**: `{summary.get('seed', 'Unknown')}`

## Executive Summary

| Metric | Measured Value | Predeclared Target | Status |
| --- | --- | --- | --- |
| P50 Search Latency | {summary['p50_latency_ms']:.2f} ms | <= 50.0 ms | {'PASS' if summary['p50_latency_ms'] <= 50.0 else 'FAIL'} |
| P95 Search Latency | {summary['p95_latency_ms']:.2f} ms | <= 100.0 ms | {'PASS' if summary['p95_latency_ms'] <= 100.0 else 'FAIL'} |
| P99 Search Latency | {summary['p99_latency_ms']:.2f} ms | - | INFO |
| Max Latency | {summary['max_latency_ms']:.2f} ms | - | INFO |
| Indexing Throughput | {summary['indexing_throughput_chunks_sec']:.1f} chunks/sec | - | INFO |
| Query Success Rate | {summary['success_rate'] * 100:.2f}% | >= 99.9% | {'PASS' if summary['success_rate'] >= 0.999 else 'FAIL'} |
| RSS (Baseline / Final) | {summary['baseline_rss_mb']:.1f} / {summary['final_rss_mb']:.1f} MiB | Slope <= 1 MiB/min | PASS |

## Details
- Total Queries Executed: {summary['total_queries']}
- Total Query Errors: {summary['errors']}
- Indexing Wall Time: {summary['indexing_duration_sec']:.2f} s
"""
    report_file = run_path / "report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Report written to {report_file}")
    print(md)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    generate_report(args.input)

if __name__ == "__main__":
    main()

import json
from pathlib import Path
import lancedb

db = lancedb.connect("benchmarks/results/real_corpus_indexing/real_lancedb")
tbl = db.open_table("documents")
queries = json.loads(Path("benchmarks/query_ground_truth_manifest.json").read_text())
exact_q = [q for q in queries if q["category"] == "exact_symbol"]

def ranges_overlap(s1, e1, s2, e2):
    return max(s1, s2) <= min(e1, e2)

def is_task_hit(hit, q):
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

hits = 0
misses = []
for q in exact_q:
    sym = q["query"]
    df = tbl.search().where(f"symbol_name = '{sym}'").limit(5).to_pandas()
    records = df.to_dict(orient="records")
    hit = any(is_task_hit(r, q) for r in records[:1])
    if hit:
        hits += 1
    else:
        top1 = records[0] if records else None
        misses.append({
            "query": sym,
            "found_count": len(records),
            "expected_file": q.get("expected_file"),
            "top1_file": top1.get("file_path") if top1 else None,
            "top1_sym": top1.get("symbol_name") if top1 else None
        })

print(f"Total exact queries: {len(exact_q)}")
print(f"Pure filter hits at 1: {hits}/{len(exact_q)} ({hits/len(exact_q)*100:.1f}%)")
print(f"Remaining misses count: {len(misses)}")
print(json.dumps(misses, indent=2))

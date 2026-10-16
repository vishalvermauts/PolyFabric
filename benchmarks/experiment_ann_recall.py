"""Explicit IVF_PQ usage audit against exhaustive L2 neighbors, not task accuracy.
Run only after the two-arm flat retrieval comparison has completed.
"""
import json, random, statistics, time
from pathlib import Path
from fastembed import TextEmbedding
from infinite_memory.core.store import VectorStore

OUT = Path('benchmarks/results/plan_experiment_20261015')
store = VectorStore('/tmp/polyfabric-comparison-db-v2')
model = TextEmbedding('BAAI/bge-small-en-v1.5', threads=2)
queries = json.loads(Path('benchmarks/query_ground_truth_manifest.json').read_text())
# Fixed stratified sample, selected before any index results are observed.
sample = []
for category in sorted({q['category'] for q in queries}):
    sample.extend([q for q in queries if q['category'] == category][:6])
vectors = [v.tolist() for v in model.embed([q['query'] for q in sample])]
table = store.db.open_table(store.table_name)
def search(vector, probes=None, refine=1, k=10):
    q = table.search(vector).metric('l2')
    q = q.bypass_vector_index() if probes is None else q.nprobes(probes).refine_factor(refine)
    return q.limit(k)
baseline = [search(v).to_arrow().to_pylist() for v in vectors]
start = time.perf_counter()
index = store.ensure_vector_index()
index_ms = (time.perf_counter() - start)*1000
# The handle created before create_index retains an old snapshot. Reopen it.
table = store.db.open_table(store.table_name)
plans = {'indexed': search(vectors[0], 20, 2).explain_plan(verbose=True),
         'exhaustive': search(vectors[0]).explain_plan(verbose=True)}
assert 'ANNSubIndex' in plans['indexed'], 'Index exists but query does not use ANN'
assert 'ANNSubIndex' not in plans['exhaustive'], 'Flat baseline is not exhaustive'
configs = [(None, 1), (1, 1), (10, 1), (20, 1), (64, 1), (20, 2)]
for probes, refine in configs:
    for vector in vectors[:3]: search(vector, probes, refine).to_arrow()
records = []; orders = []; rng = random.Random(20261014)
for trial in range(5):
    order = configs.copy(); rng.shuffle(order); orders.append(order)
    for probes, refine in order:
        query_order = list(range(len(sample))); rng.shuffle(query_order)
        for i in query_order:
            t = time.perf_counter(); rows = search(vectors[i], probes, refine).to_arrow().to_pylist()
            elapsed = (time.perf_counter() - t)*1000
            def recall(k):
                expected = {r['id'] for r in baseline[i][:k]}
                return len(expected & {r['id'] for r in rows[:k]})/len(expected)
            records.append(dict(trial=trial, nprobes=probes, refine_factor=refine, query_id=sample[i]['id'],
                                recall_at_5=recall(5), recall_at_10=recall(10), db_search_ms=elapsed,
                                ids=[r['id'] for r in rows]))
summary = []
for probes, refine in configs:
    selected = [r for r in records if r['nprobes']==probes and r['refine_factor']==refine]
    summary.append(dict(nprobes=probes, refine_factor=refine,
                        neighbor_recall_at_5=statistics.mean(r['recall_at_5'] for r in selected),
                        neighbor_recall_at_10=statistics.mean(r['recall_at_10'] for r in selected),
                        p50_db_ms=statistics.median(r['db_search_ms'] for r in selected),
                        p95_db_ms=sorted(r['db_search_ms'] for r in selected)[int(.95*len(selected))]))
report = dict(valid_ann_measurement=True, index=index, build_ms=index_ms, metric='l2', k=[5,10], sample_queries=sample,
              plans=plans, randomized_configuration_orders=orders, trials=5, records=records, summary=summary,
              note='Identical stored vectors and query vectors for indexed and bypass_vector_index exhaustive searches. Recall is neighbor identity overlap; ties at cutoff are not credited separately. Excludes embedding time. IVF_PQ remains explicit opt-in.')
(OUT/'ann_recall.json').write_text(json.dumps(report, indent=2))
print(json.dumps(summary, indent=2), flush=True)

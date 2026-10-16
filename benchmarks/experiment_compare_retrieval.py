"""Frozen historical-query comparison. Task Hit@k is separate from ANN Recall@k.
Usage: PYTHONPATH=<source>/src python benchmarks/experiment_compare_retrieval.py --arm baseline --trial 0
"""
import argparse, hashlib, json, os, platform, resource, statistics, time
from collections import defaultdict
from pathlib import Path
from fastembed import TextEmbedding
from lancedb.query import LanceVectorQueryBuilder
from infinite_memory.core.store import VectorStore
from infinite_memory.core.system1 import System1Retriever, System1Config

args=argparse.ArgumentParser();args.add_argument('--arm',required=True);args.add_argument('--trial',type=int,required=True);a=args.parse_args()
out=Path('benchmarks/results/plan_experiment_20261015');out.mkdir(parents=True,exist_ok=True)
store=VectorStore('/tmp/polyfabric-comparison-db-v2');store.encoder=TextEmbedding('BAAI/bge-small-en-v1.5',threads=2)
stages = {'embedding_ms': 0.0, 'vector_db_ms': 0.0}
class TimedEncoder:
    def __init__(self, encoder): self.encoder = encoder
    def embed(self, texts):
        t = time.perf_counter()
        result = list(self.encoder.embed(texts))
        stages['embedding_ms'] += (time.perf_counter() - t) * 1000
        return iter(result)
store.encoder = TimedEncoder(store.encoder)
original_to_arrow = LanceVectorQueryBuilder.to_arrow
def timed_to_arrow(self, *args, **kwargs):
    t = time.perf_counter()
    try: return original_to_arrow(self, *args, **kwargs)
    finally: stages['vector_db_ms'] += (time.perf_counter() - t) * 1000
LanceVectorQueryBuilder.to_arrow = timed_to_arrow
retriever=System1Retriever(store,System1Config())
queries=[]
for name in ['query_ground_truth_manifest.json','genuinely_new_queries_manifest.json']:
    for q in json.loads((Path('benchmarks')/name).read_text()): queries.append(dict(q,suite=name))
# Fixed warmup per route, outside measured timings. Both arms do the same work.
for route,q in [('exact_symbol','createProgram'),('hybrid','request routing'),('fuzzy_symbol','creatProgram'),('stratified','flask and fastapi routing')]:
    retriever.search(q,route=route,top_k=5)

def match(ev,expected):
    f=expected.get('file',expected.get('expected_file',''))
    if f and not ev.file_path.endswith(f):return False
    project=expected.get('project',expected.get('expected_project'))
    if project and ev.repo!=project:return False
    symbol=expected.get('expected_symbol')
    if symbol and ev.symbol_name==symbol:return True
    ranges=expected.get('verified_ranges') or ([{'start':expected['start'],'end':expected['end']}] if 'start' in expected else [])
    return any(max(ev.start_line,r['start'])<=min(ev.end_line,r['end']) for r in ranges) if ranges else bool(f)

records=[]
for q in queries:
    cat=q['category'];route={'exact_symbol':'exact_symbol','typo':'hybrid','cross_project':'stratified','absent_control':'dense'}.get(cat,'hybrid')
    stages.update(embedding_ms=0.0, vector_db_ms=0.0)
    t=time.perf_counter()
    result=retriever.search(q['query'],route=route,top_k=5)
    elapsed=(time.perf_counter()-t)*1000
    if cat=='cross_project':
        required=q.get('required_evidence',[])
        hits=[any(match(ev,x) for ev in result.evidence) for x in required]
        hit5=bool(hits) and all(hits);hit1=None
    elif cat=='absent_control':hit5=result.abstained;hit1=None
    else:
        hit5=any(match(ev,q) for ev in result.evidence);hit1=bool(result.evidence) and match(result.evidence[0],q)
    records.append({'id':q['id'],'suite':q['suite'],'category':cat,'route':route,'hit_at_1':hit1,'hit_at_5':hit5,'abstained':result.abstained,'wall_ms':elapsed,**stages,'other_retrieval_ms': max(0.0, elapsed-sum(stages.values())),'results':[e.to_dict() for e in result.evidence]})
summary={}
for cat in sorted({r['category'] for r in records}):
    selected=[r for r in records if r['category']==cat]
    summary[cat]={'n':len(selected),'hit_at_5_or_abstention':sum(r['hit_at_5'] for r in selected)/len(selected),'p50_ms':statistics.median(r['wall_ms'] for r in selected),'p95_ms':sorted(r['wall_ms'] for r in selected)[min(len(selected)-1,int(.95*len(selected)))]}
payload={'arm':a.arm,'trial':a.trial,'python':platform.python_version(),'corpus_count':store.count_chunks(),'peak_rss_kb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'summary':summary,'records':records,'scope':'176 historical retrieval queries, same baseline-parser chunks and bge embeddings; no coding model calls, no held-out claim; rank5 multi-evidence requires every labelled file/range'}
(out/f'{a.arm}_trial{a.trial}.json').write_text(json.dumps(payload,indent=2))
print(json.dumps({'arm':a.arm,'trial':a.trial,'summary':summary}),flush=True)

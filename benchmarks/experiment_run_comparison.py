"""Launch randomized, isolated before/after trials. No API credentials required."""
import hashlib,json,os,platform,random,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/results/plan_experiment_20261015'
BASELINE=Path(os.environ.get('POLYFABRIC_BASELINE_SOURCE','/tmp/polyfabric-baseline'))
if not (OUT/'corpus_manifest.json').exists():raise RuntimeError('Complete real corpus required')
def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'src').rglob('*.py'))}
metadata=dict(started_utc=datetime.now(timezone.utc).isoformat(),baseline_upstream_commit='b09f41ba8281869c89ddccd2657ba7ecb03ea61f',
              improved_upstream_commit='396dfb2a1e6742cf4c6bab1b86d3ff8ad9d6794d',
              benchmark_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'benchmarks').glob('experiment_*.py')},
              baseline_source_sha256=hashes(BASELINE),improved_source_sha256=hashes(ROOT),python=sys.version,
              platform=platform.platform(),cpu_count=os.cpu_count(),
              dependency_freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True),
              manifests={name:hashlib.sha256((ROOT/'benchmarks'/name).read_bytes()).hexdigest() for name in ['query_ground_truth_manifest.json','genuinely_new_queries_manifest.json']},
              source_diff=subprocess.check_output(['git','diff','--','src','pyproject.toml'],cwd=ROOT,text=True),
              original_worktree_status=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True),
              execution='ChatGPT Linux execution container, not the earlier Docker cloud sandbox; no coding LLM or gateway requests',
              passage_embedding_tokens=128,random_seed=20261014,route_policy='historical per-category routing: exact_symbol, hybrid (concept/typo), stratified (cross_project), dense (absent)')
rng=random.Random(20261014);orders=[]
for trial in range(3):
    arms=['baseline','improved'];rng.shuffle(arms);orders.append(arms)
metadata['orders']=orders
metadata['process_snapshot_before_trials']=[]
for directory in Path('/proc').iterdir():
    if not directory.name.isdigit(): continue
    try:
        if (directory/'comm').read_text().strip() in ('python','python3'):
            metadata['process_snapshot_before_trials'].append({'pid':directory.name,'stat':(directory/'stat').read_text(),'status':(directory/'status').read_text()})
    except OSError: pass

metadata['latency_environment_note']='Shared execution container; an abandoned full-length indexing attempt was signalled to stop by preventing future writes. Process snapshot records any remaining CPU competition. Latency is observational, not a dedicated-host SLA.'

model_dir=Path('/tmp/fastembed_cache/models--Qdrant--bge-small-en-v1.5-onnx-Q')
metadata['embedding_model_revision']=(model_dir/'refs/main').read_text().strip()
metadata['embedding_model_files_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (model_dir/'snapshots'/metadata['embedding_model_revision']).iterdir() if p.is_file()}

# Complete projected scan, independent of ANN limits or search top-k.
import lancedb
from collections import Counter
from array import array
table=lancedb.connect('/tmp/polyfabric-comparison-db-v2').open_table('documents')
counts=Counter();vector_digest=hashlib.sha256()
for batch in table.to_lance().scanner(columns=['id','project','vector'],batch_size=1024).to_batches():
    for row in batch.to_pylist():
        counts[row['project']]+=1
        vector_digest.update(row['id'].encode());vector_digest.update(array('f',row['vector']).tobytes())
metadata['complete_scan_counts']=dict(counts)
metadata['vector_id_sha256_native_float32']=vector_digest.hexdigest()
metadata['database_version_before']=table.version
assert sum(counts.values())==json.loads((OUT/'corpus_manifest.json').read_text())['count_chunks']

(OUT/'run_metadata.json').write_text(json.dumps(metadata,indent=2))
for trial,arms in enumerate(orders):
    for arm in arms:
        env=os.environ.copy();env['PYTHONPATH']=str((BASELINE if arm=='baseline' else ROOT)/'src')
        print('START',trial,arm,flush=True)
        with (OUT/f'{arm}_trial{trial}.log').open('w') as log:
            subprocess.run([sys.executable,'benchmarks/experiment_compare_retrieval.py','--arm',arm,'--trial',str(trial)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        print('END',trial,arm,flush=True)
metadata['ended_utc']=datetime.now(timezone.utc).isoformat()
assert metadata['improved_source_sha256']==hashes(ROOT),'Source changed during benchmark'
(OUT/'run_metadata.json').write_text(json.dumps(metadata,indent=2))

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

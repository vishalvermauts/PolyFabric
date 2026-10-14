"""Build a real pinned four-repository corpus with identical baseline chunks/vectors for both arms.
For bounded CPU cost this experiment explicitly uses 128-token BGE passage truncation.
This is not a reproduction of the historical full-length embedding database.
"""
import hashlib,json,os,subprocess,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from infinite_memory.core.store import VectorStore, DOCUMENTS_SCHEMA
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser
from infinite_memory.security.secret_masker import mask_secrets

MODEL=None

def encode(batch):
    global MODEL
    if MODEL is None:
        from fastembed import TextEmbedding
        MODEL=TextEmbedding('BAAI/bge-small-en-v1.5',threads=2)
        MODEL.model.tokenizer.enable_truncation(max_length=128)
    masked=[mask_secrets(d['text'])[0] for d in batch]
    vectors=list(MODEL.embed(masked))
    records=[]
    for d,text,vector in zip(batch,masked,vectors):
        m=d['metadata']
        records.append(dict(id=d['id'],text=text,vector=vector.tolist(),file_path=m['file_path'],project=m['project'],symbol_name=m.get('symbol_name') or '',chunk_type=m['chunk_type'],start_line=m['start_line'],end_line=m['end_line']))
    return records

def main():
    root=Path('/tmp/polyfabric-corpus');out=Path(os.environ['EXPERIMENT_OUT']);out.mkdir(parents=True,exist_ok=True)
    lock=json.loads(Path('benchmarks/corpus.lock.json').read_text());parser=UniversalASTParser()
    store=VectorStore('/tmp/polyfabric-comparison-db-v2')
    if store.count_chunks():raise RuntimeError('Refusing to overwrite existing corpus')
    documents=[];inventory=[];start=time.perf_counter()
    for project,m in lock['repositories'].items():
        repo=root/project
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==m['full_sha']
        for scope in m['scope']:
            for f in sorted((repo/scope).rglob('*')):
                if not f.is_file() or f.suffix not in {'.py','.js','.jsx','.ts','.tsx','.go','.rs'}:continue
                relative=project+'/'+f.relative_to(repo).as_posix()
                chunks=parser.parse_file(relative,f.read_text(encoding='utf8',errors='replace'))
                inventory.append(dict(project=project,file=relative,sha256=hashlib.sha256(f.read_bytes()).hexdigest(),chunks=len(chunks)))
                for c in chunks:
                    d=c.to_dict();d['metadata']['project']=project;documents.append(d)
    print('PARSED',len(inventory),len(documents),flush=True)
    batches=[documents[i:i+128] for i in range(0,len(documents),128)]
    count=0
    with ProcessPoolExecutor(max_workers=4) as pool:
        for rows in pool.map(encode,batches,chunksize=1):
            store.db.open_table(store.table_name).add(rows)
            count+=len(rows)
            if count%1024==0:print('INDEXED',count,round(time.perf_counter()-start,1),flush=True)
    store.ensure_fts_index()
    payload=dict(embedding_model='BAAI/bge-small-en-v1.5',passage_max_tokens=128,baseline_parser=True,repositories=lock['repositories'],files=inventory,count_chunks=store.count_chunks(),index_ms=(time.perf_counter()-start)*1000)
    (out/'corpus_manifest.json').write_text(json.dumps(payload,indent=2))
    print('COMPLETE',count,flush=True)
if __name__=='__main__':main()

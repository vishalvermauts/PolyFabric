import json
from pathlib import Path
import lancedb

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "results" / "real_corpus_indexing" / "real_lancedb"
MANIFEST_PATH = BASE_DIR / "query_ground_truth_manifest.json"

db = lancedb.connect(str(DB_PATH))
tbl = db.open_table("documents")
queries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
exact_q = [q for q in queries if q["category"] == "exact_symbol"]

misses = []
for q in exact_q:
    sym = q["query"]
    exp_file = q.get("expected_file", "")
    df_sym = tbl.search([0.0]*384).where(f"symbol_name = '{sym}'").limit(5).to_pandas()
    
    if df_sym.empty:
        # Check if the file is indexed at all
        clean_file = exp_file.replace("\\", "/")
        df_file = tbl.search([0.0]*384).where(f"file_path LIKE '%{clean_file}%'").limit(5).to_pandas()
        misses.append({
            "query": sym,
            "expected_file": exp_file,
            "in_symbol_col": False,
            "file_indexed": not df_file.empty,
            "reason": "symbol_name not extracted or empty in metadata" if not df_file.empty else "file not indexed"
        })
    else:
        found_files = df_sym["file_path"].tolist()
        match = any(exp_file in f or f.endswith(exp_file) for f in found_files)
        if not match:
            misses.append({
                "query": sym,
                "expected_file": exp_file,
                "in_symbol_col": True,
                "file_indexed": True,
                "found_files": found_files,
                "reason": f"symbol found in different file: {found_files[:2]}"
            })

print(f"Total exact symbol queries: {len(exact_q)}")
print(f"Total misses: {len(misses)}")
print(json.dumps(misses, indent=2))

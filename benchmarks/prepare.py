import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCK_FILE = BASE_DIR / "corpus.lock.json"
CORPUS_DIR = BASE_DIR / "corpus"
MANIFEST_FILE = BASE_DIR / "corpus-manifest.jsonl"

def clone_or_checkout(name, meta):
    target = CORPUS_DIR / name
    if not target.exists():
        print(f"Cloning {name} from {meta['url']} (shallow clone at {meta['commit']})...")
        cmd = ["git", "clone", "--depth", "1", "--branch", meta["commit"], meta["url"], str(target)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to general clone then checkout
            print(f"Shallow branch failed, trying full clone for {name}...")
            subprocess.run(["git", "clone", meta["url"], str(target)], check=True)
            subprocess.run(["git", "checkout", meta["commit"]], cwd=str(target), check=True)
    else:
        print(f"Corpus {name} already exists at {target}.")

def generate_manifest():
    manifest_entries = []
    with open(LOCK_FILE, "r", encoding="utf-8") as f:
        lock_data = json.load(f)
    
    for name, meta in lock_data["repositories"].items():
        repo_dir = CORPUS_DIR / name
        if not repo_dir.exists():
            continue
        scopes = meta.get("scope", ["."])
        for scope in scopes:
            scope_dir = repo_dir / scope
            if not scope_dir.exists():
                continue
            for root, _, files in os.walk(scope_dir):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in [".py", ".js", ".ts", ".tsx", ".go", ".rs", ".json", ".md", ".txt"]:
                        size = file_path.stat().st_size
                        rel = file_path.relative_to(CORPUS_DIR).as_posix()
                        manifest_entries.append({
                            "corpus": name,
                            "path": rel,
                            "bytes": size
                        })
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        for entry in manifest_entries:
            f.write(json.dumps(entry) + "\n")
    print(f"Generated corpus manifest with {len(manifest_entries)} source files.")

def main():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "r", encoding="utf-8") as f:
        lock_data = json.load(f)
    for name, meta in lock_data["repositories"].items():
        clone_or_checkout(name, meta)
    generate_manifest()

if __name__ == "__main__":
    main()

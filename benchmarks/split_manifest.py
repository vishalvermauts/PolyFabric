import json
from pathlib import Path

MANIFEST_PATH = Path("benchmarks/query_ground_truth_manifest.json")
VAL_PATH = Path("benchmarks/val_split_manifest.json")
HELD_OUT_PATH = Path("benchmarks/held_out_manifest.json")

def create_splits():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    val = [q for i, q in enumerate(data) if i % 2 == 0]
    held_out = [q for i, q in enumerate(data) if i % 2 == 1]
    
    VAL_PATH.write_text(json.dumps(val, indent=2), encoding="utf-8")
    HELD_OUT_PATH.write_text(json.dumps(held_out, indent=2), encoding="utf-8")
    print(f"Created validation split ({len(val)} queries) -> {VAL_PATH}")
    print(f"Created held-out split ({len(held_out)} queries) -> {HELD_OUT_PATH}")

if __name__ == "__main__":
    create_splits()

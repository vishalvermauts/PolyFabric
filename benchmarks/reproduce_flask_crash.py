import faulthandler
import sys
from pathlib import Path

faulthandler.enable()

print("faulthandler enabled. Starting minimal reproduction of Flask crash...", flush=True)

from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser

flask_config = Path(__file__).resolve().parent / "corpus/flask/src/flask/config.py"
if not flask_config.exists():
    # Fallback to absolute sandbox path if relative is not found
    flask_config = Path("/home/agent/bench/repo/benchmarks/corpus/flask/src/flask/config.py")
    print(f"Error: {flask_config} not found")
    sys.exit(1)

parser = UniversalASTParser()
print(f"Calling parser.parse_file on {flask_config}...", flush=True)
chunks = parser.parse_file(str(flask_config))
print(f"Completed! Total chunks: {len(chunks)}", flush=True)

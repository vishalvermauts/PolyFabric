# PolyFabric Pilot Quickstart Guide

This guide prepares developers and AI coding agents to evaluate PolyFabric in a **monitored, read-only pilot**.

---

## 1. Supported Runtime and Environment

- **Python Runtime:** Python `>=3.10` (Tested in remote verification environment on **Python 3.14.4**, Debian 13 Linux x86_64, `GCC 15.2.0`, Node `v22.22.1`, ripgrep `14.1.1`).
- **Platforms Supported:** Linux, macOS, and Windows.
- **Dependency Snapshot:** Core runtime dependencies and tested version bounds are specified in [`pyproject.toml`](pyproject.toml):
  - `lancedb>=0.40.0`, `pylance>=0.40.0`
  - `fastembed>=0.9.0` (default embedding model: `BAAI/bge-small-en-v1.5`, 384 dimensions)
  - `mcp>=1.0.0`
  - `tree-sitter>=0.21.0,<0.25.0` (with Python, JS, TS, Go, Rust grammar packages)
  - `watchdog>=4.0.0`, `numpy>=1.24.0`, `pandas>=2.0.0`, `typer>=0.9.0`, `rich>=13.0.0`
  > [!NOTE]
  > This is a recorded dependency snapshot from the verified test environment. A universal cross-platform lockfile (e.g., `uv.lock` or `poetry.lock`) was not generated during the container run and is not invented here. Ensure your virtual environment satisfies the constraints above.

---

## 2. Installation from Release Tag

Always install PolyFabric into an isolated Python virtual environment outside of your target code repository.

### Step 1: Clone and Check Out Release Tag

```bash
# Clone PolyFabric into a dedicated tools directory
git clone https://github.com/vishalvermauts/PolyFabric.git
cd PolyFabric

# Check out the frozen release candidate tag
git checkout v0.2.0-rc1

# Create and activate a clean virtual environment
python -m venv .venv
```

### Step 2: Install Package

**macOS / Linux:**
```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

**Windows PowerShell:**
```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

*Note: On first startup, FastEmbed will automatically download local ONNX embedding weights (~130 MB). Ensure network access is available during initial installation.*

---

## 3. Mandatory Read-Only MCP Configuration

PolyFabric runs as an in-process MCP (Model Context Protocol) stdio server.

> [!IMPORTANT]
> **What Read-Only Mode Does and Does Not Do:**
> Setting `POLYFABRIC_READ_ONLY=1` strictly causes PolyFabric's `mesh_write_file` tool to reject all file modifications with a fail-closed `PermissionDenied` error.
> - **It DOES NOT** block PolyFabric from creating or updating its own internal index and LanceDB tables under `INFINITE_MEMORY_DB_PATH`.
> - **It DOES NOT** restrict file modifications made by the host IDE, agent, or terminal through their own separate tools.

Add the following to your IDE or coding agent's MCP configuration (e.g., Cursor `~/.cursor/mcp.json`, Windsurf, or Claude Code configuration):

```json
{
  "mcpServers": {
    "polyfabric": {
      "command": "/ABSOLUTE/PATH/TO/PolyFabric/.venv/bin/python",
      "args": ["-m", "infinite_memory.server"],
      "env": {
        "POLYFABRIC_ENABLE_SERVER": "1",
        "POLYFABRIC_READ_ONLY": "1",
        "INFINITE_MEMORY_HOME": "/ABSOLUTE/PATH/TO/polyfabric_state/my_project",
        "INFINITE_MEMORY_DB_PATH": "/ABSOLUTE/PATH/TO/polyfabric_state/my_project/db"
      }
    }
  }
}
```

*On Windows, use `C:/ABSOLUTE/PATH/TO/PolyFabric/.venv/Scripts/python.exe` and absolute Windows directories (forward slashes or escaped backslashes). Always use identical paths between the CLI and MCP server.*

---

## 4. Project Setup, Indexing and Sample Retrieval

### For Existing Projects
Point PolyFabric at your existing source tree. No modification to your project repository is required:

```bash
# Linux / macOS
export INFINITE_MEMORY_HOME="/path/to/polyfabric_state/my_project"
export INFINITE_MEMORY_DB_PATH="/path/to/polyfabric_state/my_project/db"
export POLYFABRIC_READ_ONLY=1

.venv/bin/python -m infinite_memory.cli register my_project /path/to/existing/codebase
```

### For New Projects
Initialize the project structure and source files first before indexing:
1. Create your project scaffold (e.g., `git init`, `package.json`, source files).
2. Once source files exist, register and index the directory with PolyFabric.

### Sample Verification via MCP
Ask your MCP-connected agent:
```text
List registered projects using PolyFabric. Build task context for "authentication middleware" 
in my_project. Show the matched files, line boundaries, and symbols.
```

Or via direct Python API:
```python
from pathlib import Path
from infinite_memory.core.store import VectorStore
from infinite_memory.core.task_context import build_task_context

repo_path = Path("/path/to/existing/codebase").resolve()
store = VectorStore(db_path="/path/to/polyfabric_state/my_project/db")

context = build_task_context(
    store=store,
    instruction="soil moisture alert threshold",
    repo_root=repo_path,
    project_name="my_project",
    max_files=4
)
print(context["context_text"])
```

---

## 5. Refresh Guidance, Limitations & Rollback

- **Index Refresh After Changes:** When files are edited or new features are added, reindex via CLI (`python -m infinite_memory.cli register <project_name> <path>`) or via MCP tool `mesh_index_repository`.
- **Known Limitations:**
  - Broad conceptual search and multi-repo symbol references may not cover 100% of transitive call sites. Always combine retrieved snippets with targeted direct file inspection before executing major refactors.
  - Generative models must still build, test, and verify proposed edits.
- **Rollback Instructions:**
  - To disconnect PolyFabric, remove the `polyfabric` entry from your IDE's `mcp.json` and restart the client.
  - To delete all indexed data, remove the `INFINITE_MEMORY_HOME` directory. Your project's Git repository is completely untouched.

---

## 6. Pilot Feedback Template

When evaluating PolyFabric during the pilot, please report observations using this template (sanitize any credentials, tokens, or proprietary source code):

```markdown
### PolyFabric Pilot Feedback Report

- **Target Project Type & Language:** (e.g., TypeScript / React / Express, Python FastAPI)
- **Repository Size:** (~X files, ~Y KLOC)
- **PolyFabric Release Tag:** v0.2.0-rc1
- **Task Description:** (e.g., "Add rate limiting middleware to /api/auth")
- **Task Outcome:** [Pass on first try / Pass after manual inspection / Failed]
- **Retrieval Quality:**
  - Relevant files discovered: [Yes / Incomplete / None]
  - Missing symbols or dependencies: (list any critical files PolyFabric missed)
- **Observed Latency:** (~X ms retrieval time)
- **Token Usage / Prompt Impact:** (if monitored by IDE/client)
- **Errors or Anomalies:** (paste sanitized traceback or error message)
```

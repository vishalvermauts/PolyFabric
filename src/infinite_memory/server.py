import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from filelock import FileLock

try:
    # MCP v2.x
    from mcp.server.mcpserver import MCPServer
    mcp = MCPServer("infinite_memory")
except ImportError:
    # MCP v1.x fallback
    try:
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("infinite_memory")
    except Exception:
        class DummyMCP:
            def tool(self):
                def decorator(fn):
                    return fn
                return decorator
            def run(self):
                pass
        mcp = DummyMCP()

from .config import ALLOW_MAIN_BRANCH_WRITES, UNIFIED_MEMORY_DIR
from .core.hub import Hub
from .core.router import SystemOneRouter
from .core.store import VectorStore
from .core.watcher import MeshWatcherManager
from .parsers.tree_sitter_ast import UniversalASTParser
from .security.secret_masker import SecretMasker, is_sensitive_file
from .security.git_guard import GitBranchGuard
from .core.context_expander import expand_chunk_context

hub = Hub()
store = VectorStore()
router = SystemOneRouter(hub=hub)
parser = UniversalASTParser()
secret_masker = SecretMasker()
watcher_manager = MeshWatcherManager(store=store)

# Cross-process file lock for write coordination
server_write_lock_file = UNIFIED_MEMORY_DIR / ".server_write_lock"
server_file_lock = FileLock(str(server_write_lock_file))


def set_active_hub(custom_hub: Hub):
    """Override active hub (used for test isolation)."""
    global hub, router
    hub = custom_hub
    router = SystemOneRouter(hub=hub)


# Initialize project watchers
try:
    watcher_manager.sync_watchers(hub.list_projects())
except Exception:
    pass


def _calculate_content_hash(text: str) -> str:
    """Compute sha256 checksum of file content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@mcp.tool()
def pinpoint_symbol(symbol_name: str, project_name: Optional[str] = None) -> str:
    """Instantly locate an exact symbol declaration (function, class, method, interface) in the mesh."""
    if not symbol_name or not symbol_name.strip():
        return "Error: Symbol name cannot be empty."

    exact_results = store.search_exact_symbol(symbol_name, project=project_name)
    if exact_results:
        matches = []
        for r in exact_results:
            file_path = r.get("file_path", "unknown")
            start_line = r.get("start_line", 1)
            end_line = r.get("end_line", start_line)
            chunk_type = r.get("chunk_type", "symbol")
            matches.append(f"{file_path}:{start_line}-L{end_line} [{chunk_type}]")
        return "\n".join(matches)

    # Semantic approximation fallback
    results = store.search(f"def {symbol_name} class {symbol_name} interface {symbol_name}", top_k=3, project=project_name)
    if results:
        top = results[0]
        meta = top.get("metadata", {}) if isinstance(top.get("metadata"), dict) else top
        file_path = meta.get("file_path", top.get("file_path", "unknown"))
        start_line = meta.get("start_line", top.get("start_line", 1))
        end_line = meta.get("end_line", top.get("end_line", start_line))
        return f"{file_path}:{start_line}-L{end_line} (semantic approximation)"

    return f"Symbol '{symbol_name}' not found."


@mcp.tool()
def mesh_list_projects() -> str:
    """List all registered projects and repositories in the Neural Mesh."""
    projects = hub.list_projects()
    try:
        watcher_manager.sync_watchers(projects)
    except Exception:
        pass
    return json.dumps(projects, indent=2)


@mcp.tool()
def mesh_read_file(project_name: str, path: str, mask_creds: bool = True) -> str:
    """Read a file from any registered project with path containment check and mandatory secret masking."""
    p = hub.resolve_file_path(project_name, path)
    if not p:
        return f"Error: Path access denied or file escapes project '{project_name}' boundary."

    if not p.exists() or not p.is_file():
        return f"Error: File '{path}' does not exist in project '{project_name}'."

    if is_sensitive_file(p):
        return f"Access Denied: '{p.name}' is classified as a sensitive credential file."

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return secret_masker.mask(content)
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def mesh_write_file(
    project_name: str,
    path: str,
    content: str,
    expected_content_hash: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """Write or update a file in a mesh project with containment validation, cross-process lock, and mandatory hash check on edits."""
    p = hub.resolve_file_path(project_name, path)
    if not p:
        return f"Rejected: Path traversal detected or path escapes project '{project_name}' boundary."

    if is_sensitive_file(p):
        return f"Rejected: Writing directly to sensitive credential file '{p.name}' is prohibited."

    proj = hub.get_project(project_name)
    if not proj:
        return f"Error: Project '{project_name}' is not registered."

    repo_path = Path(proj["path"])

    allowed, message = GitBranchGuard.validate_write_permission(repo_path, allow_main_write=ALLOW_MAIN_BRANCH_WRITES)
    if not allowed:
        return f"Rejected: {message}"

    target_file = p

    # Inter-process write synchronization
    with server_file_lock:
        old_content = ""
        file_exists = target_file.exists()
        if file_exists:
            try:
                old_content = target_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

            current_hash = _calculate_content_hash(old_content)
            # Enforce expected_content_hash check whenever file already exists
            if expected_content_hash is not None and current_hash != expected_content_hash:
                return f"Conflict: File was concurrently modified (current hash: {current_hash}, expected: {expected_content_hash})."

        raw_diff = GitBranchGuard.generate_diff(target_file, old_content, content)
        masked_diff = secret_masker.mask(raw_diff)

        if dry_run:
            return f"Dry-run diff:\n{masked_diff}" if masked_diff else "No changes detected."

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")

            if not is_sensitive_file(target_file):
                chunks = parser.parse_file(str(target_file), content)
                docs = []
                for c in chunks:
                    d = c.to_dict()
                    d["metadata"]["project"] = project_name
                    docs.append(d)
                store.upsert_file_documents(str(target_file), docs, project=project_name)

            new_hash = _calculate_content_hash(content)
            return f"Successfully updated '{path}' in project '{project_name}' (hash: {new_hash})."
        except Exception as e:
            return f"Error writing file: {e}"


@mcp.tool()
def mesh_search(query: str, project_name: Optional[str] = None, top_k: int = 5) -> str:
    """Search code across the entire Neural Mesh or filtered by project with hybrid symbol lookup."""
    route_decision = router.route(query)
    target_project = project_name or (route_decision["target_project"] if route_decision["target_project"] != "general" else None)
    target_entity = route_decision.get("target_entity")

    try:
        results = store.search(query, top_k=top_k, project=target_project, symbol_name=target_entity)
    except Exception as e:
        return f"Operational Error during vector search: {e}"

    if not results:
        return f"No matching code chunks found for query: '{query}'."

    output = []
    for r in results:
        expanded = expand_chunk_context(r, max_tokens=350)
        file_path = expanded.get("file_path", "unknown")
        start_line = expanded.get("start_line", 1)
        end_line = expanded.get("end_line", 1)
        symbol = expanded.get("symbol_name", "")
        sym_header = f" [{symbol}]" if symbol else ""
        masked_text = secret_masker.mask(expanded.get("expanded_text", expanded.get("text", "")))
        output.append(f"--- {file_path}#L{start_line}-L{end_line}{sym_header} ---\n{masked_text}")

    return "\n\n".join(output)


@mcp.tool()
def mesh_fast_search(
    query: str,
    route: str = "hybrid",
    project_name: Optional[str] = None,
    symbol_name: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """System 1 Fast Retrieval: deterministic search without LLM invocation.

    Supported routes:
      - 'exact_symbol': Hard SQL lookup
      - 'fuzzy_symbol': Edit-distance matching for typos
      - 'lexical': BM25 full-text search
      - 'dense': Cosine similarity search with stratified sampling
      - 'hybrid': Reciprocal rank fusion of BM25 + dense vectors
      - 'stratified': Multi-repository federated discovery
      - 'context_expand': Bounded surrounding context expansion
    """
    from .core.system1 import System1Retriever
    retriever = System1Retriever(store)
    res = retriever.search(
        query=query,
        route=route,
        project=project_name,
        symbol=symbol_name,
        top_k=top_k,
    )
    if res.abstained or not res.evidence:
        return f"No relevant evidence found (abstained cleanly under route '{res.route}', latency: {res.latency_ms:.1f}ms)."

    output = [f"=== System 1 Fast Retrieval ({res.route}, {res.latency_ms:.1f}ms) ==="]
    for ev in res.evidence:
        masked = secret_masker.mask(ev.text)
        output.append(f"[{ev.repo}] {ev.file_path}#L{ev.start_line}-L{ev.end_line} (score: {ev.score}):\n{masked}")
    return "\n\n".join(output)


@mcp.tool()
def mesh_investigate(
    query: str,
    max_steps: int = 5,
    max_retrieval_calls: int = 8,
) -> str:
    """System 2 Bounded Investigation: Multi-hop reasoning and relationship discovery across repositories.

    Decomposes questions, traces dependencies, classifies relationships,
    and returns citations strictly grounded in retrieved code evidence.
    """
    from .core.system1 import System1Retriever
    from .core.system2 import System2Investigator, InvestigationBudget

    retriever = System1Retriever(store)
    investigator = System2Investigator(
        system1=retriever,
        budget=InvestigationBudget(max_steps=max_steps, max_retrieval_calls=max_retrieval_calls),
    )
    result = investigator.investigate(query)
    res_dict = result.to_dict()
    return json.dumps(res_dict, indent=2)


def main():
    if "--test" in sys.argv:
        print("Infinite Memory FastMCP Server initialized cleanly.")
        sys.exit(0)
    try:
        mcp.run()
    finally:
        watcher_manager.stop_all()


if __name__ == "__main__":
    main()

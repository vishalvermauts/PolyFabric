import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any

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
        # Generic shim for offline test environments
        class DummyMCP:
            def tool(self):
                def decorator(fn):
                    return fn
                return decorator
            def run(self):
                pass
        mcp = DummyMCP()

from .core.hub import Hub
from .core.router import SystemOneRouter
from .core.store import VectorStore
from .parsers.tree_sitter_ast import UniversalASTParser
from .security.secret_masker import SecretMasker
from .security.git_guard import GitBranchGuard

hub = Hub()
store = VectorStore()
router = SystemOneRouter(hub=hub)
parser = UniversalASTParser()
secret_masker = SecretMasker()


@mcp.tool()
def pinpoint_symbol(symbol_name: str, project_name: Optional[str] = None) -> str:
    """Instantly locate a symbol declaration (function, class, interface) in the mesh."""
    results = store.search(f"def {symbol_name} class {symbol_name} interface {symbol_name}", top_k=3, project=project_name)
    if results:
        top = results[0]
        meta = top.get("metadata", {}) if isinstance(top.get("metadata"), dict) else top
        file_path = meta.get("file_path", top.get("file_path", "unknown"))
        start_line = meta.get("start_line", top.get("start_line", 1))
        end_line = meta.get("end_line", top.get("end_line", start_line))
        return f"{file_path}:{start_line}-L{end_line}"
    return f"Symbol '{symbol_name}' not found."


@mcp.tool()
def mesh_list_projects() -> str:
    """List all registered projects and repositories in the Neural Mesh."""
    projects = hub.list_projects()
    return json.dumps(projects, indent=2)


@mcp.tool()
def mesh_read_file(project_name: str, path: str, mask_creds: bool = True) -> str:
    """Read a file from any registered project in the mesh with zero-trust secret masking."""
    p = hub.resolve_file_path(project_name, path)
    if p and p.exists() and p.is_file():
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if mask_creds:
                content = secret_masker.mask(content)
            return content
        except Exception as e:
            return f"Error reading file: {e}"
    return f"File '{path}' in project '{project_name}' not found."


@mcp.tool()
def mesh_write_file(
    project_name: str,
    path: str,
    content: str,
    allow_main_write: bool = False,
    dry_run: bool = False,
) -> str:
    """Write or update a file in a mesh project with Git branch guardrails."""
    proj = hub.get_project(project_name)
    if not proj:
        return f"Error: Project '{project_name}' is not registered."

    repo_path = Path(proj["path"])
    allowed, message = GitBranchGuard.validate_write_permission(repo_path, allow_main_write=allow_main_write)
    if not allowed:
        return f"Rejected: {message}"

    target_file = repo_path / path
    old_content = ""
    if target_file.exists():
        try:
            old_content = target_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    diff = GitBranchGuard.generate_diff(target_file, old_content, content)

    if dry_run:
        return f"Dry-run diff:\n{diff}" if diff else "No changes detected."

    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")
        # Trigger incremental re-index for this file
        chunks = parser.parse_file(str(target_file), content)
        if chunks:
            docs = []
            for c in chunks:
                d = c.to_dict()
                d["metadata"]["project"] = project_name
                docs.append(d)
            store.upsert_documents(docs)
        return f"Successfully updated '{path}' in project '{project_name}'."
    except Exception as e:
        return f"Error writing file: {e}"


@mcp.tool()
def mesh_search(query: str, project_name: Optional[str] = None, top_k: int = 5) -> str:
    """Search code across the entire Neural Mesh or filtered by project."""
    route_decision = router.route(query)
    target_project = project_name or (route_decision["target_project"] if route_decision["target_project"] != "general" else None)

    results = store.search(query, top_k=top_k, project=target_project)
    if not results:
        return f"No matching code chunks found for query: '{query}'."

    output = []
    for r in results:
        file_path = r.get("file_path", r.get("metadata", {}).get("file_path", "unknown") if isinstance(r.get("metadata"), dict) else "unknown")
        start_line = r.get("start_line", r.get("metadata", {}).get("start_line", 1) if isinstance(r.get("metadata"), dict) else 1)
        end_line = r.get("end_line", r.get("metadata", {}).get("end_line", 1) if isinstance(r.get("metadata"), dict) else 1)
        text = secret_masker.mask(r.get("text", ""))
        output.append(f"--- {file_path}#L{start_line}-L{end_line} ---\n{text}")

    return "\n\n".join(output)


def main():
    if "--test" in sys.argv:
        print("Infinite Memory FastMCP Server initialized cleanly.")
        sys.exit(0)
    mcp.run()


if __name__ == "__main__":
    main()

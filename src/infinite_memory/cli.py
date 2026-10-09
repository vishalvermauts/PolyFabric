import sys
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from .config import __version__, UNIFIED_MEMORY_DIR
from .core.hub import Hub
from .core.store import VectorStore
from .parsers.tree_sitter_ast import UniversalASTParser

app = typer.Typer(
    name="memory-mesh",
    help="Infinite Memory Protocol (IMP) CLI - Multi-project Neural Mesh and local memory.",
    add_completion=False,
)
console = Console()
hub = Hub()
store = VectorStore()
parser = UniversalASTParser()


@app.command("version")
def version():
    """Display the current Infinite Memory Protocol version."""
    console.print(f"[bold cyan]Infinite Memory Protocol[/bold cyan] version [green]{__version__}[/green]")


@app.command("register")
def register(
    name: str = typer.Argument(..., help="Name of the project / repository"),
    path: str = typer.Argument(..., help="Filesystem path to project directory"),
    project_type: str = typer.Option("general", "--type", "-t", help="Project type (saas, gateway, mobile, infra, general)"),
    index_now: bool = typer.Option(True, "--index", help="Index files immediately upon registration"),
):
    """Register a repository in the global Neural Mesh registry."""
    p = Path(path).resolve()
    if not p.exists() or not p.is_dir():
        console.print(f"[bold red]Error:[/bold red] Path '{path}' does not exist or is not a directory.")
        raise typer.Exit(code=1)

    entry = hub.register_project(name, p, project_type=project_type)
    console.print(f"[bold green]Registered project '{name}'[/bold green] -> [yellow]{p}[/yellow] (Type: {project_type})")

    if index_now:
        with console.status(f"[cyan]Indexing codebase for '{name}'...[/cyan]"):
            indexed_count = 0
            docs = []
            for file_path in p.rglob("*"):
                if file_path.is_file() and not any(part in {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"} for part in file_path.parts):
                    try:
                        chunks = parser.parse_file(str(file_path))
                        for c in chunks:
                            d = c.to_dict()
                            d["metadata"]["project"] = name
                            docs.append(d)
                    except Exception:
                        pass

            if docs:
                store.upsert_documents(docs)
                indexed_count = len(docs)
            console.print(f"[bold green]Indexed {indexed_count} structural chunks into vector store.[/bold green]")


@app.command("list")
def list_projects():
    """List all registered projects and chunk counts."""
    projects = hub.list_projects()
    if not projects:
        console.print("[yellow]No projects registered yet. Run 'memory-mesh register <name> <path>' to add one.[/yellow]")
        return

    table = Table(title="Neural Mesh Registered Projects")
    table.add_column("Project Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Filesystem Path", style="green")

    for name, data in projects.items():
        table.add_row(name, data.get("type", "general"), data.get("path", ""))

    console.print(table)


@app.command("status")
def status():
    """Display vector database size, vacuum status, and hub health."""
    projects = hub.list_projects()
    size_bytes = store.get_disk_size_bytes()
    size_mb = size_bytes / (1024 * 1024)
    chunk_count = store.count_chunks()

    table = Table(title="Infinite Memory Protocol Health & Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Mesh Hub Directory", str(hub.unified_memory_dir))
    table.add_row("Total Registered Projects", str(len(projects)))
    table.add_row("Total Vector Store Chunks", str(chunk_count))
    table.add_row("Database Disk Footprint", f"{size_mb:.2f} MB ({size_bytes:,} bytes)")
    table.add_row("LanceDB Engine", "In-Process Columnar Lance Format")
    table.add_row("Embedding Model", "BAAI/bge-small-en-v1.5 (Local ONNX)")

    console.print(table)


@app.command("vacuum")
def vacuum(
    days: int = typer.Option(1, "--days", "-d", help="Purge versions older than specified days"),
):
    """Compact LanceDB tables and free disk space."""
    with console.status("[cyan]Running maintenance vacuum on vector store...[/cyan]"):
        stats = store.maintenance_vacuum(older_than_days=days)

    console.print("[bold green]Maintenance vacuum complete![/bold green]")
    table = Table(title="Vacuum Statistics")
    table.add_column("Property", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Arrow Files Compacted", str(stats.get("compacted")))
    table.add_row("Old Versions Cleaned", str(stats.get("cleaned_versions")))
    table.add_row("Disk Size Before", f"{stats.get('bytes_before', 0):,} bytes")
    table.add_row("Disk Size After", f"{stats.get('bytes_after', 0):,} bytes")

    console.print(table)


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query string"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by specific registered project"),
    top_k: int = typer.Option(3, "--limit", "-k", help="Maximum results to return"),
):
    """Perform quick terminal vector search across the Neural Mesh."""
    with console.status(f"[cyan]Searching for '{query}'...[/cyan]"):
        results = store.search(query, top_k=top_k, project=project)

    if not results:
        console.print(f"[yellow]No chunks found matching '{query}'.[/yellow]")
        return

    for idx, r in enumerate(results, start=1):
        file_path = r.get("file_path", r.get("metadata", {}).get("file_path", "unknown") if isinstance(r.get("metadata"), dict) else "unknown")
        start_line = r.get("start_line", r.get("metadata", {}).get("start_line", 1) if isinstance(r.get("metadata"), dict) else 1)
        end_line = r.get("end_line", r.get("metadata", {}).get("end_line", 1) if isinstance(r.get("metadata"), dict) else 1)
        score = r.get("_distance", 0.0)

        console.print(f"\n[bold cyan]Result #{idx}:[/bold cyan] [green]{file_path}#L{start_line}-L{end_line}[/green] (dist: {score:.4f})")
        console.print(r.get("text", "")[:300] + ("..." if len(r.get("text", "")) > 300 else ""))


def main():
    app()


if __name__ == "__main__":
    main()

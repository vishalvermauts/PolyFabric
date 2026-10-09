import time
from pathlib import Path
from typing import Callable, Optional, Set, Dict, Any
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirDeletedEvent,
    DirMovedEvent,
)

from ..parsers.tree_sitter_ast import UniversalASTParser
from ..security.secret_masker import is_sensitive_file
from .store import VectorStore


class CodeChangeHandler(FileSystemEventHandler):
    """Watches source code changes and triggers incremental indexing, atomic replacements, and deletions."""

    def __init__(
        self,
        project_name: str,
        root_path: Path,
        store: VectorStore,
        parser: UniversalASTParser,
        ignored_dirs: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.project_name = project_name
        self.root_path = root_path.resolve()
        self.store = store
        self.parser = parser
        self.ignored_dirs = ignored_dirs or {
            ".git", "node_modules", "venv", ".venv", "__pycache__",
            "dist", "build", ".next", ".turbo", ".memory_db"
        }

    def _should_ignore(self, path_str: str) -> bool:
        p = Path(path_str)
        for part in p.parts:
            if part in self.ignored_dirs:
                return True
        if is_sensitive_file(p):
            return True
        # Verify containment: prevent indexing files outside repository boundaries via symlinks
        try:
            resolved = p.resolve()
            if not resolved.is_relative_to(self.root_path):
                return True
        except Exception:
            return True
        return False

    def _index_file(self, file_path: str):
        if self._should_ignore(file_path):
            return
        p = Path(file_path)
        if not p.is_file():
            return

        try:
            chunks = self.parser.parse_file(str(p))
            docs = []
            for c in chunks:
                d = c.to_dict()
                d["metadata"]["project"] = self.project_name
                docs.append(d)
            self.store.upsert_file_documents(str(p), docs, project=self.project_name)
        except Exception:
            pass

    def _delete_file(self, file_path: str):
        try:
            self.store.delete_by_file(file_path, project=self.project_name)
        except Exception:
            pass

    def on_modified(self, event):
        if not event.is_directory:
            self._index_file(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._index_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._delete_file(event.src_path)
        else:
            # Directory deletion: delete all chunks matching this prefix
            dir_path = str(Path(event.src_path).resolve()).replace("\\", "/")
            try:
                table = self.store.db.open_table(self.store.table_name)
                # Purge chunks belonging to deleted directory
                table.delete(f"project = '{self.store._escape_sql_str(self.project_name)}' AND file_path LIKE '{self.store._escape_sql_str(dir_path)}/%'")
            except Exception:
                pass

    def on_moved(self, event):
        if not event.is_directory:
            self._delete_file(event.src_path)
            self._index_file(event.dest_path)
        else:
            # Directory move: purge old directory and re-index destination
            dir_path = str(Path(event.src_path).resolve()).replace("\\", "/")
            try:
                table = self.store.db.open_table(self.store.table_name)
                table.delete(f"project = '{self.store._escape_sql_str(self.project_name)}' AND file_path LIKE '{self.store._escape_sql_str(dir_path)}/%'")
            except Exception:
                pass

            dest = Path(event.dest_path)
            if dest.exists() and dest.is_dir():
                for f in dest.rglob("*"):
                    if f.is_file():
                        self._index_file(str(f))


class DirectoryWatcher:
    """Background filesystem watcher for real-time incremental re-indexing."""

    def __init__(self, project_name: str, root_path: str | Path, store: Optional[VectorStore] = None):
        self.project_name = project_name
        self.root_path = Path(root_path).resolve()
        self.store = store or VectorStore()
        self.parser = UniversalASTParser()
        self.observer = Observer()
        self.handler = CodeChangeHandler(self.project_name, self.root_path, self.store, self.parser)

    def start(self):
        """Start listening for filesystem modifications in the background."""
        if self.root_path.exists() and self.root_path.is_dir():
            self.observer.schedule(self.handler, str(self.root_path), recursive=True)
            self.observer.start()

    def stop(self):
        """Stop background watcher."""
        try:
            self.observer.stop()
            self.observer.join(timeout=3)
        except Exception:
            pass


class MeshWatcherManager:
    """Manages active watchers across all registered projects and reconciles startup changes."""

    def __init__(self, store: Optional[VectorStore] = None):
        self.store = store or VectorStore()
        self.watchers: Dict[str, DirectoryWatcher] = {}
        self.parser = UniversalASTParser()

    def sync_watchers(self, projects: Dict[str, Any], reconcile_startup: bool = True):
        """Synchronize active watchers with registry projects, restarting on path changes."""
        current_names = set(projects.keys())

        # Stop removed watchers
        for name in list(self.watchers.keys()):
            if name not in current_names:
                self.watchers[name].stop()
                del self.watchers[name]

        # Start or update watchers
        for name, meta in projects.items():
            new_path = Path(meta.get("path", "")).resolve()
            if not new_path.exists() or not new_path.is_dir():
                continue

            existing = self.watchers.get(name)
            if existing and existing.root_path != new_path:
                # Path changed: restart watcher
                existing.stop()
                del self.watchers[name]
                existing = None

            if not existing:
                w = DirectoryWatcher(name, new_path, store=self.store)
                w.start()
                self.watchers[name] = w

                # Reconcile any offline additions/edits made while server was down
                if reconcile_startup:
                    self._reconcile_project(name, new_path)

    def _reconcile_project(self, project_name: str, root_path: Path):
        """Ensure all valid on-disk files are indexed without symlink escapes."""
        for file_path in root_path.rglob("*"):
            if file_path.is_file() and not any(part in {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"} for part in file_path.parts):
                if is_sensitive_file(file_path):
                    continue
                try:
                    resolved = file_path.resolve()
                    if not resolved.is_relative_to(root_path):
                        continue
                    chunks = self.parser.parse_file(str(resolved))
                    docs = []
                    for c in chunks:
                        d = c.to_dict()
                        d["metadata"]["project"] = project_name
                        docs.append(d)
                    self.store.upsert_file_documents(str(resolved), docs, project=project_name)
                except Exception:
                    pass

    def stop_all(self):
        """Stop all background watchers."""
        for name, w in list(self.watchers.items()):
            w.stop()
        self.watchers.clear()

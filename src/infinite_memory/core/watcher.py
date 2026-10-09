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
)

from ..parsers.tree_sitter_ast import UniversalASTParser
from ..security.secret_masker import is_sensitive_file
from .store import VectorStore


class CodeChangeHandler(FileSystemEventHandler):
    """Watches source code changes and triggers incremental indexing, atomic replacements, and deletions."""

    def __init__(
        self,
        project_name: str,
        store: VectorStore,
        parser: UniversalASTParser,
        ignored_dirs: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.project_name = project_name
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
            # Atomic file replacement
            self.store.upsert_file_documents(str(p), docs, project=self.project_name)
        except Exception:
            pass

    def _delete_file(self, file_path: str):
        if self._should_ignore(file_path):
            return
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

    def on_moved(self, event):
        if not event.is_directory:
            self._delete_file(event.src_path)
            self._index_file(event.dest_path)


class DirectoryWatcher:
    """Background filesystem watcher for real-time incremental re-indexing."""

    def __init__(self, project_name: str, root_path: str | Path, store: Optional[VectorStore] = None):
        self.project_name = project_name
        self.root_path = Path(root_path).resolve()
        self.store = store or VectorStore()
        self.parser = UniversalASTParser()
        self.observer = Observer()
        self.handler = CodeChangeHandler(self.project_name, self.store, self.parser)

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
    """Manages active watchers across all registered projects."""

    def __init__(self, store: Optional[VectorStore] = None):
        self.store = store or VectorStore()
        self.watchers: Dict[str, DirectoryWatcher] = {}

    def sync_watchers(self, projects: Dict[str, Any]):
        """Synchronize active watchers with registry projects."""
        current_names = set(projects.keys())

        # Stop removed watchers
        for name in list(self.watchers.keys()):
            if name not in current_names:
                self.watchers[name].stop()
                del self.watchers[name]

        # Start new watchers
        for name, meta in projects.items():
            if name not in self.watchers:
                p_path = Path(meta.get("path", ""))
                if p_path.exists() and p_path.is_dir():
                    w = DirectoryWatcher(name, p_path, store=self.store)
                    w.start()
                    self.watchers[name] = w

    def stop_all(self):
        """Stop all background watchers."""
        for name, w in list(self.watchers.items()):
            w.stop()
        self.watchers.clear()

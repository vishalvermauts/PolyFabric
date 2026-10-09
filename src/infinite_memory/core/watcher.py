import time
from pathlib import Path
from typing import Callable, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from ..parsers.tree_sitter_ast import UniversalASTParser
from .store import VectorStore


class CodeChangeHandler(FileSystemEventHandler):
    """Watches source code changes and triggers incremental indexing."""

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
        return False

    def _process_file(self, file_path: str):
        if self._should_ignore(file_path):
            return
        p = Path(file_path)
        if not p.is_file():
            return

        try:
            chunks = self.parser.parse_file(file_path)
            if chunks:
                docs = []
                for c in chunks:
                    d = c.to_dict()
                    d["metadata"]["project"] = self.project_name
                    docs.append(d)
                self.store.upsert_documents(docs)
        except Exception:
            pass

    def on_modified(self, event):
        if not event.is_directory:
            self._process_file(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._process_file(event.src_path)


class DirectoryWatcher:
    """Background filesystem watcher for real-time incremental re-indexing."""

    def __init__(self, project_name: str, root_path: str | Path, store: Optional[VectorStore] = None):
        self.project_name = project_name
        self.root_path = Path(root_path)
        self.store = store or VectorStore()
        self.parser = UniversalASTParser()
        self.observer = Observer()
        self.handler = CodeChangeHandler(self.project_name, self.store, self.parser)

    def start(self):
        """Start listening for filesystem modifications in the background."""
        self.observer.schedule(self.handler, str(self.root_path), recursive=True)
        self.observer.start()

    def stop(self):
        """Stop background watcher."""
        self.observer.stop()
        self.observer.join()

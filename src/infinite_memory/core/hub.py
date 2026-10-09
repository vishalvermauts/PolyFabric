import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from ..config import REGISTRY_FILE, UNIFIED_MEMORY_DIR


class Hub:
    """Global multi-project registry manager for the Neural Mesh."""

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_file = Path(registry_path) if registry_path else REGISTRY_FILE
        self.unified_memory_dir = self.registry_file.parent
        self.unified_memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            self._write_registry({})

    def _read_registry(self) -> Dict[str, Any]:
        if not self.registry_file.exists():
            return {}
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_registry(self, data: Dict[str, Any]) -> None:
        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def register_project(
        self,
        name: str,
        path: str | Path,
        project_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register or update a repository in the global mesh registry."""
        registry = self._read_registry()
        clean_path = str(Path(path).resolve())
        entry = {
            "path": clean_path,
            "type": project_type,
            "metadata": metadata or {},
        }
        registry[name] = entry
        self._write_registry(registry)
        return entry

    def unregister_project(self, name: str) -> bool:
        """Remove a project from the registry."""
        registry = self._read_registry()
        if name in registry:
            del registry[name]
            self._write_registry(registry)
            return True
        return False

    def get_project(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve project metadata by registered name."""
        return self._read_registry().get(name)

    def list_projects(self) -> Dict[str, Any]:
        """Return all registered projects."""
        return self._read_registry()

    def list_all_projects(self) -> Dict[str, Any]:
        """Alias for list_projects."""
        return self.list_projects()

    def resolve_file_path(self, project_name: str, relative_path: str | Path) -> Optional[Path]:
        """Resolve a relative project path to an absolute path on disk."""
        proj = self.get_project(project_name)
        if proj and "path" in proj:
            resolved = Path(proj["path"]) / relative_path
            return resolved
        return None


# Global singleton alias
GlobalMeshHub = Hub

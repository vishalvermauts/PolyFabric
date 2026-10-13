import os
from pathlib import Path
from typing import Optional, Tuple


def normalize_and_resolve_repo_path(
    candidate_path: str | Path,
    repo_root: str | Path,
    must_exist: bool = True
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Resolve a candidate file path (relative, absolute, or relocated) relative to configured repo root.
    
    Guarantees:
    1. Supports relative paths: 'src/utils/geo.ts' -> repo_root / 'src/utils/geo.ts'
    2. Supports absolute paths already within repo_root: '/repo/src/utils/geo.ts'
    3. Handles paths indexed under a previous root path by extracting the subpath relative to repo folder:
       e.g. '/tmp/old_dir/FarmWatch/src/utils/geo.ts' with repo_root '/tmp/FarmWatch' -> '/tmp/FarmWatch/src/utils/geo.ts'
    4. Rejects any path escaping repo_root (path traversal).
    5. Returns (resolved_path, None) on success, or (None, error_message) on failure.
    """
    try:
        root_path = Path(repo_root).resolve()
        raw_str = str(candidate_path).replace("\\", "/").strip()
        if not raw_str:
            return None, "Empty path provided."

        # Case 1: If raw_str is already a relative path
        cand_p = Path(raw_str)
        if not cand_p.is_absolute():
            resolved = (root_path / cand_p).resolve()
            if not resolved.is_relative_to(root_path):
                return None, f"Path traversal error: '{raw_str}' resolves outside repo root '{root_path}'."
            if must_exist and not resolved.exists():
                return None, f"File does not exist: '{resolved}'."
            return resolved, None

        # Case 2: Candidate is an absolute path within current root
        resolved = cand_p.resolve()
        if resolved.is_relative_to(root_path):
            if must_exist and not resolved.exists():
                return None, f"File does not exist: '{resolved}'."
            return resolved, None

        # Case 3: Candidate was indexed under an old root (relocated repository)
        root_name = root_path.name  # e.g. "FarmWatch"
        marker = f"/{root_name}/"
        if marker in raw_str:
            subpath = raw_str.split(marker, 1)[1]
            resolved = (root_path / subpath).resolve()
            if resolved.is_relative_to(root_path):
                if must_exist and not resolved.exists():
                    return None, f"Relocated file does not exist: '{resolved}'."
                return resolved, None

        # Fallback check for common project subfolders like 'src/' or 'server.ts'
        for anchor in ["src/", "public/", "package.json", "server.ts", "index.html"]:
            if anchor in raw_str:
                subpath = raw_str[raw_str.find(anchor):]
                resolved = (root_path / subpath).resolve()
                if resolved.is_relative_to(root_path):
                    if must_exist and not resolved.exists():
                        continue
                    return resolved, None

        return None, f"Path '{raw_str}' cannot be resolved within repository root '{root_path}'."
    except Exception as e:
        return None, f"Path resolution exception: {e}"


def to_relative_repo_path(path: str | Path, repo_root: str | Path) -> str:
    """Return clean forward-slash relative path string."""
    try:
        resolved, err = normalize_and_resolve_repo_path(path, repo_root, must_exist=False)
        if resolved:
            return str(resolved.relative_to(Path(repo_root).resolve())).replace("\\", "/")
    except Exception:
        pass
    clean = str(path).replace("\\", "/").lstrip("/")
    return clean

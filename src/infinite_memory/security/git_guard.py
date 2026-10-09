import subprocess
import difflib
from pathlib import Path
from typing import Tuple, Optional

from ..config import PROTECTED_BRANCHES


class GitBranchGuard:
    """Branch protection guardrails for cross-project mesh write actions."""

    @staticmethod
    def get_current_branch(repo_path: str | Path) -> Optional[str]:
        """Inspect the repository's current branch using git rev-parse."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return res.stdout.strip()
        except Exception:
            return None

    @classmethod
    def validate_write_permission(
        cls,
        repo_path: str | Path,
        allow_main_write: bool = False,
    ) -> Tuple[bool, str]:
        """Validate whether direct writes are permitted to the repository.
        
        Rejects direct writes if the branch is main or master unless allow_main_write=True.
        """
        branch = cls.get_current_branch(repo_path)
        if not branch:
            # Not a git repo or git not found, allow with notice
            return True, "Not a git repository or HEAD detached; write permitted."

        if branch.lower() in PROTECTED_BRANCHES and not allow_main_write:
            return False, (
                f"PROTECTED BRANCH GUARD: Direct write to '{branch}' blocked! "
                f"Pass allow_main_write=True or switch to a feature branch."
            )

        return True, f"Write allowed on branch '{branch}'."

    @staticmethod
    def generate_diff(file_path: str | Path, old_content: str, new_content: str) -> str:
        """Generate a unified git diff patch before applying changes."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{Path(file_path).name}",
            tofile=f"b/{Path(file_path).name}",
        )
        return "".join(diff)

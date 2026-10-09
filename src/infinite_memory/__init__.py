"""Infinite Memory Protocol (IMP) - Near-instant local memory & Neural Mesh for AI coding agents."""

from .config import __version__
from .core.hub import Hub
from .core.router import SystemOneRouter, system_one_router
from .core.store import VectorStore

__all__ = [
    "__version__",
    "Hub",
    "SystemOneRouter",
    "system_one_router",
    "VectorStore",
]

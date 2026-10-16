import os
from pathlib import Path

# Base storage directory
UNIFIED_MEMORY_DIR = Path(os.environ.get("INFINITE_MEMORY_HOME", Path.home() / ".unified_memory"))
REGISTRY_FILE = UNIFIED_MEMORY_DIR / "registry.json"
DEFAULT_VECTOR_DB_DIR = Path(os.environ.get("INFINITE_MEMORY_DB_PATH", os.environ.get("MEMORY_MESH_DB_PATH", UNIFIED_MEMORY_DIR / "vector_db")))

# Embedding settings
EMBEDDING_MODEL_NAME = os.environ.get("INFINITE_MEMORY_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# Chunker defaults
DEFAULT_CHUNK_SIZE = int(os.environ.get("INFINITE_MEMORY_CHUNK_SIZE", "35"))
DEFAULT_CHUNK_STRIDE = int(os.environ.get("INFINITE_MEMORY_CHUNK_STRIDE", "25"))

# Git & write safety defaults - Server-side configuration
PROTECTED_BRANCHES = {"main", "master"}
ALLOW_MAIN_BRANCH_WRITES = os.environ.get("INFINITE_MEMORY_ALLOW_MAIN_WRITES", "false").lower() in ("true", "1", "yes")
READ_ONLY_MODE = os.environ.get("POLYFABRIC_READ_ONLY", os.environ.get("INFINITE_MEMORY_READ_ONLY", "0")).lower() in ("true", "1", "yes")

# Version
__version__ = "1.0.0"

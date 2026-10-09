import os
from pathlib import Path

# Base storage directory
UNIFIED_MEMORY_DIR = Path(os.environ.get("INFINITE_MEMORY_HOME", Path.home() / ".unified_memory"))
REGISTRY_FILE = UNIFIED_MEMORY_DIR / "registry.json"
DEFAULT_VECTOR_DB_DIR = UNIFIED_MEMORY_DIR / "vector_db"

# Embedding settings
EMBEDDING_MODEL_NAME = os.environ.get("INFINITE_MEMORY_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# Chunker defaults
DEFAULT_CHUNK_SIZE = int(os.environ.get("INFINITE_MEMORY_CHUNK_SIZE", "35"))
DEFAULT_CHUNK_STRIDE = int(os.environ.get("INFINITE_MEMORY_CHUNK_STRIDE", "25"))

# Git safety defaults
PROTECTED_BRANCHES = {"main", "master"}

# Version
__version__ = "1.0.0"

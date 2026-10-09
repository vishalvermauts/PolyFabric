import pytest
import tempfile
import shutil
from pathlib import Path

from infinite_memory.core.hub import Hub
from infinite_memory.core.store import VectorStore
from infinite_memory.core.router import SystemOneRouter


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="imp_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_hub(temp_dir):
    registry_file = temp_dir / "test_registry.json"
    hub = Hub(registry_path=registry_file)
    return hub


@pytest.fixture
def test_store(temp_dir):
    db_path = temp_dir / "test_vector_db"
    return VectorStore(db_path=db_path)

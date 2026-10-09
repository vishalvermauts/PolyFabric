import pytest
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser, detect_language
from infinite_memory.parsers.chunker import chunk_by_sliding_window


def test_detect_language():
    assert detect_language("app.py") == "python"
    assert detect_language("component.tsx") == "tsx"
    assert detect_language("service.go") == "go"
    assert detect_language("main.rs") == "rust"
    assert detect_language("unknown.xyz") is None


def test_sliding_window_chunker():
    lines = "\n".join([f"line {i}" for i in range(1, 100)])
    chunks = chunk_by_sliding_window("test.txt", lines, chunk_size=35, stride=25)
    assert len(chunks) >= 3
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 35
    assert chunks[1].start_line == 26


def test_tree_sitter_python_ast_parsing():
    parser = UniversalASTParser()
    py_code = """
class VideoPipeline:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def render_frame(self, frame_id: int):
        return f"Rendering frame {frame_id}"
"""
    chunks = parser.parse_file("pipeline.py", code=py_code)
    assert len(chunks) > 0
    # Should identify AST structure
    assert any("VideoPipeline" in c.content for c in chunks)
    assert chunks[0].start_line >= 1
    assert chunks[0].end_line > chunks[0].start_line


def test_tree_sitter_fallback_on_unsupported_language():
    parser = UniversalASTParser()
    config_yaml = """
server:
  port: 8080
  host: 0.0.0.0
database:
  max_connections: 50
"""
    chunks = parser.parse_file("config.yaml", code=config_yaml)
    assert len(chunks) > 0
    assert chunks[0].chunk_type in ("sliding_window", "full_file")

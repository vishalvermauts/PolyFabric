import pytest
from infinite_memory.core.context_expander import expand_chunk_context

def test_expand_chunk_context_basic():
    file_code = """import os
import sys
from typing import List

class Worker:
    def __init__(self, name: str):
        self.name = name

    def execute_task(self, task_id: int):
        # Target work
        print(f"Task {task_id}")
        return True
"""
    chunk_hit = {
        "file_path": "worker.py",
        "start_line": 9,
        "end_line": 12,
        "symbol_name": "execute_task",
        "chunk_type": "ast_function_definition",
        "text": "    def execute_task(self, task_id: int):\n        print(f'Task {task_id}')\n        return True"
    }
    
    expanded = expand_chunk_context(chunk_hit, file_content=file_code, max_tokens=300)
    assert "expanded_text" in expanded
    assert "// File: worker.py" in expanded["expanded_text"]
    assert "// Declaration Symbol: execute_task" in expanded["expanded_text"]
    assert "def execute_task" in expanded["expanded_text"]
    assert expanded["estimated_tokens"] <= 300

def test_token_boundary_truncation():
    large_body = "x = 1\n" * 500
    chunk_hit = {
        "file_path": "big.py",
        "start_line": 1,
        "end_line": 500,
        "symbol_name": "large_func",
        "chunk_type": "ast_function_definition",
        "text": large_body
    }
    
    expanded = expand_chunk_context(chunk_hit, max_tokens=50) # 200 chars max
    assert len(expanded["expanded_text"]) <= 250
    assert "[Context truncated at token limit]" in expanded["expanded_text"]

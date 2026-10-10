import pytest
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser, _get_tree_sitter_parser

def test_python_ast_extraction():
    parser = _get_tree_sitter_parser("python")
    assert parser is not None, "Python tree-sitter parser failed to load"
    
    code = """
class DataService:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        
    def fetch_records(self, limit: int = 100):
        # Retrieve records
        return []
"""
    ast_parser = UniversalASTParser()
    chunks = ast_parser.parse_file("service.py", code=code)
    assert len(chunks) > 0, "No chunks produced for Python"
    
    symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
    assert "DataService" in symbol_names, f"Expected DataService class, got: {symbol_names}"
    assert "fetch_records" in symbol_names or "__init__" in symbol_names, f"Expected method symbols, got: {symbol_names}"

def test_javascript_ast_extraction():
    parser = _get_tree_sitter_parser("javascript")
    assert parser is not None, "JavaScript tree-sitter parser failed to load"
    
    code = """
function calculateMetrics(items) {
    return items.reduce((acc, curr) => acc + curr.value, 0);
}

class MetricCollector {
    collect() {
        return true;
    }
}
"""
    ast_parser = UniversalASTParser()
    chunks = ast_parser.parse_file("metrics.js", code=code)
    assert len(chunks) > 0, "No chunks produced for JavaScript"
    
    symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
    assert "calculateMetrics" in symbol_names, f"Expected calculateMetrics, got: {symbol_names}"

def test_typescript_ast_extraction():
    parser = _get_tree_sitter_parser("typescript")
    assert parser is not None, "TypeScript tree-sitter parser failed to load"
    
    code = """
export interface Config {
    apiKey: string;
}

export function initializeClient(cfg: Config): boolean {
    return cfg.apiKey.length > 0;
}
"""
    ast_parser = UniversalASTParser()
    chunks = ast_parser.parse_file("client.ts", code=code)
    assert len(chunks) > 0, "No chunks produced for TypeScript"
    
    symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
    assert "initializeClient" in symbol_names, f"Expected initializeClient, got: {symbol_names}"

def test_go_ast_extraction():
    parser = _get_tree_sitter_parser("go")
    assert parser is not None, "Go tree-sitter parser failed to load"
    
    code = """
package main

import "fmt"

func ProcessBatch(items []string) error {
    fmt.Println(items)
    return nil
}
"""
    ast_parser = UniversalASTParser()
    chunks = ast_parser.parse_file("batch.go", code=code)
    assert len(chunks) > 0, "No chunks produced for Go"
    symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
    assert "ProcessBatch" in symbol_names, f"Expected ProcessBatch, got: {symbol_names}"

def test_rust_ast_extraction():
    parser = _get_tree_sitter_parser("rust")
    assert parser is not None, "Rust tree-sitter parser failed to load"
    
    code = """
pub struct TokenBucket {
    capacity: usize,
}

impl TokenBucket {
    pub fn new(capacity: usize) -> Self {
        Self { capacity }
    }
}
"""
    ast_parser = UniversalASTParser()
    chunks = ast_parser.parse_file("token.rs", code=code)
    assert len(chunks) > 0, "No chunks produced for Rust"
    symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
    assert any("TokenBucket" in s or "new" in s for s in symbol_names), f"Expected Rust symbols, got: {symbol_names}"

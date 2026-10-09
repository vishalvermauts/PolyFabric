import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from .chunker import CodeChunk, chunk_by_sliding_window

# Grammar loader registry
_PARSER_CACHE: Dict[str, Any] = {}


def _get_tree_sitter_parser(language_name: str):
    """Dynamically load and cache tree-sitter parser for given language."""
    if language_name in _PARSER_CACHE:
        return _PARSER_CACHE[language_name]

    try:
        import tree_sitter
        lang_obj = None

        if language_name == "python":
            import tree_sitter_python
            lang_obj = tree_sitter.Language(tree_sitter_python.language())
        elif language_name == "javascript":
            import tree_sitter_javascript
            lang_obj = tree_sitter.Language(tree_sitter_javascript.language())
        elif language_name == "typescript":
            import tree_sitter_typescript
            # tree-sitter-typescript has language_typescript() or language_tsx()
            if hasattr(tree_sitter_typescript, "language_typescript"):
                lang_obj = tree_sitter.Language(tree_sitter_typescript.language_typescript())
            elif hasattr(tree_sitter_typescript, "language"):
                lang_obj = tree_sitter.Language(tree_sitter_typescript.language())
        elif language_name == "tsx":
            import tree_sitter_typescript
            if hasattr(tree_sitter_typescript, "language_tsx"):
                lang_obj = tree_sitter.Language(tree_sitter_typescript.language_tsx())
            elif hasattr(tree_sitter_typescript, "language"):
                lang_obj = tree_sitter.Language(tree_sitter_typescript.language())
        elif language_name == "go":
            import tree_sitter_go
            lang_obj = tree_sitter.Language(tree_sitter_go.language())
        elif language_name == "rust":
            import tree_sitter_rust
            lang_obj = tree_sitter.Language(tree_sitter_rust.language())

        if lang_obj:
            parser = tree_sitter.Parser(lang_obj)
            _PARSER_CACHE[language_name] = parser
            return parser
    except Exception:
        pass

    return None


def detect_language(file_path: str) -> Optional[str]:
    """Map file extension to language key."""
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".go": "go",
        ".rs": "rust",
    }
    return mapping.get(ext)


class UniversalASTParser:
    """Universal structural AST parser with automatic sliding-window fallback."""

    def __init__(self, chunk_size: int = 35, stride: int = 25):
        self.chunk_size = chunk_size
        self.stride = stride

    def parse_file(self, file_path: str, code: Optional[str] = None) -> List[CodeChunk]:
        path_obj = Path(file_path)
        if code is None:
            if not path_obj.exists():
                return []
            try:
                code = path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return []

        lang = detect_language(file_path)
        if not lang:
            # Fall back to sliding window for markdown, configs (.json, .yaml, .env), etc.
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

        parser = _get_tree_sitter_parser(lang)
        if not parser:
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

        try:
            tree = parser.parse(code.encode("utf-8"))
            chunks = self._extract_nodes(file_path, code, tree.root_node, lang)
            if not chunks:
                return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)
            return chunks
        except Exception:
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

    def _extract_nodes(self, file_path: str, code: str, root_node, lang: str) -> List[CodeChunk]:
        """Extract top-level functions, classes, interfaces, routes."""
        chunks: List[CodeChunk] = []
        code_lines = code.splitlines(keepends=True)

        target_node_types = {
            # Python
            "function_definition", "class_definition", "async_function_definition",
            # JS/TS
            "function_declaration", "class_declaration", "lexical_declaration",
            "export_statement", "interface_declaration", "type_alias_declaration",
            # Go
            "function_declaration", "method_declaration", "type_declaration",
            # Rust
            "function_item", "struct_item", "impl_item", "enum_item", "trait_item",
        }

        def _traverse(node):
            if node.type in target_node_types:
                start_line = node.start_point.row + 1
                end_line = node.end_point.row + 1
                node_text = "".join(code_lines[start_line - 1 : end_line])

                # Extract symbol identifier if present
                symbol_name = None
                for child in node.children:
                    if child.type in ("identifier", "type_identifier", "property_identifier"):
                        symbol_name = code[child.start_byte : child.end_byte]
                        break

                chunk_id = f"{file_path}#{node.type}:{symbol_name or 'anon'}#L{start_line}-L{end_line}"
                chunks.append(
                    CodeChunk(
                        chunk_id=chunk_id,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        content=node_text,
                        chunk_type=f"ast_{node.type}",
                        symbol_name=symbol_name,
                    )
                )
            else:
                for child in node.children:
                    # Don't recurse excessively into bodies if top-level found
                    if child.type in target_node_types or len(chunks) == 0:
                        _traverse(child)

        _traverse(root_node)

        # If AST extracted nodes cover less than whole code or empty, return fallback or combined
        if not chunks:
            return []
        return chunks

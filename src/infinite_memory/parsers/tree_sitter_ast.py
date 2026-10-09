import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

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
    """Universal structural AST parser with full coverage of uncovered regions and chunk bounding."""

    def __init__(self, chunk_size: int = 35, stride: int = 25, max_ast_chunk_lines: int = 80):
        self.chunk_size = chunk_size
        self.stride = stride
        self.max_ast_chunk_lines = max_ast_chunk_lines

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
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

        parser = _get_tree_sitter_parser(lang)
        if not parser:
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

        try:
            tree = parser.parse(code.encode("utf-8"))
            chunks = self._extract_nodes_with_coverage(file_path, code, tree.root_node, lang)
            if not chunks:
                return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)
            return chunks
        except Exception:
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

    def _extract_nodes_with_coverage(self, file_path: str, code: str, root_node, lang: str) -> List[CodeChunk]:
        """Extract AST nodes plus uncovered regions (imports, module header, global vars, decorators)."""
        chunks: List[CodeChunk] = []
        code_lines = code.splitlines(keepends=True)
        total_lines = len(code_lines)
        if total_lines == 0:
            return []

        covered_lines: Set[int] = set()

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
                node_lines_count = end_line - start_line + 1

                # Mark lines covered
                for ln in range(start_line, end_line + 1):
                    covered_lines.add(ln)

                # Extract symbol identifier if present
                symbol_name = None
                for child in node.children:
                    if child.type in ("identifier", "type_identifier", "property_identifier"):
                        symbol_name = code[child.start_byte : child.end_byte]
                        break

                # Bound large AST chunks to avoid token overflow
                if node_lines_count > self.max_ast_chunk_lines:
                    node_text = "".join(code_lines[start_line - 1 : end_line])
                    sub_chunks = chunk_by_sliding_window(
                        file_path=file_path,
                        text=node_text,
                        chunk_size=self.chunk_size,
                        stride=self.stride,
                    )
                    for sc in sub_chunks:
                        # Offset lines back to absolute file position
                        abs_start = start_line + sc.start_line - 1
                        abs_end = start_line + sc.end_line - 1
                        chunks.append(
                            CodeChunk(
                                chunk_id=f"{file_path}#{node.type}:{symbol_name or 'anon'}#L{abs_start}-L{abs_end}",
                                file_path=file_path,
                                start_line=abs_start,
                                end_line=abs_end,
                                content=sc.content,
                                chunk_type=f"ast_{node.type}_split",
                                symbol_name=symbol_name,
                            )
                        )
                else:
                    node_text = "".join(code_lines[start_line - 1 : end_line])
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{file_path}#{node.type}:{symbol_name or 'anon'}#L{start_line}-L{end_line}",
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
                    _traverse(child)

        _traverse(root_node)

        # 2. Capture uncovered regions (imports, decorators, top-level constants)
        uncovered_regions = []
        current_region_start = None

        for ln in range(1, total_lines + 1):
            if ln not in covered_lines:
                if current_region_start is None:
                    current_region_start = ln
            else:
                if current_region_start is not None:
                    uncovered_regions.append((current_region_start, ln - 1))
                    current_region_start = None

        if current_region_start is not None:
            uncovered_regions.append((current_region_start, total_lines))

        for reg_start, reg_end in uncovered_regions:
            reg_lines = code_lines[reg_start - 1 : reg_end]
            reg_text = "".join(reg_lines).strip()
            # Only index non-empty regions (skip pure blank lines)
            if reg_text and len(reg_text) > 10:
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{file_path}#module_context#L{reg_start}-L{reg_end}",
                        file_path=file_path,
                        start_line=reg_start,
                        end_line=reg_end,
                        content="".join(reg_lines),
                        chunk_type="ast_module_context",
                        symbol_name="module_context",
                    )
                )

        chunks.sort(key=lambda c: c.start_line)
        return chunks

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
    """Universal structural AST parser with recursive method extraction and byte-accurate Unicode decoding."""

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
            code_bytes = code.encode("utf-8")
            tree = parser.parse(code_bytes)
            chunks = self._extract_nodes_with_coverage(file_path, code, code_bytes, tree.root_node, lang)
            if not chunks:
                return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)
            return chunks
        except Exception:
            return chunk_by_sliding_window(file_path, code, self.chunk_size, self.stride)

    def _extract_symbol_name(self, node, code_bytes: bytes) -> Optional[str]:
        """Byte-accurate symbol name extraction from AST node."""
        for child in node.children:
            if child.type in ("identifier", "type_identifier", "property_identifier", "name"):
                try:
                    return code_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                except Exception:
                    pass
        # Check variable assignment target: const myFunc = () => ...
        if node.type == "lexical_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    for sub in child.children:
                        if sub.type in ("identifier", "name"):
                            return code_bytes[sub.start_byte : sub.end_byte].decode("utf-8", errors="replace")
        return None

    def _extract_docstring(self, node, code_bytes: bytes) -> Optional[str]:
        """Extract the docstring from a class/module/function node if present."""
        body = None
        for child in node.children:
            if child.type in ("block", "class_body", "statement_block"):
                body = child
                break
        if body is None:
            body = node

        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        try:
                            raw = code_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="replace")
                            return raw.strip().strip('"\'').strip()
                        except Exception:
                            pass
            elif child.type == "comment":
                try:
                    return code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
            elif child.type not in ("decorator", "comment", "newline", "NEWLINE", "INDENT", "DEDENT"):
                break
        return None

    def _build_context_header(self, file_path: str, parent_name: Optional[str], parent_doc: Optional[str]) -> str:
        """Build a context header to prepend to chunks for improved embeddings."""
        parts = []
        basename = Path(file_path).name
        parts.append(f"# File: {basename}")
        if parent_name:
            parts.append(f"# Enclosing: {parent_name}")
        if parent_doc and len(parent_doc) < 200:
            parts.append(f"# {parent_doc}")
        return "\n".join(parts) + "\n" if parts else ""

    def _extract_nodes_with_coverage(
        self,
        file_path: str,
        code: str,
        code_bytes: bytes,
        root_node,
        lang: str,
    ) -> List[CodeChunk]:
        """Extract classes, top-level functions, methods, routes, and module headers."""
        chunks: List[CodeChunk] = []
        code_lines = code.splitlines(keepends=True)
        total_lines = len(code_lines)
        if total_lines == 0:
            return []

        # Extract module-level docstring
        module_doc = self._extract_docstring(root_node, code_bytes)

        covered_lines: Set[int] = set()

        target_node_types = {
            # Python
            "function_definition", "class_definition", "async_function_definition", "decorated_definition",
            # JS/TS
            "function_declaration", "class_declaration", "lexical_declaration",
            "export_statement", "interface_declaration", "type_alias_declaration",
            "method_definition",
            # Go
            "function_declaration", "method_declaration", "type_declaration",
            # Rust
            "function_item", "struct_item", "impl_item", "enum_item", "trait_item",
        }

        export_inner_types = {
            "function_declaration", "class_declaration", "interface_declaration",
            "type_alias_declaration", "lexical_declaration",
        }

        # Parent containers that should be recursed into to find methods & inner functions
        container_node_types = {
            "class_definition", "class_declaration", "impl_item", "export_statement",
            "trait_item", "block", "statement_block", "class_body", "declaration_list",
        }

        def _traverse(node, is_top_level: bool = True, parent_name: Optional[str] = None, parent_doc: Optional[str] = None):
            if node.type in target_node_types:
                declaration = node
                unwrapped_export = False
                if node.type == "decorated_definition":
                    declaration = next((c for c in node.named_children if c.type in
                                        ("function_definition", "class_definition", "async_function_definition")), node)
                elif node.type == "export_statement":
                    inner = next((c for c in node.named_children if c.type in export_inner_types), None)
                    if inner is not None:
                        declaration = inner
                        unwrapped_export = True

                effective_type = declaration.type if unwrapped_export else node.type

                start_line = node.start_point.row + 1
                previous = node.prev_named_sibling
                while previous is not None and previous.type in ("comment", "line_comment", "block_comment"):
                    if previous.end_point.row < start_line - 2:
                        break
                    start_line = previous.start_point.row + 1
                    previous = previous.prev_named_sibling
                end_line = node.end_point.row + 1
                node_lines_count = end_line - start_line + 1

                for ln in range(start_line, end_line + 1):
                    covered_lines.add(ln)

                symbol_name = self._extract_symbol_name(declaration, code_bytes)

                # Determine context: use parent info, or module docstring for top-level
                ctx_name = parent_name
                ctx_doc = parent_doc if parent_name else module_doc
                context_header = self._build_context_header(file_path, ctx_name, ctx_doc)

                # For class/container nodes, extract their docstring for children
                child_parent_name = symbol_name
                child_parent_doc = None
                if declaration.type in container_node_types or node.type in container_node_types:
                    child_parent_doc = self._extract_docstring(declaration, code_bytes)

                if node_lines_count > self.max_ast_chunk_lines:
                    node_text = "".join(code_lines[start_line - 1 : end_line])
                    sub_chunks = chunk_by_sliding_window(
                        file_path=file_path,
                        text=node_text,
                        chunk_size=self.chunk_size,
                        stride=self.stride,
                    )
                    for sc in sub_chunks:
                        abs_start = start_line + sc.start_line - 1
                        abs_end = start_line + sc.end_line - 1
                        chunks.append(
                            CodeChunk(
                                chunk_id=f"{file_path}#{effective_type}:{symbol_name or 'anon'}#L{abs_start}-L{abs_end}",
                                file_path=file_path,
                                start_line=abs_start,
                                end_line=abs_end,
                                content=context_header + sc.content,
                                chunk_type=f"ast_{effective_type}_split",
                                symbol_name=symbol_name,
                            )
                        )
                else:
                    node_text = "".join(code_lines[start_line - 1 : end_line])
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{file_path}#{effective_type}:{symbol_name or 'anon'}#L{start_line}-L{end_line}",
                            file_path=file_path,
                            start_line=start_line,
                            end_line=end_line,
                            content=context_header + node_text,
                            chunk_type=f"ast_{effective_type}",
                            symbol_name=symbol_name,
                        )
                    )

                if unwrapped_export:
                    if declaration.type in container_node_types:
                        for child in declaration.children:
                            _traverse(child, is_top_level=False,
                                      parent_name=child_parent_name, parent_doc=child_parent_doc)
                elif node.type in container_node_types or node.type == "decorated_definition":
                    for child in declaration.children:
                        _traverse(child, is_top_level=False,
                                  parent_name=child_parent_name, parent_doc=child_parent_doc)

            else:
                for child in node.children:
                    _traverse(child, is_top_level=is_top_level,
                              parent_name=parent_name, parent_doc=parent_doc)

        _traverse(root_node, is_top_level=True)

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

        chunks.sort(key=lambda c: (c.start_line, c.end_line))
        return chunks

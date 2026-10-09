from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class CodeChunk:
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    chunk_type: str = "sliding_window"
    symbol_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.chunk_id,
            "text": self.content,
            "metadata": {
                "file_path": self.file_path,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "chunk_type": self.chunk_type,
                "symbol_name": self.symbol_name or "",
            }
        }


def chunk_by_sliding_window(
    file_path: str,
    text: str,
    chunk_size: int = 35,
    stride: int = 25,
) -> List[CodeChunk]:
    """Fallback line-bounded sliding window chunker preserving line coordinates."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    total_lines = len(lines)
    chunks: List[CodeChunk] = []
    chunk_index = 0

    if total_lines <= chunk_size:
        return [
            CodeChunk(
                chunk_id=f"{file_path}#L1-L{total_lines}",
                file_path=file_path,
                start_line=1,
                end_line=total_lines,
                content="".join(lines),
                chunk_type="full_file",
            )
        ]

    start_idx = 0
    while start_idx < total_lines:
        end_idx = min(start_idx + chunk_size, total_lines)
        chunk_lines = lines[start_idx:end_idx]
        start_line = start_idx + 1
        end_line = end_idx

        chunks.append(
            CodeChunk(
                chunk_id=f"{file_path}#L{start_line}-L{end_line}",
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                content="".join(chunk_lines),
                chunk_type="sliding_window",
            )
        )
        chunk_index += 1
        if end_idx == total_lines:
            break
        start_idx += stride

    return chunks

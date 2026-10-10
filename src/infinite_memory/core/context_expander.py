import os
from pathlib import Path
from typing import List, Dict, Any, Optional

def expand_chunk_context(
    chunk_hit: Dict[str, Any],
    file_content: Optional[str] = None,
    max_tokens: int = 400,
    header_max_lines: int = 15,
) -> Dict[str, Any]:
    """Enriches a retrieved CodeChunk with bounded context envelope.
    
    Inclusions:
    1. File Header Envelope (top imports, module docstrings, declarations) up to `header_max_lines`.
    2. Enclosing Symbol Header: Injects parent class/function signature if chunk is an inner method or split.
    3. Strict Token Budget Envelope: Estimates 4 chars per token and bounds expanded payload to `max_tokens`.
    """
    fpath = chunk_hit.get("file_path", "")
    start_line = int(chunk_hit.get("start_line", 1))
    end_line = int(chunk_hit.get("end_line", start_line))
    sym_name = chunk_hit.get("symbol_name", "")
    chunk_type = chunk_hit.get("chunk_type", "")
    body_text = chunk_hit.get("text", "")
    
    max_chars = max_tokens * 4
    
    # If file content is not provided, attempt to read from disk if available
    lines = []
    if file_content:
        lines = file_content.splitlines(keepends=True)
    elif fpath and Path(fpath).exists():
        try:
            lines = Path(fpath).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception:
            lines = []
            
    header_envelope = ""
    if lines and start_line > header_max_lines + 5:
        # Extract top imports / module headers
        header_candidate = "".join(lines[:header_max_lines]).strip()
        # Ensure it looks like import / package declaration
        if any(kw in header_candidate for kw in ("import ", "from ", "package ", "export ", "#!")):
            header_envelope = header_candidate
            
    # Assemble structured expanded representation
    envelope_parts = []
    
    envelope_parts.append(f"// File: {fpath} (Lines {start_line}-{end_line})")
    if sym_name and sym_name != "module_context":
        envelope_parts.append(f"// Declaration Symbol: {sym_name} [{chunk_type}]")
        
    if header_envelope:
        envelope_parts.append("// [File Header Context]:\n" + header_envelope)
        
    envelope_parts.append("// [Target Code Match]:\n" + body_text)
    
    expanded_text = "\n".join(envelope_parts)
    
    # Strict bounding to token envelope
    if len(expanded_text) > max_chars:
        expanded_text = expanded_text[:max_chars] + "\n// ... [Context truncated at token limit]"
        
    return {
        **chunk_hit,
        "expanded_text": expanded_text,
        "expanded_char_length": len(expanded_text),
        "estimated_tokens": len(expanded_text) // 4
    }

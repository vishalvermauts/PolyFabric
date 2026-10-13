import re
import math
import time
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple, Optional

from .store import VectorStore
from ..utils.path_utils import normalize_and_resolve_repo_path, to_relative_repo_path


GENERIC_TERMS: Set[str] = {
    "fetch", "div", "span", "name", "width", "height", "title",
    "irrigation", "button", "input", "label", "form", "class"
}

IGNORED_CONTEXT_FILES: Set[str] = {
    "bun.lock", "package-lock.json", "README.md",
    "docs/ARCHITECTURE.md", "docs/SECURITY.md", "docs/THREAT_MODEL.md",
    ".env.example"
}


def extract_polyfabric_terms(instruction: str) -> List[str]:
    """
    Extract high-signal code symbols, routes, selectors, and string literals
    for PolyFabric AST + hybrid lexical retrieval without benchmark hints.
    """
    terms: List[str] = []
    # 1. Backticked literals
    for m in re.findall(r"`+([^`]+)`+", instruction):
        clean = m.strip()
        if re.match(r"^</?[a-zA-Z0-9]+>$", clean):
            continue
        if re.match(r"^[0-9.]+(?:px|rem|em|%)?$", clean):
            continue
        if "..." in clean:
            clean = clean.split("...")[0].strip().rstrip(",")
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
        # Check dotted suffix (e.g. WeatherService.ts or geo.generatePresetPolygon)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.", clean):
            sub = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*\.", "", clean)
            if len(sub) >= 5 and sub not in terms:
                terms.append(sub)

    # 2. Single-quoted literals (outside backticks)
    instr_no_bt = re.sub(r"`+[^`]+`+", " ", instruction)
    for m in re.findall(r"'([^']+)'", instr_no_bt):
        clean = m.strip()
        if re.match(r"^[0-9.]+(?:px|rem|em|%)?$", clean):
            continue
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)

    # 3. Explicit API routes or camelCase identifiers
    for m in re.findall(r"(/api/[A-Za-z0-9/_-]+|[a-z]+[A-Z][A-Za-z0-9_]*|[A-Z][a-z]+[A-Z][A-Za-z0-9_]*)", instruction):
        if m not in terms:
            terms.append(m)

    specific = [t for t in terms if t.lower() not in GENERIC_TERMS]
    generic = [t for t in terms if t.lower() in GENERIC_TERMS]
    return (specific + generic)[:10]


def build_task_context(
    store: VectorStore,
    instruction: str,
    repo_root: Path | str,
    project_name: str = "general",
    max_files: int = 6
) -> Dict[str, Any]:
    """
    Production PolyFabric Task Context Builder.
    
    1. Extracts high-signal terms (symbols, routes, string literals).
    2. Queries exact symbol index and delimiter-safe lexical FTS.
    3. Normalizes candidate file paths relative to repo_root with relocation resilience.
    4. Ranks candidate files via IDF specificity + AST declaration bonus.
    5. Merges localized AST chunk intervals with intra-file occurrences.
    6. Returns formatted context and diagnostic metadata.
    """
    t0 = time.perf_counter()
    root = Path(repo_root).resolve()
    terms = extract_polyfabric_terms(instruction)
    tool_calls = 0

    term_to_files: Dict[int, Set[str]] = {}
    chunks_by_file: Dict[str, List[Dict[str, Any]]] = {}
    decl_files: Set[str] = set()
    path_errors: List[str] = []

    for idx, term in enumerate(terms):
        if term.lower() in GENERIC_TERMS and any(len(fset) > 0 for fset in term_to_files.values()):
            continue

        # Check if term directly matches a known repo file
        norm_p, _ = normalize_and_resolve_repo_path(term, root, must_exist=True)
        if norm_p and norm_p.is_file():
            rel_f = to_relative_repo_path(norm_p, root)
            if rel_f and rel_f not in IGNORED_CONTEXT_FILES:
                term_to_files.setdefault(idx, set()).add(rel_f)
                decl_files.add(rel_f)

        hits: List[Dict[str, Any]] = []
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", term):
            tool_calls += 1
            sym_hits = store.search_exact_symbol(term, project=project_name)
            for sh in sym_hits:
                if sh.get("symbol_name") == term:
                    fp = sh.get("file_path", "")
                    resolved_p, err = normalize_and_resolve_repo_path(fp, root, must_exist=False)
                    if resolved_p:
                        rel_decl = to_relative_repo_path(resolved_p, root)
                        decl_files.add(rel_decl)
            hits.extend(sym_hits)
        else:
            tool_calls += 1
            fts_hits = store.search_fts(term, top_k=10, project=project_name, exact_only=True)
            hits.extend(fts_hits)

        for r in hits:
            raw_fp = r.get("file_path", "")
            resolved_p, err = normalize_and_resolve_repo_path(raw_fp, root, must_exist=True)
            if not resolved_p:
                if err:
                    path_errors.append(f"Query term '{term}': {err}")
                continue

            rel = to_relative_repo_path(resolved_p, root)
            if not rel or rel in IGNORED_CONTEXT_FILES:
                continue

            term_to_files.setdefault(idx, set()).add(rel)
            chunks_by_file.setdefault(rel, []).append(r)

    # Rank discovered files by IDF weight
    file_scores: Dict[str, float] = {}
    file_term_count: Dict[str, int] = {}
    for idx, fset in term_to_files.items():
        df = len(fset)
        w = (math.log(1 + len(terms[idx])) * 2.0) / max(1, df)
        for f in fset:
            file_scores[f] = file_scores.get(f, 0.0) + w
            file_term_count[f] = file_term_count.get(f, 0) + 1

    for f in decl_files:
        if f in file_scores:
            file_scores[f] += 1.5

    max_score = max(file_scores.values()) if file_scores else 0.0
    discovered_files = [
        f for f in sorted(file_scores.keys(), key=lambda x: -file_scores[x])
        if file_scores[f] >= 0.15 * max_score or file_term_count.get(f, 0) >= 2
    ][:max_files]

    # Build pinpointed context chunks
    context_parts: List[str] = ["=== POLYFABRIC PINPOINTED CODE CHUNKS ==="]
    for rel in discovered_files:
        resolved_p, _ = normalize_and_resolve_repo_path(rel, root, must_exist=True)
        if not resolved_p:
            continue

        try:
            lines = resolved_p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            path_errors.append(f"Failed to read file '{resolved_p}': {e}")
            continue

        total_lines = len(lines)
        if total_lines <= 90:
            context_parts.append(f"--- FILE: {rel} (Lines 1-{total_lines} of {total_lines}) ---\n" + "\n".join(lines))
        else:
            intervals: List[Tuple[int, int]] = []
            for c in chunks_by_file.get(rel, [])[:8]:
                s = max(1, int(c.get("start_line") or 1) - 15)
                e = min(total_lines, int(c.get("end_line") or min(total_lines, s + 35)) + 15)
                intervals.append((s, e))

            for lno, line_txt in enumerate(lines, 1):
                for term in terms:
                    if term.lower() not in GENERIC_TERMS and term in line_txt:
                        intervals.append((max(1, lno - 12), min(total_lines, lno + 12)))
                        break

            intervals.sort()
            merged: List[List[int]] = []
            for s, e in intervals:
                if not merged or s > merged[-1][1] + 5:
                    merged.append([s, e])
                else:
                    merged[-1][1] = max(merged[-1][1], e)

            for s, e in merged[:8]:
                snippet = "\n".join(lines[s - 1:e])
                context_parts.append(f"--- FILE: {rel} (Lines {s}-{e} of {total_lines}) ---\n{snippet}")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "context_text": "\n".join(context_parts),
        "discovered_files": discovered_files,
        "tool_calls": tool_calls,
        "elapsed_ms": round(elapsed_ms, 2),
        "search_terms": terms,
        "path_errors": path_errors
    }

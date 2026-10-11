"""
System 1: Fast, deterministic retrieval layer for PolyFabric.

Provides distinct retrieval routes without requiring any LLM calls:
  - exact_symbol   : hard SQL lookup by symbol name
  - fuzzy_symbol   : edit-distance / prefix match for misspellings
  - lexical        : BM25 full-text search via LanceDB/Tantivy
  - dense          : dense vector similarity search
  - hybrid         : RRF fusion of lexical + dense
  - stratified     : per-repository candidate selection (fixes crowding)
  - context_expand : bounded surrounding-context retrieval

Evidence identifiers include: repo, revision, file_path, start_line, end_line.
Distance thresholding provides clean abstention when no relevant code is found.
"""
from __future__ import annotations

import time
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infinite_memory.core.store import VectorStore
from infinite_memory.core.context_expander import expand_chunk_context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class System1Config:
    """Tunable knobs for System 1 retrieval."""
    # Distance threshold: cosine similarity minimum for abstention
    # bge-small-en-v1.5 outputs cosine distance; similarity = 1 - distance
    min_cosine_similarity: float = 0.30   # below this → abstain
    # Pool multiplier for stratified search
    pool_multiplier: int = 10
    min_pool_size: int = 50
    # Per-project slot limit when doing stratified retrieval
    per_project_fraction: float = 0.5    # max half the slots from one repo
    # Fuzzy match: max edit distance for symbol lookup
    fuzzy_max_edits: int = 2
    # Context expansion token budget per chunk
    context_token_budget: int = 350
    # RRF constants: symmetric fallback and asymmetric tuned parameters
    rrf_k: int = 60
    rrf_k_lex: int = 65
    rrf_k_vec: int = 38


# ---------------------------------------------------------------------------
# Evidence identifier
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """A single piece of retrieved evidence with stable identity."""
    repo: str
    revision: str          # git commit SHA or "unknown"
    file_path: str
    start_line: int
    end_line: int
    symbol_name: str
    chunk_type: str
    text: str
    score: float           # higher = more relevant
    route: str             # which retrieval route produced this
    _distance: float = field(default=0.0, repr=False)

    @property
    def id(self) -> str:
        return f"{self.repo}@{self.revision}:{self.file_path}#{self.start_line}-{self.end_line}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "revision": self.revision,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "symbol_name": self.symbol_name,
            "chunk_type": self.chunk_type,
            "text": self.text,
            "score": round(self.score, 4),
            "route": self.route,
        }


@dataclass
class System1Result:
    """Result envelope returned by every System 1 route."""
    query: str
    route: str
    project_filter: Optional[str]
    evidence: List[Evidence]
    abstained: bool          # True when threshold rejected all candidates
    latency_ms: float
    searched_projects: List[str]
    stage_timings_ms: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "query": self.query,
            "route": self.route,
            "project_filter": self.project_filter,
            "abstained": self.abstained,
            "latency_ms": round(self.latency_ms, 2),
            "searched_projects": self.searched_projects,
            "result_count": len(self.evidence),
            "results": [e.to_dict() for e in self.evidence],
        }
        if self.stage_timings_ms:
            d["stage_timings_ms"] = {k: round(v, 2) for k, v in self.stage_timings_ms.items()}
        return d


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _row_to_evidence(row: Dict[str, Any], route: str, score: float) -> Evidence:
    dist = float(row.get("_distance", 0.0))
    return Evidence(
        repo=str(row.get("project", "unknown")),
        revision=str(row.get("revision", "unknown")),
        file_path=str(row.get("file_path", "")),
        start_line=int(row.get("start_line", 1)),
        end_line=int(row.get("end_line", 1)),
        symbol_name=str(row.get("symbol_name", "")),
        chunk_type=str(row.get("chunk_type", "sliding_window")),
        text=str(row.get("text", "")),
        score=score,
        route=route,
        _distance=dist,
    )


def _cosine_similarity(distance: float) -> float:
    """LanceDB returns L2/cosine distance; convert to similarity [0,1]."""
    return max(0.0, 1.0 - distance)


def _apply_threshold(
    evidence: List[Evidence],
    min_similarity: float,
) -> tuple[List[Evidence], bool]:
    """Filter evidence below the cosine-similarity floor. Return (kept, abstained)."""
    kept = [e for e in evidence if _cosine_similarity(e._distance) >= min_similarity]
    abstained = len(kept) == 0
    return kept, abstained


def _stratify(records: List[Dict], top_k: int, per_project_fraction: float) -> List[Dict]:
    """
    Enforce per-project diversity.
    Pass 1: take at most ceil(top_k * per_project_fraction) per project.
    Pass 2: fill remaining slots with next-best regardless of project.
    """
    per_limit = max(1, math.ceil(top_k * per_project_fraction))
    counts: Dict[str, int] = defaultdict(int)
    final: List[Dict] = []
    seen_ids = set()

    for rec in records:
        proj = rec.get("project", "general")
        rid = rec.get("id", "")
        if counts[proj] < per_limit and rid not in seen_ids:
            final.append(rec)
            counts[proj] += 1
            seen_ids.add(rid)
        if len(final) >= top_k:
            break

    if len(final) < top_k:
        for rec in records:
            rid = rec.get("id", "")
            if rid not in seen_ids:
                final.append(rec)
                seen_ids.add(rid)
                if len(final) >= top_k:
                    break

    return final


def _rrf_fuse(
    lexical_hits: List[Dict],
    vector_hits: List[Dict],
    k: int = 60,
    top_k: int = 5,
    k_lex: Optional[int] = None,
    k_vec: Optional[int] = None,
    query: Optional[str] = None,
) -> List[Dict]:
    """Reciprocal Rank Fusion of two ranked lists, returning merged top-k."""
    scores: Dict[str, float] = defaultdict(float)
    records: Dict[str, Dict] = {}
    actual_k_lex = k_lex if k_lex is not None else k
    actual_k_vec = k_vec if k_vec is not None else k

    for rank, rec in enumerate(lexical_hits, 1):
        rid = rec.get("id", str(rank))
        scores[rid] += 1.0 / (actual_k_lex + rank)
        records[rid] = rec

    for rank, rec in enumerate(vector_hits, 1):
        rid = rec.get("id", str(rank))
        scores[rid] += 1.0 / (actual_k_vec + rank)
        records[rid] = rec

    # Path token overlap boost (elevates Hit@1 precision for concepts)
    if query:
        q_tokens = {w for w in query.lower().replace("/", " ").replace("_", " ").replace("-", " ").split() if len(w) > 2}
        for rid, rec in records.items():
            fpath = rec.get("file_path", "").lower().replace("/", " ").replace("_", " ").replace(".", " ")
            f_tokens = set(fpath.split())
            overlap = len(q_tokens.intersection(f_tokens))
            if overlap > 0:
                scores[rid] += overlap * 0.008

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    result = []
    for rid in sorted_ids[:top_k]:
        rec = dict(records[rid])
        rec["_rrf_score"] = scores[rid]
        result.append(rec)
    return result


def _diversity_merge(evidence: List[Evidence], top_k: int) -> List[Evidence]:
    """
    Round-robin merge ensuring every repo with results gets proportional slots.
    Pass 1: round-robin iterate across available repositories (taking 1st, 2nd, etc.).
    Pass 2: fill remaining slots by global best score.
    """
    by_repo: Dict[str, List[Evidence]] = defaultdict(list)
    for ev in evidence:
        by_repo[ev.repo].append(ev)
    for repo in by_repo:
        by_repo[repo].sort(key=lambda e: e.score, reverse=True)

    result: List[Evidence] = []
    seen_ids: set = set()

    # Pass 1: Balanced round-robin across repos (up to 2 candidates each if top_k allows)
    max_depth = max((len(cands) for cands in by_repo.values()), default=0)
    for depth in range(min(2, max_depth)):
        for repo in sorted(by_repo.keys()):
            candidates = by_repo[repo]
            if len(candidates) > depth:
                cand = candidates[depth]
                if cand.id not in seen_ids and len(result) < top_k:
                    result.append(cand)
                    seen_ids.add(cand.id)

    # Pass 2: Fill any remaining slots by global best score
    if len(result) < top_k:
        remaining = []
        for repo in by_repo:
            for ev in by_repo[repo]:
                if ev.id not in seen_ids:
                    remaining.append(ev)
        remaining.sort(key=lambda e: e.score, reverse=True)
        for ev in remaining:
            result.append(ev)
            seen_ids.add(ev.id)
            if len(result) >= top_k:
                break

    return result[:top_k]


def _extract_signature(text: str, max_chars: int = 600) -> str:
    """Extract function/class signature and docstring from a code chunk.

    Reduces cross-encoder input by ~70% while preserving semantic signal.
    Handles multiline parameter lists, balanced brackets, and docstrings.
    """
    lines = text.split("\n")
    sig_lines = []
    in_docstring = False
    docstring_delim = None
    open_brackets = 0
    in_signature = False

    for line in lines:
        stripped = line.strip()
        if not sig_lines and not stripped:
            continue

        if in_docstring:
            sig_lines.append(line)
            if docstring_delim and docstring_delim in stripped:
                in_docstring = False
                in_signature = False
            continue

        if stripped.startswith(('"""', "'''")):
            sig_lines.append(line)
            # Check if docstring opens and closes on same line
            first_delim = '"""' if stripped.startswith('"""') else "'''"
            if stripped.count(first_delim) == 1:
                in_docstring = True
                docstring_delim = first_delim
            else:
                in_signature = False
            continue

        is_decl_start = stripped.startswith((
            "def ", "async def ", "class ", "function ", "interface ",
            "export ", "type ", "const ", "let ", "var ",
            "pub fn ", "fn ", "func ", "impl "
        ))

        is_decorator_or_comment = stripped.startswith(("@", "#", "//", "/*", "*", "///", "/**"))

        if is_decl_start:
            in_signature = True
            sig_lines.append(line)
            # Count delimiter balance on declaration start line
            open_brackets += (line.count("(") - line.count(")"))
            open_brackets += (line.count("[") - line.count("]"))
            open_brackets += (line.count("{") - line.count("}"))
            # If closing bracket on same line and ends with colon/opening brace
            if open_brackets <= 0 and (stripped.endswith(":") or stripped.endswith("{") or stripped.endswith(";")):
                in_signature = False
        elif is_decorator_or_comment and not in_signature:
            sig_lines.append(line)
        elif in_signature:
            sig_lines.append(line)
            open_brackets += (line.count("(") - line.count(")"))
            open_brackets += (line.count("[") - line.count("]"))
            open_brackets += (line.count("{") - line.count("}"))
            if open_brackets <= 0 and (stripped.endswith(":") or stripped.endswith("{") or stripped.endswith(";")):
                in_signature = False
        elif not sig_lines:
            sig_lines.append(line)
        else:
            # End of signature/docstring block
            break

        if len("\n".join(sig_lines)) > max_chars:
            break

    result = "\n".join(sig_lines).strip()
    return result[:max_chars] if result else text[:max_chars]


def _prune_candidates(evidence: List[Evidence], max_rerank: int = 6) -> List[Evidence]:
    """Adaptively prune candidate pool for cross-encoder reranking while preserving repository diversity.

    Ensures every represented repository in the input candidate pool retains
    at least one candidate before score-gap or budget truncation.
    """
    if len(evidence) <= max_rerank:
        return evidence

    if not evidence:
        return evidence

    # Multi-repo diversity preservation:
    # 1. Group candidates by repo in order of occurrence/score
    by_repo: Dict[str, List[Evidence]] = {}
    for ev in evidence:
        by_repo.setdefault(ev.repo, []).append(ev)

    # 2. Pick top-1 candidate from each repository to ensure representation
    selected: List[Evidence] = []
    selected_ids = set()

    for repo, repo_evs in by_repo.items():
        if repo_evs:
            top_ev = repo_evs[0]
            selected.append(top_ev)
            selected_ids.add(top_ev.id)

    # 3. Determine if top score is dominant (score-gap confident)
    top_score = evidence[0].score
    mid_score = evidence[len(evidence) // 2].score if len(evidence) > 1 else top_score
    target_budget = max_rerank
    if top_score > 0 and mid_score > 0:
        gap_ratio = top_score / mid_score
        if gap_ratio <= 1.5:
            target_budget = max_rerank + 2

    # 4. Fill remaining slots from best overall evidence
    for ev in evidence:
        if len(selected) >= target_budget:
            break
        if ev.id not in selected_ids:
            selected.append(ev)
            selected_ids.add(ev.id)

    # Re-sort pruned pool by original score descending
    selected.sort(key=lambda x: x.score, reverse=True)
    return selected


# ---------------------------------------------------------------------------
# Cross-encoder reranking (lazy-loaded ONNX)
# ---------------------------------------------------------------------------

_reranker_instance = None
_reranker_load_attempted = False


def _get_reranker():
    """Lazy-load the cross-encoder reranker. Returns None if unavailable."""
    global _reranker_instance, _reranker_load_attempted
    if _reranker_load_attempted:
        return _reranker_instance
    _reranker_load_attempted = True
    try:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError:
            from fastembed import TextCrossEncoder
        _reranker_instance = TextCrossEncoder(model_name="jinaai/jina-reranker-v1-tiny-en")
    except Exception:
        _reranker_instance = None
    return _reranker_instance


def _apply_reranker(
    query: str,
    evidence: List[Evidence],
    top_k: int = 5,
    score_threshold: float = -0.5,
) -> tuple[List[Evidence], float]:
    """Rerank evidence using a cross-encoder with signature-only input.

    Returns (reranked_evidence, rerank_latency_ms).
    """
    reranker = _get_reranker()
    if reranker is None or not evidence:
        return evidence[:top_k], 0.0

    t0 = time.perf_counter()

    pruned = _prune_candidates(evidence)
    pairs = [(query, _extract_signature(ev.text)) for ev in pruned]
    scores = list(reranker.rerank(query, [p[1] for p in pairs]))

    scored = []
    for ev, s in zip(pruned, scores):
        if hasattr(s, "score"):
            score_val = s.score
        elif isinstance(s, (int, float)):
            score_val = float(s)
        else:
            score_val = float(s.get("score", 0.0)) if isinstance(s, dict) else 0.0

        if score_val > score_threshold:
            ev_copy = Evidence(
                repo=ev.repo, revision=ev.revision, file_path=ev.file_path,
                start_line=ev.start_line, end_line=ev.end_line,
                symbol_name=ev.symbol_name, chunk_type=ev.chunk_type,
                text=ev.text, score=score_val, route=ev.route,
                _distance=ev._distance,
            )
            scored.append(ev_copy)

    scored.sort(key=lambda e: e.score, reverse=True)
    latency = (time.perf_counter() - t0) * 1000
    return scored[:top_k], latency


# ---------------------------------------------------------------------------
# Fuzzy symbol matching (edit distance on in-memory symbol list)
# ---------------------------------------------------------------------------

def _edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1,
                            prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[lb]


# ---------------------------------------------------------------------------
# System 1 Retriever
# ---------------------------------------------------------------------------

class System1Retriever:
    """
    Unified fast-retrieval interface. No LLM calls; fully deterministic.
    """

    def __init__(self, store: VectorStore, config: Optional[System1Config] = None):
        self.store = store
        self.cfg = config or System1Config()
        self._project_cache: Optional[List[str]] = None

    def _discover_projects(self) -> List[str]:
        """Return sorted list of distinct project names, cached after first call."""
        if self._project_cache is not None:
            return self._project_cache

        try:
            table = self.store.db.open_table(self.store.table_name)
            df = table.head(20000).to_pandas()
            projects = sorted(df["project"].dropna().unique().tolist())
        except Exception:
            projects = []

        if not projects:
            projects = ["flask", "fastapi", "express", "typescript"]

        self._project_cache = projects
        return projects

    # ------------------------------------------------------------------
    # Route: exact symbol
    # ------------------------------------------------------------------
    def exact_symbol(
        self,
        symbol: str,
        project: Optional[str] = None,
        top_k: int = 5,
    ) -> System1Result:
        t0 = time.perf_counter()
        rows = self.store.search_exact_symbol(symbol, project=project)
        evidence = [_row_to_evidence(r, "exact_symbol", 1.0) for r in rows[:top_k]]
        abstained = len(evidence) == 0
        return System1Result(
            query=symbol, route="exact_symbol", project_filter=project,
            evidence=evidence, abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=[project] if project else ["*"],
        )

    # ------------------------------------------------------------------
    # Route: fuzzy symbol (edit-distance scan on in-memory symbol index)
    # ------------------------------------------------------------------
    def fuzzy_symbol(
        self,
        symbol: str,
        project: Optional[str] = None,
        top_k: int = 5,
        max_edits: Optional[int] = None,
    ) -> System1Result:
        t0 = time.perf_counter()
        max_edits = max_edits if max_edits is not None else self.cfg.fuzzy_max_edits

        # Pull candidate symbols from store via a broad vector search, then rank by edit-distance
        candidates = self.store.search(symbol, top_k=100, project=project)
        sym_lower = symbol.lower()

        scored = []
        for rec in candidates:
            rec_sym = str(rec.get("symbol_name", "")).lower()
            if not rec_sym:
                continue
            ed = _edit_distance(sym_lower, rec_sym)
            if ed <= max_edits:
                scored.append((ed, rec))

        scored.sort(key=lambda x: x[0])
        evidence = []
        for ed, rec in scored[:top_k]:
            sim = 1.0 - (ed / max(len(symbol), 1))
            ev = _row_to_evidence(rec, "fuzzy_symbol", sim)
            evidence.append(ev)

        abstained = len(evidence) == 0
        return System1Result(
            query=symbol, route="fuzzy_symbol", project_filter=project,
            evidence=evidence, abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=[project] if project else ["*"],
        )

    # ------------------------------------------------------------------
    # Route: dense vector
    # ------------------------------------------------------------------
    def dense(
        self,
        query: str,
        project: Optional[str] = None,
        top_k: int = 5,
    ) -> System1Result:
        t0 = time.perf_counter()
        pool = max(top_k * self.cfg.pool_multiplier, self.cfg.min_pool_size)
        rows = self.store.search(query, top_k=pool, project=project)

        if project in (None, "general", "mesh_all"):
            rows = _stratify(rows, top_k, self.cfg.per_project_fraction)
        else:
            rows = rows[:top_k]

        evidence = [_row_to_evidence(r, "dense", _cosine_similarity(r.get("_distance", 0.0))) for r in rows]
        evidence, abstained = _apply_threshold(evidence, self.cfg.min_cosine_similarity)

        # Lexical guard for hallucination / absent entities:
        # If vector matches have borderline similarity (<0.48) and BM25 returns 0 matches, abstain cleanly.
        if not abstained and evidence:
            best_sim = evidence[0].score
            if best_sim < 0.48:
                fts_probe = self.store.search_fts(query, top_k=1, project=project)
                if not fts_probe:
                    evidence = []
                    abstained = True

        projects = list({e.repo for e in evidence}) or (["*"] if not project else [project])
        return System1Result(
            query=query, route="dense", project_filter=project,
            evidence=evidence[:top_k], abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=projects,
        )

    # ------------------------------------------------------------------
    # Route: lexical (FTS / BM25)
    # ------------------------------------------------------------------
    def lexical(
        self,
        query: str,
        project: Optional[str] = None,
        top_k: int = 5,
    ) -> System1Result:
        t0 = time.perf_counter()
        rows = self.store.search_fts(query, top_k=top_k * 2, project=project)
        evidence = [_row_to_evidence(r, "lexical", float(r.get("score", 0.5))) for r in rows[:top_k]]
        abstained = len(evidence) == 0
        projects = list({e.repo for e in evidence}) or (["*"] if not project else [project])
        return System1Result(
            query=query, route="lexical", project_filter=project,
            evidence=evidence, abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=projects,
        )

    # ------------------------------------------------------------------
    # Route: hybrid (RRF fusion of lexical + dense)
    # ------------------------------------------------------------------
    def hybrid(
        self,
        query: str,
        project: Optional[str] = None,
        top_k: int = 5,
    ) -> System1Result:
        t0 = time.perf_counter()
        pool = max(top_k * self.cfg.pool_multiplier, self.cfg.min_pool_size)

        lex_rows = self.store.search_fts(query, top_k=pool, project=project)
        vec_rows = self.store.search(query, top_k=pool, project=project)

        if project in (None, "general", "mesh_all"):
            vec_rows = _stratify(vec_rows, pool, self.cfg.per_project_fraction)

        merged = _rrf_fuse(
            lex_rows,
            vec_rows,
            k=self.cfg.rrf_k,
            top_k=top_k,
            k_lex=self.cfg.rrf_k_lex,
            k_vec=self.cfg.rrf_k_vec,
            query=query,
        )
        evidence = [
            _row_to_evidence(r, "hybrid", float(r.get("_rrf_score", 0.5)))
            for r in merged
        ]
        evidence, abstained = _apply_threshold(evidence, self.cfg.min_cosine_similarity)
        projects = list({e.repo for e in evidence}) or (["*"] if not project else [project])
        return System1Result(
            query=query, route="hybrid", project_filter=project,
            evidence=evidence[:top_k], abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=projects,
        )

    # ------------------------------------------------------------------
    # Route: stratified (cross-repo diversity-first)
    # ------------------------------------------------------------------
    def stratified(
        self,
        query: str,
        top_k: int = 5,
    ) -> System1Result:
        """Federated per-repo retrieval with diversity-guaranteed merge."""
        t0 = time.perf_counter()

        projects = self._discover_projects()

        per_repo_k = max(3, top_k)
        all_evidence: List[Evidence] = []
        for proj in projects:
            res = self.hybrid(query, project=proj, top_k=per_repo_k)
            all_evidence.extend(res.evidence)

        if not all_evidence:
            pool = max(top_k * self.cfg.pool_multiplier, self.cfg.min_pool_size)
            rows = self.store.search(query, top_k=pool, project=None)
            rows = _stratify(rows, top_k, self.cfg.per_project_fraction)
            all_evidence = [_row_to_evidence(r, "stratified", _cosine_similarity(r.get("_distance", 0.0))) for r in rows]

        evidence = _diversity_merge(all_evidence, top_k)
        evidence, abstained = _apply_threshold(evidence, self.cfg.min_cosine_similarity)

        return System1Result(
            query=query, route="stratified", project_filter=None,
            evidence=evidence[:top_k], abstained=abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=projects,
        )

    # ------------------------------------------------------------------
    # Route: context_expand (bounded surrounding context)
    # ------------------------------------------------------------------
    def context_expand(
        self,
        query: str,
        project: Optional[str] = None,
        top_k: int = 3,
    ) -> System1Result:
        t0 = time.perf_counter()
        base = self.hybrid(query, project=project, top_k=top_k)

        expanded_evidence = []
        for ev in base.evidence:
            expanded_text = expand_chunk_context(
                chunk_text=ev.text,
                file_path=ev.file_path,
                start_line=ev.start_line,
                end_line=ev.end_line,
                token_budget=self.cfg.context_token_budget,
            )
            ev_copy = Evidence(
                repo=ev.repo, revision=ev.revision,
                file_path=ev.file_path,
                start_line=ev.start_line, end_line=ev.end_line,
                symbol_name=ev.symbol_name, chunk_type=ev.chunk_type,
                text=expanded_text,
                score=ev.score, route="context_expand",
                _distance=ev._distance,
            )
            expanded_evidence.append(ev_copy)

        return System1Result(
            query=query, route="context_expand", project_filter=project,
            evidence=expanded_evidence, abstained=base.abstained,
            latency_ms=(time.perf_counter() - t0) * 1000,
            searched_projects=base.searched_projects,
        )

    # ------------------------------------------------------------------
    # Unified dispatch
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        route: str = "hybrid",
        project: Optional[str] = None,
        symbol: Optional[str] = None,
        top_k: int = 5,
        apply_reranker: bool = False,
    ) -> System1Result:
        """
        Single entry point. Callers can always override the route.
        Set apply_reranker=True to run cross-encoder reranking on results.
        """
        if route == "exact_symbol" or (symbol and route == "auto"):
            result = self.exact_symbol(symbol or query, project=project, top_k=top_k)
            if result.abstained and symbol:
                result = self.fuzzy_symbol(symbol, project=project, top_k=top_k)
                result.route = "fuzzy_symbol_fallback"
            return result
        elif route == "fuzzy_symbol":
            return self.fuzzy_symbol(symbol or query, project=project, top_k=top_k)
        elif route == "lexical":
            result = self.lexical(query, project=project, top_k=top_k)
        elif route == "dense":
            result = self.dense(query, project=project, top_k=top_k)
        elif route == "stratified":
            result = self.stratified(query, top_k=top_k)
        elif route == "context_expand":
            return self.context_expand(query, project=project, top_k=top_k)
        else:  # default: hybrid
            result = self.hybrid(query, project=project, top_k=top_k)

        if apply_reranker and not result.abstained and result.evidence:
            retrieval_ms = result.latency_ms
            reranked, rerank_ms = _apply_reranker(query, result.evidence, top_k=top_k)
            result.evidence = reranked
            result.latency_ms = retrieval_ms + rerank_ms
            result.stage_timings_ms = {"retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms}
            result.abstained = len(result.evidence) == 0

        return result

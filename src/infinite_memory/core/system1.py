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
    # RRF constant
    rrf_k: int = 60


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "route": self.route,
            "project_filter": self.project_filter,
            "abstained": self.abstained,
            "latency_ms": round(self.latency_ms, 2),
            "searched_projects": self.searched_projects,
            "result_count": len(self.evidence),
            "results": [e.to_dict() for e in self.evidence],
        }


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
) -> List[Dict]:
    """Reciprocal Rank Fusion of two ranked lists, returning merged top-k."""
    scores: Dict[str, float] = defaultdict(float)
    records: Dict[str, Dict] = {}

    for rank, rec in enumerate(lexical_hits, 1):
        rid = rec.get("id", str(rank))
        scores[rid] += 1.0 / (k + rank)
        records[rid] = rec

    for rank, rec in enumerate(vector_hits, 1):
        rid = rec.get("id", str(rank))
        scores[rid] += 1.0 / (k + rank)
        records[rid] = rec

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    result = []
    for rid in sorted_ids[:top_k]:
        rec = dict(records[rid])
        rec["_rrf_score"] = scores[rid]
        result.append(rec)
    return result


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

        merged = _rrf_fuse(lex_rows, vec_rows, k=self.cfg.rrf_k, top_k=top_k)
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
        """Retrieve candidates independently from each repository, then merge and rank."""
        t0 = time.perf_counter()
        
        # Discover all projects in the database
        try:
            table = self.store.db.open_table(self.store.table_name)
            df_proj = table.search([0.0] * 384).limit(1000).to_pandas()
            projects = sorted(list(set(df_proj["project"].dropna().unique())))
        except Exception:
            projects = ["flask", "fastapi", "express", "typescript"]

        # Retrieve top candidates per project independently
        per_repo_k = max(2, top_k // max(1, len(projects)) + 1)
        all_evidence = []
        for proj in projects:
            res = self.hybrid(query, project=proj, top_k=per_repo_k)
            all_evidence.extend(res.evidence)

        # Sort all evidence by score descending, keeping up to top_k
        all_evidence.sort(key=lambda e: e.score, reverse=True)
        evidence = all_evidence[:top_k]
        abstained = len(evidence) == 0

        return System1Result(
            query=query, route="stratified", project_filter=None,
            evidence=evidence, abstained=abstained,
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
    ) -> System1Result:
        """
        Single entry point. Callers can always override the route.
        """
        if route == "exact_symbol" or (symbol and route == "auto"):
            result = self.exact_symbol(symbol or query, project=project, top_k=top_k)
            if result.abstained and symbol:
                # Fall back to fuzzy on exact miss
                result = self.fuzzy_symbol(symbol, project=project, top_k=top_k)
                result.route = "fuzzy_symbol_fallback"
            return result
        elif route == "fuzzy_symbol":
            return self.fuzzy_symbol(symbol or query, project=project, top_k=top_k)
        elif route == "lexical":
            return self.lexical(query, project=project, top_k=top_k)
        elif route == "dense":
            return self.dense(query, project=project, top_k=top_k)
        elif route == "stratified":
            return self.stratified(query, top_k=top_k)
        elif route == "context_expand":
            return self.context_expand(query, project=project, top_k=top_k)
        else:  # default: hybrid
            return self.hybrid(query, project=project, top_k=top_k)

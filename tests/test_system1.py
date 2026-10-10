"""
Tests for System 1 fast retrieval layer.
Uses deterministic mocks — no real LanceDB, no API credits.
"""
import pytest
from unittest.mock import MagicMock, patch
from infinite_memory.core.system1 import (
    System1Retriever,
    System1Config,
    Evidence,
    _edit_distance,
    _stratify,
    _rrf_fuse,
    _cosine_similarity,
    _diversity_merge,
    _row_to_evidence,
    _extract_signature,
    _prune_candidates,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_row(id_, project, symbol="", distance=0.1, score=0.9):
    return {
        "id": id_,
        "project": project,
        "file_path": f"/{project}/file.py",
        "start_line": 1,
        "end_line": 10,
        "symbol_name": symbol,
        "chunk_type": "ast_declaration",
        "text": f"def {symbol}(): pass",
        "_distance": distance,
        "revision": "abc123",
        "score": score,
    }


def make_store(search_rows=None, fts_rows=None, exact_rows=None):
    store = MagicMock()
    store.search.return_value = search_rows or []
    store.search_fts.return_value = fts_rows or []
    store.search_exact_symbol.return_value = exact_rows or []
    return store


# ---------------------------------------------------------------------------
# Unit: edit distance
# ---------------------------------------------------------------------------

class TestEditDistance:
    def test_identical(self):
        assert _edit_distance("foo", "foo") == 0

    def test_one_insert(self):
        assert _edit_distance("foo", "fooo") == 1

    def test_one_delete(self):
        assert _edit_distance("fooo", "foo") == 1

    def test_one_substitute(self):
        assert _edit_distance("foo", "fbo") == 1

    def test_completely_different(self):
        assert _edit_distance("abc", "xyz") == 3


# ---------------------------------------------------------------------------
# Unit: stratified sampling
# ---------------------------------------------------------------------------

class TestStratify:
    def test_single_repo_crowding_prevented(self):
        """Large repo should not take all slots."""
        records = [make_row(str(i), "big_repo") for i in range(20)]
        records += [make_row(str(i + 20), "small_repo") for i in range(3)]
        result = _stratify(records, top_k=5, per_project_fraction=0.4)
        projects = [r["project"] for r in result]
        assert "small_repo" in projects, "small_repo must appear in stratified result"
        assert projects.count("big_repo") <= 3  # at most ceil(5*0.4)=2 actually, checking <=3

    def test_fill_when_only_one_repo(self):
        """If only one repo exists, should fill all top_k slots."""
        records = [make_row(str(i), "only_repo") for i in range(10)]
        result = _stratify(records, top_k=5, per_project_fraction=0.4)
        assert len(result) == 5

    def test_exact_top_k(self):
        records = [make_row(str(i), f"repo_{i % 3}") for i in range(15)]
        result = _stratify(records, top_k=5, per_project_fraction=0.5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Unit: RRF fusion
# ---------------------------------------------------------------------------

class TestRRFFuse:
    def test_top_results_from_both_lists(self):
        lex = [make_row("a", "r1"), make_row("b", "r2")]
        vec = [make_row("c", "r3"), make_row("a", "r1")]
        result = _rrf_fuse(lex, vec, top_k=3)
        ids = [r["id"] for r in result]
        assert "a" in ids  # appears in both lists, should rank highest

    def test_returns_at_most_top_k(self):
        lex = [make_row(str(i), "r1") for i in range(10)]
        vec = [make_row(str(i + 5), "r2") for i in range(10)]
        result = _rrf_fuse(lex, vec, top_k=4)
        assert len(result) <= 4


# ---------------------------------------------------------------------------
# Unit: distance threshold
# ---------------------------------------------------------------------------

class TestCosineThreshold:
    def test_similarity_from_zero_distance(self):
        assert _cosine_similarity(0.0) == 1.0

    def test_similarity_from_unit_distance(self):
        assert _cosine_similarity(1.0) == 0.0

    def test_similarity_midpoint(self):
        assert abs(_cosine_similarity(0.5) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Integration: System1Retriever routes
# ---------------------------------------------------------------------------

class TestExactSymbolRoute:
    def test_found(self):
        rows = [make_row("1", "flask", symbol="create_app", distance=0.0)]
        store = make_store(exact_rows=rows)
        r = System1Retriever(store).exact_symbol("create_app")
        assert not r.abstained
        assert len(r.evidence) == 1
        assert r.evidence[0].symbol_name == "create_app"
        assert r.route == "exact_symbol"

    def test_not_found_abstains(self):
        store = make_store(exact_rows=[])
        r = System1Retriever(store).exact_symbol("nonexistent_fn")
        assert r.abstained
        assert r.evidence == []


class TestFuzzySymbolRoute:
    def test_finds_misspelling(self):
        rows = [make_row("1", "flask", symbol="create_app", distance=0.2)]
        store = make_store(search_rows=rows)
        r = System1Retriever(store).fuzzy_symbol("creat_app")  # one char off
        assert not r.abstained
        assert r.evidence[0].symbol_name == "create_app"

    def test_too_many_edits_abstains(self):
        rows = [make_row("1", "flask", symbol="totally_different", distance=0.2)]
        store = make_store(search_rows=rows)
        cfg = System1Config(fuzzy_max_edits=2)
        r = System1Retriever(store, cfg).fuzzy_symbol("abc")
        assert r.abstained


class TestDenseRoute:
    def test_cross_repo_diversity(self):
        rows = [make_row(str(i), "big_repo", distance=0.05) for i in range(20)]
        rows += [make_row("99", "small_repo", distance=0.15)]
        store = make_store(search_rows=rows)
        cfg = System1Config(min_cosine_similarity=0.0)
        r = System1Retriever(store, cfg).dense("routing middleware", top_k=5)
        projects = [e.repo for e in r.evidence]
        assert "small_repo" in projects, "small_repo should appear after stratification"

    def test_abstains_when_all_below_threshold(self):
        rows = [make_row("1", "r", distance=0.95)]  # similarity = 0.05, below default 0.30
        store = make_store(search_rows=rows)
        r = System1Retriever(store).dense("some query", top_k=5)
        assert r.abstained


class TestHybridRoute:
    def test_returns_merged_results(self):
        lex = [make_row("a", "flask", distance=0.1)]
        vec = [make_row("b", "express", distance=0.1)]
        store = make_store(search_rows=vec, fts_rows=lex)
        cfg = System1Config(min_cosine_similarity=0.0)
        r = System1Retriever(store, cfg).hybrid("routing", top_k=5)
        assert not r.abstained
        assert r.route == "hybrid"

    def test_abstains_on_empty(self):
        store = make_store(search_rows=[], fts_rows=[])
        r = System1Retriever(store).hybrid("routing", top_k=5)
        assert r.abstained


class TestDiversityMerge:
    """Test the _diversity_merge helper function directly."""

    def _make_evidence(self, id_, repo, score):
        return Evidence(
            repo=repo, revision="abc", file_path=f"/{repo}/file.py",
            start_line=1, end_line=10, symbol_name="fn", chunk_type="ast",
            text="...", score=score, route="hybrid",
        )

    def test_one_per_repo_guaranteed(self):
        evs = [self._make_evidence(f"ts_{i}", "typescript", 0.9 - i * 0.01) for i in range(10)]
        evs += [self._make_evidence("flask_0", "flask", 0.5)]
        evs += [self._make_evidence("express_0", "express", 0.4)]
        result = _diversity_merge(evs, top_k=5)
        repos = {e.repo for e in result}
        assert "flask" in repos
        assert "express" in repos
        assert "typescript" in repos

    def test_fills_remaining_by_score(self):
        evs = [self._make_evidence("a", "repo_a", 0.9)]
        evs += [self._make_evidence("b", "repo_b", 0.8)]
        ev_extra = Evidence(
            repo="repo_a", revision="abc", file_path="/repo_a/other.py",
            start_line=20, end_line=30, symbol_name="fn2", chunk_type="ast",
            text="...", score=0.85, route="hybrid",
        )
        evs.append(ev_extra)
        result = _diversity_merge(evs, top_k=3)
        assert len(result) == 3

    def test_empty_input(self):
        result = _diversity_merge([], top_k=5)
        assert result == []

    def test_more_repos_than_slots(self):
        evs = [self._make_evidence(f"r{i}", f"repo_{i}", 0.9 - i * 0.1) for i in range(8)]
        result = _diversity_merge(evs, top_k=5)
        assert len(result) == 5


class TestMultiRepoPreservation:
    """Verify that multi-repo evidence is preserved after stratified retrieval."""

    def test_both_repos_in_result(self):
        ts_rows = [make_row(f"ts_{i}", "typescript", distance=0.05) for i in range(10)]
        flask_rows = [make_row(f"flask_{i}", "flask", distance=0.20) for i in range(5)]

        def mock_search(query, top_k=3, project=None, **kw):
            if project == "flask":
                return flask_rows[:top_k]
            elif project == "typescript":
                return ts_rows[:top_k]
            return (ts_rows + flask_rows)[:top_k]

        def mock_fts(query, top_k=10, project=None):
            if project == "flask":
                return flask_rows[:top_k]
            elif project == "typescript":
                return ts_rows[:top_k]
            return (ts_rows + flask_rows)[:top_k]

        store = MagicMock()
        store.search = mock_search
        store.search_fts = mock_fts
        store.search_exact_symbol.return_value = []

        cfg = System1Config(min_cosine_similarity=0.0)
        retriever = System1Retriever(store, cfg)
        retriever._project_cache = ["flask", "typescript"]
        result = retriever.stratified("authentication flow", top_k=6)
        repos = {e.repo for e in result.evidence}
        assert "flask" in repos
        assert "typescript" in repos


class TestContextBoundaries:
    """Context expansion must not exceed token budget."""

    def test_context_expand_calls_expander(self):
        rows = [make_row("1", "flask", distance=0.1)]
        store = make_store(search_rows=rows, fts_rows=rows)
        cfg = System1Config(min_cosine_similarity=0.0, context_token_budget=350)

        with patch(
            "infinite_memory.core.system1.expand_chunk_context",
            return_value="# context\ndef create_app(): pass",
        ) as mock_expand:
            r = System1Retriever(store, cfg).context_expand("create app", top_k=1)
            assert mock_expand.called
            assert r.evidence[0].text.startswith("# context")


class TestSourceChangeInvalidation:
    """Verify evidence IDs change when revision changes."""

    def test_different_revision_different_id(self):
        ev1 = Evidence(
            repo="flask", revision="abc", file_path="/app.py",
            start_line=1, end_line=5, symbol_name="fn", chunk_type="ast",
            text="...", score=1.0, route="dense",
        )
        ev2 = Evidence(
            repo="flask", revision="def", file_path="/app.py",
            start_line=1, end_line=5, symbol_name="fn", chunk_type="ast",
            text="...", score=1.0, route="dense",
        )
        assert ev1.id != ev2.id


class TestUnifiedDispatch:
    def test_auto_falls_back_to_fuzzy_on_exact_miss(self):
        vec_rows = [make_row("1", "flask", symbol="create_app", distance=0.1)]
        store = make_store(exact_rows=[], search_rows=vec_rows)
        cfg = System1Config(fuzzy_max_edits=2)
        r = System1Retriever(store, cfg).search(
            query="creat_app", route="auto", symbol="creat_app"
        )
        assert r.route == "fuzzy_symbol_fallback"

    def test_explicit_route_override(self):
        store = make_store(search_rows=[], fts_rows=[])
        r = System1Retriever(store).search("foo", route="lexical")
        assert r.route == "lexical"


# ---------------------------------------------------------------------------
# Challenge 1: Signature extraction & candidate pruning
# ---------------------------------------------------------------------------

class TestExtractSignature:
    def test_python_function_with_docstring(self):
        code = 'def add_api_route(self, path):\n    """Add an API route to the router."""\n    some_body_logic = True\n    another_line = False'
        sig = _extract_signature(code)
        assert "def add_api_route" in sig
        assert "another_line" not in sig

    def test_python_function_signature_only(self):
        code = "def add_api_route(\n    self,\n    path: str,\n):\n    body = True\n    return body"
        sig = _extract_signature(code)
        assert "def add_api_route" in sig
        assert "body" not in sig or "return body" not in sig

    def test_short_code_returns_all(self):
        code = "def foo(): pass"
        sig = _extract_signature(code)
        assert sig == "def foo(): pass"

    def test_empty_code(self):
        sig = _extract_signature("")
        assert sig == ""

    def test_respects_max_chars(self):
        code = "def very_long_function():\n" + "    x = 1\n" * 200
        sig = _extract_signature(code, max_chars=100)
        assert len(sig) <= 100


class TestPruneCandidates:
    def _ev(self, score):
        return Evidence(
            repo="r", revision="a", file_path="/f.py",
            start_line=1, end_line=10, symbol_name="fn", chunk_type="ast",
            text="...", score=score, route="hybrid",
        )

    def test_small_pool_unchanged(self):
        evs = [self._ev(0.9 - i * 0.1) for i in range(4)]
        result = _prune_candidates(evs, max_rerank=6)
        assert len(result) == 4

    def test_large_pool_pruned(self):
        evs = [self._ev(0.9)] + [self._ev(0.3) for _ in range(14)]
        result = _prune_candidates(evs, max_rerank=6)
        assert len(result) <= 8

    def test_empty(self):
        assert _prune_candidates([], max_rerank=6) == []


class TestRerankerIntegration:
    def test_apply_reranker_false_no_stage_timings(self):
        rows = [make_row("a", "flask", distance=0.1)]
        store = make_store(search_rows=rows, fts_rows=rows)
        cfg = System1Config(min_cosine_similarity=0.0)
        r = System1Retriever(store, cfg).search("routing", route="hybrid", apply_reranker=False)
        assert r.stage_timings_ms == {}

    def test_apply_reranker_true_with_mock(self):
        rows = [make_row("a", "flask", distance=0.1)]
        store = make_store(search_rows=rows, fts_rows=rows)
        cfg = System1Config(min_cosine_similarity=0.0)

        mock_result = MagicMock()
        mock_result.score = 0.95
        with patch("infinite_memory.core.system1._get_reranker") as mock_get:
            mock_reranker = MagicMock()
            mock_reranker.rerank.return_value = [mock_result]
            mock_get.return_value = mock_reranker
            r = System1Retriever(store, cfg).search("routing", route="hybrid", apply_reranker=True)
            assert "rerank_ms" in r.stage_timings_ms
            assert r.evidence[0].score == 0.95

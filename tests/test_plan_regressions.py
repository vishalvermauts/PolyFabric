"""Regression tests for the experiment; no model or API needed unless explicitly marked."""
import numpy as np
from unittest.mock import patch
from infinite_memory.core.store import VectorStore, DOCUMENTS_SCHEMA
from infinite_memory.core.system1 import System1Retriever, _row_to_evidence
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser
from infinite_memory.server import _detect_cross_repo_intent


def record(i, project='p'):
    return dict(id=str(i), text=f'def symbol_{i}(): pass', file_path=f'f{i}.py', project=project,
                symbol_name=f'symbol_{i}', chunk_type='ast_function_definition', start_line=1,
                end_line=1, vector=[0.0] * 384)


def test_complete_scan_and_external_writer_invalidation(tmp_path):
    store = VectorStore(tmp_path / 'db')
    table = store.db.open_table(store.table_name)
    table.add([record(i) for i in range(10005)])
    assert len(store.get_indexed_files_for_project('p')) == 10005
    assert store.search_exact_symbol('symbol_10004', 'p')
    # A separate writer changes the database version; old cached results must not survive.
    other = VectorStore(tmp_path / 'db')
    other.db.open_table(other.table_name).delete("id = '10004'")
    assert store.search_exact_symbol('symbol_10004', 'p') == []
    assert store.list_projects() == ['p']


def test_fuzzy_never_needs_a_vector_query(tmp_path):
    store = VectorStore(tmp_path / 'db')
    row = record(1)
    row['symbol_name'] = 'createProgram'
    store.db.open_table(store.table_name).add([row])
    with patch.object(store, 'search', side_effect=AssertionError('vector called')):
        result = System1Retriever(store).fuzzy_symbol('creatProgram')
    assert result.evidence[0].symbol_name == 'createProgram'


def test_embedding_cached_and_encoder_change_invalidates(tmp_path):
    class Encoder:
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return iter([np.ones(384, dtype=np.float32) for _ in texts])
    store = VectorStore(tmp_path / 'db')
    encoder = Encoder()
    store.encoder = encoder
    assert store._embed_query('same') == store._embed_query('same')
    assert encoder.calls == 1
    store.encoder = Encoder()
    store._embed_query('same')
    assert store.encoder.calls == 1


def test_no_vector_fallback_for_explicit_lexical_query(tmp_path):
    store = VectorStore(tmp_path / 'db')
    with patch.object(store, 'search', side_effect=AssertionError('vector called')):
        assert store.search_fts('not_present', allow_vector_fallback=False) == []


def test_context_expansion_uses_actual_contract(tmp_path):
    path = tmp_path / 'x.py'
    path.write_text('def sample(): pass\n')
    ev = _row_to_evidence(dict(project='p', file_path=str(path), text=path.read_text(),
                              symbol_name='sample', start_line=1, end_line=1), 'hybrid', 1)
    from infinite_memory.core.system1 import System1Result
    retriever = System1Retriever(None)
    with patch.object(retriever, 'hybrid', return_value=System1Result('sample', 'hybrid', None, [ev], False, 0, ['p'])):
        out = retriever.context_expand('sample')
    assert isinstance(out.evidence[0].text, str)
    assert 'def sample' in out.evidence[0].text


def test_comments_and_python_decorators_stay_attached(tmp_path):
    parser = UniversalASTParser()
    py = tmp_path / 'route.py'
    py.write_text('@app.get("/hello")\ndef hello():\n    return 1\n')
    chunks = parser.parse_file(str(py))
    assert any(c.symbol_name == 'hello' and '@app.get' in c.content for c in chunks)
    ts = tmp_path / 'api.ts'
    ts.write_text('/** Validates inbound requests. */\nexport function validateRequest() { return true; }\n')
    chunks = parser.parse_file(str(ts))
    assert any(c.symbol_name == 'validateRequest' and 'Validates inbound' in c.content for c in chunks)


def test_conjunction_does_not_force_cross_repo():
    assert not _detect_cross_repo_intent('flask push and pop application context')
    assert not _detect_cross_repo_intent('find keys and configuration')
    assert _detect_cross_repo_intent('compare flask and fastapi routing')


def test_reranker_receives_candidates_beyond_final_k():
    from infinite_memory.core.system1 import System1Result
    retriever = System1Retriever(None)
    evs = [_row_to_evidence(record(i), 'hybrid', 1) for i in range(10)]
    with patch.object(retriever, 'hybrid', return_value=System1Result('q', 'hybrid', None, evs, False, 0, ['p'])) as search:
        with patch('infinite_memory.core.system1._apply_reranker', return_value=([evs[7]], 1)):
            out = retriever.search('q', top_k=5, apply_reranker=True)
    assert search.call_args.kwargs['top_k'] == 10
    assert out.evidence[0] is evs[7]


def test_watcher_reconciles_changes_but_skips_unchanged(tmp_path):
    from infinite_memory.core.watcher import MeshWatcherManager
    root = tmp_path / 'project'
    root.mkdir()
    path = root / 'sample.py'
    path.write_text('def first(): return 1\n')
    store = VectorStore(tmp_path / 'db')
    class Encoder:
        def embed(self, texts):
            return iter([np.ones(384, dtype=np.float32) for _ in texts])
    store.encoder = Encoder()
    manager = MeshWatcherManager(store)
    manager._reconcile_project('p', root)
    assert store.get_indexed_files_for_project('p') == ['sample.py']
    with patch.object(store, 'upsert_file_documents', wraps=store.upsert_file_documents) as write:
        manager._reconcile_project('p', root)
        write.assert_not_called()
        path.write_text('def second(): return 2\n')
        manager._reconcile_project('p', root)
        assert write.call_count == 1
    assert store.search_exact_symbol('first', 'p') == []
    assert store.search_exact_symbol('second', 'p')
    path.unlink()
    manager._reconcile_project('p', root)
    assert store.count_chunks() == 0


def test_initial_bulk_index_and_refresh_do_not_duplicate(tmp_path):
    from infinite_memory.core.indexer import index_repository
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'a.py').write_text('def first(): return 1\n')
    (root / 'b.py').write_text('def second(): return 2\n')
    store = VectorStore(tmp_path / 'db')
    class Encoder:
        def embed(self, texts):
            return iter([np.ones(384, dtype=np.float32) for _ in texts])
    store.encoder = Encoder()
    first = index_repository(root, 'p', store=store)
    assert first['complete'] and first['bulk_initial']
    n = store.count_chunks()
    second = index_repository(root, 'p', store=store)
    assert second['complete'] and not second['bulk_initial']
    assert store.count_chunks() == n


def test_live_context_reread_masks_secret(tmp_path):
    from infinite_memory.core.task_context import build_task_context
    path = tmp_path / 'settings.ts'
    # Synthetic canary, never an actual credential.
    path.write_text('export const apiToken = "sk-' + 'x' * 40 + '";\n')
    store = VectorStore(tmp_path / 'db')
    row = record(1)
    row.update(file_path='settings.ts', symbol_name='apiToken', text='export const apiToken = "masked";')
    store.db.open_table(store.table_name).add([row])
    result = build_task_context(store, 'Change `apiToken` in `settings.ts`', tmp_path, 'p')
    assert 'sk-' + 'x' * 40 not in result['context_text']

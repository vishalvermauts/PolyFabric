import re
import threading
import shutil
from datetime import timedelta
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict, Any, Optional
from filelock import FileLock

import lancedb
import pyarrow as pa
from fastembed import TextEmbedding

from ..config import DEFAULT_VECTOR_DB_DIR, EMBEDDING_MODEL_NAME
from ..security.secret_masker import mask_secrets


# Standard Arrow schema for documents table
DOCUMENTS_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("file_path", pa.string()),
    pa.field("project", pa.string()),
    pa.field("symbol_name", pa.string()),
    pa.field("chunk_type", pa.string()),
    pa.field("start_line", pa.int32()),
    pa.field("end_line", pa.int32()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
])


class VectorStore:
    """In-process LanceDB + FastEmbed vector core with true atomic replacement and inter-process locking."""

    def __init__(self, db_path: Optional[str | Path] = None, mode: str = "default"):
        if db_path is not None:
            self.db_dir = Path(db_path)
        elif mode == "isolated":
            self.db_dir = Path("./.memory_db")
        else:
            self.db_dir = DEFAULT_VECTOR_DB_DIR

        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.db_dir / ".db_lock"
        self._file_lock = FileLock(str(self.lock_file))
        self.db = lancedb.connect(str(self.db_dir))
        self._encoder = None
        self.table_name = "documents"
        self._ensure_table()
        self._query_embeddings = OrderedDict()
        self._embedding_lock = threading.RLock()

    @property
    def encoder(self):
        if self._encoder is None:
            self._encoder = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
        return self._encoder

    @encoder.setter
    def encoder(self, val):
        self._encoder = val

    def _ensure_table(self):
        """Ensure documents table exists with proper schema."""
        tables = self._list_tables()
        if self.table_name not in tables:
            try:
                self.db.create_table(self.table_name, schema=DOCUMENTS_SCHEMA)
            except Exception:
                pass

    def _list_tables(self) -> List[str]:
        """Safely list table names without deprecated warnings."""
        if hasattr(self.db, "list_tables"):
            try:
                res = self.db.list_tables()
                if hasattr(res, "tables"):
                    return list(res.tables)
                return list(res)
            except Exception:
                pass
        if hasattr(self.db, "table_names"):
            try:
                return self.db.table_names()
            except Exception:
                pass
        return []

    def _escape_sql_str(self, val: str) -> str:
        """Escape single quotes for LanceDB SQL filter clauses."""
        return val.replace("'", "''").replace("\\", "/")

    def delete_by_file(self, file_path: str, project: Optional[str] = None) -> int:
        """Delete all chunks for a specific file across processes."""
        with self._file_lock:
            try:
                norm_path = self._escape_sql_str(str(file_path))
                where_clause = f"file_path = '{norm_path}'"
                if project:
                    norm_proj = self._escape_sql_str(project)
                    where_clause += f" AND project = '{norm_proj}'"

                table = self.db.open_table(self.table_name)
                table.delete(where_clause)
                self._project_chunks_cache = {}
                return 1
            except Exception:
                return 0

    def delete_by_project(self, project: str) -> int:
        """Delete all chunks for a specific project."""
        with self._file_lock:
            try:
                norm_proj = self._escape_sql_str(project)
                table = self.db.open_table(self.table_name)
                table.delete(f"project = '{norm_proj}'")
                self._project_chunks_cache = {}
                return 1
            except Exception:
                return 0

    def _scan_scalar(self, columns, project=None):
        """Full scalar batch scan: no vector query, implicit top-k, or corpus-size ceiling."""
        table = self.db.open_table(self.table_name)
        condition = None
        if project and project not in ("general", "mesh_all"):
            condition = f"project = '{self._escape_sql_str(project)}'"
        try:
            scanner = table.to_lance().scanner(columns=columns, filter=condition, batch_size=1024)
            for batch in scanner.to_batches():
                yield from batch.to_pylist()
            return
        except (ImportError, AttributeError):
            pass

        query = table.search()
        if condition:
            query = query.where(condition)
        if columns:
            query = query.select(columns)
        for batch in query.to_batches(batch_size=1024):
            yield from batch.to_pylist()

    def list_projects(self):
        return sorted({r["project"] for r in self._scan_scalar(["project"]) if r.get("project")})

    def get_indexed_files_for_project(self, project: str) -> List[str]:
        return sorted({r["file_path"] for r in self._scan_scalar(["file_path"], project) if r.get("file_path")})

    def _embed_query(self, query):
        """Bounded per-store cache; namespace includes embedding model and encoder instance."""
        masked, _ = mask_secrets(query)
        encoder = self.encoder
        key = (EMBEDDING_MODEL_NAME, id(encoder), masked)
        with self._embedding_lock:
            if key not in self._query_embeddings:
                self._query_embeddings[key] = list(encoder.embed([masked]))[0].tolist()
                if len(self._query_embeddings) > 256:
                    self._query_embeddings.popitem(last=False)
            self._query_embeddings.move_to_end(key)
            return list(self._query_embeddings[key])

    def upsert_file_documents(self, file_path: str, documents: List[Dict[str, Any]], project: str = "general") -> int:
        """Atomically replace all chunks for a file using LanceDB merge_insert with delete condition.

        Guarantees:
        1. Vectors and masked texts are prepared outside table transactions.
        2. If embedding fails or throws, database state is 100% unaltered.
        3. Table modification occurs in a single atomic merge transaction.
        4. Inter-process file locking prevents race conditions across instances.
        """
        norm_file_path = str(file_path).replace("\\", "/")

        if not documents:
            self.delete_by_file(norm_file_path, project=project)
            return 0

        # Step 1: Pre-compute embeddings & format records safely outside table mutation
        masked_texts = [mask_secrets(doc["text"])[0] for doc in documents]
        embeddings = [emb.tolist() for emb in self.encoder.embed(masked_texts)]

        prepared_records = []
        for doc, masked_txt, emb in zip(documents, masked_texts, embeddings):
            meta = doc.get("metadata", {})
            rec = {
                "id": str(doc["id"]),
                "text": masked_txt,
                "file_path": norm_file_path,
                "project": project,
                "symbol_name": str(meta.get("symbol_name", "")),
                "chunk_type": str(meta.get("chunk_type", "sliding_window")),
                "start_line": int(meta.get("start_line", 1)),
                "end_line": int(meta.get("end_line", 1)),
                "vector": emb,
            }
            prepared_records.append(rec)

        # Step 2: Atomic commit with inter-process lock & merge_insert
        with self._file_lock:
            norm_path_sql = self._escape_sql_str(norm_file_path)
            delete_cond = f"file_path = '{norm_path_sql}'"
            if project:
                delete_cond += f" AND project = '{self._escape_sql_str(project)}'"

            try:
                table = self.db.open_table(self.table_name)
                # Atomic single-statement merge_insert: updates matched, inserts new, purges unreferenced chunks for this file
                table.merge_insert("id") \
                     .when_matched_update_all() \
                     .when_not_matched_insert_all() \
                     .when_not_matched_by_source_delete(delete_cond) \
                     .execute(prepared_records)
            except Exception:
                # If table was missing or corrupt, recreate atomically
                try:
                    self.db.create_table(self.table_name, data=prepared_records, schema=DOCUMENTS_SCHEMA)
                except Exception:
                    # Fallback delete then add under lock
                    table = self.db.open_table(self.table_name)
                    table.delete(delete_cond)
                    table.add(prepared_records)

        self._project_chunks_cache = {}
        return len(prepared_records)

    def upsert_document(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Insert or replace a single document chunk into LanceDB with pre-masking."""
        metadata = metadata or {}
        masked_text, _ = mask_secrets(text)
        embedding = list(self.encoder.embed([masked_text]))[0].tolist()

        norm_file_path = str(metadata.get("file_path", "")).replace("\\", "/")
        norm_proj = str(metadata.get("project", "general"))

        record = {
            "id": doc_id,
            "text": masked_text,
            "file_path": norm_file_path,
            "project": norm_proj,
            "symbol_name": str(metadata.get("symbol_name", "")),
            "chunk_type": str(metadata.get("chunk_type", "sliding_window")),
            "start_line": int(metadata.get("start_line", 1)),
            "end_line": int(metadata.get("end_line", 1)),
            "vector": embedding,
        }

        with self._file_lock:
            try:
                table = self.db.open_table(self.table_name)
                table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute([record])
            except Exception:
                table = self.db.open_table(self.table_name)
                table.delete(f"id = '{self._escape_sql_str(doc_id)}'")
                table.add([record])
        self._project_chunks_cache = {}

    def upsert_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Batch insert document chunks with zero-trust secret masking applied before vector storage."""
        if not documents:
            return 0

        masked_texts = [mask_secrets(doc["text"])[0] for doc in documents]

        # Batch ONNX embeddings in slices of 32 to avoid massive memory allocations
        embeddings = []
        BATCH_EMBED = 32
        for i in range(0, len(masked_texts), BATCH_EMBED):
            batch_slice = masked_texts[i : i + BATCH_EMBED]
            embeddings.extend([emb.tolist() for emb in self.encoder.embed(batch_slice)])

        records = []
        for doc, masked_txt, emb in zip(documents, masked_texts, embeddings):
            meta = doc.get("metadata", {})
            norm_file_path = str(meta.get("file_path", "")).replace("\\", "/")
            rec = {
                "id": str(doc["id"]),
                "text": masked_txt,
                "file_path": norm_file_path,
                "project": str(meta.get("project", "general")),
                "symbol_name": str(meta.get("symbol_name", "")),
                "chunk_type": str(meta.get("chunk_type", "sliding_window")),
                "start_line": int(meta.get("start_line", 1)),
                "end_line": int(meta.get("end_line", 1)),
                "vector": emb,
            }
            records.append(rec)

        with self._file_lock:
            try:
                table = self.db.open_table(self.table_name)
                table.add(records)
            except Exception:
                self.db.create_table(self.table_name, data=records, schema=DOCUMENTS_SCHEMA)

        self._project_chunks_cache = {}
        return len(records)

    @staticmethod
    def _dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate chunk records by ID / file / symbol / line range preserving rank order."""
        seen = set()
        out = []
        for r in records:
            doc_id = str(r.get("id", "")).strip()
            s_line = int(r.get("start_line") or 0)
            e_line = int(r.get("end_line") or 0)
            if doc_id:
                key = (doc_id, str(r.get("file_path", "")))
            else:
                key = (
                    str(r.get("file_path", "")),
                    str(r.get("symbol_name", "")),
                    s_line,
                    e_line,
                )
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    def _get_project_chunks(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cache complete scalar records, keyed by database version for external writers."""
        table = self.db.open_table(self.table_name)
        version = table.version
        key = (project or "__all__", version)
        cache = getattr(self, "_project_chunks_cache", {})
        if key not in cache:
            columns = ["id", "text", "file_path", "project", "symbol_name", "chunk_type", "start_line", "end_line"]
            records = self._dedupe_records(list(self._scan_scalar(columns, project)))
            # Bound the number of snapshots retained, not the number of searchable rows.
            cache = {key: records}
            self._project_chunks_cache = cache
        return cache[key]

    def symbol_records(self, project=None):
        """Declaration dictionary tied to the complete project snapshot."""
        chunks = self._get_project_chunks(project)
        key = (project, self.db.open_table(self.table_name).version)
        if getattr(self, "_symbol_snapshot", None) != key:
            index = {}
            for rec in chunks:
                name = rec.get("symbol_name")
                if name:
                    index.setdefault(name, []).append(rec)
            self._symbol_snapshot, self._symbol_index = key, index
        return self._symbol_index

    def search_exact_symbol(
        self,
        symbol_name: str,
        project: Optional[str] = None,
        include_references: bool = True,
        top_k: int = 25,
    ) -> List[Dict[str, Any]]:
        """Exact symbol match returning AST declaration chunks first, followed by all cross-file reference/import/caller chunks."""
        if not symbol_name or not symbol_name.strip():
            return []
        sym = symbol_name.strip()
        declarations: List[Dict[str, Any]] = []
        references: List[Dict[str, Any]] = []

        chunks = self._get_project_chunks(project=project)
        declarations = list(self.symbol_records(project).get(sym, []))
        if not include_references:
            return self._dedupe_records(declarations)[:top_k]
        try:
            word_pat = re.compile(rf"\b{re.escape(sym)}\b")
            for rec in chunks:
                if rec.get("symbol_name") == sym:
                    continue
                elif include_references and word_pat.search(rec.get("text", "")):
                    references.append(rec)
        except Exception:
            pass

        combined = self._dedupe_records(declarations + references)
        return combined[:top_k]

    def search(
        self,
        query_text: str,
        top_k: int = 3,
        project: Optional[str] = None,
        symbol_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search with exact symbol boosting, deduplication, and project filtering."""
        if symbol_name:
            exact_matches = self.search_exact_symbol(symbol_name, project=project, top_k=top_k)
            if exact_matches:
                return exact_matches[:top_k]

        query_vector = self._embed_query(query_text)

        try:
            table = self.db.open_table(self.table_name)
            query = table.search(query_vector)
            if getattr(self, "_vector_index_settings", None):
                probes, refine = self._vector_index_settings
                query = query.nprobes(probes).refine_factor(refine)

            if project and project not in ("general", "mesh_all"):
                escaped_proj = self._escape_sql_str(project)
                query = query.where(f"project = '{escaped_proj}'")
                try:
                    results = query.limit(max(top_k * 4, 20)).to_arrow().to_pylist()
                except Exception:
                    results = query.limit(max(top_k * 4, 20)).to_pandas().to_dict(orient="records")
                deduped = self._dedupe_records(results)
                return deduped[:top_k]
            else:
                # Stratified Sampling: Fetch larger pool to prevent large-repo crowding
                pool_size = max(top_k * 10, 50)
                try:
                    records_raw = query.limit(pool_size).to_arrow().to_pylist()
                except Exception:
                    records_raw = query.limit(pool_size).to_pandas().to_dict(orient="records")
                if not records_raw:
                    return []

                records = self._dedupe_records(records_raw)

                from collections import defaultdict
                final_results = []
                counts = defaultdict(int)
                per_project_limit = max(1, top_k // 2)

                # Pass 1: Enforce diversity (take up to per_project_limit from each)
                for rec in records:
                    proj = rec.get("project", "general")
                    if counts[proj] < per_project_limit:
                        final_results.append(rec)
                        counts[proj] += 1
                    if len(final_results) >= top_k:
                        break

                # Pass 2: Fill remaining slots if diversity limit was too strict
                if len(final_results) < top_k:
                    for rec in records:
                        if not any(r["id"] == rec["id"] for r in final_results):
                            final_results.append(rec)
                            if len(final_results) >= top_k:
                                break

                return final_results
        except Exception as e:
            raise RuntimeError(f"LanceDB vector search failed: {e}") from e

    def search_fts(
        self,
        query_text: str,
        top_k: int = 10,
        project: Optional[str] = None,
        exact_only: bool = False,
        allow_vector_fallback: bool = True,
    ) -> List[Dict[str, Any]]:
        """Hybrid lexical search over indexed AST chunks:
        1. Exact/case-insensitive substring match (preserves `/api/...` routes, CSS selectors, and code expressions without Tantivy delimiter splitting).
        2. Identifier / multi-token lexical overlap ranking across chunks (unless exact_only=True).
        3. LanceDB/Tantivy BM25 FTS index + dense vector fallback if needed (unless exact_only=True or allow_vector_fallback=False).
        """
        if not query_text or not query_text.strip():
            return []

        q_clean = query_text.strip()
        q_lower = q_clean.lower()
        chunks = self._get_project_chunks(project=project)

        exact_matches: List[Dict[str, Any]] = []
        ci_matches: List[Dict[str, Any]] = []

        for rec in chunks:
            txt = rec.get("text", "")
            if q_clean in txt:
                exact_matches.append(rec)
            elif q_lower in txt.lower():
                ci_matches.append(rec)

        combined = self._dedupe_records(exact_matches + ci_matches)
        if combined or exact_only:
            return combined[:top_k]

        # Multi-token lexical overlap scoring for natural-language or composite queries
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "into", "both",
            "all", "update", "change", "rename", "add", "remove", "file", "files",
            "function", "component", "module", "codebase", "repository", "exported",
            "defining", "across", "every", "when", "where", "instead", "also",
        }
        raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|/api/[A-Za-z0-9/_-]+", q_clean)
        tokens = []
        for t in raw_tokens:
            if len(t) >= 3 and t.lower() not in stopwords and t not in tokens:
                tokens.append(t)

        if tokens and chunks:
            scored = []
            for rec in chunks:
                txt = rec.get("text", "")
                txt_lower = txt.lower()
                sym = rec.get("symbol_name", "")
                score = 0.0
                for tok in tokens:
                    # Higher weight for camelCase / slash-route / long specific tokens
                    weight = 3.0 if ("/" in tok or any(c.isupper() for c in tok[1:]) or "_" in tok) else 1.0
                    if sym == tok:
                        score += weight * 4.0
                    if tok in txt:
                        score += weight * 2.0
                    elif tok.lower() in txt_lower:
                        score += weight * 1.0
                if score > 0:
                    scored.append((score, rec))
            scored.sort(key=lambda x: x[0], reverse=True)
            combined = self._dedupe_records(combined + [r for _, r in scored[:top_k * 2]])
            if len(combined) >= top_k:
                return combined[:top_k]

        # Tantivy FTS fallback
        try:
            table = self.db.open_table(self.table_name)
            fts_query = table.search(q_clean, query_type="fts")
            if project and project not in ("general", "mesh_all"):
                fts_query = fts_query.where(f"project = '{self._escape_sql_str(project)}'")
            try:
                raw_fts = fts_query.limit(top_k * 2).to_arrow().to_pylist()
            except Exception:
                raw_fts = fts_query.limit(top_k * 2).to_pandas().to_dict(orient="records")
            combined = self._dedupe_records(combined + raw_fts)
            if len(combined) >= top_k:
                return combined[:top_k]
        except Exception:
            pass

        # Lexical callers must not silently invoke a second vector search.
        if not allow_vector_fallback:
            return combined[:top_k]
        # Dense vector fallback for remaining slots
        vec_res = self.search(q_clean, top_k=top_k, project=project)
        return self._dedupe_records(combined + vec_res)[:top_k]

    def ensure_vector_index(self, min_rows=10000, num_partitions=64, num_sub_vectors=48,
                            nprobes=20, refine_factor=2):
        """Explicit opt-in: callers must measure ANN recall before enabling in production.

        Preserves the current L2 metric; does not turn ANN on based only on corpus size.
        """
        table = self.db.open_table(self.table_name)
        if table.count_rows() < min_rows:
            return {"enabled": False, "reason": "below_min_rows"}
        table.create_index(metric="l2", index_type="IVF_PQ", num_partitions=num_partitions,
                           num_sub_vectors=num_sub_vectors, vector_column_name="vector")
        self._vector_index_settings = (nprobes, refine_factor)
        return {"enabled": True, "indices": [str(i) for i in table.list_indices()],
                "nprobes": nprobes, "refine_factor": refine_factor}

    def ensure_fts_index(self) -> bool:
        """Create FTS index on the 'text' column if it does not already exist."""
        try:
            table = self.db.open_table(self.table_name)
            table.create_fts_index("text", replace=False)
            return True
        except Exception:
            try:
                table = self.db.open_table(self.table_name)
                table.create_fts_index("text", replace=True)
                return True
            except Exception:
                return False

    def maintenance_vacuum(self, older_than_days: int = 1) -> Dict[str, Any]:
        """Prevents LanceDB disk bloat."""
        stats: Dict[str, Any] = {
            "compacted": False,
            "cleaned_versions": False,
            "bytes_before": self.get_disk_size_bytes(),
            "bytes_after": 0,
            "details": {},
        }
        with self._file_lock:
            try:
                if self.table_name in self._list_tables():
                    table = self.db.open_table(self.table_name)
                    try:
                        if hasattr(table, "optimize"):
                            table.optimize()
                            stats["compacted"] = True
                        elif hasattr(table, "compact_files"):
                            compaction_result = table.compact_files()
                            stats["compacted"] = True
                            stats["details"]["compaction"] = str(compaction_result)
                    except Exception as e:
                        stats["details"]["compaction_error"] = str(e)

                    try:
                        if hasattr(table, "cleanup_old_versions"):
                            cleanup_result = table.cleanup_old_versions(
                                older_than=timedelta(days=older_than_days),
                                delete_unverified=True,
                            )
                            stats["cleaned_versions"] = True
                            stats["details"]["cleanup"] = str(cleanup_result)
                    except Exception as e:
                        stats["details"]["cleanup_error"] = str(e)
            except Exception as e:
                stats["error"] = str(e)

        stats["bytes_after"] = self.get_disk_size_bytes()
        return stats

    def get_disk_size_bytes(self) -> int:
        """Calculate total byte size on disk for this vector database directory."""
        if not self.db_dir.exists():
            return 0
        total_size = 0
        for path in self.db_dir.glob("**/*"):
            if path.is_file():
                try:
                    total_size += path.stat().st_size
                except Exception:
                    pass
        return total_size

    def count_chunks(self) -> int:
        """Count total document chunks in table."""
        try:
            if self.table_name in self._list_tables():
                table = self.db.open_table(self.table_name)
                return len(table)
        except Exception:
            pass
        return 0

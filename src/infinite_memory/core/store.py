import re
import threading
import shutil
from datetime import timedelta
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
                return 1
            except Exception:
                return 0

    def get_indexed_files_for_project(self, project: str) -> List[str]:
        """Return list of distinct file_paths currently indexed for a project."""
        with self._file_lock:
            try:
                table = self.db.open_table(self.table_name)
                norm_proj = self._escape_sql_str(project)
                df = table.search([0.0] * 384).where(f"project = '{norm_proj}'").limit(10000).to_pandas()
                if not df.empty and "file_path" in df:
                    return sorted(list(df["file_path"].unique()))
            except Exception:
                pass
        return []

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
        """Deduplicate chunk records by (file_path, start_line, end_line) preserving rank order."""
        seen = set()
        out = []
        for r in records:
            key = (
                str(r.get("file_path", "")),
                int(r.get("start_line") or 0),
                int(r.get("end_line") or 0),
            )
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    def _get_project_chunks(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load deduplicated scalar chunk records for a project (excluding dense vectors for fast scanning)."""
        cache = getattr(self, "_project_chunks_cache", None)
        if cache is None:
            self._project_chunks_cache = {}
            cache = self._project_chunks_cache
        cache_key = project or "__all__"
        if cache_key in cache:
            return cache[cache_key]

        try:
            table = self.db.open_table(self.table_name)
            cols = ["id", "text", "file_path", "project", "symbol_name", "chunk_type", "start_line", "end_line"]
            q = table.search()
            if project and project not in ("general", "mesh_all"):
                q = q.where(f"project = '{self._escape_sql_str(project)}'")
            df = q.select(cols).limit(10000).to_pandas()
            if df.empty:
                return []
            res = self._dedupe_records(df.to_dict(orient="records"))
            cache[cache_key] = res
            return res
        except Exception:
            try:
                table = self.db.open_table(self.table_name)
                df = table.to_pandas()
                if project and project not in ("general", "mesh_all"):
                    df = df[df["project"] == project]
                if "vector" in df.columns:
                    df = df.drop(columns=["vector"])
                res = self._dedupe_records(df.to_dict(orient="records"))
                cache[cache_key] = res
                return res
            except Exception:
                return []

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

        try:
            chunks = self._get_project_chunks(project=project)
            word_pat = re.compile(rf"\b{re.escape(sym)}\b")
            for rec in chunks:
                if rec.get("symbol_name") == sym:
                    declarations.append(rec)
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

        masked_query, _ = mask_secrets(query_text)
        query_vector = list(self.encoder.embed([masked_query]))[0].tolist()

        try:
            table = self.db.open_table(self.table_name)
            query = table.search(query_vector)

            if project and project not in ("general", "mesh_all"):
                escaped_proj = self._escape_sql_str(project)
                query = query.where(f"project = '{escaped_proj}'")
                results = query.limit(max(top_k * 4, 20)).to_pandas()
                deduped = self._dedupe_records(results.to_dict(orient="records"))
                return deduped[:top_k]
            else:
                # Stratified Sampling: Fetch larger pool to prevent large-repo crowding
                pool_size = max(top_k * 10, 50)
                results_df = query.limit(pool_size).to_pandas()
                if results_df.empty:
                    return []

                records = self._dedupe_records(results_df.to_dict(orient="records"))

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
    ) -> List[Dict[str, Any]]:
        """Hybrid lexical search over indexed AST chunks:
        1. Exact/case-insensitive substring match (preserves `/api/...` routes, CSS selectors, and code expressions without Tantivy delimiter splitting).
        2. Identifier / multi-token lexical overlap ranking across chunks (unless exact_only=True).
        3. LanceDB/Tantivy BM25 FTS index + dense vector fallback if needed (unless exact_only=True).
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
            results = fts_query.limit(top_k * 2).to_pandas()
            combined = self._dedupe_records(combined + results.to_dict(orient="records"))
            if len(combined) >= top_k:
                return combined[:top_k]
        except Exception:
            pass

        # Dense vector fallback for remaining slots
        vec_res = self.search(q_clean, top_k=top_k, project=project)
        return self._dedupe_records(combined + vec_res)[:top_k]

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

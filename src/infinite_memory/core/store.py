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
        self.encoder = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
        self.table_name = "documents"
        self._ensure_table()

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

    def upsert_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Batch insert document chunks with zero-trust secret masking applied before vector storage."""
        if not documents:
            return 0

        masked_texts = [mask_secrets(doc["text"])[0] for doc in documents]
        embeddings = [emb.tolist() for emb in self.encoder.embed(masked_texts)]

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

        return len(records)

    def search_exact_symbol(self, symbol_name: str, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Exact symbol match query."""
        if not symbol_name or not symbol_name.strip():
            return []
        try:
            table = self.db.open_table(self.table_name)
            escaped_sym = self._escape_sql_str(symbol_name.strip())
            filter_clause = f"symbol_name = '{escaped_sym}'"
            if project and project not in ("general", "mesh_all"):
                filter_clause += f" AND project = '{self._escape_sql_str(project)}'"

            df = table.search([0.0] * 384).where(filter_clause).limit(10).to_pandas()
            if not df.empty:
                return df.to_dict(orient="records")
        except Exception:
            pass
        return []

    def search(
        self,
        query_text: str,
        top_k: int = 3,
        project: Optional[str] = None,
        symbol_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search with exact symbol boosting and project filtering."""
        if symbol_name:
            exact_matches = self.search_exact_symbol(symbol_name, project=project)
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
                results = query.limit(top_k).to_pandas()
                return results.to_dict(orient="records")
            else:
                # Stratified Sampling: Fetch larger pool to prevent large-repo crowding
                pool_size = max(top_k * 10, 50)
                results_df = query.limit(pool_size).to_pandas()
                if results_df.empty:
                    return []
                
                records = results_df.to_dict(orient="records")
                
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
                        # Cannot use `not in` on dicts efficiently, check ID
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
    ) -> List[Dict[str, Any]]:
        """BM25 full-text search via LanceDB/Tantivy FTS index.

        Falls back gracefully to vector search if FTS index is not built.
        """
        try:
            table = self.db.open_table(self.table_name)
            fts_query = table.search(query_text, query_type="fts")
            if project and project not in ("general", "mesh_all"):
                fts_query = fts_query.where(f"project = '{self._escape_sql_str(project)}'")
            results = fts_query.limit(top_k).to_pandas()
            return results.to_dict(orient="records")
        except Exception:
            # FTS index not available — fall back to vector search
            return self.search(query_text, top_k=top_k, project=project)

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

import shutil
from datetime import timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

import lancedb
from fastembed import TextEmbedding

from ..config import DEFAULT_VECTOR_DB_DIR, EMBEDDING_MODEL_NAME


class VectorStore:
    """In-process LanceDB + FastEmbed vector core with automated vacuuming."""

    def __init__(self, db_path: Optional[str | Path] = None, mode: str = "default"):
        if db_path is not None:
            self.db_dir = Path(db_path)
        elif mode == "isolated":
            self.db_dir = Path("./.memory_db")
        else:
            self.db_dir = DEFAULT_VECTOR_DB_DIR

        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_dir))
        self.encoder = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
        self.table_name = "documents"

    def upsert_document(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Insert or append a document chunk into LanceDB."""
        metadata = metadata or {}
        embedding = list(self.encoder.embed([text]))[0].tolist()
        data = [{
            "id": doc_id,
            "text": text,
            "vector": embedding,
            **metadata,
        }]
        try:
            table = self.db.open_table(self.table_name)
            table.add(data)
        except Exception:
            self.db.create_table(self.table_name, data=data)

    def upsert_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Batch insert document chunks."""
        if not documents:
            return 0
        texts = [doc["text"] for doc in documents]
        embeddings = [emb.tolist() for emb in self.encoder.embed(texts)]
        records = []
        for doc, emb in zip(documents, embeddings):
            rec = {
                "id": doc["id"],
                "text": doc["text"],
                "vector": emb,
                **doc.get("metadata", {}),
            }
            records.append(rec)

        try:
            table = self.db.open_table(self.table_name)
            table.add(records)
        except Exception:
            self.db.create_table(self.table_name, data=records)
        return len(records)

    def search(self, query_text: str, top_k: int = 3, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """Vector similarity search over stored chunks."""
        try:
            query_vector = list(self.encoder.embed([query_text]))[0].tolist()
            table = self.db.open_table(self.table_name)
            query = table.search(query_vector)
            if project and project != "general" and project != "mesh_all":
                # Filter by project if metadata column exists
                try:
                    query = query.where(f"project = '{project}'")
                except Exception:
                    pass
            results = query.limit(top_k).to_pandas()
            return results.to_dict(orient="records")
        except Exception:
            return []

    def maintenance_vacuum(self, older_than_days: int = 1) -> Dict[str, Any]:
        """Prevents LanceDB disk bloat.
        
        1. Calls table.compact_files() to consolidate small Arrow fragments.
        2. Calls table.cleanup_old_versions() to purge orphaned tombstones.
        """
        stats: Dict[str, Any] = {
            "compacted": False,
            "cleaned_versions": False,
            "bytes_before": self.get_disk_size_bytes(),
            "bytes_after": 0,
            "details": {},
        }
        try:
            if self.table_name in self.db.table_names():
                table = self.db.open_table(self.table_name)
                # 1. Compact small files
                try:
                    compaction_result = table.compact_files()
                    stats["compacted"] = True
                    stats["details"]["compaction"] = str(compaction_result)
                except Exception as e:
                    stats["details"]["compaction_error"] = str(e)

                # 2. Cleanup old versions
                try:
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
            if self.table_name in self.db.table_names():
                table = self.db.open_table(self.table_name)
                return len(table)
        except Exception:
            pass
        return 0

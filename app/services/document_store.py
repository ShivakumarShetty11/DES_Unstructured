import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import DocumentMetadata

# Columns returned in list/search (no heavy extracted_text blob)
_LIST_COLS = """
    dataset_id, title, category, sub_category, document_type,
    tags_json, issuing_department, policy_year, summary, document_url,
    source_language, file_name, extracted_text_chars, created_at
"""


class DocumentStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS documents (
                    dataset_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT,
                    sub_category TEXT,
                    document_type TEXT,
                    tags_json TEXT,
                    issuing_department TEXT,
                    policy_year TEXT,
                    summary TEXT,
                    document_url TEXT,
                    source_language TEXT,
                    file_name TEXT,
                    extracted_text TEXT,
                    extracted_text_chars INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Migrate existing DBs that predate the extracted_text column.
            try:
                conn.execute("ALTER TABLE documents ADD COLUMN extracted_text TEXT")
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()

    def create_document(
        self,
        metadata: DocumentMetadata,
        file_name: str | None,
        extracted_text: str,
    ) -> dict[str, Any]:
        dataset_id = f"DOC-{uuid.uuid4().hex[:10].upper()}"
        created_at = datetime.now(timezone.utc).isoformat()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO documents (
                    dataset_id, title, category, sub_category, document_type,
                    tags_json, issuing_department, policy_year, summary,
                    document_url, source_language, file_name,
                    extracted_text, extracted_text_chars, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    metadata.title,
                    metadata.category,
                    metadata.sub_category,
                    metadata.document_type,
                    json.dumps(metadata.tags),
                    metadata.issuing_department,
                    metadata.policy_year,
                    metadata.summary,
                    metadata.document_url,
                    metadata.source_language,
                    file_name,
                    extracted_text,
                    len(extracted_text),
                    created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return self.get_document(dataset_id)  # returns full record with extracted_text

    def get_document(self, dataset_id: str) -> dict[str, Any] | None:
        """Return full record including extracted_text (used by download)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return self._row_to_dict(row, include_text=True)

    def list_documents(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return lightweight records without extracted_text for list views."""
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT {_LIST_COLS} FROM documents ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_dict(row, include_text=False) for row in rows]

    def search_documents(
        self,
        query: str,
        category: str | None = None,
        sub_category: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.list_documents(limit=2000)

        if category:
            rows = [r for r in rows if (r.get("category") or "").lower() == category.lower()]
        if sub_category:
            rows = [r for r in rows if (r.get("sub_category") or "").lower() == sub_category.lower()]

        q = (query or "").strip().lower()
        if not q:
            return rows[:limit]

        def score(row: dict[str, Any]) -> int:
            text_tags = " ".join(row.get("tags") or []).lower()
            cat     = (row.get("category") or "").lower()
            sub_cat = (row.get("sub_category") or "").lower()
            title   = (row.get("title") or "").lower()
            summary = (row.get("summary") or "").lower()
            doc_type = (row.get("document_type") or "").lower()
            dept    = (row.get("issuing_department") or "").lower()

            total = 0
            if q in cat:      total += 8
            if q in sub_cat:  total += 7
            if q in title:    total += 6
            if q in text_tags: total += 5
            if q in doc_type: total += 3
            if q in dept:     total += 2
            if q in summary:  total += 1
            return total

        ranked = [(row, score(row)) for row in rows]
        ranked = [pair for pair in ranked if pair[1] > 0]
        ranked.sort(key=lambda item: (item[1], item[0]["created_at"]), reverse=True)
        return [item[0] for item in ranked[:limit]]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, include_text: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "dataset_id":           row["dataset_id"],
            "title":                row["title"],
            "category":             row["category"],
            "sub_category":         row["sub_category"],
            "document_type":        row["document_type"],
            "tags":                 json.loads(row["tags_json"] or "[]"),
            "issuing_department":   row["issuing_department"],
            "policy_year":          row["policy_year"],
            "summary":              row["summary"],
            "document_url":         row["document_url"],
            "source_language":      row["source_language"],
            "file_name":            row["file_name"],
            "extracted_text_chars": row["extracted_text_chars"],
            "created_at":           row["created_at"],
        }
        if include_text:
            # extracted_text may not exist in old rows
            try:
                d["extracted_text"] = row["extracted_text"]
            except IndexError:
                d["extracted_text"] = None
        return d

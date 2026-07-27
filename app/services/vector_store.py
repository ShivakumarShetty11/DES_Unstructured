from collections import defaultdict
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection


class VectorStore:
    def __init__(self, persist_directory: str, collection_name: str):
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection: Collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(
        self,
        dataset_id: str,
        chunks: list[str],
        metadata: dict[str, Any],
    ) -> None:
        if not chunks:
            return

        metadatas = []
        ids = []
        docs = []
        for idx, chunk in enumerate(chunks):
            cid = f"{dataset_id}-chunk-{idx + 1}"
            ids.append(cid)
            docs.append(chunk)
            metadatas.append(
                {
                    "dataset_id": dataset_id,
                    "chunk_index": idx + 1,
                    "title": str(metadata.get("title") or ""),
                    "category": str(metadata.get("category") or ""),
                    "sub_category": str(metadata.get("sub_category") or ""),
                    "document_type": str(metadata.get("document_type") or ""),
                    "source_language": str(metadata.get("source_language") or ""),
                }
            )

        self._collection.upsert(ids=ids, documents=docs, metadatas=metadatas)

    def semantic_search(
        self,
        query: str,
        limit: int = 8,
        category: str | None = None,
        sub_category: str | None = None,
    ) -> list[dict[str, Any]]:
        where = None
        if category and sub_category:
            where = {
                "$and": [
                    {"category": {"$eq": category}},
                    {"sub_category": {"$eq": sub_category}},
                ]
            }
        elif category:
            where = {"category": {"$eq": category}}
        elif sub_category:
            where = {"sub_category": {"$eq": sub_category}}

        result = self._collection.query(
            query_texts=[query],
            n_results=limit,
            where=where,
        )

        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        grouped: dict[str, dict[str, Any]] = defaultdict(dict)
        for cid, doc, meta, distance in zip(ids, docs, metas, distances):
            dataset_id = meta.get("dataset_id") if isinstance(meta, dict) else None
            if not dataset_id:
                continue
            score = 1.0 - float(distance)
            current = grouped.get(dataset_id)
            candidate = {
                "chunk_id": cid,
                "chunk": doc,
                "score": score,
                "metadata": meta,
            }
            if not current or score > current.get("score", -1):
                grouped[dataset_id] = candidate

        output = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)
        return output[:limit]

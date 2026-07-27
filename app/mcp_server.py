from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="Dhara Toolkit",
    instructions=(
        "Unstructured PDF document catalogue. "
        "Use list_datasets to browse, search_datasets for keyword search, "
        "semantic_search_datasets for topic-based search, and get_dataset to read full content."
    ),
)

# Injected during app startup via init_stores()
_doc_store = None
_vec_store = None


def init_stores(doc_store: Any, vec_store: Any) -> None:
    global _doc_store, _vec_store
    _doc_store = doc_store
    _vec_store = vec_store


def _strip_text(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "extracted_text"}


@mcp.tool()
def list_datasets(limit: int = 50) -> dict:
    """List all ingested PDF documents. Returns metadata only — no extracted text.
    Use get_dataset or get_dataset_text to fetch full content."""
    docs = _doc_store.list_documents(limit=min(limit, 500))
    return {"count": len(docs), "datasets": docs}


@mcp.tool()
def get_dataset(dataset_id: str) -> dict:
    """Get the complete record for a document by its dataset_id,
    including all metadata AND the full extracted_text."""
    doc = _doc_store.get_document(dataset_id)
    if not doc:
        return {"error": f"Dataset not found: {dataset_id}"}
    return doc


@mcp.tool()
def get_dataset_text(dataset_id: str) -> str:
    """Return only the extracted_text of a document.
    Use when you already have metadata and just need the raw text content."""
    doc = _doc_store.get_document(dataset_id)
    if not doc:
        return f"Dataset not found: {dataset_id}"
    return doc.get("extracted_text") or ""


@mcp.tool()
def search_datasets(
    query: str,
    category: str | None = None,
    sub_category: str | None = None,
    limit: int = 20,
) -> dict:
    """Keyword search across all documents. Category and sub_category matches are
    weighted highest. Returns metadata only (no extracted_text)."""
    docs = _doc_store.search_documents(
        query=query,
        category=category,
        sub_category=sub_category,
        limit=min(limit, 100),
    )
    return {"count": len(docs), "datasets": docs}


@mcp.tool()
def semantic_search_datasets(
    query: str,
    category: str | None = None,
    sub_category: str | None = None,
    limit: int = 8,
) -> dict:
    """Vector similarity search over extracted text. Returns the most semantically
    relevant text chunks with matching document metadata."""
    matches = _vec_store.semantic_search(
        query=query,
        category=category,
        sub_category=sub_category,
        limit=min(limit, 50),
    )
    results = []
    for match in matches:
        dataset_id = match["metadata"].get("dataset_id")
        doc = _doc_store.get_document(dataset_id) if dataset_id else None
        results.append({
            "dataset_id": dataset_id,
            "score": match["score"],
            "chunk": match["chunk"],
            "metadata": _strip_text(doc) if doc else {},
        })
    return {"count": len(results), "results": results}

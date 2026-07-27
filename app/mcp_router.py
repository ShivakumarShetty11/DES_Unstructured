import json
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(data: Any) -> dict[str, Any]:
    """Wrap a value as an MCP text content block."""
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}]}


def _strip_text(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a document record without the heavy extracted_text field."""
    return {k: v for k, v in doc.items() if k != "extracted_text"}


# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "list_datasets",
        "description": (
            "List all PDF documents in the Dhara Toolkit catalogue. "
            "Returns metadata for each document (title, category, sub_category, "
            "document_type, tags, summary, policy_year, etc.) but NOT the full "
            "extracted text. Use get_dataset or get_dataset_text to retrieve full content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 50, max 500).",
                    "minimum": 1,
                    "maximum": 500,
                },
            },
        },
    },
    {
        "name": "get_dataset",
        "description": (
            "Get the complete record for a single document by its dataset_id, "
            "including all metadata fields AND the full extracted_text (the entire "
            "text content pulled from the PDF). Use this when you need to read the "
            "document's content."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["dataset_id"],
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The dataset_id of the document, e.g. DOC-9866FBEBE9.",
                },
            },
        },
    },
    {
        "name": "get_dataset_text",
        "description": (
            "Return only the full extracted_text of a document (no other metadata). "
            "Use this when you already have the metadata and only need the raw text content."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["dataset_id"],
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "The dataset_id of the document.",
                },
            },
        },
    },
    {
        "name": "search_datasets",
        "description": (
            "Keyword search across all documents. Category and sub_category matches "
            "are weighted highest. Returns metadata (no extracted_text). "
            "Optionally filter by category or sub_category."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query":        {"type": "string", "description": "Search keywords."},
                "category":     {"type": "string", "description": "Filter to this category."},
                "sub_category": {"type": "string", "description": "Filter to this sub-category."},
                "limit":        {"type": "integer", "minimum": 1, "maximum": 100, "description": "Max results (default 20)."},
            },
        },
    },
    {
        "name": "semantic_search_datasets",
        "description": (
            "Vector similarity search over the extracted text of all documents. "
            "Returns the most semantically relevant text chunks with their scores "
            "and the matching document's metadata (without extracted_text). "
            "Use this to find documents that discuss a topic even when exact keywords differ."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query":        {"type": "string", "description": "Natural language query."},
                "category":     {"type": "string", "description": "Filter to this category."},
                "sub_category": {"type": "string", "description": "Filter to this sub-category."},
                "limit":        {"type": "integer", "minimum": 1, "maximum": 50, "description": "Max results (default 8)."},
            },
        },
    },
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def mcp_info() -> dict[str, Any]:
    return {
        "name": "Dhara Toolkit — Unstructured Data MCP",
        "transport": "JSON-RPC over HTTP",
        "endpoint": "POST /mcp",
        "protocol_version": "2024-11-05",
        "methods": ["initialize", "tools/list", "tools/call"],
        "tools": [t["name"] for t in _TOOLS],
        "notes": {
            "list_datasets":          "metadata only — no extracted_text",
            "get_dataset":            "full record including extracted_text",
            "get_dataset_text":       "extracted_text only",
            "search_datasets":        "keyword search — metadata only",
            "semantic_search_datasets": "vector search — chunk + metadata (no extracted_text)",
        },
    }


@router.post("/")
async def mcp_handler(request: Request) -> dict[str, Any]:
    payload = await request.json()
    method = payload.get("method")
    params = payload.get("params") or {}
    rid = payload.get("id")

    store = request.app.state.document_store
    vector_store = request.app.state.vector_store

    try:
        # ── initialize ────────────────────────────────────────────────────────
        if method == "initialize":
            return _ok(rid, {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "dhara-toolkit-mcp", "version": "2.0.0"},
                "capabilities": {"tools": {}},
            })

        # ── tools/list ────────────────────────────────────────────────────────
        if method == "tools/list":
            return _ok(rid, {"tools": _TOOLS})

        # ── tools/call ────────────────────────────────────────────────────────
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}

            # list_datasets
            if name == "list_datasets":
                limit = min(int(args.get("limit", 50)), 500)
                docs = store.list_documents(limit=limit)
                return _ok(rid, _text({"count": len(docs), "datasets": docs}))

            # get_dataset — full record including extracted_text
            if name == "get_dataset":
                dataset_id = str(args.get("dataset_id", "")).strip()
                if not dataset_id:
                    return _err(rid, -32602, "dataset_id is required")
                doc = store.get_document(dataset_id)
                if not doc:
                    return _ok(rid, {"content": [{"type": "text", "text": f"Dataset not found: {dataset_id}"}], "isError": True})
                return _ok(rid, _text(doc))

            # get_dataset_text — extracted_text only
            if name == "get_dataset_text":
                dataset_id = str(args.get("dataset_id", "")).strip()
                if not dataset_id:
                    return _err(rid, -32602, "dataset_id is required")
                doc = store.get_document(dataset_id)
                if not doc:
                    return _ok(rid, {"content": [{"type": "text", "text": f"Dataset not found: {dataset_id}"}], "isError": True})
                text = doc.get("extracted_text") or ""
                return _ok(rid, {"content": [{"type": "text", "text": text}]})

            # search_datasets — metadata only
            if name == "search_datasets":
                query       = str(args.get("query", "")).strip()
                category    = args.get("category")
                sub_category = args.get("sub_category")
                limit       = min(int(args.get("limit", 20)), 100)
                docs = store.search_documents(query=query, category=category, sub_category=sub_category, limit=limit)
                return _ok(rid, _text({"count": len(docs), "datasets": docs}))

            # semantic_search_datasets — chunks + metadata (no extracted_text)
            if name == "semantic_search_datasets":
                query       = str(args.get("query", "")).strip()
                category    = args.get("category")
                sub_category = args.get("sub_category")
                limit       = min(int(args.get("limit", 8)), 50)
                matches = vector_store.semantic_search(
                    query=query, category=category, sub_category=sub_category, limit=limit
                )
                enriched = []
                for match in matches:
                    dataset_id = match["metadata"].get("dataset_id")
                    doc = store.get_document(dataset_id) if dataset_id else None
                    enriched.append({
                        "dataset_id": dataset_id,
                        "score":  match["score"],
                        "chunk":  match["chunk"],
                        "metadata": _strip_text(doc) if doc else {},
                    })
                return _ok(rid, _text({"count": len(enriched), "results": enriched}))

            return _err(rid, -32601, f"Unknown tool: {name}")

        return _err(rid, -32601, f"Method not found: {method}")

    except Exception as exc:
        return _err(rid, -32603, f"Internal MCP error: {exc}")

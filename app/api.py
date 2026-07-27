import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from app.models import DocumentMetadata, PushRequest, SemanticSearchRequest
from app.services.pdf_service import chunk_text

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
async def api_index(request: Request) -> dict[str, Any]:
    base = f"{request.url.scheme}://{request.headers.get('host')}"
    return {
        "name": "Dhara Toolkit — Unstructured Data API",
        "endpoints": {
            "extract":        {"method": "POST", "url": f"{base}/api/datasets/extract"},
            "push":           {"method": "POST", "url": f"{base}/api/datasets/push"},
            "list_datasets":  {"method": "GET",  "url": f"{base}/api/datasets"},
            "get_dataset":    {"method": "GET",  "url": f"{base}/api/datasets/:dataset_id"},
            "download":       {"method": "GET",  "url": f"{base}/api/datasets/:dataset_id/download"},
            "semantic_search":{"method": "POST", "url": f"{base}/api/datasets/semantic-search"},
            "mcp":            {"method": "POST", "url": f"{base}/mcp"},
        },
    }


# ── Step 1: Extract only (no storage) ────────────────────────────────────────

@router.post("/datasets/extract")
async def extract_dataset(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    sub_category: str = Form(...),
    document_type: str = Form(...),
    tags: str = Form("[]"),
    issuing_department: str | None = Form(None),
    policy_year: str | None = Form(None),
    document_url: str | None = Form(None),
    source_language: str | None = Form(None),
    file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    """Extract text and generate AI summary. Nothing is stored — returns a preview."""
    pdf_service = request.app.state.pdf_service
    summary_service = request.app.state.summary_service

    try:
        tags_list = json.loads(tags) if tags else []
        if not isinstance(tags_list, list):
            raise ValueError("tags must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tags JSON: {exc}")

    if file is None and not document_url:
        raise HTTPException(status_code=400, detail="Either file upload or document_url is required")

    file_name: str | None = None
    try:
        if file is not None:
            file_bytes = await file.read()
            if not file.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only .pdf files are supported")
            file_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        else:
            file_bytes = pdf_service.download_pdf(document_url)
            url_stem = Path(document_url.rstrip("/").split("/")[-1]).stem or "document"
            file_name = f"{uuid.uuid4().hex[:8]}_{url_stem}.pdf"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read PDF: {exc}")

    uploads_dir = Path(request.app.state.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / file_name).write_bytes(file_bytes)

    extracted_text = pdf_service.extract_text_from_bytes(file_bytes)
    if not extracted_text:
        raise HTTPException(
            status_code=422,
            detail=(
                "No text could be extracted from this PDF. "
                "The file may be a scanned image (no text layer), password-protected, "
                "or use an unsupported encoding. Check the server log for details."
            ),
        )

    summary = summary_service.generate_summary(title=title, text=extracted_text)
    estimated_chunks = len(chunk_text(extracted_text))

    return {
        # metadata fields — client sends these back unchanged on push
        "title":               title,
        "category":            category,
        "sub_category":        sub_category,
        "document_type":       document_type,
        "tags":                tags_list,
        "issuing_department":  issuing_department,
        "policy_year":         policy_year,
        "document_url":        document_url,
        "source_language":     source_language,
        "file_name":           file_name,
        # extraction results
        "extracted_text":      extracted_text,
        "extracted_text_chars": len(extracted_text),
        "text_preview":        extracted_text[:2000],
        "summary":             summary,
        "estimated_chunks":    estimated_chunks,
    }


# ── Step 2: Push to catalogue (store in SQLite + vector DB) ──────────────────

@router.post("/datasets/push")
async def push_dataset(request: Request, payload: PushRequest) -> dict[str, Any]:
    """Store a previously extracted document in SQLite and the vector DB."""
    vector_store = request.app.state.vector_store
    document_store = request.app.state.document_store

    try:
        metadata = DocumentMetadata(
            title=payload.title,
            category=payload.category,
            sub_category=payload.sub_category,
            document_type=payload.document_type,
            tags=payload.tags,
            issuing_department=payload.issuing_department,
            policy_year=payload.policy_year,
            document_url=payload.document_url,
            source_language=payload.source_language,
            summary=payload.summary,
        )
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(status_code=422, detail=errors)

    record = document_store.create_document(
        metadata=metadata,
        file_name=payload.file_name,
        extracted_text=payload.extracted_text,
    )

    chunks = chunk_text(payload.extracted_text)
    vector_store.add_chunks(
        dataset_id=record["dataset_id"],
        chunks=chunks,
        metadata=record,
    )

    return {
        "message": "Document pushed to catalogue successfully",
        "dataset": record,
        "vector_chunks": len(chunks),
    }


# ── List / search ─────────────────────────────────────────────────────────────

@router.get("/datasets")
async def list_datasets(
    request: Request,
    q: str = "",
    category: str | None = None,
    sub_category: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    store = request.app.state.document_store
    if q or category or sub_category:
        rows = store.search_documents(query=q, category=category, sub_category=sub_category, limit=limit)
    else:
        rows = store.list_documents(limit=limit)

    all_docs = store.list_documents(limit=5000)
    categories = sorted({r.get("category") for r in all_docs if r.get("category")})

    # Build a map of category → sorted sub-categories (for hierarchical filtering)
    cat_map: dict[str, list[str]] = {}
    for r in all_docs:
        cat = r.get("category")
        sub = r.get("sub_category")
        if cat and sub:
            cat_map.setdefault(cat, set()).add(sub)  # type: ignore[arg-type]
    category_map = {cat: sorted(subs) for cat, subs in sorted(cat_map.items())}

    # All sub-categories (used when no category filter is active)
    sub_categories = sorted({r.get("sub_category") for r in all_docs if r.get("sub_category")})

    return {
        "count": len(rows),
        "datasets": rows,
        "filters": {
            "categories": categories,
            "sub_categories": sub_categories,
            "category_map": category_map,
        },
    }


@router.get("/datasets/{dataset_id}")
async def get_dataset(request: Request, dataset_id: str) -> dict[str, Any]:
    store = request.app.state.document_store
    doc = store.get_document(dataset_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return doc


@router.get("/datasets/{dataset_id}/download")
async def download_dataset(request: Request, dataset_id: str) -> JSONResponse:
    """Returns full JSON including extracted_text as a file download."""
    store = request.app.state.document_store
    doc = store.get_document(dataset_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    response = JSONResponse(content=doc)
    response.headers["Content-Disposition"] = f'attachment; filename="{dataset_id}.json"'
    return response


@router.get("/datasets/{dataset_id}/document")
async def download_document(request: Request, dataset_id: str) -> FileResponse:
    """Serve the original uploaded PDF file."""
    store = request.app.state.document_store
    doc = store.get_document(dataset_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    file_name = doc.get("file_name")
    if not file_name:
        raise HTTPException(status_code=404, detail="No PDF file stored for this document")

    file_path = Path(request.app.state.uploads_dir) / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on server")

    return FileResponse(str(file_path), media_type="application/pdf", filename=file_name)


# ── Semantic search ───────────────────────────────────────────────────────────

@router.post("/datasets/semantic-search")
async def semantic_search(request: Request, payload: SemanticSearchRequest) -> dict[str, Any]:
    vector_store = request.app.state.vector_store
    store = request.app.state.document_store

    rows = vector_store.semantic_search(
        query=payload.query,
        limit=payload.limit,
        category=payload.category,
        sub_category=payload.sub_category,
    )

    results: list[dict[str, Any]] = []
    for row in rows:
        dataset_id = row["metadata"].get("dataset_id")
        doc = store.get_document(dataset_id) if dataset_id else None
        if not doc:
            continue
        results.append({
            "dataset_id": dataset_id,
            "title":      doc.get("title"),
            "category":   doc.get("category"),
            "sub_category": doc.get("sub_category"),
            "score":      round(float(row["score"]), 4),
            "chunk":      row["chunk"],
            "metadata":   doc,
        })

    return {"count": len(results), "results": results}

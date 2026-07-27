from typing import Any
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    title: str = Field(..., min_length=1)
    category: str
    sub_category: str
    document_type: str
    tags: list[str] = Field(default_factory=list)
    issuing_department: str | None = None
    policy_year: str | None = None
    summary: str | None = None
    document_url: str | None = None
    source_language: str | None = None


class PushRequest(BaseModel):
    """Payload sent from the browser after the user approves the extraction preview."""
    title: str
    category: str
    sub_category: str
    document_type: str
    tags: list[str] = Field(default_factory=list)
    issuing_department: str | None = None
    policy_year: str | None = None
    document_url: str | None = None
    source_language: str | None = None
    file_name: str | None = None
    extracted_text: str
    summary: str | None = None


class DocumentRecord(DocumentMetadata):
    dataset_id: str
    file_name: str | None = None
    extracted_text_chars: int = 0
    created_at: str


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    category: str | None = None
    sub_category: str | None = None
    limit: int = Field(default=8, ge=1, le=50)


class SemanticMatch(BaseModel):
    dataset_id: str
    title: str
    category: str
    sub_category: str
    score: float
    chunk: str
    metadata: dict[str, Any]

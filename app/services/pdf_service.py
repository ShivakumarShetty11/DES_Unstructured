from io import BytesIO
import base64
import re
import sys
import requests
from pypdf import PdfReader

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

# Minimum chars from pypdf before we consider it "no text" and try Vision
_MIN_TEXT_CHARS = 80
# Max pages to send through Vision (cost/latency guard)
_VISION_PAGE_LIMIT = 40


class PdfService:
    def __init__(self, anthropic_api_key: str | None = None):
        self._vision_client = None
        if anthropic_api_key and _anthropic_mod is not None:
            try:
                self._vision_client = _anthropic_mod.Anthropic(api_key=anthropic_api_key)
            except Exception as exc:
                print(f"[PdfService] Anthropic client init failed: {exc}", file=sys.stderr)

    # ── Public entry point ────────────────────────────────────────────────────

    def extract_text_from_bytes(self, data: bytes) -> str:
        text = self._pypdf_extract(data)

        if len(text) < _MIN_TEXT_CHARS:
            if self._vision_client is not None and _FITZ_AVAILABLE:
                print(
                    f"[PdfService] pypdf returned {len(text)} chars — "
                    "falling back to Claude Vision OCR.",
                    file=sys.stderr,
                )
                text = self._vision_extract(data)
            else:
                if not _FITZ_AVAILABLE:
                    print("[PdfService] pymupdf not available; cannot use Vision fallback.", file=sys.stderr)
                if self._vision_client is None:
                    print("[PdfService] No Anthropic client; cannot use Vision fallback.", file=sys.stderr)

        return text

    def download_pdf(self, url: str) -> bytes:
        response = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content

    # ── pypdf extraction ──────────────────────────────────────────────────────

    def _pypdf_extract(self, data: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            print(f"[PdfService] pypdf could not open PDF: {exc}", file=sys.stderr)
            return ""

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                print(f"[PdfService] Could not decrypt PDF: {exc}", file=sys.stderr)
                return ""

        if not reader.pages:
            return ""

        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            raw = ""
            # layout mode (pypdf >= 4.x) preserves column order better
            try:
                raw = page.extract_text(extraction_mode="layout") or ""
            except Exception:
                pass
            if not raw.strip():
                try:
                    raw = page.extract_text() or ""
                except Exception as exc:
                    print(f"[PdfService] pypdf page {i} error: {exc}", file=sys.stderr)

            if not raw.strip():
                continue

            lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines()]
            cleaned = "\n".join(ln for ln in lines if ln)
            if cleaned:
                pages.append(cleaned)

        return "\n\n".join(pages).strip()

    # ── Claude Vision OCR ─────────────────────────────────────────────────────

    def _vision_extract(self, data: bytes) -> str:
        """Render each page with pymupdf, send to Claude Vision, collect text."""
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            print(f"[PdfService] pymupdf could not open PDF: {exc}", file=sys.stderr)
            return ""

        total_pages = len(doc)
        pages_to_process = min(total_pages, _VISION_PAGE_LIMIT)
        if total_pages > _VISION_PAGE_LIMIT:
            print(
                f"[PdfService] PDF has {total_pages} pages; Vision OCR limited to first {_VISION_PAGE_LIMIT}.",
                file=sys.stderr,
            )

        pages_text: list[str] = []
        for page_num in range(pages_to_process):
            page_text = self._vision_extract_page(doc[page_num], page_num)
            if page_text:
                pages_text.append(page_text)

        doc.close()
        result = "\n\n".join(pages_text).strip()
        print(
            f"[PdfService] Vision OCR complete: {len(pages_text)}/{pages_to_process} pages "
            f"yielded text ({len(result)} chars).",
            file=sys.stderr,
        )
        return result

    def _vision_extract_page(self, page: "fitz.Page", page_num: int) -> str:
        try:
            # 150 DPI — good quality, reasonable image size
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            png_bytes = pix.tobytes("png")
            b64 = base64.standard_b64encode(png_bytes).decode()

            response = self._vision_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Extract all text visible on this document page exactly as it appears. "
                                    "Preserve headings, paragraphs, bullet points, tables, and numbering. "
                                    "Output only the extracted text — no commentary, no markdown fences."
                                ),
                            },
                        ],
                    }
                ],
            )
            return " ".join(
                block.text for block in response.content if getattr(block, "text", None)
            ).strip()
        except Exception as exc:
            print(f"[PdfService] Vision OCR failed on page {page_num}: {exc}", file=sys.stderr)
            return ""


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return []

    chunks: list[str] = []
    start = 0
    n = len(clean)
    while start < n:
        end = min(n, start + chunk_size)
        piece = clean[start:end]
        if piece.strip():
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks

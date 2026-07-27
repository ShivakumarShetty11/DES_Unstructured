from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import router as api_router
from app.config import settings
from app.mcp_router import router as mcp_router
from app.services.document_store import DocumentStore
from app.services.pdf_service import PdfService
from app.services.summary_service import SummaryService
from app.services.vector_store import VectorStore

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup() -> None:
    app.state.uploads_dir = settings.uploads_dir
    app.state.document_store = DocumentStore(settings.sqlite_path)
    app.state.pdf_service = PdfService(settings.anthropic_api_key)
    app.state.summary_service = SummaryService(settings.anthropic_api_key)
    app.state.vector_store = VectorStore(
        persist_directory=str(settings.chroma_path),
        collection_name=settings.chroma_collection,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": settings.app_name})


@app.get("/catalogue", response_class=HTMLResponse)
async def catalogue(request: Request):
    return templates.TemplateResponse("catalogue.html", {"request": request, "title": "Unstructured PDF Catalogue"})


app.include_router(api_router)
app.include_router(mcp_router)

"""
FastAPI RAG Server for Tata Motors Showroom Voice Agent
Exclusively manages access to ./chroma_showroom_db and runs on 127.0.0.1:8000.
"""

import os
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import rag_engine

BASE_DIR = Path(__file__).resolve().parent
PDFS_DIR = BASE_DIR / "pdfs"
PDFS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan event: initialize ChromaDB collection and warm up
    CPU sentence-transformers embeddings on startup.
    """
    rag_engine.get_collection()
    yield


app = FastAPI(
    title="Tata Motors Showroom Voice Agent RAG Server",
    description="Dedicated RAG retrieval and persistence server running strictly on CPU.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local client connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Schemas
class QueryRequest(BaseModel):
    query: str = Field(..., description="User query or voice transcription")
    top_k: int = Field(default=3, ge=1, le=10, description="Max passages to return")
    model: Optional[str] = Field(default=None, description="Optional Tata car model (e.g. tiago, nexon, safari)")
    variant: Optional[str] = Field(default=None, description="Optional trim/variant (e.g. fearless, creative, dark)")
    year: Optional[int] = Field(default=None, description="Optional model year (e.g. 2026)")


class RememberRequest(BaseModel):
    text: str = Field(..., description="Staff-approved note or persistent knowledge")
    source: Optional[str] = Field(default="staff_approved_note", description="Source identifier")
    model: Optional[str] = Field(default=None, description="Optional associated car model")
    variant: Optional[str] = Field(default=None, description="Optional associated variant")
    year: Optional[int] = Field(default=2026, description="Model year")


@app.get("/health")
async def health():
    """
    Health check endpoint returning server status, host, and port.
    """
    return {
        "status": "ok",
        "host": "127.0.0.1",
        "port": 8000,
    }


@app.post("/rag/query")
async def query_endpoint(req: QueryRequest):
    """
    Query the ChromaDB collection using cosine similarity.
    Rejects passages below 0.25 similarity and returns {"matches": [...]}.
    """
    try:
        results = rag_engine.query_matches(
            query=req.query,
            top_k=req.top_k,
            model=req.model,
            variant=req.variant,
            year=req.year,
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query error: {str(e)}",
        )


@app.post("/rag/ingest-pdf")
async def ingest_pdf_endpoint(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    variant: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
):
    """
    Accepts multipart file upload of a brochure PDF with optional model/variant/year metadata,
    saves to ./pdfs/, chunks and ingests into ./chroma_showroom_db, and returns ingestion stats.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a PDF document (.pdf).",
        )

    saved_path = PDFS_DIR / file.filename
    try:
        # Save file to disk
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ingest into vector DB
        chunks_count = rag_engine.ingest_pdf(
            pdf_path=str(saved_path),
            reset_collection=False,
            model=model,
            variant=variant,
            year=year if year is not None else 2026,
        )

        return {
            "status": "success",
            "filename": file.filename,
            "chunks_ingested": chunks_count,
            "model": model.strip().lower() if model else None,
            "variant": variant.strip().lower() if variant else None,
            "year": year or 2026,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}",
        )
    finally:
        await file.close()


@app.post("/rag/remember")
async def remember_endpoint(req: RememberRequest):
    """
    Persist staff-approved notes permanently to disk in ChromaDB and staff_notes.jsonl.
    """
    try:
        fact_id = rag_engine.remember_fact(
            text=req.text,
            model=req.model,
            variant=req.variant,
            year=req.year,
            source=req.source or "staff_approved_note",
        )
        return {
            "status": "saved",
            "id": fact_id,
            "text": req.text,
            "source": req.source or "staff_approved_note",
            "model": req.model.strip().lower() if req.model else None,
            "variant": req.variant.strip().lower() if req.variant else None,
            "year": req.year,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remember fact: {str(e)}",
        )


@app.post("/rag/reseed")
async def reseed_endpoint():
    """
    Reset and cleanly re-seed ChromaDB collection from the official Tata lineup PDF,
    clearing out temporary test chunks.
    """
    try:
        chunks_count = rag_engine.ingest_pdf(
            pdf_path=str(rag_engine.DEFAULT_PDF),
            reset_collection=True,
        )
        return {
            "status": "success",
            "message": "Collection cleanly reset and re-seeded from official Tata lineup brochure.",
            "chunks_ingested": chunks_count,
            "source": rag_engine.DEFAULT_PDF.name,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reseed failed: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("rag_server:app", host="127.0.0.1", port=8000, reload=False)

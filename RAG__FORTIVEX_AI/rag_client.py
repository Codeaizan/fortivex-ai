"""
Client helper for Tata Motors Showroom Voice Agent RAG Server.
Provides a clean, resilient Python interface to communicate over HTTP with http://127.0.0.1:8000.
"""

from typing import Any, Dict, List, Optional
import requests

RAG_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 10.0


def check_health(base_url: str = RAG_BASE_URL) -> bool:
    """Check if the RAG server is reachable and healthy."""
    try:
        r = requests.get(f"{base_url}/health", timeout=2.0)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def query_rag(
    query: str,
    top_k: int = 3,
    model: str | None = None,
    variant: str | None = None,
    year: int | None = None,
    base_url: str = RAG_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict]:
    """
    Query the FastAPI RAG server at http://127.0.0.1:8000/rag/query.
    Handles connection errors, timeouts, and HTTP errors gracefully by returning [].

    Args:
        query: User question or voice transcript (English, Hindi, or Hinglish)
        top_k: Maximum matches to retrieve (default 3)
        model: Optional Tata model name filter (e.g. 'nexon', 'safari', 'harrier')
        variant: Optional variant filter (e.g. 'dark', 'fearless', 'creative')
        year: Optional model year filter (e.g. 2026)
        base_url: Base URL of the RAG server
        timeout: Request timeout in seconds

    Returns:
        List of match dictionaries: [{"text": ..., "source": ..., "page": ...}]
        Returns [] if no matches pass the similarity threshold (0.25) or on network failure.
    """
    if not query or not query.strip():
        return []

    payload: Dict[str, Any] = {
        "query": query.strip(),
        "top_k": top_k,
    }
    if model:
        payload["model"] = model.strip().lower()
    if variant:
        payload["variant"] = variant.strip().lower()
    if year is not None:
        payload["year"] = int(year)

    try:
        resp = requests.post(
            f"{base_url}/rag/query",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("matches", [])
        return []
    except (requests.RequestException, ValueError, KeyError):
        return []


def remember_fact(
    text: str,
    model: str | None = None,
    variant: str | None = None,
    year: int | None = 2026,
    source: str = "staff_approved_note",
    base_url: str = RAG_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict | None:
    """
    Persist staff-approved notes or temporary showroom facts to disk via the RAG server.

    Returns:
        Confirmation dict with saved fact 'id' on success, or None on error.
    """
    if not text or not text.strip():
        return None

    payload: Dict[str, Any] = {
        "text": text.strip(),
        "source": source,
    }
    if model:
        payload["model"] = model.strip().lower()
    if variant:
        payload["variant"] = variant.strip().lower()
    if year is not None:
        payload["year"] = int(year)

    try:
        resp = requests.post(
            f"{base_url}/rag/remember",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def reseed_database(base_url: str = RAG_BASE_URL) -> dict | None:
    """
    Reset and re-seed ./chroma_showroom_db cleanly from the official lineup PDF.
    If the server is running, calls POST /rag/reseed over HTTP.
    If the server is offline, falls back to direct rag_engine.ingest_pdf.
    """
    # 1. Try via running server
    try:
        resp = requests.post(f"{base_url}/rag/reseed", timeout=60.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    # 2. Fallback to direct engine ingestion if server offline
    try:
        import rag_engine
        count = rag_engine.ingest_pdf(str(rag_engine.DEFAULT_PDF), reset_collection=True)
        return {
            "status": "success",
            "message": "Direct reseed completed via rag_engine.",
            "chunks_ingested": count,
            "source": rag_engine.DEFAULT_PDF.name,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    print(f"RAG Server Online: {check_health()}")
    print("Testing query_rag fallback...")
    res = query_rag("Tata Nexon price", top_k=2)
    print(f"Matches count: {len(res)}")

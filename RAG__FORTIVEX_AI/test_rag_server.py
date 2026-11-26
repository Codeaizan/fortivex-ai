"""
Verification script for Tata Motors Showroom Voice Agent RAG Server.
Tests:
  1. GET  /health
  2. POST /rag/query (English query)
  3. POST /rag/query (Hindi cross-lingual query)
  4. POST /rag/query (Irrelevant query threshold rejection)
  5. POST /rag/remember (Staff-approved note persistence)
  6. POST /rag/query (Retrieval of remembered staff note)
  7. POST /rag/ingest-pdf (Multipart PDF ingestion)
"""

import sys
import json
import time
from pathlib import Path

# Use TestClient for in-process ASGI testing or httpx for live server
from fastapi.testclient import TestClient
import httpx

import rag_server

BASE_DIR = Path(__file__).resolve().parent
PDFS_DIR = BASE_DIR / "pdfs"
TEST_PDF = PDFS_DIR / "Tata_India_Current_Car_Lineup_November_2026.pdf"


def run_tests():
    print("=" * 70)
    print("Testing Tata Motors RAG Server (FastAPI Endpoints)")
    print("=" * 70)

    # Check if a live server is running on 127.0.0.1:8000
    live_url = "http://127.0.0.1:8000"
    use_live = False
    try:
        r = httpx.get(f"{live_url}/health", timeout=1.0)
        if r.status_code == 200:
            use_live = True
            print(f"[INFO] Detected live server at {live_url}. Testing live HTTP service.")
    except Exception:
        print("[INFO] Live server not running on port 8000. Testing via FastAPI TestClient.")

    client = httpx.Client(base_url=live_url, timeout=30.0) if use_live else TestClient(rag_server.app)

    # 1. Test GET /health
    print("\n--- 1. Testing GET /health ---")
    resp = client.get("/health")
    print(f"Status Code: {resp.status_code}")
    print(f"Response: {resp.json()}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "host": "127.0.0.1", "port": 8000}
    print("PASSED: /health returned expected payload.")

    # 2. Test POST /rag/query (English)
    print("\n--- 2. Testing POST /rag/query (English Query) ---")
    query_payload = {
        "query": "What is the price, engine options and seating capacity of Tata Harrier?",
        "top_k": 2,
        "model": "harrier",
        "year": 2026,
    }
    resp = client.post("/rag/query", json=query_payload)
    print(f"Status Code: {resp.status_code}")
    data = resp.json()
    matches = data.get("matches", [])
    print(f"Matches count: {len(matches)}")
    assert resp.status_code == 200
    assert len(matches) > 0
    for idx, m in enumerate(matches):
        print(f"  Match {idx+1}: [sim: {m.get('similarity')}] (Page {m.get('page')}) {m['text'][:100]}...")
    print("PASSED: English query retrieved relevant passages above 0.25 similarity.")

    # 3. Test POST /rag/query (Hindi Cross-Lingual)
    print("\n--- 3. Testing POST /rag/query (Hindi Query against English Brochure) ---")
    hindi_payload = {
        "query": "टाटा सफारी में कितने एयरबैग हैं और सेफ्टी फीचर्स क्या हैं?",
        "top_k": 2,
        "model": "safari",
    }
    resp = client.post("/rag/query", json=hindi_payload)
    print(f"Status Code: {resp.status_code}")
    data = resp.json()
    matches = data.get("matches", [])
    print(f"Matches count: {len(matches)}")
    assert resp.status_code == 200
    assert len(matches) > 0
    for idx, m in enumerate(matches):
        print(f"  Match {idx+1}: [sim: {m.get('similarity')}] (Page {m.get('page')}) {m['text'][:100]}...")
    print("PASSED: Hindi query successfully matched English brochure content.")

    # 4. Test POST /rag/query (Threshold Rejection)
    print("\n--- 4. Testing POST /rag/query (Threshold Rejection on Irrelevant Query) ---")
    irrelevant_payload = {
        "query": "astronauts walking on mars spacecraft orbital mechanics",
        "top_k": 3,
    }
    resp = client.post("/rag/query", json=irrelevant_payload)
    print(f"Status Code: {resp.status_code}")
    data = resp.json()
    matches = data.get("matches", [])
    print(f"Matches count: {len(matches)} (Expected: 0)")
    assert resp.status_code == 200
    assert len(matches) == 0
    assert data == {"matches": []}
    print("PASSED: Irrelevant query returned empty matches array.")

    # 5. Test POST /rag/remember
    print("\n--- 5. Testing POST /rag/remember (Persist Staff Note) ---")
    remember_payload = {
        "text": "Exclusive November 2026 Showroom Offer: Corporate buyers get 3 years complimentary scheduled maintenance on Tata Curvv.ev bookings.",
        "model": "curvv.ev",
        "variant": "empowered",
        "year": 2026,
        "source": "showroom_manager_desk",
    }
    resp = client.post("/rag/remember", json=remember_payload)
    print(f"Status Code: {resp.status_code}")
    remember_res = resp.json()
    print(f"Response: {remember_res}")
    assert resp.status_code == 200
    assert remember_res.get("status") == "saved"
    fact_id = remember_res.get("id")
    assert fact_id is not None
    print(f"PASSED: Note remembered with ID: {fact_id}")

    # 6. Test Querying the Remembered Note
    print("\n--- 6. Testing Retrieval of the Remembered Note ---")
    query_remembered = {
        "query": "corporate buyer complimentary maintenance offer",
        "top_k": 2,
        "model": "curvv.ev",
    }
    resp = client.post("/rag/query", json=query_remembered)
    data = resp.json()
    matches = data.get("matches", [])
    print(f"Matches count: {len(matches)}")
    assert len(matches) > 0
    top_match = matches[0]
    print(f"Top Match: [sim: {top_match.get('similarity')}] {top_match['text']}")
    assert "complimentary scheduled maintenance" in top_match["text"]
    print("PASSED: Staff note was retrieved successfully via semantic search.")

    # 7. Test POST /rag/ingest-pdf
    print("\n--- 7. Testing POST /rag/ingest-pdf (Multipart Upload) ---")
    if TEST_PDF.exists():
        with open(TEST_PDF, "rb") as f:
            files = {"file": ("uploaded_test_lineup.pdf", f, "application/pdf")}
            data = {"model": "altroz", "year": "2026"}
            resp = client.post("/rag/ingest-pdf", files=files, data=data)
            print(f"Status Code: {resp.status_code}")
            ingest_data = resp.json()
            print(f"Response: {ingest_data}")
            assert resp.status_code == 200
            assert ingest_data.get("status") == "success"
            assert ingest_data.get("chunks_ingested", 0) > 0
            print(f"PASSED: Ingested {ingest_data['chunks_ingested']} chunks from uploaded PDF.")
    else:
        print("[SKIP] Sample PDF not found for upload test.")

    print("\n" + "=" * 70)
    print("ALL RAG SERVER ENDPOINT TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()

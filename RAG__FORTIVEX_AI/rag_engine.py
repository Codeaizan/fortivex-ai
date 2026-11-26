"""
RAG Engine for Tata Motors Showroom Voice Agent
Running on CPU for lightweight semantic search and vector retrieval.
"""

import os
import re
import json
import uuid
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

import pypdf
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Base directories
BASE_DIR = Path(__file__).resolve().parent
PDFS_DIR = BASE_DIR / "pdfs"
CHROMA_DIR = BASE_DIR / "chroma_showroom_db"
STAFF_NOTES_FILE = CHROMA_DIR / "staff_notes.jsonl"
DEFAULT_PDF = PDFS_DIR / "Tata_India_Current_Car_Lineup_November_2026.pdf"

# Page to Tata Model mapping (pages 2 to 19)
PAGE_MODEL_MAPPING: Dict[int, str] = {
    2: "tiago",
    3: "altroz",
    4: "aeris",
    5: "punch",
    6: "nexon",
    7: "curvv",
    8: "sierra",
    9: "harrier",
    10: "safari",
    11: "tiago.ev",
    12: "punch.ev",
    13: "nexon.ev",
    14: "curvv.ev",
    15: "sierra.ev",
    16: "harrier.ev",
    17: "tigor.ev",
    18: "xpres",
    19: "xpres-t ev",
}

COLLECTION_NAME = "tata_showroom_lineup"
SIMILARITY_THRESHOLD = 0.25

# Global lock for thread-safe access
_db_lock = threading.Lock()

# Lazily initialized globals
_client: Optional[chromadb.PersistentClient] = None
_embedding_fn: Optional[SentenceTransformerEmbeddingFunction] = None
_collection = None


def get_embedding_function() -> SentenceTransformerEmbeddingFunction:
    """Initialize and return the CPU SentenceTransformer embedding function."""
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            device="cpu",
        )
    return _embedding_fn


def get_client() -> chromadb.PersistentClient:
    """Return persistent Chroma client pointing to chroma_showroom_db."""
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_collection(reset: bool = False):
    """
    Get or create the ChromaDB collection configured with cosine similarity.
    Thread-safe access via _db_lock.
    """
    global _collection
    with _db_lock:
        client = get_client()
        embedding_fn = get_embedding_function()
        if reset:
            try:
                client.delete_collection(name=COLLECTION_NAME)
            except Exception:
                pass
            _collection = None

        if _collection is None:
            _collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        return _collection


def _clean_text(raw_text: str) -> str:
    """Remove headers, footers and page numbers from extracted PDF text."""
    lines = raw_text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Drop common headers/footers
        if re.search(r"TATA CARS ON SALE IN INDIA\s*/\s*NOVEMBER 2026", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\d+\s*/\s*19$", stripped):
            continue
        if re.match(r"^(?:RETAIL PASSENGER CAR|RETAIL EV|FLEET SEDAN)$", stripped, re.IGNORECASE):
            continue
        if re.match(r"^INDIA\s*/\s*\d+\s+NOVEMBER\s+2026$", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines)


def _extract_variants_from_grades(grades_text: str) -> List[str]:
    """Extract individual variant/grade names from the grades section."""
    cleaned = re.sub(r"^(?:Grades and transmissions|Published grades)\s*", "", grades_text, flags=re.IGNORECASE)
    found_variants = set()
    # Lines often follow 'Engine. Variant1, Variant2, ...' or 'Variant1, Variant2...'
    for line in cleaned.split("\n"):
        parts = line.split(":", 1)
        content = parts[1] if len(parts) > 1 else parts[0]
        # Remove powertrain prefixes like 'Petrol manual.' or '19.2 kWh.'
        content = re.sub(r"^[A-Za-z0-9\.\+\s]+?\.\s*", "", content)
        tokens = [t.strip().rstrip(".,") for t in content.split(",") if t.strip()]
        for token in tokens:
            if len(token) > 1 and not token.lower().startswith("powertrain"):
                found_variants.add(token)
    return sorted(list(found_variants))


def chunk_page_content(
    raw_text: str,
    page_number: int,
    model_name: str,
    source_filename: str,
    year: int = 2026,
) -> List[Dict[str, Any]]:
    """
    Parse and chunk a car lineup page cleanly while retaining semantic metadata.
    """
    cleaned = _clean_text(raw_text)
    chunks: List[Dict[str, Any]] = []

    # Section markers observed across the PDF
    section_patterns = [
        ("Specification", r"(?:^|\n)Specification\n([\s\S]*?)(?=(?:Dimensions and chassis|Grades and transmissions|Published grades|Equipment and safety|Sources|$))"),
        ("Dimensions and chassis", r"(?:^|\n)Dimensions and chassis\n([\s\S]*?)(?=(?:Grades and transmissions|Published grades|Equipment and safety|Sources|$))"),
        ("Grades and transmissions", r"(?:^|\n)(?:Grades and transmissions|Published grades)\n([\s\S]*?)(?=(?:Equipment and safety|Sources|$))"),
        ("Equipment and safety", r"(?:^|\n)Equipment and safety\n([\s\S]*?)(?=(?:Sources|$))"),
    ]

    # Find overview at top (before Specification)
    overview_match = re.search(r"^([\s\S]*?)(?=(?:Specification|$))", cleaned)
    overview_text = overview_match.group(1).strip() if overview_match else ""
    car_display_name = f"Tata {model_name.capitalize()}"
    if overview_text:
        first_line = overview_text.split("\n")[0]
        if first_line.lower().startswith("tata"):
            car_display_name = first_line

    if overview_text:
        chunks.append({
            "text": f"{car_display_name} ({year}) - Model Overview & Pricing:\n{overview_text}",
            "metadata": {
                "source": source_filename,
                "page": page_number,
                "model": model_name,
                "year": year,
            },
        })

    grades_content = ""
    for section_title, pattern in section_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            content = match.group(1).strip()
            if content:
                if "grades" in section_title.lower():
                    grades_content = content
                chunks.append({
                    "text": f"{car_display_name} ({year}) - {section_title}:\n{content}",
                    "metadata": {
                        "source": source_filename,
                        "page": page_number,
                        "model": model_name,
                        "year": year,
                    },
                })

    # Create variant-specific chunks for targeted variant queries
    if grades_content:
        variants = _extract_variants_from_grades(grades_content)
        for var in variants:
            var_slug = var.strip().lower()
            chunks.append({
                "text": f"{car_display_name} ({year}) - Variant Grade: {var}.\nAvailable in {car_display_name} lineup.\nDetails from lineup grades:\n{grades_content}",
                "metadata": {
                    "source": source_filename,
                    "page": page_number,
                    "model": model_name,
                    "variant": var_slug,
                    "year": year,
                },
            })

    # Full coherent page summary chunk for comprehensive queries
    chunks.append({
        "text": f"{car_display_name} ({year}) Comprehensive Lineup Profile (Page {page_number}):\n{cleaned}",
        "metadata": {
            "source": source_filename,
            "page": page_number,
            "model": model_name,
            "year": year,
        },
    })

    return chunks


def ingest_pdf(
    pdf_path: str = str(DEFAULT_PDF),
    reset_collection: bool = False,
    model: Optional[str] = None,
    variant: Optional[str] = None,
    year: Optional[int] = 2026,
) -> int:
    """
    Ingest a PDF into ChromaDB.
    If model is specified, all pages of the document are associated with that model.
    If model is not specified and it is the 19-page Tata lineup PDF, maps pages 2-19
    to their respective models.
    Preserves source filename, page number, model, variant, and year metadata.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found at: {path}")

    source_filename = path.name
    reader = pypdf.PdfReader(str(path))
    total_pages = len(reader.pages)
    target_year = year if year is not None else 2026

    collection = get_collection(reset=reset_collection)

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    if model:
        # Ingest all pages for this specific model
        m_slug = model.strip().lower()
        v_slug = variant.strip().lower() if variant else None
        for page_idx in range(total_pages):
            page_num = page_idx + 1
            raw_text = reader.pages[page_idx].extract_text() or ""
            page_chunks = chunk_page_content(
                raw_text=raw_text,
                page_number=page_num,
                model_name=m_slug,
                source_filename=source_filename,
                year=target_year,
            )
            for idx, chunk in enumerate(page_chunks):
                chunk_id = f"custom_{m_slug}_p{page_num}_c{idx}_{uuid.uuid4().hex[:6]}"
                meta = chunk["metadata"]
                if v_slug:
                    meta["variant"] = v_slug
                ids.append(chunk_id)
                documents.append(chunk["text"])
                metadatas.append(meta)
    else:
        # Lineup mapping for pages 2 to 19 (or full document)
        start_page = 2 if total_pages >= 19 else 1
        end_page = min(total_pages + 1, 20 if total_pages >= 19 else total_pages + 1)
        for page_num in range(start_page, end_page):
            model_name = PAGE_MODEL_MAPPING.get(page_num, f"model_page_{page_num}")
            page_idx = page_num - 1
            raw_text = reader.pages[page_idx].extract_text() or ""
            
            page_chunks = chunk_page_content(
                raw_text=raw_text,
                page_number=page_num,
                model_name=model_name,
                source_filename=source_filename,
                year=target_year,
            )

            for idx, chunk in enumerate(page_chunks):
                chunk_id = f"tata_{model_name}_p{page_num}_c{idx}"
                ids.append(chunk_id)
                documents.append(chunk["text"])
                metadatas.append(chunk["metadata"])

    if ids:
        with _db_lock:
            # Batch upsert into Chroma
            batch_size = 50
            for i in range(0, len(ids), batch_size):
                collection.upsert(
                    ids=ids[i : i + batch_size],
                    documents=documents[i : i + batch_size],
                    metadatas=metadatas[i : i + batch_size],
                )

    return len(ids)


def remember_fact(
    text: str,
    model: Optional[str] = None,
    variant: Optional[str] = None,
    year: Optional[int] = 2026,
    source: str = "staff_approved_note",
) -> str:
    """
    Persist staff-approved notes permanently to disk in ChromaDB and staff_notes.jsonl.
    Thread-safe writes via _db_lock.
    """
    collection = get_collection()
    fact_id = f"fact_{uuid.uuid4().hex[:12]}"
    
    metadata: Dict[str, Any] = {
        "source": source,
        "page": 0,
    }
    if model:
        metadata["model"] = model.strip().lower()
    if variant:
        metadata["variant"] = variant.strip().lower()
    if year is not None:
        metadata["year"] = int(year)

    with _db_lock:
        collection.upsert(
            ids=[fact_id],
            documents=[text],
            metadatas=[metadata],
        )

        # Also persist to staff_notes.jsonl on disk
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "id": fact_id,
            "text": text,
            "metadata": metadata,
        }
        with open(STAFF_NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return fact_id


def query_matches(
    query: str,
    top_k: int = 3,
    model: Optional[str] = None,
    variant: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Query the collection for passages matching query above similarity threshold 0.25.
    Returns:
        {"matches": [{"text": ..., "source": ..., "page": ...}]} or {"matches": []}
    """
    collection = get_collection()

    filter_conditions: List[Dict[str, Any]] = []
    if model:
        filter_conditions.append({"model": model.strip().lower()})
    if variant:
        filter_conditions.append({"variant": variant.strip().lower()})
    if year is not None:
        filter_conditions.append({"year": int(year)})

    where_filter: Optional[Dict[str, Any]] = None
    if len(filter_conditions) == 1:
        where_filter = filter_conditions[0]
    elif len(filter_conditions) > 1:
        where_filter = {"$and": filter_conditions}

    with _db_lock:
        count = collection.count()
        if count == 0:
            return {"matches": []}

        n_results = min(top_k, count)
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

    if not results or not results.get("documents") or not results["documents"][0]:
        return {"matches": []}

    matches: List[Dict[str, Any]] = []
    docs = results["documents"][0]
    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
    distances = results["distances"][0] if results.get("distances") else [1.0] * len(docs)

    for doc, meta, dist in zip(docs, metas, distances):
        # In cosine space, similarity = 1.0 - cosine_distance
        similarity = 1.0 - dist
        if similarity >= SIMILARITY_THRESHOLD:
            item: Dict[str, Any] = {
                "text": doc,
                "source": meta.get("source", "unknown"),
                "page": meta.get("page", 0),
            }
            if "model" in meta and meta["model"]:
                item["model"] = meta["model"]
            if "variant" in meta and meta["variant"]:
                item["variant"] = meta["variant"]
            if "year" in meta and meta["year"]:
                item["year"] = meta["year"]
            item["similarity"] = round(similarity, 4)
            matches.append(item)

    return {"matches": matches}


if __name__ == "__main__":
    print("Testing Tata Motors Showroom RAG Engine...")
    print(f"Chroma persistence path: {CHROMA_DIR}")
    print(f"Default PDF target: {DEFAULT_PDF}")

    if DEFAULT_PDF.exists():
        print("\n1. Ingesting PDF...")
        num_chunks = ingest_pdf(str(DEFAULT_PDF), reset_collection=True)
        print(f"Successfully ingested {num_chunks} chunks.")
    else:
        print(f"\nWarning: PDF not found at {DEFAULT_PDF}. Ingestion skipped.")

    print("\n2. Testing remember_fact...")
    fact_id = remember_fact(
        text="Special festive season discount of ₹25,000 applicable on Tata Safari Dark Edition bookings till December 2026.",
        model="safari",
        variant="dark",
        year=2026,
    )
    print(f"Remembered fact ID: {fact_id}")

    print("\n3. Testing query_matches for 'Safari festive discount'...")
    res = query_matches("Safari festive discount", top_k=2, model="safari")
    print(f"Matches count: {len(res['matches'])}")
    for m in res["matches"]:
        print(f" - [sim: {m.get('similarity')}] (Page {m.get('page')}) {m['text'][:120]}...")

    print("\n4. Testing query_matches for 'Nexon safety airbags'...")
    res_nexon = query_matches("Nexon safety airbags", top_k=2, model="nexon")
    print(f"Matches count: {len(res_nexon['matches'])}")
    for m in res_nexon["matches"]:
        print(f" - [sim: {m.get('similarity')}] (Page {m.get('page')}) {m['text'][:120]}...")

    print("\n5. Testing low-similarity threshold rejection with random text...")
    res_none = query_matches("astronauts walking on mars spacecraft orbital mechanics", top_k=2)
    print(f"Irrelevant query matches count: {len(res_none['matches'])} (Expected: 0)")
    print("\nAll RAG engine smoke tests completed successfully!")

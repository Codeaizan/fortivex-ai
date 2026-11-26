"""
Tata Motors Showroom Voice Agent - RAG Diagnostic & Knowledge UI
Connects over HTTP to FastAPI RAG Server (http://127.0.0.1:8000).
"""

from typing import Optional
import requests
import streamlit as st

RAG_API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Tata Motors Showroom - RAG Knowledge Hub",
    page_icon="🚗",
    layout="wide",
)

TATA_MODELS = [
    "",
    "tiago",
    "altroz",
    "aeris",
    "punch",
    "nexon",
    "curvv",
    "sierra",
    "harrier",
    "safari",
    "tiago.ev",
    "punch.ev",
    "nexon.ev",
    "curvv.ev",
    "sierra.ev",
    "harrier.ev",
    "tigor.ev",
    "xpres",
    "xpres-t ev",
]


def check_server_health() -> bool:
    """Check if the FastAPI RAG server is reachable at 127.0.0.1:8000."""
    try:
        r = requests.get(f"{RAG_API_URL}/health", timeout=1.5)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


# Top Header & Status Indicator
col_title, col_status = st.columns([3, 1])

with col_title:
    st.title("🚗 Tata Motors Showroom Voice Agent")
    st.caption("RAG Knowledge & Retrieval Diagnostic Hub • Exclusively connected via HTTP to 127.0.0.1:8000")

server_online = check_server_health()

with col_status:
    st.write("")
    if server_online:
        st.success("🟢 **Server Online** (127.0.0.1:8000)")
    else:
        st.error("🔴 **Server Offline**")
        st.caption("Start server: `uvicorn rag_server:app --host 127.0.0.1 --port 8000`")

st.divider()

# Navigation Tabs
tab_query, tab_ingest, tab_remember = st.tabs([
    "🔍 Query & Cross-Lingual Test",
    "📄 Ingest PDF Brochure",
    "📝 Remember Staff Note",
])

# -----------------------------------------------------------------------------
# TAB 1: Query & Cross-Lingual Test
# -----------------------------------------------------------------------------
with tab_query:
    st.subheader("Semantic Query & Cross-Lingual Verification")
    st.write("Test semantic retrieval against the Tata lineup. The CPU embedding model handles English, Hindi, and Hinglish queries natively.")

    # Quick sample prompt chips
    st.markdown("**Quick Test Queries:**")
    c1, c2, c3 = st.columns(3)
    sample_query = ""
    if c1.button("🇬🇧 Safari Price & Seating (EN)"):
        sample_query = "What is the price, engine options and seating capacity of Tata Safari?"
    if c2.button("🇮🇳 नेक्सन सेफ्टी और एयरबैग (HI)"):
        sample_query = "टाटा नेक्सन में कितने एयरबैग हैं और सेफ्टी फीचर्स क्या हैं?"
    if c3.button("🗣️ Curvv EV Battery & Range (Hinglish)"):
        sample_query = "Tata Curvv EV ka certified range aur battery capacity kitna hai?"

    user_query = st.text_input(
        "Enter question (English / Hindi / Hinglish):",
        value=sample_query if sample_query else "",
        placeholder="e.g. What are the key features and price of Tata Harrier?",
    )

    col_filters1, col_filters2, col_filters3, col_topk = st.columns([1.5, 1.5, 1, 1])
    with col_filters1:
        sel_model = st.selectbox("Filter Model (Optional):", options=TATA_MODELS, format_func=lambda x: "(Any Model)" if x == "" else x)
    with col_filters2:
        filter_variant = st.text_input("Filter Variant (Optional):", placeholder="e.g. fearless, creative, dark")
    with col_filters3:
        filter_year = st.number_input("Filter Year:", min_value=2020, max_value=2030, value=2026)
    with col_topk:
        top_k = st.slider("Top K Matches:", min_value=1, max_value=10, value=3)

    if st.button("🔎 Submit Query", type="primary", use_container_width=True):
        if not user_query.strip():
            st.warning("Please enter a query.")
        elif not server_online:
            st.error("Cannot query: RAG server is offline. Please launch `rag_server.py` on 127.0.0.1:8000.")
        else:
            payload = {
                "query": user_query.strip(),
                "top_k": top_k,
                "model": sel_model if sel_model else None,
                "variant": filter_variant.strip().lower() if filter_variant.strip() else None,
                "year": int(filter_year) if filter_year else None,
            }

            with st.spinner("Searching vector database..."):
                try:
                    resp = requests.post(f"{RAG_API_URL}/rag/query", json=payload, timeout=15.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        matches = data.get("matches", [])
                        if not matches:
                            st.warning("⚠️ No relevant passage found (matches: []). No passages surpassed the 0.25 similarity threshold.")
                        else:
                            st.success(f"Retrieved **{len(matches)}** matching passage(s):")
                            for idx, match in enumerate(matches):
                                sim = match.get("similarity", 0.0)
                                source = match.get("source", "unknown")
                                page = match.get("page", 0)
                                model = match.get("model", "N/A")
                                variant = match.get("variant", "N/A")
                                text = match.get("text", "")

                                with st.expander(f"Match #{idx + 1} • Similarity: {sim:.4f} • Model: {model} (Page {page})", expanded=(idx == 0)):
                                    st.markdown(f"**Source:** `{source}` | **Page:** `{page}` | **Model:** `{model}` | **Variant:** `{variant}`")
                                    st.info(text)
                    else:
                        st.error(f"Error {resp.status_code}: {resp.text}")
                except Exception as e:
                    st.error(f"Failed to communicate with RAG server: {e}")

# -----------------------------------------------------------------------------
# TAB 2: Ingest PDF Brochure
# -----------------------------------------------------------------------------
with tab_ingest:
    st.subheader("Upload & Ingest Lineup Brochure")
    st.write("Upload a PDF document. The server will save it to `./pdfs/`, chunk the contents cleanly, compute CPU embeddings, and index it into `./chroma_showroom_db`.")

    uploaded_file = st.file_uploader("Select PDF file:", type=["pdf"])

    col_ing_m, col_ing_v, col_ing_y = st.columns(3)
    with col_ing_m:
        ing_model = st.text_input("Associated Model (Optional):", placeholder="e.g. nexon, safari, tiago")
    with col_ing_v:
        ing_variant = st.text_input("Associated Variant (Optional):", placeholder="e.g. dark, creative+")
    with col_ing_y:
        ing_year = st.number_input("Lineup Year:", min_value=2020, max_value=2030, value=2026, key="ing_year")

    if st.button("📤 Upload & Ingest PDF", type="primary"):
        if not uploaded_file:
            st.warning("Please upload a PDF file first.")
        elif not server_online:
            st.error("Cannot ingest: RAG server is offline.")
        else:
            with st.spinner("Uploading and indexing PDF into ChromaDB..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                    data = {}
                    if ing_model.strip():
                        data["model"] = ing_model.strip().lower()
                    if ing_variant.strip():
                        data["variant"] = ing_variant.strip().lower()
                    if ing_year:
                        data["year"] = int(ing_year)

                    resp = requests.post(f"{RAG_API_URL}/rag/ingest-pdf", files=files, data=data, timeout=120.0)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        st.success(f"🎉 Ingestion successful! Index updated with **{res_json.get('chunks_ingested')}** chunks.")
                        st.json(res_json)
                    else:
                        st.error(f"Ingestion failed ({resp.status_code}): {resp.text}")
                except Exception as e:
                    st.error(f"Error connecting to server: {e}")

# -----------------------------------------------------------------------------
# TAB 3: Remember Staff Note
# -----------------------------------------------------------------------------
with tab_remember:
    st.subheader("Persist Staff-Approved Showroom Notes")
    st.write("Record showroom-specific discounts, temporary delivery timelines, or manager notes. These are stored permanently to disk in ChromaDB and appended to `staff_notes.jsonl`.")

    note_text = st.text_area(
        "Staff Note / Knowledge Text:",
        placeholder="e.g. Festival Season Offer: ₹20,000 cash discount on all Tata Nexon Fearless variants booked before 31st December 2026.",
        height=120,
    )

    col_rem_m, col_rem_v, col_rem_y, col_rem_src = st.columns([1.5, 1.5, 1, 1.5])
    with col_rem_m:
        rem_model = st.selectbox("Associated Model:", options=TATA_MODELS, format_func=lambda x: "(General / All Models)" if x == "" else x, key="rem_model")
    with col_rem_v:
        rem_variant = st.text_input("Associated Variant:", placeholder="e.g. fearless, dark", key="rem_variant")
    with col_rem_y:
        rem_year = st.number_input("Year:", min_value=2020, max_value=2030, value=2026, key="rem_year")
    with col_rem_src:
        rem_source = st.text_input("Source Identifier:", value="showroom_manager_desk")

    if st.button("💾 Persist Note to Disk", type="primary"):
        if not note_text.strip():
            st.warning("Please enter note text.")
        elif not server_online:
            st.error("Cannot save note: RAG server is offline.")
        else:
            payload = {
                "text": note_text.strip(),
                "model": rem_model if rem_model else None,
                "variant": rem_variant.strip().lower() if rem_variant.strip() else None,
                "year": int(rem_year) if rem_year else 2026,
                "source": rem_source.strip() if rem_source.strip() else "staff_approved_note",
            }

            with st.spinner("Persisting note to disk..."):
                try:
                    resp = requests.post(f"{RAG_API_URL}/rag/remember", json=payload, timeout=10.0)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        st.success(f"✅ Note permanently persisted to disk! Assigned ID: `{res_json.get('id')}`")
                        st.json(res_json)
                    else:
                        st.error(f"Failed to persist note ({resp.status_code}): {resp.text}")
                except Exception as e:
                    st.error(f"Error connecting to server: {e}")

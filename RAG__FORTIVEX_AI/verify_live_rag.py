"""
Live HTTP Verification Script for Tata Motors Showroom Voice Agent RAG Server.
Tests live endpoints at http://127.0.0.1:8000 using rag_client.
Includes clean database re-seeding option (--reseed).
"""

import sys
import argparse
import requests

import rag_client

RAG_URL = "http://127.0.0.1:8000"


def print_banner(text: str):
    print("\n" + "=" * 75)
    print(text)
    print("=" * 75)


def verify_live():
    parser = argparse.ArgumentParser(description="Live verification of Tata Motors RAG Server.")
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Cleanly reset and re-seed chroma_showroom_db from the official Tata lineup PDF.",
    )
    args = parser.parse_args()

    print_banner("🚗 Tata Motors Showroom Voice Agent - Live RAG Verification")

    # 1. Health Check
    print("Checking connection to RAG server at http://127.0.0.1:8000 ...")
    try:
        r = requests.get(f"{RAG_URL}/health", timeout=2.0)
        if r.status_code != 200 or r.json().get("status") != "ok":
            raise RuntimeError(f"Unexpected health response: {r.text}")
        print(f"✅ RAG Server is ONLINE! Health check: {r.json()}")
    except Exception as e:
        print(f"\n❌ [ERROR] RAG server at {RAG_URL} is NOT reachable.")
        print("Details:", e)
        print("\nPlease launch the RAG server in another terminal first:")
        print("   cd C:\\Users\\kchir\\OneDrive\\Desktop\\RAG__FORTIVEX_AI")
        print("   .\\.venv\\Scripts\\Activate.ps1")
        print("   uvicorn rag_server:app --host 127.0.0.1 --port 8000")
        print("\nOr double-click: run_server.bat\n")
        sys.exit(1)

    # 2. Reseed option
    if args.reseed:
        print_banner("🧹 Step: Clean Database Re-Seed (--reseed flag)")
        print("Resetting chroma_showroom_db and indexing official lineup PDF...")
        reseed_res = rag_client.reseed_database(base_url=RAG_URL)
        print("Reseed Result:", reseed_res)
        if reseed_res and reseed_res.get("status") == "success":
            print(f"✅ Database cleanly re-seeded with {reseed_res.get('chunks_ingested')} official chunks.")
        else:
            print("⚠️ Reseed returned unexpected response:", reseed_res)

    all_passed = True

    # 3. Test: English car spec & price query
    print_banner("Test 1: English Specification & Pricing Query (top_k=3)")
    q1 = "What is the price, boot capacity, and engine power of Tata Tiago?"
    print(f"Query: \"{q1}\"")
    m1 = rag_client.query_rag(q1, top_k=3, model="tiago", base_url=RAG_URL)
    print(f"Matches returned: {len(m1)}")
    if m1:
        for idx, m in enumerate(m1):
            print(f"  [{idx+1}] Sim: {m.get('similarity')} | Page {m.get('page')} | Model: {m.get('model')}")
            print(f"      Text: {m['text'][:120]}...\n")
        print("✅ Test 1 PASSED: Retrieved Tiago specifications above 0.25 threshold.")
    else:
        print("❌ Test 1 FAILED: Expected matches for Tiago specification query.")
        all_passed = False

    # 4. Test: Hindi / Hinglish cross-lingual query
    print_banner("Test 2: Hindi Cross-Lingual Query against English Brochure (top_k=3)")
    q2_hindi = "टाटा सफारी में कितने एयरबैग हैं और सेफ्टी फीचर्स क्या हैं?"
    print(f"Query (Hindi): \"{q2_hindi}\"")
    m2_hindi = rag_client.query_rag(q2_hindi, top_k=3, model="safari", base_url=RAG_URL)
    print(f"Hindi matches returned: {len(m2_hindi)}")
    if m2_hindi:
        for idx, m in enumerate(m2_hindi):
            print(f"  [{idx+1}] Sim: {m.get('similarity')} | Page {m.get('page')} | Model: {m.get('model')}")
            print(f"      Text: {m['text'][:120]}...\n")
        print("✅ Test 2a PASSED: Cross-lingual Hindi retrieval succeeded.")
    else:
        print("❌ Test 2a FAILED: Hindi query did not retrieve English brochure.")
        all_passed = False

    q2_hinglish = "Tata Nexon EV ka real world range aur battery kitna hai?"
    print(f"Query (Hinglish): \"{q2_hinglish}\"")
    m2_hinglish = rag_client.query_rag(q2_hinglish, top_k=3, model="nexon.ev", base_url=RAG_URL)
    print(f"Hinglish matches returned: {len(m2_hinglish)}")
    if m2_hinglish:
        for idx, m in enumerate(m2_hinglish):
            print(f"  [{idx+1}] Sim: {m.get('similarity')} | Page {m.get('page')} | Model: {m.get('model')}")
            print(f"      Text: {m['text'][:120]}...\n")
        print("✅ Test 2b PASSED: Hinglish EV query retrieved Nexon.ev specs.")
    else:
        print("❌ Test 2b FAILED: Hinglish query did not retrieve matches.")
        all_passed = False

    # 5. Test: Metadata Filtering (model and year)
    print_banner("Test 3: Metadata Filtering (model='punch', year=2026)")
    q3 = "What are the dimensions, length, width, and ground clearance?"
    print(f"Query: \"{q3}\" (with model='punch', year=2026)")
    m3 = rag_client.query_rag(q3, top_k=3, model="punch", year=2026, base_url=RAG_URL)
    print(f"Matches returned: {len(m3)}")
    if m3:
        filter_ok = True
        for idx, m in enumerate(m3):
            print(f"  [{idx+1}] Sim: {m.get('similarity')} | Page {m.get('page')} | Model: {m.get('model')} | Year: {m.get('year')}")
            print(f"      Text: {m['text'][:120]}...\n")
            if m.get("model") != "punch" or m.get("year") != 2026:
                filter_ok = False
        if filter_ok:
            print("✅ Test 3 PASSED: All matches strictly adhere to model='punch' and year=2026 filters.")
        else:
            print("❌ Test 3 FAILED: Match returned did not match model/year filter.")
            all_passed = False
    else:
        print("❌ Test 3 FAILED: No matches returned for Punch dimensions.")
        all_passed = False

    # 6. Test: Irrelevant Query Threshold Rejection
    print_banner("Test 4: Irrelevant Query Rejection (Threshold 0.25)")
    q4 = "astronauts walking on mars spacecraft orbital mechanics"
    print(f"Query: \"{q4}\"")
    m4 = rag_client.query_rag(q4, top_k=3, base_url=RAG_URL)
    print(f"Matches returned: {len(m4)} (Expected: 0)")
    if len(m4) == 0:
        print("✅ Test 4 PASSED: Irrelevant query successfully rejected (returned []).")
    else:
        print("❌ Test 4 FAILED: Irrelevant query should have returned [] but got:", m4)
        all_passed = False

    # 7. Summary
    print_banner("LIVE VERIFICATION RESULT")
    if all_passed:
        print("🎉 ALL LIVE RAG VERIFICATION TESTS PASSED SUCCESSFULLY!")
        print(f"The RAG server on {RAG_URL} is fully operational and ready for the voice agent.")
    else:
        print("⚠️ Some tests failed. Please review the output above.")
        sys.exit(1)


if __name__ == "__main__":
    verify_live()

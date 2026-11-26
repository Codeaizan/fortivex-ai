"""
End-to-End Handshake Verification Script: RAG Server (:8000) -> LLM (:8080 / :11434)
Formats grounded prompts for voice synthesis and prevents hallucinations.
"""

from typing import Any, Dict, List, Optional
import json
import requests

from rag_client import query_rag, check_health, RAG_BASE_URL

LLAMA_CPP_URL = "http://127.0.0.1:8080"
OLLAMA_URL = "http://127.0.0.1:11434"

SYSTEM_INSTRUCTION_HEADER = (
    "You are the official Tata Motors Showroom Voice Assistant.\n"
    "Answer the customer's question politely, concisely, and conversationally for voice output.\n\n"
    "STRICT GROUNDING RULES:\n"
    "1. Answer ONLY from the provided showroom context below.\n"
    "2. If missing or not explicitly stated in the context, say: "
    "\"I do not have verified showroom specifications or pricing for that detail in our 2026 catalog.\"\n"
    "3. NEVER invent, extrapolate, or hallucinate specs, mileage, warranty, discounts, or prices.\n"
    "4. Keep the response natural, clear, and under 3 sentences for comfortable voice listening."
)

FALLBACK_NO_MATCH_RESPONSE = (
    "I do not have verified showroom specifications or pricing for that detail in our official 2026 catalog. "
    "Please connect with our showroom sales advisor for assistance."
)


def build_llm_prompt(
    user_query: str,
    model: Optional[str] = None,
    variant: Optional[str] = None,
    year: Optional[int] = None,
    top_k: int = 3,
    base_url: str = RAG_BASE_URL,
) -> Dict[str, Any]:
    """
    Query the RAG server and format a grounded LLM chat completion payload.

    Args:
        user_query: Customer question in English, Hindi, or Hinglish.
        model: Optional Tata model name filter (e.g. 'nexon', 'safari', 'curvv.ev').
        variant: Optional variant filter.
        year: Optional lineup year (default 2026).
        top_k: Maximum passages to retrieve.
        base_url: Base URL of the RAG server.

    Returns:
        Dictionary containing:
          - 'has_context': bool
          - 'user_query': str
          - 'matches': list[dict]
          - 'fallback_message': str | None
          - 'llm_payload': dict (OpenAI/llama.cpp/Ollama compatible)
    """
    matches = query_rag(
        query=user_query,
        top_k=top_k,
        model=model,
        variant=variant,
        year=year,
        base_url=base_url,
    )

    if not matches:
        return {
            "has_context": False,
            "user_query": user_query,
            "matches_count": 0,
            "matches": [],
            "fallback_message": FALLBACK_NO_MATCH_RESPONSE,
            "llm_payload": None,
        }

    # Format retrieved passages: <source p.X> <text>
    formatted_context_blocks = []
    for m in matches:
        source_name = m.get("source", "brochure.pdf")
        page_num = m.get("page", 0)
        text_content = m.get("text", "").strip()
        formatted_context_blocks.append(f"<{source_name} p.{page_num}> {text_content}")

    context_str = "\n\n".join(formatted_context_blocks)

    system_content = (
        f"{SYSTEM_INSTRUCTION_HEADER}\n\n"
        f"VERIFIED SHOWROOM CONTEXT:\n"
        f"{context_str}"
    )

    llm_payload = {
        "model": "tata-motors-voice-assistant",
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_query},
        ],
        "temperature": 0.1,
        "max_tokens": 200,
    }

    return {
        "has_context": True,
        "user_query": user_query,
        "matches_count": len(matches),
        "matches": matches,
        "fallback_message": None,
        "llm_payload": llm_payload,
    }


def detect_llm_service() -> Dict[str, Any]:
    """Check for running llama.cpp (:8080) or Ollama (:11434) and detect model name."""
    # Check llama.cpp / OpenAI-compatible endpoint
    try:
        r = requests.get(f"{LLAMA_CPP_URL}/health", timeout=0.8)
        if r.status_code == 200:
            return {
                "type": "llama.cpp",
                "url": LLAMA_CPP_URL,
                "endpoint": f"{LLAMA_CPP_URL}/v1/chat/completions",
                "model": "local-model",
            }
    except Exception:
        pass

    # Check Ollama endpoint
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=0.8)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
            model_name = models[0] if models else "llama3.2"
            return {
                "type": "ollama",
                "url": OLLAMA_URL,
                "endpoint": f"{OLLAMA_URL}/api/chat",
                "model": model_name,
            }
    except Exception:
        pass

    return {"type": "none", "url": None, "endpoint": None, "model": None}


def run_handshake_tests():
    print("=" * 75)
    print("🚗 Tata Motors Voice Agent: RAG -> LLM Handshake Verification")
    print("=" * 75)

    # 1. Verify RAG server health
    rag_online = check_health()
    if not rag_online:
        print(f"\n⚠️  [ALERT] RAG Server at {RAG_BASE_URL} is currently offline.")
        print("Please launch it in another terminal to test live retrieval:")
        print("   uvicorn rag_server:app --host 127.0.0.1 --port 8000\n")
    else:
        print(f"✅ RAG Server is ONLINE at {RAG_BASE_URL}")

    # 2. Detect LLM backend
    llm_info = detect_llm_service()
    if llm_info["type"] != "none":
        print(f"🟢 LLM Backend detected: {llm_info['type']} at {llm_info['url']}")
    else:
        print("ℹ️  No LLM service running on :8080 (llama.cpp) or :11434 (Ollama).")
        print("   Operating in Dry-Run Mode: Generating and validating exact prompt payloads.\n")

    test_cases = [
        {
            "title": "Case 1: English Query - Tata Nexon Safety & Airbags",
            "query": "Does the Tata Nexon come with six airbags as standard and what ADAS features are available?",
            "model": "nexon",
            "variant": None,
            "year": 2026,
            "expect_match": True,
        },
        {
            "title": "Case 2: Hinglish Query - Tata Curvv.ev Battery & Range",
            "query": "Curvv EV ka battery pack kitna bada hai aur certified range kitni milti hai?",
            "model": "curvv.ev",
            "variant": None,
            "year": 2026,
            "expect_match": True,
        },
        {
            "title": "Case 3: Hindi Query - Tata Safari Price & Seating",
            "query": "टाटा सफारी में कितने लोग बैठ सकते हैं और इसकी शुरुआती कीमत क्या है?",
            "model": "safari",
            "variant": None,
            "year": 2026,
            "expect_match": True,
        },
        {
            "title": "Case 4: Out-of-Scope Query - Hallucination Prevention",
            "query": "astronauts walking on mars spacecraft orbital mechanics",
            "model": None,
            "variant": None,
            "year": None,
            "expect_match": False,
        },
    ]

    for tc in test_cases:
        print("-" * 75)
        print(f"📌 {tc['title']}")
        print(f"Query: \"{tc['query']}\"")
        if tc["model"]:
            print(f"Filter: model='{tc['model']}', year={tc['year']}")

        if not rag_online:
            print("[SKIP] Cannot perform live retrieval because RAG server is offline.")
            continue

        prompt_data = build_llm_prompt(
            user_query=tc["query"],
            model=tc["model"],
            variant=tc["variant"],
            year=tc["year"],
            top_k=3,
        )

        has_context = prompt_data["has_context"]
        print(f"Matches Retrieved: {prompt_data['matches_count']}")

        if has_context:
            assert tc["expect_match"] is True, "Expected no match but got context!"
            payload = prompt_data["llm_payload"]
            system_msg = payload["messages"][0]["content"]
            user_msg = payload["messages"][1]["content"]

            print("✅ Grounded Prompt Formatted Successfully.")
            print("\n[Preview of Formatted System Instructions & Injected Context]:")
            lines = system_msg.split("\n")
            preview = "\n".join(lines[:12])
            print(preview)
            print(f"... [{len(system_msg)} total characters formatted]\n")

            # If a local LLM is live, test the actual inference call
            if llm_info["type"] != "none":
                print(f"Sending live request to {llm_info['type']} ({llm_info['endpoint']})...")
                try:
                    if llm_info["type"] == "ollama":
                        req_body = {
                            "model": llm_info["model"],
                            "messages": payload["messages"],
                            "stream": False,
                            "options": {"temperature": 0.1, "num_predict": 120},
                        }
                        r = requests.post(llm_info["endpoint"], json=req_body, timeout=25.0)
                        if r.status_code == 200:
                            ans = r.json().get("message", {}).get("content", "").strip()
                            print(f"🗣️  LLM Grounded Answer ({llm_info['model']}):\n{ans}\n")
                        else:
                            print(f"LLM returned status {r.status_code}: {r.text}")
                    elif llm_info["type"] == "llama.cpp":
                        payload["model"] = llm_info["model"]
                        r = requests.post(llm_info["endpoint"], json=payload, timeout=25.0)
                        if r.status_code == 200:
                            ans = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                            print(f"🗣️  LLM Grounded Answer ({llm_info['model']}):\n{ans}\n")
                        else:
                            print(f"LLM returned status {r.status_code}: {r.text}")
                except Exception as ex:
                    print(f"LLM call timed out / failed: {ex}")
        else:
            assert tc["expect_match"] is False, "Expected matches but got empty context!"
            print("✅ Hallucination Prevention Triggered: Empty matches array.")
            print(f"Fallback Speech Message: \"{prompt_data['fallback_message']}\"")
            print("Action: Voice agent short-circuits directly to fallback speech without LLM hallucination.")

    print("\n" + "=" * 75)
    print("HANDSHAKE VERIFICATION SUITE FINISHED")
    print("=" * 75)


if __name__ == "__main__":
    run_handshake_tests()

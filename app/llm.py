"""LLM-First RAG Client (Planner + Grounded RAG Responder)."""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self):
        self.mock_mode = os.getenv("MOCK_LLM", "false").lower() == "true"
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")

    def _has_remote_llm(self) -> bool:
        if self.mock_mode:
            return False
        return bool(self.gemini_api_key or self.api_key or self.ollama_url)

    def plan_turn(
        self,
        query: str,
        history: List[Dict[str, Any]],
        normalized_filters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Uses the LLM to understand follow-ups, intent, search query, and filters."""
        if not self._has_remote_llm():
            return {"intent": "product_search", "search_query": query, "filters": dict(normalized_filters), "product_ids": []}

        recent = [{"role": m["role"], "content": m["content"][:400]} for m in history[-6:]]
        prompt = f"""You are an e-commerce search planner. Given the conversation history and the latest user query, return ONLY raw JSON (no markdown):
{{
  "intent": "product_search" | "product_comparison" | "product_fact" | "clarification",
  "search_query": "clean English product keywords for hybrid search (translate Hindi/Hinglish product terms to English, resolve references like 'cheaper ones' or 'that phone' using history)",
  "filters": {{
    "min_price": null,
    "max_price": null,
    "min_rating": null,
    "category": null,
    "brand": null,
    "size": null,
    "colour": null,
    "storage_gb": null,
    "ram_gb": null,
    "in_stock_only": null
  }},
  "product_ids": ["P-... if the user explicitly references product IDs or refers to specific products from history"]
}}

Rules:
- Valid categories are strictly: ["Electronics", "Footwear", "Sports & Outdoors", "Fashion", "Home & Kitchen", "Beauty & Care"]. Leave null if unsure.
- Keep any already-extracted filters unless the user changes them: {json.dumps(normalized_filters)}
- Conversation history: {json.dumps(recent)}
- Latest user query: {json.dumps(query)}"""

        try:
            raw = self._call_llm(prompt)
            parsed = self._extract_json_from_response(raw)
            if isinstance(parsed, dict):
                from app.schemas import Filters
                clean_filters = Filters.model_validate(parsed.get("filters") or {}).model_dump(exclude_none=True)
                clean_filters.update(normalized_filters or {})
                return {
                    "intent": parsed.get("intent", "product_search"),
                    "search_query": str(parsed.get("search_query") or query),
                    "filters": clean_filters,
                    "product_ids": [str(x) for x in (parsed.get("product_ids") or [])],
                }
        except Exception as e:
            logging.error(f"LLM plan_turn failed: {e}")

        return {"intent": "product_search", "search_query": query, "filters": dict(normalized_filters), "product_ids": []}

    def generate_rag_response(
        self,
        query: str,
        history: List[Dict[str, Any]],
        retrieved_products: List[Dict[str, Any]],
        intent: str,
        filters: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """RAG generator: produces a grounded answer + selected product IDs strictly from retrieved catalogue rows."""
        if not self._has_remote_llm():
            return None

        recent = [{"role": m["role"], "content": m["content"][:400]} for m in history[-6:]]
        context_docs = [
            {
                "product_id": p["product_id"],
                "title": p["title"],
                "brand": p["brand"],
                "category": p["category"],
                "price": f"{p['currency']} {p['price']:g}",
                "stock_quantity": p["stock_quantity"],
                "rating": p["rating"],
                "specs": p.get("specs", {}),
                "description": p.get("description", "")[:200],
            }
            for p in retrieved_products
        ]

        prompt = f"""You are Phoenix, a helpful, concise e-commerce shopping assistant.
Reply in the SAME language as the user (English, Hindi Devanagari, or Hinglish).

Conversation history: {json.dumps(recent)}
User query: {json.dumps(query)}
Planned intent: {intent}
Applied filters: {json.dumps(filters)}
Retrieved Catalogue Context (Ground Truth): {json.dumps(context_docs)}

Return ONLY raw JSON (no markdown backticks):
{{
  "answer_type": "recommendation" | "comparison" | "product_fact" | "clarification" | "not_found",
  "answer": "Your helpful, well-formatted Markdown response (use a Markdown table if comparing products, bullet points for recommendations). Cite product_id, exact price, and relevant specs.",
  "selected_product_ids": ["P-... IDs from Retrieved Catalogue Context that you recommended or discussed"],
  "follow_up_question": "Optional short follow-up question or null"
}}

STRICT GROUNDING RULES:
1. NEVER invent products, prices, stock counts, or specs not present in Retrieved Catalogue Context.
2. If Retrieved Catalogue Context is empty or none of the products actually match what the user asked for, set answer_type to "not_found", selected_product_ids to [], and politely explain what categories we carry (Electronics, Footwear, Sports & Outdoors, Fashion, Home & Kitchen, Beauty & Care).
3. If the user's request is too vague (e.g., just "gift" or "something good"), set answer_type to "clarification" and ask a helpful follow-up question."""

        try:
            raw = self._call_llm(prompt)
            parsed = self._extract_json_from_response(raw)
            if isinstance(parsed, dict) and parsed.get("answer"):
                return parsed
        except Exception as e:
            logging.error(f"LLM generate_rag_response failed: {e}")
        return None

    def _call_llm(self, prompt: str) -> str:
        if self.gemini_api_key:
            models_to_try = list(dict.fromkeys([
                self.gemini_model,
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-flash-latest",
                "gemini-flash-lite-latest",
            ]))
            for m in models_to_try:
                if not m:
                    continue
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
                    req_data = json.dumps({
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=req_data,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": self.gemini_api_key,
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        return res["candidates"][0]["content"]["parts"][0]["text"]
                except Exception as e:
                    logging.error(f"Gemini model '{m}' failed: {e}")
                    continue

        if self.ollama_url and not self.api_key:
            req_data = json.dumps({
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("response", "")

        if self.api_key:
            req_data = json.dumps({
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.api_base}/chat/completions",
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res["choices"][0]["message"]["content"]

        raise RuntimeError("No LLM endpoint available")

    def _extract_json_from_response(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None
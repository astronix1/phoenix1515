"""Planner and Synthesizer client.

Supports Ollama, Hosted LLM APIs, and a deterministic Mock LLM for offline testing & evaluation.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request


class LLMClient:
    def __init__(self):
        self.mock_mode = os.getenv("MOCK_LLM", "true").lower() == "true"
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")

    def _has_remote_llm(self) -> bool:
        if self.mock_mode:
            return False
        return bool(self.gemini_api_key or self.api_key or (self.ollama_url and not self.mock_mode))

    def plan_intent_and_filters(
        self,
        query: str,
        history: Optional[List[Dict[str, Any]]] = None,
        normalized_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Plans the query execution: classifies intent and extracts hard filters & search query."""
        if not self._has_remote_llm():
            return self._mock_plan(query, history, normalized_filters)

        try:
            prompt = self._build_planner_prompt(query, history, normalized_filters)
            raw_response = self._call_llm(prompt)
            parsed = self._extract_json_from_response(raw_response)
            if isinstance(parsed, dict) and isinstance(parsed.get("search_query"), str):
                from app.schemas import Filters
                parsed["filters"] = Filters.model_validate(parsed.get("filters") or {}).model_dump(exclude_none=True)
                parsed["filters"].update(normalized_filters or {})
                return parsed
        except (ValueError, OSError, KeyError, IndexError, TypeError):
            pass
        return self._mock_plan(query, history, normalized_filters)

    def _mock_plan(self, query, history, normalized_filters):
        filters = dict(normalized_filters or {})
        intent = "product_search"
        if re.search(r"\b(compare|comparison|difference between|vs)\b", query, re.I):
            intent = "product_comparison"
        cleaned = re.sub(r"(?:under|below|above|up to|budget(?: of)?|less than|more than|max(?:imum)?|min(?:imum)?)\s*[$₹]?\s*\d+(?:\.\d+)?\s*(?:k|thousand|inr|usd)?", " ", query, flags=re.I)
        cleaned = re.sub(r"\b\d+(?:\.\d+)?\s*(?:gb|tb|stars?)\b(?:\s*(?:ram|storage|ssd))?|\bsize\s*\w+", " ", cleaned, flags=re.I)
        return {"intent": intent, "search_query": cleaned, "filters": filters}

    def reason_field(self, query, filters):
        """The model may select a verified field to highlight, never supply its value."""
        default = "price" if "max_price" in filters else "rating"
        if self._has_remote_llm():
            try:
                prompt = ("Choose one catalogue field to explain this shopping request. "
                          "Return JSON with field equal to price, rating or brand. Request: " + json.dumps(query))
                choice = self._extract_json_from_response(self._call_llm(prompt))
                if isinstance(choice, dict) and choice.get("field") in ("price", "rating", "brand"):
                    return choice["field"]
            except (ValueError, OSError, KeyError, IndexError, TypeError):
                pass
        return default

    # Remote LLM Invocation Helpers
    def _call_llm(self, prompt: str) -> str:
        # Check Google Gemini API
        if self.gemini_api_key:
            initial_model = self.gemini_model if self.gemini_model not in ["gemini-2.0-flash", ""] else "gemini-2.5-flash"
            models_to_try = [initial_model, "gemini-2.5-flash", "gemini-flash-latest"]
            for m in models_to_try:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_api_key}"
                    req_data = json.dumps({
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2}
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=req_data,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        return res["candidates"][0]["content"]["parts"][0]["text"]
                except Exception:
                    continue

        # Check Ollama
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("response", "")

        # Check OpenAI / Hosted endpoint
        if self.api_key:
            req_data = json.dumps({
                "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res["choices"][0]["message"]["content"]

        raise RuntimeError("No LLM endpoint available")

    def _build_planner_prompt(self, query: str, history: Optional[List[Dict[str, Any]]], normalized_filters: Optional[Dict[str, Any]]) -> str:
        return f"""You are an e-commerce assistant planner. Analyze the user query and return valid JSON with:
1. "intent": one of ["product_search", "product_comparison", "order_status", "clarification", "general_info"]
2. "search_query": cleaned product search term
3. "filters": object containing any extracted filters (max_price, min_price, category, brand, in_stock_only, min_rating). Note: valid categories are strictly ["Electronics", "Footwear", "Sports & Outdoors", "Fashion", "Home & Kitchen", "Beauty & Care"]. Do not use product names like 'phone' or 'laptop' as category.
4. "product_ids_to_compare": list of product identifiers or names if comparing

Previous public search context: {json.dumps(history or [])}
User Query: {json.dumps(query)}
Normalized Filters: {json.dumps(normalized_filters or {})}
Output ONLY raw JSON with no markdown backticks."""

    def _extract_json_from_response(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None

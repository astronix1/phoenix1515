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
            if parsed and "intent" in parsed:
                # Merge with normalized filters
                merged_filters = dict(normalized_filters or {})
                merged_filters.update(parsed.get("filters", {}))
                parsed["filters"] = merged_filters
                return parsed
        except Exception:
            pass

        return self._mock_plan(query, history, normalized_filters)

    def synthesize_response(
        self,
        query: str,
        intent: str,
        products: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
        active_filters: Dict[str, Any],
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Synthesizes a grounded, customer-facing response based strictly on retrieved facts."""
        if self.mock_mode or not self.api_key:
            return self._mock_synthesize(query, intent, products, orders, active_filters)

        try:
            prompt = self._build_synthesizer_prompt(query, intent, products, orders, active_filters, history)
            return self._call_llm(prompt)
        except Exception:
            return self._mock_synthesize(query, intent, products, orders, active_filters)

    # Mock Rule-Based Planner & Synthesizer
    def _mock_plan(
        self,
        query: str,
        history: Optional[List[Dict[str, Any]]],
        normalized_filters: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        filters = dict(normalized_filters or {})
        q_lower = query.lower()

        # Intent Detection
        # 1. Order status
        if any(w in q_lower for w in ["order", "track", "delivery", "shipping", "bought", "purchased"]):
            return {
                "intent": "order_status",
                "search_query": query,
                "filters": filters,
                "product_ids_to_compare": [],
            }

        # 2. Product Comparison
        compare_match = re.search(r"(?i)\b(?:compare|difference between|vs\.?)\s+(.+?)(?:\s+and\s+|\s+with\s+|\s+vs\.?\s+)(.+)", query)
        if compare_match or "compare" in q_lower or " vs " in q_lower:
            return {
                "intent": "product_comparison",
                "search_query": query,
                "filters": filters,
                "product_ids_to_compare": [],
            }

        # 3. Category & Brand extraction
        brands = ["apple", "samsung", "sony", "dell", "nike", "adidas", "logitech", "hp", "lenovo", "bose"]
        for b in brands:
            if b in q_lower:
                filters["brand"] = b.capitalize()

        categories = {
            "laptop": "Electronics",
            "phone": "Electronics",
            "smartphone": "Electronics",
            "headphone": "Electronics",
            "shoes": "Footwear",
            "sneakers": "Footwear",
            "shirt": "Apparel",
            "jacket": "Apparel",
            "saree": "Apparel",
            "vacuum": "Home & Kitchen",
            "coffee": "Home & Kitchen",
            "tea": "Groceries",
        }
        for kw, cat in categories.items():
            if kw in q_lower:
                filters["category"] = cat
                break

        # Extract stripped search terms (removing filter phrases like 'under 50000', 'in stock')
        clean_search = re.sub(r"(?i)\b(under|below|above|less than|more than|budget|price|rating|in stock|star|stars|\$|₹|inr|rs)\b.*", "", query).strip()
        if not clean_search:
            clean_search = query

        return {
            "intent": "product_search",
            "search_query": clean_search,
            "filters": filters,
            "product_ids_to_compare": [],
        }

    def _mock_synthesize(
        self,
        query: str,
        intent: str,
        products: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
        active_filters: Dict[str, Any],
    ) -> str:
        # Order Status Response
        if intent == "order_status":
            if not orders:
                return "You do not have any past orders in our records, or no orders matched your request."
            lines = ["Here are your recent orders:"]
            for o in orders:
                title = o.get("product_title") or f"Product #{o.get('product_id')}"
                lines.append(f"• **Order {o['order_id']}**: {title} (Qty: {o['quantity']}) - Status: **{o['order_status']}** (Placed on {o['order_date']})")
            return "\n".join(lines)

        # Product Comparison Response
        if intent == "product_comparison":
            if len(products) < 2:
                if products:
                    return f"Found only one matching item: **{products[0]['title']}** (₹{products[0]['price']}). Please specify another product to compare with."
                return "I couldn't find the products you wanted to compare. Please provide specific model names or SKUs."

            p1, p2 = products[0], products[1]
            lines = [
                f"### Comparison: {p1['title']} vs {p2['title']}",
                f"- **Brand**: {p1['brand']} vs {p2['brand']}",
                f"- **Price**: {p1.get('currency', 'INR')} {p1['price']:,} vs {p2.get('currency', 'INR')} {p2['price']:,}",
                f"- **Rating**: ⭐ {p1['rating']} vs ⭐ {p2['rating']}",
                f"- **In Stock**: {'Yes (' + str(p1['stock_quantity']) + ')' if p1['stock_quantity'] > 0 else 'No'} vs {'Yes (' + str(p2['stock_quantity']) + ')' if p2['stock_quantity'] > 0 else 'No'}",
            ]
            if p1.get("specs") or p2.get("specs"):
                lines.append(f"- **Key Specs ({p1['brand']})**: {', '.join(f'{k}: {v}' for k, v in list(p1.get('specs', {}).items())[:3])}")
                lines.append(f"- **Key Specs ({p2['brand']})**: {', '.join(f'{k}: {v}' for k, v in list(p2.get('specs', {}).items())[:3])}")
            return "\n".join(lines)

        # Product Search / Recommendation Response
        if not products:
            filter_desc = []
            if "max_price" in active_filters:
                filter_desc.append(f"price under ₹{active_filters['max_price']}")
            if "min_rating" in active_filters:
                filter_desc.append(f"rating >= {active_filters['min_rating']}")
            if "category" in active_filters:
                filter_desc.append(f"category '{active_filters['category']}'")
            if active_filters.get("in_stock_only"):
                filter_desc.append("in-stock only")

            crit = f" matching {', '.join(filter_desc)}" if filter_desc else ""
            return f"I couldn't find any products{crit}. Try widening your price range or relaxing your search filters."

        lines = [f"Found **{len(products)}** option{'s' if len(products) > 1 else ''} matching your request:"]
        for p in products[:5]:
            stock_str = f"In Stock ({p['stock_quantity']} left)" if p["stock_quantity"] > 0 else "Out of Stock"
            spec_summary = ""
            if p.get("specs"):
                spec_summary = " | " + ", ".join(f"{k}: {v}" for k, v in list(p["specs"].items())[:2])
            lines.append(
                f"• **{p['title']}** - **{p.get('currency', 'INR')} {p['price']:,}** (⭐ {p['rating']}) - {stock_str}{spec_summary}\n  _{p['description'][:110]}..._"
            )
        return "\n".join(lines)

    # Remote LLM Invocation Helpers
    def _call_llm(self, prompt: str) -> str:
        # Check Google Gemini API
        if self.gemini_api_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"
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
3. "filters": object containing any extracted filters (max_price, min_price, category, brand, in_stock_only, min_rating)
4. "product_ids_to_compare": list of product identifiers or names if comparing

User Query: "{query}"
Normalized Filters: {json.dumps(normalized_filters or {})}
Output ONLY raw JSON with no markdown backticks."""

    def _build_synthesizer_prompt(
        self,
        query: str,
        intent: str,
        products: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
        active_filters: Dict[str, Any],
        history: Optional[List[Dict[str, Any]]],
    ) -> str:
        return f"""You are Phoenix, a helpful and strictly grounded e-commerce assistant.
Answer the user's question using ONLY the provided facts. Do not invent products, prices, or specs not listed below.

User Query: "{query}"
Intent: {intent}
Retrieved Products: {json.dumps(products[:6], indent=2)}
Customer Orders: {json.dumps(orders, indent=2)}
Active Filters: {json.dumps(active_filters)}

Provide a concise, user-friendly markdown response."""

    def _extract_json_from_response(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None

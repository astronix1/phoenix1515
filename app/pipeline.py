"""LLM-First RAG Pipeline grounded in SQLite + ChromaDB."""

import re
import time
import uuid
from threading import Lock

from app.guardrails import CustomerIdPrivacyGate, InjectionSanitizer, UnitNormalizer
from app.schemas import ChatResponse, ProductSummary

VALID_ANSWER_TYPES = {"recommendation", "comparison", "clarification", "product_fact", "not_found", "refusal"}


class Pipeline:
    def __init__(self, db, search_engine, llm):
        self.db, self.search, self.llm = db, search_engine, llm
        self.session_locks = [Lock() for _ in range(64)]

    def process_chat(self, req):
        session_id = req.session_id or f"sess_{uuid.uuid4().hex}"
        with self.session_locks[hash((session_id, req.customer_id)) % len(self.session_locks)]:
            return self._turn(req, session_id)

    def _turn(self, req, session_id):
        start = time.perf_counter()
        trace_id = f"tr_{uuid.uuid4().hex}"
        customer = req.customer_id
        history = self.db.get_session_history(session_id, customer)

        # 1. Guardrails & Unit Normalization
        query, safety = InjectionSanitizer.sanitize(req.query)
        query, filters = UnitNormalizer.normalize_query_and_extract_filters(query)
        if req.filters:
            filters.update(req.filters.model_dump(exclude_none=True))
        privacy = CustomerIdPrivacyGate.check_access(query, customer)

        tools, rows, orders, products, sources = [], [], [], [], []
        question = None
        plan = {}
        intent = "refusal"
        kind = "refusal"

        # 2. Hard Privacy / Safety Refusal
        if not safety.passed or not privacy.passed:
            answer = privacy.reason if not privacy.passed else "I can help you search the catalogue or check your own orders."

        # 3. Private Order Lookup (Always SQLite, never LLM-generated)
        elif CustomerIdPrivacyGate.is_order_related_query(query):
            intent = "order_status"
            tools.append({"tool": "db.get_customer_orders", "customer_id": customer})
            orders = self.db.get_customer_orders(customer)
            kind = "product_fact" if orders else "not_found"
            answer = "\n".join(
                f"- **{o['order_id']}** · {o['product_title']} · {o['order_date']} · `{o['order_status']}`"
                for o in orders
            ) or "There are no recorded orders for this shopper."

        # 4. LLM-First RAG Flow
        else:
            # Step A: LLM Planner
            plan = self.llm.plan_turn(query, history, filters)
            tools.append({"tool": "llm.plan_turn", "model": self.llm.gemini_model})
            intent = plan.get("intent", "product_search")
            filters = plan.get("filters", filters)
            search_query = plan.get("search_query", query)
            product_ids = plan.get("product_ids") or re.findall(r"(?<!\w)P-[\w-]+", query, re.I)

            # Step B: RAG Retrieval (ChromaDB + FTS5 + SQLite Hard Filters)
            if product_ids:
                rows = self.db.compare_products(product_ids)
                tools.append({"tool": "db.compare_products", "product_ids": product_ids})
            else:
                cheaper = bool(re.search(r"\b(cheaper|cheapest|cheap|sasta|saste)\b|सस्ता|सस्ते", query, re.I))
                rows = self.search.search(search_query, filters, top_k=8, cheapest=cheaper)
                tools.append({"tool": "search.hybrid_rag", "query": search_query, "filters": filters})

            # Step C: LLM RAG Synthesis
            rag_out = self.llm.generate_rag_response(query, history, rows, intent, filters)
            if rag_out:
                tools.append({"tool": "llm.generate_rag_response", "model": self.llm.gemini_model})
                kind = rag_out.get("answer_type", "recommendation")
                if kind not in VALID_ANSWER_TYPES:
                    kind = "recommendation" if rows else "not_found"
                answer = rag_out["answer"]
                question = rag_out.get("follow_up_question")

                selected_ids = set(rag_out.get("selected_product_ids") or [])
                display_rows = [p for p in rows if p["product_id"] in selected_ids] if selected_ids else rows[:5]
                if kind in ("not_found", "clarification"):
                    display_rows = []
            else:
                # Fallback if LLM is offline
                display_rows = rows[:5]
                kind = "recommendation" if display_rows else "not_found"
                if display_rows:
                    answer = "Here are the matching products from our catalogue:\n" + "\n".join(
                        f"- **{p['title']}** ({p['product_id']}) — {p['currency']} {p['price']:g}" for p in display_rows
                    )
                else:
                    answer = "I couldn't find matching products in our catalogue."

            for p in display_rows:
                products.append(
                    ProductSummary(
                        **p,
                        name=p["title"],
                        in_stock=p["stock_quantity"] > 0,
                        reason=f"{p['currency']} {p['price']:g} · ★ {p['rating']:g}",
                    )
                )
                sources.append({
                    "product_id": p["product_id"],
                    "fields": ["title", "brand", "category", "price", "currency", "stock_quantity", "rating", "specs"],
                })

        elapsed = round((time.perf_counter() - start) * 1000, 2)
        response = ChatResponse(
            trace_id=trace_id,
            session_id=session_id,
            customer_id=customer,
            answer=answer,
            answer_type=kind,
            products=products,
            orders=orders,
            sources=sources,
            follow_up_question=question,
            active_filters=filters,
            latency_ms=elapsed,
        )

        history.append({"role": "user", "content": req.query})
        history.append({"role": "assistant", "content": answer})
        self.db.update_session(session_id, customer, history)
        self.db.save_audit_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trace_id": trace_id,
            "customer_id": customer,
            "session_id": session_id,
            "user_query": req.query,
            "normalized_query": query,
            "intent": intent,
            "parsed_filters": filters,
            "applied_hard_filters": filters,
            "tool_calls": tools,
            "guardrail_flags": {"privacy_violation": not privacy.passed, "injection_detected": not safety.passed},
            "llm_plan": plan,
            "retrieved_candidates": [{"id": p["product_id"], "score": p.get("score")} for p in rows],
            "total_latency_ms": elapsed,
            "final_answer_type": kind,
            "response": answer,
            "result": response.model_dump(),
        })
        return response
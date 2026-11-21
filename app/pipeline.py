"""End-to-End Orchestrator Pipeline for Phoenix Shopper Assistant.

Handles:
- Guardrail Privacy Gate & Injection Sanitization
- Unit Normalization
- Intent & Tool Routing (Hybrid Search, SQL Hard Filters, Order Lookup, Comparison)
- Grounded Response Synthesis
- Latency & Audit Trace Logging
"""

import time
from typing import Any, Dict, List, Optional
import uuid

from app.db import DatabaseManager
from app.guardrails import CustomerIdPrivacyGate, InjectionSanitizer, UnitNormalizer
from app.llm import LLMClient
from app.schemas import AnswerType, ChatRequest, ChatResponse, OrderItem, ProductSummary
from app.search import HybridSearchEngine


class Pipeline:
    def __init__(self, db: DatabaseManager, search_engine: HybridSearchEngine, llm: LLMClient):
        self.db = db
        self.search = search_engine
        self.llm = llm

    def process_chat(self, req: ChatRequest) -> ChatResponse:
        start_time = time.perf_counter()
        trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
        customer_id = req.customer_id
        latency_breakdown: Dict[str, float] = {}

        # 1. Guardrail Step 1: Injection Sanitization
        t0 = time.perf_counter()
        sanitized_query, injection_res = InjectionSanitizer.sanitize(req.query)
        latency_breakdown["guardrail_injection_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if not injection_res.passed:
            total_latency = round((time.perf_counter() - start_time) * 1000, 2)
            blocked_msg = "Security Alert: Your request was flagged and blocked by our safety guardrails."
            self._save_trace(
                trace_id=trace_id,
                session_id=session_id,
                customer_id=customer_id,
                user_query=req.query,
                normalized_query=sanitized_query,
                guardrail_flags={"injection_detected": True, "reason": injection_res.reason},
                intent="guardrail_blocked",
                parsed_filters={},
                retrieved_candidates=[],
                applied_hard_filters={},
                tool_calls=[],
                llm_plan={},
                latency_breakdown=latency_breakdown,
                total_latency_ms=total_latency,
                final_answer_type="guardrail_blocked",
                response=blocked_msg,
            )
            return ChatResponse(
                trace_id=trace_id,
                session_id=session_id,
                customer_id=customer_id,
                answer=blocked_msg,
                answer_type="guardrail_blocked",
                products=[],
                orders=[],
                active_filters={},
                latency_ms=total_latency,
            )

        # 2. Guardrail Step 2: Unit Normalization & Filter Extraction
        t0 = time.perf_counter()
        normalized_query, unit_filters = UnitNormalizer.normalize_query_and_extract_filters(sanitized_query)
        latency_breakdown["unit_normalization_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # Merge with explicit request filters if provided
        active_filters = dict(unit_filters)
        if req.filters:
            active_filters.update(req.filters)

        # 3. Session History Retrieval
        t0 = time.perf_counter()
        history = self.db.get_session_history(session_id)
        latency_breakdown["session_read_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 4. LLM Planner
        t0 = time.perf_counter()
        plan = self.llm.plan_intent_and_filters(
            query=normalized_query,
            history=history,
            normalized_filters=active_filters,
        )
        latency_breakdown["llm_planner_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        intent = plan.get("intent", "product_search")
        search_query = plan.get("search_query", normalized_query)
        active_filters = plan.get("filters", active_filters)
        tool_calls = []

        products_result: List[Dict[str, Any]] = []
        orders_result: List[Dict[str, Any]] = []
        final_answer_type: AnswerType = "product_recommendation"

        # 5. Guardrail Step 3: Privacy Gate for Order Inquiries
        t0 = time.perf_counter()
        privacy_res = CustomerIdPrivacyGate.check_access(
            user_query=normalized_query,
            current_customer_id=customer_id,
        )
        latency_breakdown["guardrail_privacy_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if not privacy_res.passed:
            total_latency = round((time.perf_counter() - start_time) * 1000, 2)
            self._save_trace(
                trace_id=trace_id,
                session_id=session_id,
                customer_id=customer_id,
                user_query=req.query,
                normalized_query=normalized_query,
                guardrail_flags={"privacy_violation": True, "reason": privacy_res.reason},
                intent="order_status",
                parsed_filters=active_filters,
                retrieved_candidates=[],
                applied_hard_filters={},
                tool_calls=[],
                llm_plan=plan,
                latency_breakdown=latency_breakdown,
                total_latency_ms=total_latency,
                final_answer_type="guardrail_blocked",
                response=privacy_res.reason,
            )
            return ChatResponse(
                trace_id=trace_id,
                session_id=session_id,
                customer_id=customer_id,
                answer=privacy_res.reason,
                answer_type="guardrail_blocked",
                products=[],
                orders=[],
                active_filters=active_filters,
                latency_ms=total_latency,
            )

        # 6. Tool Routing & Execution
        t0 = time.perf_counter()
        if intent == "order_status":
            tool_calls.append({"tool": "db.get_customer_orders", "customer_id": customer_id})
            orders_result = self.db.get_customer_orders(customer_id) if customer_id else []
            final_answer_type = "order_status"

        elif intent == "product_comparison":
            tool_calls.append({"tool": "search.hybrid_search", "query": search_query})
            # Retrieve products relevant to the comparison query
            products_result = self.search.search(query=search_query, filters=active_filters, top_k=4)
            final_answer_type = "product_comparison"

        else:
            # Default: Hybrid Search with Filter Merge
            tool_calls.append({"tool": "search.hybrid_search", "query": search_query, "filters": active_filters})
            products_result = self.search.search(query=search_query, filters=active_filters, top_k=10)
            final_answer_type = "product_recommendation"

        latency_breakdown["tool_execution_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 7. LLM Synthesizer
        t0 = time.perf_counter()
        answer = self.llm.synthesize_response(
            query=normalized_query,
            intent=intent,
            products=products_result,
            orders=orders_result,
            active_filters=active_filters,
            history=history,
        )
        latency_breakdown["llm_synthesizer_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 8. Session Memory Persistence
        history.append({"role": "user", "content": req.query})
        history.append({"role": "assistant", "content": answer})
        self.db.update_session(session_id=session_id, customer_id=customer_id, messages=history[-20:])

        total_latency = round((time.perf_counter() - start_time) * 1000, 2)

        # 9. Audit Trace Logging
        self._save_trace(
            trace_id=trace_id,
            session_id=session_id,
            customer_id=customer_id,
            user_query=req.query,
            normalized_query=normalized_query,
            guardrail_flags={"injection_detected": False, "privacy_violation": False},
            intent=intent,
            parsed_filters=active_filters,
            retrieved_candidates=[{"id": p.get("product_id"), "title": p.get("title"), "score": p.get("score")} for p in products_result],
            applied_hard_filters=active_filters,
            tool_calls=tool_calls,
            llm_plan=plan,
            latency_breakdown=latency_breakdown,
            total_latency_ms=total_latency,
            final_answer_type=final_answer_type,
            response=answer,
        )

        # 10. Format Output
        product_summaries = [
            ProductSummary(
                product_id=p["product_id"],
                title=p["title"],
                category=p["category"],
                brand=p["brand"],
                price=float(p["price"]),
                currency=p.get("currency", "INR"),
                stock_quantity=int(p.get("stock_quantity", 0)),
                rating=float(p.get("rating", 0.0)),
                specs=p.get("specs", {}),
                score=p.get("score"),
            )
            for p in products_result
        ]

        order_items = [
            OrderItem(
                order_id=o["order_id"],
                customer_id=o["customer_id"],
                product_id=o["product_id"],
                product_title=o.get("product_title"),
                quantity=int(o["quantity"]),
                total_amount=float(o["total_amount"]),
                order_status=o["order_status"],
                order_date=o["order_date"],
                tracking_number=o.get("tracking_number"),
            )
            for o in orders_result
        ]

        return ChatResponse(
            trace_id=trace_id,
            session_id=session_id,
            customer_id=customer_id,
            answer=answer,
            answer_type=final_answer_type,
            products=product_summaries,
            orders=order_items,
            active_filters=active_filters,
            latency_ms=total_latency,
        )

    def _save_trace(self, **kwargs):
        trace_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **kwargs,
        }
        self.db.save_audit_trace(trace_data)

"""Automated Evaluation Runner for Phoenix Shopper Assistant.

Runs 40+ test cases from eval/eval_set.json against POST /chat and GET /trace/{trace_id}.
Evaluates:
- Functional accuracy & answer_type compliance
- Guardrail Defense Rate (Security & Injection Attacks)
- Customer Privacy Gate Enforcement
- Unit Normalization Accuracy
- Latency (Avg, p50, p95)
- Trace Record Integrity
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Try importing in-process fallback if HTTP server is not running
IN_PROCESS_AVAILABLE = False
try:
    from app.db import DatabaseManager
    from app.llm import LLMClient
    from app.pipeline import Pipeline
    from app.schemas import ChatRequest
    from app.search import HybridSearchEngine
    IN_PROCESS_AVAILABLE = True
except Exception:
    pass


class Evaluator:
    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.use_in_process = False
        self.pipeline = None
        self._setup_client()

    def _setup_client(self):
        # Test if server is up
        try:
            req = urllib.request.Request(f"{self.api_base}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    print(f"🔗 Connected to running server at {self.api_base}")
                    return
        except Exception:
            pass

        if IN_PROCESS_AVAILABLE:
            print("⚡ Server not reachable on port 8000. Running in-process pipeline evaluation...")
            self.use_in_process = True
            db_path = os.path.join(os.path.dirname(__file__), "..", "shop.db")
            db = DatabaseManager(db_path=db_path)
            search_engine = HybridSearchEngine(db=db)
            llm_client = LLMClient()
            self.pipeline = Pipeline(db=db, search_engine=search_engine, llm=llm_client)

            # Ensure data is seeded
            for fname in ["products.json", "catalogue.json"]:
                cat_path = os.path.join(os.path.dirname(__file__), "..", "data", fname)
                if os.path.exists(cat_path):
                    with open(cat_path, "r", encoding="utf-8") as f:
                        search_engine.upsert_products(json.load(f))
                    break
            shop_path = os.path.join(os.path.dirname(__file__), "..", "data", "shoppers.json")
            if os.path.exists(shop_path):
                with open(shop_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    if isinstance(raw_data, list):
                        shoppers_list = []
                        orders_list = []
                        for s in raw_data:
                            cid = s.get("customer_id") or s.get("shopper_id")
                            shoppers_list.append({
                                "customer_id": cid,
                                "name": s.get("name", "Shopper"),
                                "email": s.get("email", f"{cid.lower()}@example.com"),
                                "loyalty_tier": s.get("loyalty_tier", "Gold"),
                                "address": s.get("address", ""),
                            })
                            for o in s.get("orders", []):
                                orders_list.append({
                                    "order_id": o.get("order_id"),
                                    "customer_id": cid,
                                    "product_id": o.get("product_id"),
                                    "quantity": o.get("quantity") or o.get("qty", 1),
                                    "total_amount": float(o.get("total_amount", 0.0)),
                                    "order_status": o.get("order_status") or o.get("status", "Delivered"),
                                    "order_date": o.get("order_date") or o.get("ordered_at", "2026-11-01"),
                                    "tracking_number": o.get("tracking_number", ""),
                                })
                        db.upsert_shoppers(shoppers_list)
                        db.upsert_orders(orders_list)
                    else:
                        db.upsert_shoppers(raw_data.get("shoppers", []))
                        db.upsert_orders(raw_data.get("orders", []))
        else:
            print("⚠️ Server is not running and in-process pipeline could not be loaded.")

    def run_chat(self, query: str, customer_id: Optional[str]) -> Dict[str, Any]:
        if self.use_in_process and self.pipeline:
            req = ChatRequest(query=query, customer_id=customer_id)
            res = self.pipeline.process_chat(req)
            return res.model_dump()

        payload = json.dumps({"query": query, "customer_id": customer_id}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base}/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        if self.use_in_process and self.pipeline:
            return self.pipeline.db.get_audit_trace(trace_id)

        try:
            req = urllib.request.Request(f"{self.api_base}/trace/{trace_id}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None


def run_evaluation():
    eval_set_path = os.path.join(os.path.dirname(__file__), "eval_set.json")
    with open(eval_set_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    evaluator = Evaluator()

    total_tests = len(test_cases)
    passed_tests = 0
    guardrail_security_tests = 0
    guardrail_security_passed = 0
    privacy_tests = 0
    privacy_passed = 0
    latencies: List[float] = []

    print(f"\n=======================================================")
    print(f"🚀 Running Phoenix E-Commerce Test Suite ({total_tests} Cases)")
    print(f"=======================================================\n")

    results_table = []

    for tc in test_cases:
        tc_id = tc["id"]
        tc_name = tc["name"]
        query = tc["query"]
        customer_id = tc.get("customer_id")
        expected_type = tc["expected_answer_type"]
        should_pass_guards = tc.get("should_pass_guardrails", True)

        is_security_test = "Security:" in tc_name
        is_privacy_test = "Privacy Gate:" in tc_name

        if is_security_test:
            guardrail_security_tests += 1
        if is_privacy_test:
            privacy_tests += 1

        t0 = time.perf_counter()
        try:
            res = evaluator.run_chat(query, customer_id)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            latencies.append(elapsed_ms)

            actual_type = res.get("answer_type")
            trace_id = res.get("trace_id")
            trace_valid = evaluator.get_trace(trace_id) is not None if trace_id else False

            type_mapping = {
                "recommendation": "product_recommendation",
                "comparison": "product_comparison",
                "refusal": "guardrail_blocked",
            }
            mapped_actual = type_mapping.get(actual_type, actual_type)

            # Verify conditions
            type_match = mapped_actual == expected_type or actual_type == expected_type
            guard_match = (mapped_actual != "guardrail_blocked") if should_pass_guards else (mapped_actual == "guardrail_blocked")

            test_passed = type_match and guard_match and trace_valid

            if test_passed:
                passed_tests += 1
                if is_security_test:
                    guardrail_security_passed += 1
                if is_privacy_test:
                    privacy_passed += 1
                status_icon = "✅ PASS"
            else:
                status_icon = "❌ FAIL"

            print(f"[{status_icon}] {tc_id}: {tc_name:<45} | Type: {actual_type:<22} | Latency: {elapsed_ms:>6.1f}ms")

        except Exception as e:
            print(f"[❌ FAIL] {tc_id}: {tc_name:<45} | ERROR: {str(e)[:30]}")

    # Compute Statistics
    pass_rate = (passed_tests / total_tests) * 100
    security_rate = (guardrail_security_passed / guardrail_security_tests * 100) if guardrail_security_tests else 100.0
    privacy_rate = (privacy_passed / privacy_tests * 100) if privacy_tests else 100.0

    latencies.sort()
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p50_latency = latencies[len(latencies) // 2] if latencies else 0.0
    p95_latency = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

    print(f"\n=======================================================")
    print(f"📊 EVALUATION SUMMARY REPORT")
    print(f"=======================================================")
    print(f"Total Test Cases:          {total_tests}")
    print(f"Passed Test Cases:         {passed_tests}")
    print(f"Pass Rate:                 {pass_rate:.1f}%")
    print(f"Guardrail Defense Rate:    {security_rate:.1f}% ({guardrail_security_passed}/{guardrail_security_tests})")
    print(f"Privacy Gate Pass Rate:    {privacy_rate:.1f}% ({privacy_passed}/{privacy_tests})")
    print(f"Avg Latency:               {avg_latency:.2f} ms")
    print(f"p50 Latency:               {p50_latency:.2f} ms")
    print(f"p95 Latency:               {p95_latency:.2f} ms")
    print(f"=======================================================\n")

    if pass_rate < 85:
        sys.exit(1)


if __name__ == "__main__":
    run_evaluation()

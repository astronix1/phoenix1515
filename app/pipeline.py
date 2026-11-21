"""Route each shopping turn, using SQLite as the source for customer-visible facts."""

import re
import time
import uuid
from threading import Lock

from app.db import CATEGORY_MAPPING
from app.guardrails import CustomerIdPrivacyGate, InjectionSanitizer, UnitNormalizer
from app.schemas import ChatResponse, ProductSummary
from app.search import PRODUCT_TYPES, search_terms


def language(query):
    if re.search(r"[\u0900-\u097f]", query):
        return "hi"
    if re.search(r"\b(sasta|saste|mujhe|chahiye|dikhao|liye|wala|badhiya|mera|mere|ka)\b", query, re.I):
        return "hinglish"
    return "en"


def localized(lang, english, hindi, hinglish):
    return {"en": english, "hi": hindi, "hinglish": hinglish}[lang]


def compare_answer(rows, lang):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    fields = {"Price": [f"{p['currency']} {p['price']:g}" for p in rows],
              "Stock": [p["stock_quantity"] for p in rows], "Rating": [p["rating"] for p in rows]}
    for key in sorted(set().union(*(p["specs"] for p in rows))):
        fields[key] = [p["specs"].get(key, "—") for p in rows]
    table = [["Field", *(f"{p['title']} ({p['product_id']})" for p in rows)], ["---"] * (len(rows) + 1)]
    table.extend([key, *values] for key, values in fields.items())
    lowest = min(p["price"] for p in rows)
    names = ", ".join(p["title"] for p in rows if p["price"] == lowest)
    verdict = localized(lang, f"Lowest price: {names}.", f"सबसे कम कीमत: {names}।", f"Sabse kam daam: {names}.")
    return "\n".join("| " + " | ".join(map(cell, row)) + " |" for row in table) + "\n\n" + verdict


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
        previous = next((m["state"] for m in reversed(history) if "state" in m), {})
        query, safety = InjectionSanitizer.sanitize(req.query)
        query, filters = UnitNormalizer.normalize_query_and_extract_filters(query)
        explicit = req.filters.model_dump(exclude_none=True) if req.filters else {}
        filters.update(explicit)
        privacy = CustomerIdPrivacyGate.check_access(query, customer)
        lang = language(query)
        tools, rows, orders, products, sources = [], [], [], [], []
        question = None
        plan = {}
        state = None
        intent = "refusal"
        kind = "refusal"
        if not safety.passed or not privacy.passed:
            answer = privacy.reason if not privacy.passed else "I can help you search the catalogue or check your own orders."
        elif CustomerIdPrivacyGate.is_order_related_query(query):
            intent = "order_status"
            tools.append({"tool": "db.get_customer_orders", "customer_id": customer})
            orders = self.db.get_customer_orders(customer)
            kind = "product_fact" if orders else "not_found"
            answer = "\n".join(f"- {o['order_id']} · {o['product_title']} · {o['order_date']} · {o['order_status']}"
                               for o in orders) or "There are no recorded orders for this shopper."
        else:
            plan = self.llm.plan_intent_and_filters(query, [previous] if previous else [], filters)
            intent = plan.get("intent", "product_search")
            filters = {**plan["filters"], **filters}
            if "category" in filters and filters["category"]:
                cat_raw = str(filters["category"]).lower().strip()
                cat = CATEGORY_MAPPING.get(cat_raw, cat_raw)
                if cat in ("Electronics", "Footwear", "Sports & Outdoors", "Fashion", "Beauty & Care", "Home & Kitchen"):
                    filters["category"] = cat
                else:
                    filters.pop("category", None)
            catalogue = self.db.get_all_products(limit=-1)
            brands = {p["brand"] for p in catalogue}
            for brand in brands:
                if re.search(r"(?<!\w)" + re.escape(brand) + r"(?!\w)", query, re.I):
                    filters.setdefault("brand", brand)
            if m := re.fullmatch(r"only\s+(.+?)[.!?]?", query, re.I):
                if not filters:
                    filters["brand"] = m[1]
            terms = search_terms(plan.get("search_query", query))
            has_type = any(t in PRODUCT_TYPES for t in search_terms(query))
            cheaper = bool(re.search(r"\b(cheaper|cheapest|cheap|sasta|saste)\b|सस्ता|सस्ते", query, re.I))
            ids = re.findall(r"(?<!\w)P-[\w-]+", query, re.I)
            by_id = {p["product_id"].casefold(): p["product_id"] for p in catalogue}
            ids = [by_id.get(pid.casefold(), pid) for pid in ids]
            named = [p for p in catalogue if re.search(r"(?<!\w)" + re.escape(p["title"]) + r"(?!\w)", query, re.I)]
            if not ids:
                ids = [p["product_id"] for p in sorted(named, key=lambda p: query.lower().find(p["title"].lower()))]
            comparison = intent == "product_comparison" or re.search(r"\b(compare|vs|difference between)\b", query, re.I)
            fact = bool(ids or intent == "product_fact" or re.search(r"\b(is|does|what(?:'s| is)|how much|how many|price of|stock of)\b", query, re.I)
                        and re.search(r"\b(stock|size|blue|available|price|cost|battery|ram|storage|weigh|weight|colour|color|left)\b", query, re.I))

            prev_brand = str(previous.get("filters", {}).get("brand", "")).lower()
            curr_brand = str(filters.get("brand", "")).lower()
            brand_changed = bool(curr_brand and prev_brand and curr_brand != prev_brand)
            explicit_brand_new = bool(curr_brand and not prev_brand)

            follow = (
                bool(previous)
                and not ids
                and not brand_changed
                and not explicit_brand_new
                and (
                    re.search(r"\b(first|second|third|those|these|ones|the blue one)\b", query, re.I)
                    or (not has_type and (cheaper or filters or previous.get("questions")))
                )
            )
            subject = previous.get("subject", "") if follow else plan.get("search_query", query)
            if follow:
                merged = dict(previous.get("filters", {}))
                merged.update(filters)
                filters = merged
                if lang == "en":
                    lang = previous.get("language", lang)
            turns = previous.get("questions", 0) if follow or query == previous.get("query") else 0
            search_filters = dict(filters)
            prior_ids = previous.get("ids", [])
            vague = not filters and not cheaper and (not terms or len(terms) == 1 and terms[0] in PRODUCT_TYPES
                    or intent == "clarification" or re.fullmatch(r"(i need |show me |looking for )?(a |an )?(gift|something|electronics|footwear|clothes|help)[.!?]?", query, re.I))
            if comparison:
                if not ids and re.search(r"\b(first two|these two|those two|them|both)\b", query, re.I):
                    ids = prior_ids[:2]
                tools.append({"tool": "db.compare_products", "product_ids": ids})
                found = {p["product_id"]: p for p in self.db.compare_products(ids)}
                if len(set(ids)) >= 2 and all(pid in found for pid in ids):
                    rows = [found[pid] for pid in dict.fromkeys(ids)]
                    kind = "comparison"
                elif not ids and re.search(r"\b(these|those|first|them|both)\b", query, re.I) and turns < 2:
                    question = "Which two product names or IDs would you like to compare?"
                else:
                    kind = "not_found"
            elif vague and not fact and turns < 2:
                question = localized(lang, "What budget do you have in mind?" if not turns else "What will you use it for?",
                                     "आपका बजट क्या है?" if not turns else "आप इसे किस लिए चाहते हैं?",
                                     "Aapka budget kya hai?" if not turns else "Aap ise kis liye chahte hain?")
            else:
                if not fact:
                    search_filters["in_stock_only"] = True
                if follow and cheaper and previous.get("prices"):
                    ceiling = min(previous["prices"]) - 0.01
                    search_filters["max_price"] = min(ceiling, search_filters.get("max_price", ceiling))
                if fact and follow and not ids:
                    ordinal = re.search(r"\b(first|second|third)\b", query, re.I)
                    if ordinal:
                        i = ["first", "second", "third"].index(ordinal[1].lower())
                        ids = prior_ids[i:i + 1]
                    else:
                        ids = prior_ids
                if ids or fact and follow:
                    # A stock check can legitimately return an out-of-stock item.
                    candidates = self.db.filter_products(search_filters, ids)
                    indexed = {p["product_id"]: p for p in candidates}
                    rows = [indexed[pid] for pid in ids if pid in indexed]
                    tools.append({"tool": "db.filter_products", "product_ids": ids, "filters": search_filters})
                else:
                    rows = self.search.search(subject, search_filters, top_k=5, cheapest=cheaper)
                    tools.append({"tool": "search.hybrid_search", "query": subject, "filters": search_filters})
                kind = ("product_fact" if fact else "recommendation") if rows else "not_found"
            if question:
                kind, answer = "clarification", question
            elif kind == "comparison":
                answer = compare_answer(rows, lang)
            elif kind == "not_found":
                answer = localized(lang, "I couldn’t find a catalogue match. Would you like to widen the search?",
                                   "कैटलॉग में कोई मेल नहीं मिला। क्या आप खोज बदलना चाहेंगे?",
                                   "Catalogue mein koi match nahi mila. Search badlein?")
            else:
                answer = localized(lang, "Here’s what the catalogue shows.", "कैटलॉग में ये विकल्प मिले।", "Catalogue mein ye options mile.")
            field = self.llm.reason_field(query, filters) if kind == "recommendation" else "price"
            for p in rows:
                value = {"price": f"{p['currency']} {p['price']:g}", "rating": f"★ {p['rating']:g}", "brand": p["brand"]}[field]
                reason = localized(lang, f"{p['title']} matches your search ({value}).",
                                   f"{p['title']} आपकी खोज से मेल खाता है ({value})।",
                                   f"{p['title']} aapki search se match karta hai ({value}).")
                products.append(ProductSummary(**p, name=p["title"], in_stock=p["stock_quantity"] > 0, reason=reason))
                fields = ["title", "brand", "category", "price", "currency", "stock_quantity", "rating", "specs"]
                sources.append({"product_id": p["product_id"], "fields": fields})
                if kind in ("product_fact", "recommendation"):
                    detail = reason
                    if kind == "product_fact":
                        specs = ", ".join(f"{k}={v}" for k, v in p["specs"].items())
                        detail = f"{p['title']} · {p['currency']} {p['price']:g} · Stock {p['stock_quantity']} · {specs}"
                    answer += f"\n\n- {p['product_id']} · {detail}"
            state = {"subject": subject, "query": query, "language": lang, "filters": filters,
                     "ids": [p["product_id"] for p in rows], "prices": [p["price"] for p in rows],
                     "questions": turns + 1 if question else 0}
            filters = search_filters

        elapsed = round((time.perf_counter() - start) * 1000, 2)
        response = ChatResponse(trace_id=trace_id, session_id=session_id, customer_id=customer, answer=answer,
                                answer_type=kind, products=products, orders=orders, sources=sources,
                                follow_up_question=question, active_filters=filters, latency_ms=elapsed)
        history.append({"role": "user", "content": req.query})
        history.append({"role": "assistant", "content": answer, **({"state": state} if state else {})})
        self.db.update_session(session_id, customer, history)
        self.db.save_audit_trace({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "trace_id": trace_id,
            "customer_id": customer, "session_id": session_id, "user_query": req.query, "normalized_query": query,
            "intent": intent, "parsed_filters": filters, "applied_hard_filters": filters, "tool_calls": tools,
            "guardrail_flags": {"privacy_violation": not privacy.passed, "injection_detected": not safety.passed},
            "llm_plan": plan, "retrieved_candidates": [{"id": p["product_id"], "score": p.get("score")} for p in rows],
            "total_latency_ms": elapsed, "final_answer_type": kind, "response": answer, "result": response.model_dump(),
        })
        return response

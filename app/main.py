"""FastAPI Backend Application for Phoenix Shopper Assistant."""

from contextlib import asynccontextmanager
import json
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.db import DatabaseManager
from app.llm import LLMClient
from app.pipeline import Pipeline
from app.schemas import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    ProductBase,
)
from app.search import HybridSearchEngine


# Global components
db: Optional[DatabaseManager] = None
search_engine: Optional[HybridSearchEngine] = None
llm_client: Optional[LLMClient] = None
pipeline: Optional[Pipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, search_engine, llm_client, pipeline
    db_path = os.getenv("SQLITE_DB_PATH", "shop.db")
    db = DatabaseManager(db_path=db_path)
    search_engine = HybridSearchEngine(db=db)
    llm_client = LLMClient()
    pipeline = Pipeline(db=db, search_engine=search_engine, llm=llm_client)

    # Check if DB has products; if empty, load default sample data
    products = db.get_all_products(limit=5)
    if not products:
        for fname in ["products.json", "catalogue.json"]:
            sample_path = os.path.join(os.path.dirname(__file__), "..", "data", fname)
            if os.path.exists(sample_path):
                with open(sample_path, "r", encoding="utf-8") as f:
                    catalogue = json.load(f)
                    search_engine.upsert_products(catalogue)
                break

        shoppers_path = os.path.join(os.path.dirname(__file__), "..", "data", "shoppers.json")
        if os.path.exists(shoppers_path):
            with open(shoppers_path, "r", encoding="utf-8") as f:
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

    yield


app = FastAPI(
    title="Phoenix Shopper Assistant API",
    description="High-performance Agentic E-Commerce API with Hybrid Search, Guardrails, and Tracing",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for UI & Evaluation scripts
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "phoenix1515-api",
        "mock_llm": llm_client.mock_mode if llm_client else True,
    }


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """Processes shopper natural language queries through the guardrail and hybrid retrieval pipeline."""
    if not pipeline:
        raise HTTPException(status_code=500, detail="Pipeline not initialized")
    return pipeline.process_chat(request)


@app.get("/products/{product_id}")
def get_product(product_id: str):
    """Fetches full specifications for a single product SKU."""
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    product = db.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return product


@app.post("/ingest", response_model=IngestResponse)
def ingest_products(request: IngestRequest):
    """Ingests and indexes products into both SQLite FTS5 and the vector index."""
    if not search_engine:
        raise HTTPException(status_code=500, detail="Search engine not initialized")

    items = [p.model_dump() for p in request.products]
    search_engine.upsert_products(items)
    return IngestResponse(
        ingested_count=len(items),
        message=f"Successfully ingested and indexed {len(items)} products.",
    )


@app.get("/trace/{trace_id}")
def get_trace(trace_id: str):
    """Retrieves end-to-end execution audit trace including guardrails, latencies, and tool calls."""
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    trace = db.get_audit_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return trace


@app.get("/shoppers")
def get_shoppers():
    """Returns list of active shoppers for testing and customer identity selection."""
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db.get_all_shoppers()


@app.get("/orders/{customer_id}")
def get_orders(customer_id: str):
    """Retrieves orders for a given customer."""
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db.get_customer_orders(customer_id)

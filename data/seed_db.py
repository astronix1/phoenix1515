"""Database & Vector Index Seeding Script for Phoenix Shopper Assistant.

Reads data/products.json and data/shoppers.json, then seeds:
1. SQLite database (shop.db) -> products, products_fts, shoppers, orders
2. ChromaDB (chroma_db/) -> vector embeddings collection
"""

import json
import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.db import DatabaseManager
from app.search import HybridSearchEngine


def seed():
    db_path = os.getenv("SQLITE_DB_PATH", os.path.join(BASE_DIR, "shop.db"))
    print(f"📦 Initializing database at: {db_path}")
    db = DatabaseManager(db_path)
    search_engine = HybridSearchEngine(db)

    # 1. Ingest Products into SQLite + ChromaDB
    prod_files = ["products.json", "catalogue.json"]
    products_seeded = 0
    for fname in prod_files:
        p_path = os.path.join(BASE_DIR, "data", fname)
        if os.path.exists(p_path):
            with open(p_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                search_engine.upsert_products(data)
                products_seeded = len(data)
                print(f"✅ Ingested {products_seeded} products from data/{fname} -> SQLite + Vector Index")
            break

    # 2. Ingest Shoppers and Orders
    shop_path = os.path.join(BASE_DIR, "data", "shoppers.json")
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
                print(f"✅ Ingested {len(shoppers_list)} shoppers and {len(orders_list)} orders -> SQLite")
            else:
                shoppers = raw_data.get("shoppers", [])
                orders = raw_data.get("orders", [])
                db.upsert_shoppers(shoppers)
                db.upsert_orders(orders)
                print(f"✅ Ingested {len(shoppers)} shoppers and {len(orders)} orders -> SQLite")

    print("\n🎉 Seeding complete! Total verified in shop.db:")
    print(f"   • Products in DB: {len(db.get_all_products(limit=500))}")
    print(f"   • Shoppers in DB: {len(db.get_all_shoppers())}")


if __name__ == "__main__":
    seed()

"""Database module for SQLite storage, FTS5 full-text search, and audit traces."""

import json
import sqlite3
from typing import Any, Dict, List, Optional


class DatabaseManager:
    def __init__(self, db_path: str = "shop.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self):
        """Initializes tables, FTS5 virtual tables, and synchronization triggers."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Products Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                stock_quantity INTEGER NOT NULL DEFAULT 0,
                rating REAL NOT NULL DEFAULT 0.0,
                specs TEXT NOT NULL DEFAULT '{}',
                tags TEXT NOT NULL DEFAULT '[]',
                multilingual_titles TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. Products FTS5 Virtual Table
            cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
                product_id UNINDEXED,
                title,
                description,
                category,
                brand,
                specs,
                tags,
                tokenize = 'porter unicode61'
            );
            """)

            # Triggers to keep FTS5 synchronized with products table
            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_products_insert AFTER INSERT ON products BEGIN
                INSERT INTO products_fts(product_id, title, description, category, brand, specs, tags)
                VALUES (new.product_id, new.title, new.description, new.category, new.brand, new.specs, new.tags);
            END;
            """)

            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_products_delete AFTER DELETE ON products BEGIN
                DELETE FROM products_fts WHERE product_id = old.product_id;
            END;
            """)

            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_products_update AFTER UPDATE ON products BEGIN
                DELETE FROM products_fts WHERE product_id = old.product_id;
                INSERT INTO products_fts(product_id, title, description, category, brand, specs, tags)
                VALUES (new.product_id, new.title, new.description, new.category, new.brand, new.specs, new.tags);
            END;
            """)

            # 3. Shoppers / Customers Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS shoppers (
                customer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                loyalty_tier TEXT NOT NULL DEFAULT 'Bronze',
                address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 4. Orders Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                total_amount REAL NOT NULL,
                order_status TEXT NOT NULL,
                order_date TEXT NOT NULL,
                tracking_number TEXT,
                FOREIGN KEY (customer_id) REFERENCES shoppers(customer_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
            """)

            # 5. Sessions Table (Chat Conversation State)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                customer_id TEXT,
                messages TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 6. Audit Traces Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_traces (
                trace_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                customer_id TEXT,
                session_id TEXT,
                user_query TEXT NOT NULL,
                answer_type TEXT NOT NULL,
                response TEXT NOT NULL,
                trace_data TEXT NOT NULL
            );
            """)

            conn.commit()

    # Product Operations
    def upsert_products(self, products: List[Dict[str, Any]]) -> int:
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for p in products:
                title = p.get("title") or p.get("name") or "Product"
                desc = p.get("description", "")
                cat = p.get("category", "General")
                brand = p.get("brand", "Generic")
                price = float(p.get("price") if p.get("price") is not None else p.get("price_inr", 0.0))
                currency = p.get("currency", "INR")
                stock = int(p.get("stock_quantity") if p.get("stock_quantity") is not None else p.get("stock", 0))
                rating = float(p.get("rating", 0.0))
                raw_specs = p.get("specs") if p.get("specs") is not None else p.get("attributes", {})

                specs_str = json.dumps(raw_specs) if isinstance(raw_specs, dict) else str(raw_specs)
                tags_str = json.dumps(p.get("tags", [])) if isinstance(p.get("tags"), list) else str(p.get("tags", "[]"))
                multi_str = json.dumps(p.get("multilingual_titles", {})) if isinstance(p.get("multilingual_titles"), dict) else str(p.get("multilingual_titles", "{}"))

                cursor.execute("""
                INSERT INTO products (product_id, title, description, category, brand, price, currency, stock_quantity, rating, specs, tags, multilingual_titles)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    category=excluded.category,
                    brand=excluded.brand,
                    price=excluded.price,
                    currency=excluded.currency,
                    stock_quantity=excluded.stock_quantity,
                    rating=excluded.rating,
                    specs=excluded.specs,
                    tags=excluded.tags,
                    multilingual_titles=excluded.multilingual_titles;
                """, (
                    p["product_id"],
                    title,
                    desc,
                    cat,
                    brand,
                    price,
                    currency,
                    stock,
                    rating,
                    specs_str,
                    tags_str,
                    multi_str,
                ))
                count += 1
            conn.commit()
        return count

    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE product_id = ?", (product_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_product(row)

    def search_fts(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Performs full-text BM25 search across products."""
        # Sanitize query for FTS5 syntax
        clean_terms = [t for t in query.replace("'", " ").replace('"', " ").split() if t.isalnum()]
        if not clean_terms:
            return self.get_all_products(limit=limit)

        match_expression = " OR ".join(f'"{term}"*' for term in clean_terms)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                SELECT p.*, bm25(products_fts) AS rank_score
                FROM products_fts fts
                JOIN products p ON fts.product_id = p.product_id
                WHERE products_fts MATCH ?
                ORDER BY rank_score ASC
                LIMIT ?;
                """, (match_expression, limit))
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to LIKE query if FTS expression fails
                cursor.execute("""
                SELECT *, 0.0 AS rank_score FROM products
                WHERE title LIKE ? OR description LIKE ? OR category LIKE ?
                LIMIT ?;
                """, (f"%{clean_terms[0]}%", f"%{clean_terms[0]}%", f"%{clean_terms[0]}%", limit))
                rows = cursor.fetchall()

            return [self._row_to_product(r) for r in rows]

    def filter_products(self, filters: Dict[str, Any], candidate_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Applies SQL hard filters (price range, category, brand, stock, ratings)."""
        conditions = []
        params = []

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ",".join("?" for _ in candidate_ids)
            conditions.append(f"product_id IN ({placeholders})")
            params.extend(candidate_ids)

        if "category" in filters and filters["category"]:
            conditions.append("LOWER(category) = LOWER(?)")
            params.append(filters["category"])

        if "brand" in filters and filters["brand"]:
            conditions.append("LOWER(brand) = LOWER(?)")
            params.append(filters["brand"])

        if "min_price" in filters and filters["min_price"] is not None:
            conditions.append("price >= ?")
            params.append(float(filters["min_price"]))

        if "max_price" in filters and filters["max_price"] is not None:
            conditions.append("price <= ?")
            params.append(float(filters["max_price"]))

        if filters.get("in_stock_only"):
            conditions.append("stock_quantity > 0")

        if "min_rating" in filters and filters["min_rating"] is not None:
            conditions.append("rating >= ?")
            params.append(float(filters["min_rating"]))

        sql = "SELECT * FROM products"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rating DESC, price ASC LIMIT 20;"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            products = [self._row_to_product(r) for r in rows]

        # In-memory check for RAM or Storage in JSON specs if specified
        if "ram_gb" in filters:
            req_ram = filters["ram_gb"]
            products = [p for p in products if p.get("specs", {}).get("ram_gb") == req_ram or f"{req_ram}GB" in str(p.get("specs"))]

        return products

    def compare_products(self, product_ids: List[str]) -> List[Dict[str, Any]]:
        if not product_ids:
            return []
        placeholders = ",".join("?" for _ in product_ids)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM products WHERE product_id IN ({placeholders})", product_ids)
            return [self._row_to_product(r) for r in cursor.fetchall()]

    def get_all_products(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products LIMIT ?", (limit,))
            return [self._row_to_product(r) for r in cursor.fetchall()]

    def _row_to_product(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["specs"] = json.loads(d["specs"]) if isinstance(d.get("specs"), str) else (d.get("specs") or {})
        except Exception:
            d["specs"] = {}
        try:
            d["tags"] = json.loads(d["tags"]) if isinstance(d.get("tags"), str) else (d.get("tags") or [])
        except Exception:
            d["tags"] = []
        try:
            d["multilingual_titles"] = json.loads(d["multilingual_titles"]) if isinstance(d.get("multilingual_titles"), str) else (d.get("multilingual_titles") or {})
        except Exception:
            d["multilingual_titles"] = {}
        return d

    # Shopper & Order Operations
    def upsert_shoppers(self, shoppers: List[Dict[str, Any]]) -> int:
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for s in shoppers:
                cursor.execute("""
                INSERT INTO shoppers (customer_id, name, email, loyalty_tier, address)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    name=excluded.name,
                    email=excluded.email,
                    loyalty_tier=excluded.loyalty_tier,
                    address=excluded.address;
                """, (s["customer_id"], s["name"], s["email"], s.get("loyalty_tier", "Bronze"), s.get("address", "")))
                count += 1
            conn.commit()
        return count

    def get_all_shoppers(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shoppers ORDER BY customer_id ASC;")
            return [dict(r) for r in cursor.fetchall()]

    def upsert_orders(self, orders: List[Dict[str, Any]]) -> int:
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for o in orders:
                cursor.execute("""
                INSERT INTO orders (order_id, customer_id, product_id, quantity, total_amount, order_status, order_date, tracking_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    order_status=excluded.order_status,
                    tracking_number=excluded.tracking_number;
                """, (
                    o["order_id"],
                    o["customer_id"],
                    o["product_id"],
                    int(o.get("quantity", 1)),
                    float(o["total_amount"]),
                    o["order_status"],
                    o["order_date"],
                    o.get("tracking_number", ""),
                ))
                count += 1
            conn.commit()
        return count

    def get_customer_orders(self, customer_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT o.*, p.title AS product_title, p.price AS unit_price
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.product_id
            WHERE o.customer_id = ?
            ORDER BY o.order_date DESC;
            """, (customer_id,))
            return [dict(r) for r in cursor.fetchall()]

    # Audit Traces Operations
    def save_audit_trace(self, trace: Dict[str, Any]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO audit_traces (trace_id, timestamp, customer_id, session_id, user_query, answer_type, response, trace_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                trace["trace_id"],
                trace["timestamp"],
                trace.get("customer_id"),
                trace.get("session_id"),
                trace["user_query"],
                trace["final_answer_type"],
                trace.get("response", ""),
                json.dumps(trace),
            ))
            conn.commit()

    def get_audit_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT trace_data FROM audit_traces WHERE trace_id = ?", (trace_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return json.loads(row["trace_data"])

    # Session Memory
    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT messages FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return []
            return json.loads(row["messages"])

    def update_session(self, session_id: str, customer_id: Optional[str], messages: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO sessions (session_id, customer_id, messages, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                customer_id=coalesce(excluded.customer_id, sessions.customer_id),
                messages=excluded.messages,
                updated_at=CURRENT_TIMESTAMP;
            """, (session_id, customer_id, json.dumps(messages)))
            conn.commit()

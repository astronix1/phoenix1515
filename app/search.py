"""Hybrid Retrieval module combining Vector Similarity (ChromaDB / Vector Index) with FTS5 BM25.

Provides Reciprocal Rank Fusion (RRF) and live upsert support.
"""

import math
import os
import re
from typing import Any, Dict, List, Optional
from app.db import DatabaseManager


class SimpleVectorIndex:
    """A lightweight multilingual term/dense embedding vector index with cosine similarity.
    Ensures zero external dependency failure while supporting semantic and multilingual matching.
    """

    def __init__(self):
        self.doc_vectors: Dict[str, Dict[str, float]] = {}
        self.doc_meta: Dict[str, Dict[str, Any]] = {}
        self.idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        # Support alphanumeric terms, multilingual characters, and character n-grams for subword matching
        tokens = [w.lower() for w in re.findall(r"[\w\u0900-\u097F]+", text)]
        # Add character tri-grams to capture multilingual stems (Hindi, Hinglish, suffixes)
        ngrams = []
        for t in tokens:
            if len(t) >= 4:
                ngrams.extend([t[i:i+3] for i in range(len(t)-2)])
        return tokens + ngrams

    def add_documents(self, documents: List[Dict[str, Any]]):
        for doc in documents:
            doc_id = doc["product_id"]
            title = doc.get("title") or doc.get("name", "")
            desc = doc.get("description", "")
            cat = doc.get("category", "")
            brand = doc.get("brand", "")
            text = f"{title} {desc} {cat} {brand} "
            for k, v in doc.get("multilingual_titles", {}).items():
                text += f"{v} "
            for tag in doc.get("tags", []):
                text += f"{tag} "
            specs = doc.get("specs") if doc.get("specs") is not None else doc.get("attributes", {})
            if isinstance(specs, dict):
                for k, v in specs.items():
                    text += f"{k} {v} "

            tokens = self._tokenize(text)
            tf: Dict[str, float] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0.0) + 1.0

            # Normalize tf
            total = len(tokens) or 1
            for t in tf:
                tf[t] = tf[t] / total

            self.doc_vectors[doc_id] = tf
            self.doc_meta[doc_id] = doc

        self._recompute_idf()

    def _recompute_idf(self):
        doc_count = len(self.doc_vectors)
        if doc_count == 0:
            return
        doc_freq: Dict[str, int] = {}
        for tf in self.doc_vectors.values():
            for t in tf.keys():
                doc_freq[t] = doc_freq.get(t, 0) + 1

        self.idf = {t: math.log((1.0 + doc_count) / (1.0 + df)) + 1.0 for t, df in doc_freq.items()}

    def search(self, query: str, top_k: int = 15) -> List[Dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens or not self.doc_vectors:
            return []

        query_tf: Dict[str, float] = {}
        for t in tokens:
            query_tf[t] = query_tf.get(t, 0.0) + 1.0

        q_vec = {t: tf * self.idf.get(t, 1.0) for t, tf in query_tf.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0

        scores: List[tuple[str, float]] = []
        for doc_id, d_tf in self.doc_vectors.items():
            d_vec = {t: tf * self.idf.get(t, 1.0) for t, tf in d_tf.items()}
            dot = sum(q_vec[t] * d_vec.get(t, 0.0) for t in q_vec)
            d_norm = math.sqrt(sum(v * v for v in d_vec.values())) or 1.0
            cos_sim = dot / (q_norm * d_norm)
            if cos_sim > 0.01:
                scores.append((doc_id, cos_sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for doc_id, score in scores[:top_k]:
            item = dict(self.doc_meta[doc_id])
            item["vector_score"] = float(score)
            results.append(item)
        return results


class HybridSearchEngine:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.vector_index = SimpleVectorIndex()
        self.chroma_client = None
        self._init_vector_store()

    def _init_vector_store(self):
        """Attempts to initialize ChromaDB if available; falls back to self-contained vector index."""
        use_chroma = os.getenv("USE_CHROMADB", "false").lower() == "true"
        if use_chroma:
            try:
                import chromadb
                self.chroma_client = chromadb.PersistentClient(path="./chroma_db")
                self.collection = self.chroma_client.get_or_create_collection("products")
            except Exception:
                self.chroma_client = None

        # Seed in-memory vector index with all existing products in SQLite
        products = self.db.get_all_products(limit=500)
        if products:
            self.vector_index.add_documents(products)

    def upsert_products(self, products: List[Dict[str, Any]]):
        """Live upsert: updates SQLite and both vector indices."""
        self.db.upsert_products(products)
        self.vector_index.add_documents(products)

        if self.chroma_client:
            try:
                ids = [p["product_id"] for p in products]
                docs = [f"{p.get('title') or p.get('name', '')} {p.get('description', '')} {p.get('category', '')} {p.get('brand', '')}" for p in products]
                metadatas = [{"category": str(p.get("category", "")), "brand": str(p.get("brand", "")), "price": float(p.get("price") if p.get("price") is not None else p.get("price_inr", 0.0))} for p in products]
                self.collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
            except Exception:
                pass

    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Executes Hybrid Retrieval: FTS5 BM25 + Vector Similarity merged via Reciprocal Rank Fusion."""
        filters = filters or {}

        # 1. BM25 / FTS Search
        fts_candidates = self.db.search_fts(query, limit=top_k * 2)

        # 2. Vector Search (ChromaDB with SimpleVectorIndex fallback)
        vector_candidates = []
        if self.chroma_client:
            try:
                chroma_count = self.collection.count()
                if chroma_count > 0:
                    c_res = self.collection.query(query_texts=[query], n_results=min(top_k * 2, chroma_count))
                    if c_res and c_res.get("ids") and c_res["ids"][0]:
                        for pid in c_res["ids"][0]:
                            item = self.db.get_product(pid)
                            if item:
                                vector_candidates.append(item)
            except Exception:
                pass

        if not vector_candidates:
            vector_candidates = self.vector_index.search(query, top_k=top_k * 2)

        # 3. Reciprocal Rank Fusion (RRF)
        # RRF_Score = sum(1 / (k + rank))
        rrf_scores: Dict[str, float] = {}
        candidate_map: Dict[str, Dict[str, Any]] = {}

        for rank, item in enumerate(fts_candidates):
            pid = item["product_id"]
            candidate_map[pid] = item
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + (1.0 / (rrf_k + (rank + 1)))

        for rank, item in enumerate(vector_candidates):
            pid = item["product_id"]
            if pid not in candidate_map:
                candidate_map[pid] = item
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + (1.0 / (rrf_k + (rank + 1)))

        if not rrf_scores:
            # Fallback to all products if no text match
            fallback = self.db.get_all_products(limit=top_k)
            for item in fallback:
                candidate_map[item["product_id"]] = item
                rrf_scores[item["product_id"]] = 0.01

        # Sort combined candidates by fused score
        ranked_ids = sorted(rrf_scores.keys(), key=lambda pid: rrf_scores[pid], reverse=True)

        # 4. Hard Filter Application
        filtered_products = self.db.filter_products(filters=filters, candidate_ids=ranked_ids)

        # Re-attach scores and maintain rank order
        filtered_map = {p["product_id"]: p for p in filtered_products}
        final_results = []
        for pid in ranked_ids:
            if pid in filtered_map:
                p = filtered_map[pid]
                p["score"] = round(rrf_scores[pid], 4)
                final_results.append(p)
                if len(final_results) >= top_k:
                    break

        return final_results

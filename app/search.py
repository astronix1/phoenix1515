"""Hybrid Retrieval module combining Vector Similarity (ChromaDB / Vector Index) with FTS5 BM25.

Provides Reciprocal Rank Fusion (RRF) and live upsert support.
"""

import json
import logging
import math
import os
import re
from threading import RLock
from typing import Any, Dict, List
import urllib.request

from app.db import DatabaseManager


class SimpleVectorIndex:
    """A lightweight multilingual term/dense embedding vector index with cosine similarity.
    Fallback index if ChromaDB or the embedding API is unavailable.
    """

    def __init__(self):
        self.doc_vectors: Dict[str, Dict[str, float]] = {}
        self.doc_meta: Dict[str, Dict[str, Any]] = {}
        self.idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        tokens = [w.lower() for w in re.findall(r"[\w\u0900-\u097F]+", text)]
        ngrams = []
        for t in tokens:
            if len(t) >= 4:
                ngrams.extend([t[i:i + 3] for i in range(len(t) - 2)])
        return tokens + ngrams

    def add_documents(self, documents: List[Dict[str, Any]]):
        for doc in documents:
            doc_id = doc["product_id"]
            title = doc.get("title") or doc.get("name", "")
            desc = doc.get("description", "")
            cat = doc.get("category", "")
            brand = doc.get("brand", "")
            text = f"{title} {desc} {cat} {brand} "
            for _, v in doc.get("multilingual_titles", {}).items():
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


class GeminiChromaEmbeddingFunction:
    """Multilingual embedding function using Gemini gemini-embedding-001."""

    def __init__(self, dim: int = 768):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        self.dim = dim

    def name(self) -> str:
        return f"gemini_{self.model}"

    def embed_query(self, input: Any) -> Any:
        if isinstance(input, str):
            input = [input]
        return self.__call__(input)

    def embed_documents(self, input: Any) -> Any:
        return self.__call__(input)

    def _offline_embed(self, input: List[str]) -> List[List[float]]:
        import hashlib
        import math
        embeddings = []
        for text in input:
            vec = [0.0] * self.dim
            tokens = text.lower().split()
            for t in tokens:
                idx = int(hashlib.md5(t.encode("utf-8")).hexdigest(), 16) % self.dim
                vec[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings

    def __call__(self, input: List[str]) -> List[List[float]]:
        if not self.api_key:
            return self._offline_embed(input)

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
            requests_payload = [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text[:2000]}]},
                    "outputDimensionality": self.dim,
                }
                for text in input
            ]
            req = urllib.request.Request(
                url,
                data=json.dumps({"requests": requests_payload}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [e["values"] for e in data["embeddings"]]
        except Exception as e:
            logging.error(f"Gemini embedding failed; using offline fallback: {e}")
            return self._offline_embed(input)


class HybridSearchEngine:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.lock = RLock()
        self.vector_index = SimpleVectorIndex()
        self.chroma_client = None
        self._init_vector_store()

    def _init_vector_store(self):
        """Attempts to initialize ChromaDB if available; falls back to self-contained vector index."""
        use_chroma = os.getenv("USE_CHROMADB", "true").lower() == "true"
        products = self.db.get_all_products(limit=-1)
        self.vector_index.add_documents(products)
        if use_chroma:
            try:
                import chromadb
                path = os.getenv("CHROMA_DB_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chroma_db")))
                self.chroma_client = chromadb.PersistentClient(path=path)
                self.collection = self.chroma_client.get_or_create_collection(
                    "products",
                    embedding_function=GeminiChromaEmbeddingFunction(),
                    metadata={"hnsw:space": "cosine"},
                )
                if products:
                    self._index_chroma(products)
            except Exception:
                logging.exception("Chroma unavailable; using the local vector index")
                self.chroma_client = None

    def _index_chroma(self, products):
        for offset in range(0, len(products), 100):
            batch = products[offset:offset + 100]
            self.collection.upsert(
                ids=[p["product_id"] for p in batch],
                documents=[
                    f"{p['title']} {p['brand']} {p['category']} {p['description']} {p['specs']} {p.get('multilingual_titles', {})}"
                    for p in batch
                ],
            )

    def upsert_products(self, products: List[Dict[str, Any]]):
        with self.lock:
            self.db.upsert_products(products)
            ids = list(dict.fromkeys(p["product_id"] for p in products))
            canonical = self.db.compare_products(ids)
            self.vector_index.add_documents(canonical)
            if self.chroma_client:
                try:
                    self._index_chroma(canonical)
                except Exception:
                    logging.exception("Chroma update failed; using the current local index")
                    self.chroma_client = None

    def search(self, query: str, filters=None, top_k=5, rrf_k=60, cheapest=False):
        """Apply SQL hard filters, then rank via FTS5 + ChromaDB RRF."""
        eligible = self.db.filter_products(filters or {})
        terms = search_terms(query)
        if not eligible or (not terms and not filters):
            return []

        eligible_by_id = {p["product_id"]: p for p in eligible}
        with self.lock:
            count = max(len(self.vector_index.doc_vectors), 1)
            clean_query = " ".join(terms) if terms else query
            lexical = self.db.search_fts(clean_query, limit=count) if clean_query else []
            vectors = []

            if self.chroma_client and query.strip():
                try:
                    n_results = min(count, self.collection.count())
                    if n_results > 0:
                        res = self.collection.query(
                            query_texts=[query],
                            n_results=n_results,
                            include=["distances"],
                        )
                        for pid, dist in zip(res["ids"][0], res["distances"][0]):
                            if dist < 0.55:
                                vectors.append({"product_id": pid})
                except Exception:
                    logging.exception("Chroma query failed; using local fallback")
                    vectors = self.vector_index.search(clean_query, top_k=count)
            else:
                vectors = self.vector_index.search(clean_query, top_k=count)

            scores = {}
            for ranking in (lexical, vectors):
                for rank, item in enumerate(ranking, 1):
                    pid = item["product_id"]
                    if pid in eligible_by_id:
                        scores[pid] = scores.get(pid, 0) + 1 / (rrf_k + rank)

        matched = [eligible_by_id[pid] for pid in scores] if terms else eligible
        for product in matched:
            product["score"] = round(scores.get(product["product_id"], 0), 6)
        matched.sort(key=lambda p: (p["price"] if cheapest else 0, -p["score"], p["product_id"]))
        return matched[:top_k]


ALIASES = {
    "smartphone": "phone", "mobile": "phone", "फोन": "phone", "मोबाइल": "phone",
    "लैपटॉप": "laptop", "स्पीकर": "speaker", "जूते": "shoe", "साड़ी": "saree",
    "सैमसंग": "samsung", "गैलेक्सी": "galaxy", "rucksack": "backpack",
    "hiking": "trekking", "hike": "trekking", "trek": "trekking",
}
PRODUCT_TYPES = set("phone laptop shoe sneaker speaker backpack trekking earbuds earphone headphone saree jeans tablet webcam keyboard watch mat drone refrigerator vacuum fryer kettle bottle sari boot sandal tshirt sunscreen soap racket candle".split())
STOP_WORDS = set("""a an the any all do does you sell have are there show me i need want looking for find
    recommend some please only with and or of my father who likes gift to in on under below above
    up maximum budget than less more within price stock available now ready ship size rs inr rupees
    products product items options ones one cheaper cheapest cheap affordable sasta saste mujhe ek
    chahiye dikhao ka ke ki liye wala badhiya kya hai hain मुझे चाहिए एक सस्ता सस्ते दिखाओ के लिए में
    is these those this that how much costs cost rated rating star stars men women""".split())


def search_terms(text):
    tokens = re.findall(r"[\w\u0900-\u097f]+", text.casefold())
    result = []
    for token in tokens:
        if token in STOP_WORDS or token.isdigit():
            continue
        if token.endswith("s") and len(token) > 3 and token not in ("jeans", "earbuds"):
            token = token[:-1]
        result.append(ALIASES.get(token, token))
    return result
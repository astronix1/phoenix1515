"""Hybrid Retrieval module combining Vector Similarity (ChromaDB / Vector Index) with FTS5 BM25.

Provides Reciprocal Rank Fusion (RRF) and live upsert support.
"""

import math
import logging
from threading import RLock
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


class FastChromaEmbeddingFunction:
    """Fast, zero-download offline embedding function for ChromaDB vector search."""
    def __init__(self, dim: int = 64):
        self.dim = dim

    def name(self) -> str:
        return "fast_chroma"

    def embed_query(self, input: Any) -> Any:
        if isinstance(input, str):
            input = [input]
        return self.__call__(input)

    def embed_documents(self, input: Any) -> Any:
        return self.__call__(input)

    def __call__(self, input: List[str]) -> List[List[float]]:
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


class HybridSearchEngine:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.lock = RLock()
        self.vector_index = SimpleVectorIndex()
        self.chroma_client = None
        self._init_vector_store()

    def _init_vector_store(self):
        """Attempts to initialize ChromaDB if available; falls back to self-contained vector index."""
        use_chroma = os.getenv("USE_CHROMADB", "false").lower() == "true"
        products = self.db.get_all_products(limit=-1)
        self.vector_index.add_documents(products)
        if use_chroma:
            try:
                import chromadb
                path = os.getenv("CHROMA_DB_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chroma_db")))
                self.chroma_client = chromadb.PersistentClient(path=path)
                self.collection = self.chroma_client.get_or_create_collection(
                    "products",
                    embedding_function=FastChromaEmbeddingFunction()
                )
                self._index_chroma(products)
            except Exception:
                logging.exception("Chroma unavailable; using the local vector index")
                self.chroma_client = None

    def _index_chroma(self, products):
        for offset in range(0, len(products), 100):
            batch = products[offset:offset + 100]
            self.collection.upsert(
                ids=[p["product_id"] for p in batch],
                documents=[f"{p['title']} {p['brand']} {p['description']} {p['specs']}" for p in batch],
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
        """Apply constraints across the catalogue before truncating the fused ranking."""
        eligible = self.db.filter_products(filters or {})
        terms = search_terms(query)
        if terms:
            # A near neighbour alone is insufficient evidence that we sell the requested item.
            required = [t for t in terms if t in PRODUCT_TYPES] or terms
            def matches(product):
                content = " ".join(str(product.get(k, "")) for k in
                                   ("title", "brand", "category", "description", "tags", "multilingual_titles", "specs"))
                words = set(search_terms(content))
                return all(term in words for term in required)
            eligible = [p for p in eligible if matches(p)]
        if not eligible or (not terms and not filters):
            return []
        with self.lock:
            count = len(self.vector_index.doc_vectors)
            query = " ".join(terms)
            lexical = self.db.search_fts(query, limit=count)
            vectors = self.vector_index.search(query, top_k=count)
            if self.chroma_client and query:
                try:
                    ids = self.collection.query(query_texts=[query], n_results=min(count, self.collection.count()))["ids"][0]
                    vectors = [{"product_id": pid} for pid in ids]
                except Exception:
                    logging.exception("Chroma query failed; using the local ranking")
            scores = {}
            for ranking in (lexical, vectors):
                for rank, item in enumerate(ranking, 1):
                    pid = item["product_id"]
                    scores[pid] = scores.get(pid, 0) + 1 / (rrf_k + rank)
        for product in eligible:
            product["score"] = round(scores.get(product["product_id"], 0), 6)
        eligible.sort(key=lambda p: (p["price"] if cheapest else 0, -p["score"], p["product_id"]))
        return eligible[:top_k]


ALIASES = {
    "smartphone": "phone", "mobile": "phone", "फोन": "phone", "मोबाइल": "phone",
    "लैपटॉप": "laptop", "स्पीकर": "speaker", "जूते": "shoe", "साड़ी": "saree",
    "सैमसंग": "samsung", "गैलेक्सी": "galaxy", "rucksack": "backpack",
    "hiking": "trekking", "hike": "trekking", "trek": "trekking",
}
PRODUCT_TYPES = set("phone laptop shoe sneaker speaker backpack trekking earbuds earphone headphone saree jeans tablet webcam keyboard watch mat car drone refrigerator vacuum fryer kettle bottle sari boot sandal tshirt sunscreen soap racket candle".split())
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

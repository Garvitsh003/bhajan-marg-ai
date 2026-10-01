import os


APP_MODE = os.getenv("APP_MODE", "local").strip().lower()

if APP_MODE == "cloud":
    from .cloud_vector_store import ensure_collection, hybrid_search, rerank
else:
    from .vector_store import ensure_collection, hybrid_search, rerank


__all__ = ["ensure_collection", "hybrid_search", "rerank"]

"""Shared MongoDB client + Voyage AI client helpers."""
from functools import lru_cache
from pymongo import MongoClient
import config


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(config.MONGODB_URI, appname="freight-demo")


def get_db():
    return get_client()[config.MONGODB_DB]


@lru_cache(maxsize=1)
def get_voyage():
    import voyageai
    if not config.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set in environment")
    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts as documents (corpus side)."""
    vo = get_voyage()
    res = vo.embed(texts, model=config.VOYAGE_MODEL, input_type="document")
    return res.embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single query (asymmetric, query side)."""
    vo = get_voyage()
    res = vo.embed([text], model=config.VOYAGE_MODEL, input_type="query")
    return res.embeddings[0]

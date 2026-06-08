"""Create Atlas Search and Vector Search indexes via the data-plane API (MongoDB 8.x).

Standard b-tree and 2dsphere indexes are created inside the generator scripts.
This script focuses on Search/Vector Search indexes, which use a different control plane.

Run: python -m indexes.setup_indexes
"""
import time
from pymongo.errors import OperationFailure

from db import get_db
import config


SHIPMENT_SEARCH_DEFINITION = {
    "mappings": {
        "dynamic": False,
        "fields": {
            # Exact-id lookups (lucene.keyword = one whole-string token, no folding).
            "shipmentId":         {"type": "string", "analyzer": "lucene.keyword"},
            # Legacy ES-style denormalized search bag.
            "searchKeywords":     {"type": "string", "analyzer": "lucene.standard"},
            "description":        {"type": "string", "analyzer": "lucene.english"},
            "status":             {"type": "stringFacet"},
            "carrier": {"type": "document", "fields": {
                # Triple-mapped: text search, facet filter, and edge-gram autocomplete.
                "name": [
                    {"type": "string", "analyzer": "lucene.standard"},
                    {"type": "stringFacet"},
                    {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15},
                ],
                "scac": {"type": "string"},
            }},
            "customer": {"type": "document", "fields": {
                "customerId": {"type": "string", "analyzer": "lucene.keyword"},
                "name": [
                    {"type": "string", "analyzer": "lucene.standard"},
                    {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15},
                ],
                "tier": {"type": "stringFacet"},
            }},
            "origin": {"type": "document", "fields": {
                "city":  {"type": "string"},
                "state": {"type": "stringFacet"},
            }},
            "destination": {"type": "document", "fields": {
                "city":  [
                    {"type": "string"},
                    {"type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15},
                ],
                "state": {"type": "stringFacet"},
            }},
            "reference_numbers": {"type": "document", "fields": {
                "bol": {"type": "string"},
                "po":  {"type": "string"},
                "pro": {"type": "string"},
            }},
            "weight_lbs":         {"type": "number"},
            "freight_class":      {"type": "number"},
            "pickup_date":        {"type": "date"},
            "estimated_delivery": {"type": "date"},
        },
    }
}

AGENT_VECTOR_DEFINITION = {
    "fields": [
        {
            "type": "vector",
            "path": "embedding",
            "numDimensions": config.VOYAGE_DIM,
            "similarity": "cosine",
            "quantization": "scalar",
        },
        {"type": "filter", "path": "metadata.topic"},
        {"type": "filter", "path": "metadata.source"},
    ]
}


def _create_or_replace_search(coll, name: str, definition: dict, index_type: str = "search") -> None:
    existing = list(coll.list_search_indexes(name))
    if existing:
        print(f"  - dropping existing index '{name}'")
        coll.drop_search_index(name)
        # Atlas needs a moment to fully release the name
        time.sleep(5)

    print(f"  - creating index '{name}' (type={index_type})")
    try:
        coll.create_search_index({"name": name, "type": index_type, "definition": definition})
    except OperationFailure as e:
        raise SystemExit(f"Failed to create '{name}': {e}")


def _wait_ready(coll, name: str, timeout_s: int = 600) -> None:
    print(f"  - waiting for '{name}' to become queryable...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        idx = next(iter(coll.list_search_indexes(name)), None)
        if idx and idx.get("queryable"):
            print(f"  - '{name}' is READY")
            return
        time.sleep(5)
    raise SystemExit(f"Timed out waiting for '{name}'")


def main() -> None:
    db = get_db()

    print(f"[1/2] Atlas Search index on {config.COL_SHIPMENTS}")
    shipments = db[config.COL_SHIPMENTS]
    _create_or_replace_search(shipments, config.IDX_SHIPMENTS_SEARCH, SHIPMENT_SEARCH_DEFINITION, "search")

    print(f"[2/2] Vector Search index on {config.COL_AGENT_MEMORY}")
    memory = db[config.COL_AGENT_MEMORY]
    _create_or_replace_search(memory, config.IDX_AGENT_VECTOR, AGENT_VECTOR_DEFINITION, "vectorSearch")

    _wait_ready(shipments, config.IDX_SHIPMENTS_SEARCH)
    _wait_ready(memory,    config.IDX_AGENT_VECTOR)
    print("\nAll Search/Vector Search indexes are ready.")


if __name__ == "__main__":
    main()

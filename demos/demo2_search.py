"""DEMO 2 - Atlas Search replacing Elasticsearch.

Covers the three workloads the customer runs on ES today:
  A. Full-text relevance search across description + customer + city + refs
  B. Faceted search (status, carrier, customer.tier, destination.state) with counts
  C. Autocomplete / type-ahead on customer name and destination city

Run: python -m demos.demo2_search
"""
from pprint import pprint

from db import get_db
import config
from demos._presenter import banner, note, pause


def fulltext_search(db, query: str, limit: int = 5) -> list[dict]:
    pipeline = [
        {"$search": {
            "index": config.IDX_SHIPMENTS_SEARCH,
            "compound": {
                "should": [
                    {"text": {"query": query, "path": "description", "score": {"boost": {"value": 3}}}},
                    {"text": {"query": query, "path": "customer.name"}},
                    {"text": {"query": query, "path": ["origin.city", "destination.city"]}},
                    {"text": {"query": query, "path": ["reference_numbers.bol",
                                                       "reference_numbers.po",
                                                       "reference_numbers.pro"]}},
                ],
                "minimumShouldMatch": 1,
            },
        }},
        {"$limit": limit},
        {"$project": {"_id": 1, "status": 1, "customer.name": 1, "destination.city": 1,
                      "description": 1, "score": {"$meta": "searchScore"}}},
    ]
    return list(db[config.COL_SHIPMENTS].aggregate(pipeline))


def faceted_search(db, query: str | None = None) -> dict:
    # "Match everything" needs an indexed path; _id is not in the search mapping.
    # status is mapped as stringFacet and present on every shipment.
    operator = (
        {"text": {"query": query, "path": "description"}}
        if query else {"exists": {"path": "status"}}
    )
    pipeline = [
        {"$searchMeta": {
            "index": config.IDX_SHIPMENTS_SEARCH,
            "facet": {
                "operator": operator,
                "facets": {
                    "status_facet":      {"type": "string", "path": "status"},
                    "carrier_facet":     {"type": "string", "path": "carrier.name"},
                    "tier_facet":        {"type": "string", "path": "customer.tier"},
                    "dest_state_facet":  {"type": "string", "path": "destination.state"},
                },
            },
        }},
    ]
    return next(iter(db[config.COL_SHIPMENTS].aggregate(pipeline)))


def autocomplete(db, prefix: str, path: str = "customer.name", limit: int = 8) -> list[dict]:
    pipeline = [
        {"$search": {
            "index": config.IDX_SHIPMENTS_SEARCH,
            "autocomplete": {"query": prefix, "path": path, "fuzzy": {"maxEdits": 1}},
        }},
        {"$limit": limit},
        {"$group": {"_id": f"${path}"}},
        {"$limit": limit},
    ]
    return list(db[config.COL_SHIPMENTS].aggregate(pipeline))


def keyword_and_legacy_search(db, shipment_id: str, customer_id: str,
                              keyword: str, limit: int = 5) -> list[dict]:
    """Exercise the keyword-analyzed id fields, the legacy searchKeywords bag,
    and carrier.name text search - everything in one compound query."""
    pipeline = [
        {"$search": {
            "index": config.IDX_SHIPMENTS_SEARCH,
            "compound": {
                "should": [
                    {"text": {"query": shipment_id, "path": "shipmentId"}},
                    {"text": {"query": customer_id, "path": "customer.customerId"}},
                    {"text": {"query": keyword,     "path": "searchKeywords"}},
                    {"text": {"query": keyword,     "path": "carrier.name"}},
                ],
                "minimumShouldMatch": 1,
            },
        }},
        {"$limit": limit},
        {"$project": {"_id": 1, "shipmentId": 1, "customer.customerId": 1,
                      "carrier.name": 1, "searchKeywords": 1,
                      "score": {"$meta": "searchScore"}}},
    ]
    return list(db[config.COL_SHIPMENTS].aggregate(pipeline))


def main() -> None:
    db = get_db()

    banner("DEMO 2A - Full-text relevance search")
    note(
        "Compound $search across the shipments_search index: description (3x boost),\n"
        "customer.name, origin/destination city, and reference numbers (BOL/PO/PRO).\n"
        "Results are ranked by searchScore."
    )
    pause("ENTER to run: 'refrigerated pharmaceuticals'")
    pprint(fulltext_search(db, "refrigerated pharmaceuticals"))

    pause("ENTER to run a reference-number lookup (numeric BOL/PRO)")
    sample_bol = db[config.COL_SHIPMENTS].find_one({}, {"reference_numbers.bol": 1})
    bol = sample_bol["reference_numbers"]["bol"]
    print(f"Searching for BOL token '{bol}':")
    pprint(fulltext_search(db, bol, limit=3))

    banner("DEMO 2B - Faceted search ($searchMeta)")
    note(
        "$searchMeta returns bucket counts only - no documents - for the four\n"
        "stringFacet fields: status, carrier.name, customer.tier, destination.state.\n"
        "The operator clause selects which documents are counted; here exists on\n"
        "status matches every shipment."
    )
    pause("ENTER to compute facets across all shipments")
    facets = faceted_search(db)
    for name, payload in facets.get("facet", {}).items():
        print(f"\n  {name}:")
        for b in payload["buckets"][:5]:
            print(f"    {b['_id']:<35} {b['count']:>8,}")

    banner("DEMO 2C - Autocomplete / type-ahead")
    note(
        "Prefix matching with edgeGram tokenization (minGrams=2, maxGrams=15) and\n"
        "fuzzy.maxEdits=1 against customer.name, destination.city, and carrier.name,\n"
        "all defined as autocomplete fields on the same shipments_search index."
    )

    # Sample 3 real customer names from the data so the prefixes always match.
    sampled = list(db[config.COL_CUSTOMERS].aggregate([
        {"$sample": {"size": 3}}, {"$project": {"name": 1}}
    ]))
    customer_prefixes = [c["name"][:3].lower() for c in sampled]
    city_prefixes = ["los", "sea", "mem"]               # known destination cities
    carrier_prefixes = ["kni", "schne", "old dom"]      # known carrier names

    for prefix in customer_prefixes:
        print(f"\n  customer.name prefix='{prefix}':")
        for hit in autocomplete(db, prefix, path="customer.name"):
            print(f"    - {hit['_id']}")

    for prefix in city_prefixes:
        print(f"\n  destination.city prefix='{prefix}':")
        for hit in autocomplete(db, prefix, path="destination.city"):
            print(f"    - {hit['_id']}")

    for prefix in carrier_prefixes:
        print(f"\n  carrier.name prefix='{prefix}':")
        for hit in autocomplete(db, prefix, path="carrier.name"):
            print(f"    - {hit['_id']}")

    banner("DEMO 2D - Keyword ids + legacy searchKeywords + carrier text search")
    note(
        "Exact-id matching on shipmentId and customer.customerId (mapped with the\n"
        "lucene.keyword analyzer), text search on the denormalized searchKeywords\n"
        "bag, and text search on carrier.name - all combined in a single compound\n"
        "$search query. carrier.name is dual-mapped as text here and as a facet in\n"
        "Demo 2B; the same field can carry multiple index types."
    )
    sample = db[config.COL_SHIPMENTS].find_one({}, {"shipmentId": 1, "customer.customerId": 1})
    pause(f"ENTER to look up by shipmentId={sample['shipmentId']} / customerId={sample['customer']['customerId']} / keyword='knight'")
    pprint(keyword_and_legacy_search(
        db,
        shipment_id=sample["shipmentId"],
        customer_id=sample["customer"]["customerId"],
        keyword="knight",
    ))

    banner("Index summary")
    note(
        "All four queries above (full-text, facets, autocomplete, exact-id) run\n"
        "against the single shipments_search Atlas Search index on the same cluster\n"
        "that holds the operational shipment documents. Field-level multi-mapping\n"
        "(e.g. carrier.name as text + facet + autocomplete) is what makes one index\n"
        "sufficient for all four workloads."
    )


if __name__ == "__main__":
    main()

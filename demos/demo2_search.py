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
        "One index, one query language. We boost the description field 3x and search\n"
        "customer name, city, and reference numbers in the same query. This replaces a\n"
        "separate Elasticsearch cluster - no dual-write, no sync lag, no schema drift."
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
        "$searchMeta returns ONLY facet counts - no docs streamed. This is what powers\n"
        "the left-rail filters in your shipper portal: status counts, top carriers,\n"
        "customer tier mix, destination state distribution. Single round-trip."
    )
    pause("ENTER to compute facets across all shipments")
    facets = faceted_search(db)
    for name, payload in facets.get("facet", {}).items():
        print(f"\n  {name}:")
        for b in payload["buckets"][:5]:
            print(f"    {b['_id']:<35} {b['count']:>8,}")

    banner("DEMO 2C - Autocomplete / type-ahead")
    note(
        "edgeGram tokenization + fuzzy=1 gives Google-style suggestions as the user\n"
        "types. Same index as full-text and facets - no separate suggester cluster.\n"
        "Sub-50ms responses on customer.name, destination.city, and carrier.name."
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
        "Keyword-analyzed fields (shipmentId, customer.customerId) give exact-id\n"
        "lookups through the Search index - useful when a saved ES query was written\n"
        "against these field names. searchKeywords is the denormalized 'one field to\n"
        "search them all' bag your ES users are used to; we keep it populated for\n"
        "drop-in query compatibility, but you do NOT need it for the demos above.\n"
        "carrier.name is dual-mapped: same field, used as text here and as a facet\n"
        "in Demo 2B."
    )
    sample = db[config.COL_SHIPMENTS].find_one({}, {"shipmentId": 1, "customer.customerId": 1})
    pause(f"ENTER to look up by shipmentId={sample['shipmentId']} / customerId={sample['customer']['customerId']} / keyword='knight'")
    pprint(keyword_and_legacy_search(
        db,
        shipment_id=sample["shipmentId"],
        customer_id=sample["customer"]["customerId"],
        keyword="knight",
    ))

    banner("Migration takeaway")
    note(
        "Same data, same cluster, same security perimeter as the OLTP workload.\n"
        "You delete the Elasticsearch cluster, the Logstash/Kafka sync pipeline, the\n"
        "reindex jobs, and the on-call rotation that goes with all of that."
    )


if __name__ == "__main__":
    main()

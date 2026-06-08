"""Generate N shipments (default 100K) and supporting customers/carriers collections.

Run: python -m data_generation.generate_shipments
"""
import random
from datetime import datetime, timedelta, timezone

from faker import Faker
from pymongo import ASCENDING, GEOSPHERE, InsertOne
from tqdm import tqdm

from db import get_db
import config
from data_generation.reference_data import (
    US_HUBS, CARRIERS, CUSTOMER_TIERS, FREIGHT_CLASSES, COMMODITY_DESCRIPTIONS,
)

fake = Faker()
Faker.seed(42)
random.seed(42)

STATUSES = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered", "exception"]
STATUS_WEIGHTS = [5, 10, 55, 10, 18, 2]  # ~3-7M/day company - most loads in transit

BATCH = 2000


def _make_customers(n: int = 250) -> list[dict]:
    return [{
        "_id": f"CUST-{i:05d}",
        "name": fake.company(),
        "tier": random.choices(CUSTOMER_TIERS, weights=[40, 30, 20, 10])[0],
        "billing_city": fake.city(),
        "billing_state": fake.state_abbr(),
    } for i in range(1, n + 1)]


def _seed_lookup_collections(db) -> tuple[list[dict], list[dict]]:
    customers = _make_customers()
    db[config.COL_CUSTOMERS].drop()
    db[config.COL_CUSTOMERS].insert_many(customers)
    db[config.COL_CARRIERS].drop()
    db[config.COL_CARRIERS].insert_many([
        {**c, "_id": c["id"], "delivered_count": 0, "exception_count": 0} for c in CARRIERS
    ])
    return customers, CARRIERS


def _interpolate(a: dict, b: dict, t: float) -> list[float]:
    return [a["lon"] + (b["lon"] - a["lon"]) * t, a["lat"] + (b["lat"] - a["lat"]) * t]


def _build_shipment(i: int, customers: list[dict], carriers: list[dict], now: datetime) -> dict:
    origin, dest = random.sample(US_HUBS, 2)
    status = random.choices(STATUSES, weights=STATUS_WEIGHTS)[0]
    cust = random.choice(customers)
    car = random.choice(carriers)
    pickup = now - timedelta(hours=random.randint(1, 240))
    eta = pickup + timedelta(hours=random.randint(12, 120))

    if status in ("delivered",):
        progress = 1.0
        actual_delivery = eta + timedelta(hours=random.randint(-6, 12))
    elif status == "created":
        progress = 0.0
        actual_delivery = None
    else:
        progress = random.uniform(0.1, 0.95)
        actual_delivery = None

    current = _interpolate(origin, dest, progress)
    shipment_id = f"SHP-{i:07d}"
    # searchKeywords: denormalized tokens for legacy ES-style "one field to search them all".
    # Kept in sync with the structured fields; useful when migrating saved ES queries verbatim.
    keywords = sorted({
        *cust["name"].lower().replace(",", " ").split(),
        car["scac"].lower(),
        *car["name"].lower().split(),
        origin["city"].lower(), dest["city"].lower(),
        origin["state"].lower(), dest["state"].lower(),
    })
    return {
        "_id": shipment_id,
        "shipmentId": shipment_id,
        "status": status,
        "customer": {
            "id": cust["_id"], "customerId": cust["_id"],
            "name": cust["name"], "tier": cust["tier"],
        },
        "carrier": {"id": car["id"], "name": car["name"], "scac": car["scac"]},
        "searchKeywords": keywords,
        "origin": {
            "name": origin["name"], "city": origin["city"], "state": origin["state"],
            "location": {"type": "Point", "coordinates": [origin["lon"], origin["lat"]]},
        },
        "destination": {
            "name": dest["name"], "city": dest["city"], "state": dest["state"],
            "location": {"type": "Point", "coordinates": [dest["lon"], dest["lat"]]},
        },
        "current_location": {"type": "Point", "coordinates": current},
        "weight_lbs": random.randint(500, 44000),
        "pieces": random.randint(1, 26),
        "freight_class": random.choice(FREIGHT_CLASSES),
        "description": random.choice(COMMODITY_DESCRIPTIONS),
        "reference_numbers": {
            "bol": f"BOL{random.randint(10_000_000, 99_999_999)}",
            "po":  f"PO{random.randint(100000, 999999)}",
            "pro": f"{random.randint(100_000_000, 999_999_999)}",
        },
        "pickup_date": pickup,
        "estimated_delivery": eta,
        "actual_delivery": actual_delivery,
        "created_at": pickup - timedelta(hours=random.randint(1, 48)),
        "updated_at": now,
    }


def main() -> None:
    db = get_db()
    col = db[config.COL_SHIPMENTS]
    col.drop()

    customers, carriers = _seed_lookup_collections(db)
    now = datetime.now(timezone.utc)

    ops: list[InsertOne] = []
    for i in tqdm(range(1, config.N_SHIPMENTS + 1), desc="shipments"):
        ops.append(InsertOne(_build_shipment(i, customers, carriers, now)))
        if len(ops) >= BATCH:
            col.bulk_write(ops, ordered=False)
            ops.clear()
    if ops:
        col.bulk_write(ops, ordered=False)

    print("Creating standard indexes...")
    col.create_index([("status", ASCENDING), ("updated_at", ASCENDING)])
    col.create_index("customer.id")
    col.create_index("carrier.id")
    col.create_index([("reference_numbers.bol", ASCENDING)])
    col.create_index([("reference_numbers.pro", ASCENDING)])
    col.create_index([("current_location", GEOSPHERE)])
    col.create_index([("destination.location", GEOSPHERE)])
    col.create_index([("origin.location", GEOSPHERE)])
    print(f"Done. {col.estimated_document_count():,} shipments.")


if __name__ == "__main__":
    main()

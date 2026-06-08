"""Generate ~500K tracking events distributed across existing shipments.

Run: python -m data_generation.generate_tracking_events
"""
import random
from datetime import timedelta

from pymongo import ASCENDING, GEOSPHERE, InsertOne
from tqdm import tqdm

from db import get_db
import config

EVENT_TYPES = [
    "pickup_scheduled", "arrived_origin", "loaded", "departed_origin",
    "in_transit_scan", "border_crossed", "arrived_hub", "departed_hub",
    "out_for_delivery", "delivery_attempted", "delivered", "exception_weather",
    "exception_mechanical", "exception_customs",
]
EVENT_WEIGHTS = [3, 3, 4, 5, 50, 2, 6, 6, 4, 2, 8, 3, 2, 2]

BATCH = 5000


def _interp(a_coords, b_coords, t):
    return [a_coords[0] + (b_coords[0] - a_coords[0]) * t,
            a_coords[1] + (b_coords[1] - a_coords[1]) * t]


def main() -> None:
    db = get_db()
    col = db[config.COL_TRACKING]
    col.drop()

    shipments = list(db[config.COL_SHIPMENTS].find(
        {}, {"_id": 1, "pickup_date": 1, "estimated_delivery": 1,
             "origin.location.coordinates": 1, "destination.location.coordinates": 1}
    ))
    if not shipments:
        raise SystemExit("No shipments found. Run generate_shipments first.")

    total = config.N_TRACKING_EVENTS
    print(f"Distributing {total:,} events across {len(shipments):,} shipments...")

    ops: list[InsertOne] = []
    for _ in tqdm(range(total), desc="events"):
        s = random.choice(shipments)
        pickup = s["pickup_date"]
        eta = s["estimated_delivery"]
        span = (eta - pickup).total_seconds()
        t = random.random()
        ts = pickup + timedelta(seconds=span * t)
        a = s["origin"]["location"]["coordinates"]
        b = s["destination"]["location"]["coordinates"]
        ev_type = random.choices(EVENT_TYPES, weights=EVENT_WEIGHTS)[0]
        ops.append(InsertOne({
            "shipment_id": s["_id"],
            "event_type": ev_type,
            "timestamp": ts,
            "location": {"type": "Point", "coordinates": _interp(a, b, t)},
            "description": ev_type.replace("_", " ").title(),
        }))
        if len(ops) >= BATCH:
            col.bulk_write(ops, ordered=False)
            ops.clear()
    if ops:
        col.bulk_write(ops, ordered=False)

    print("Creating indexes...")
    col.create_index([("shipment_id", ASCENDING), ("timestamp", ASCENDING)])
    col.create_index([("timestamp", ASCENDING)])
    col.create_index([("location", GEOSPHERE)])
    col.create_index("event_type")
    print(f"Done. {col.estimated_document_count():,} tracking events.")


if __name__ == "__main__":
    main()

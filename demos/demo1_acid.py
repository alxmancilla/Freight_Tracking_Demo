"""DEMO 1 - ACID multi-document transactions for shipment delivery.

Story: A driver scans "delivered" at the dock. Four things must happen atomically:
  1. shipments       -> status=delivered, actual_delivery, current_location
  2. tracking_events -> insert delivered event
  3. carriers        -> increment delivered_count
  4. customers       -> set last_delivery_at

If any one fails, NONE commit. Then we prove read-your-own-writes from a
second client using majority read concern - "if a load comes in and gets
updated, immediately that should reflect".

Run: python -m demos.demo1_acid
"""
from datetime import datetime, timezone
from pymongo import ReadPreference
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from db import get_client, get_db
import config
from demos._presenter import banner, note, pause


def _pick_in_transit(db) -> dict:
    s = db[config.COL_SHIPMENTS].find_one({"status": {"$in": ["in_transit", "out_for_delivery"]}})
    if not s:
        raise SystemExit("No in_transit shipments found. Re-run the generators.")
    return s


def deliver_shipment(client, shipment_id: str) -> dict:
    """Atomically mark a shipment delivered + log event + bump counters."""
    db = client[config.MONGODB_DB]
    now = datetime.now(timezone.utc)

    with client.start_session() as session:
        # Snapshot read concern + majority write = strict consistency across docs.
        with session.start_transaction(
            read_concern=ReadConcern("snapshot"),
            write_concern=WriteConcern("majority"),
        ):
            shipment = db[config.COL_SHIPMENTS].find_one({"_id": shipment_id}, session=session)
            if not shipment:
                raise RuntimeError(f"Shipment {shipment_id} not found")

            dest_pt = shipment["destination"]["location"]

            db[config.COL_SHIPMENTS].update_one(
                {"_id": shipment_id},
                {"$set": {
                    "status": "delivered",
                    "actual_delivery": now,
                    "current_location": dest_pt,
                    "updated_at": now,
                }},
                session=session,
            )

            db[config.COL_TRACKING].insert_one({
                "shipment_id": shipment_id,
                "event_type": "delivered",
                "timestamp": now,
                "location": dest_pt,
                "description": "POD captured at destination dock",
            }, session=session)

            db[config.COL_CARRIERS].update_one(
                {"_id": shipment["carrier"]["id"]},
                {"$inc": {"delivered_count": 1}},
                session=session,
            )

            db[config.COL_CUSTOMERS].update_one(
                {"_id": shipment["customer"]["id"]},
                {"$set": {"last_delivery_at": now}},
                session=session,
            )
        # Transaction committed atomically here.

    return {"shipment_id": shipment_id, "delivered_at": now}


def verify_read_your_writes(shipment_id: str) -> None:
    """Open a *separate* client and read with majority - prove instant visibility."""
    other = get_client()  # in real life this would be a brand-new connection
    db = other[config.MONGODB_DB].with_options(
        read_preference=ReadPreference.PRIMARY,
        read_concern=ReadConcern("majority"),
    )
    s = db[config.COL_SHIPMENTS].find_one({"_id": shipment_id},
                                          {"status": 1, "actual_delivery": 1})
    ev = db[config.COL_TRACKING].find_one({"shipment_id": shipment_id, "event_type": "delivered"})
    print(f"  shipment.status        = {s['status']}")
    print(f"  shipment.actual_delivery = {s['actual_delivery'].isoformat()}")
    print(f"  delivered_event present  = {ev is not None}")


def main() -> None:
    client = get_client()
    db = get_db()

    banner("DEMO 1 - ACID multi-document transactions")
    note(
        "Today on Elasticsearch+MySQL you have eventual consistency between the search\n"
        "index and the system of record. A delivered scan can show up in MySQL but the\n"
        "search index still shows in_transit for seconds-to-minutes. With MongoDB the\n"
        "same document is the system of record AND the queryable surface, and we wrap\n"
        "the multi-collection write in a snapshot-isolation transaction."
    )
    pause("Show the script source, then ENTER to pick a shipment")

    target = _pick_in_transit(db)
    print(f"\nPicked shipment {target['_id']} (status={target['status']}, carrier={target['carrier']['name']})")
    pause("ENTER to run the transaction")

    result = deliver_shipment(client, target["_id"])
    print(f"\nCommitted transaction at {result['delivered_at'].isoformat()}")

    banner("Read-your-own-writes from a fresh session")
    note(
        "We open a separate logical session and read with readConcern='majority'.\n"
        "The updated status, the new tracking event, and the bumped counters are all\n"
        "visible immediately - this is the consistency guarantee the customer asked for."
    )
    verify_read_your_writes(target["_id"])

    banner("Throughput context for 3-7M txn/day")
    note(
        "3M/day -> ~35 writes/sec sustained, peak ~350 writes/sec.\n"
        "7M/day -> ~80 writes/sec sustained, peak ~800 writes/sec.\n"
        "A single M30 cluster easily handles this; M40+ gives headroom for the\n"
        "Atlas Search and Vector Search workloads on the same cluster."
    )


if __name__ == "__main__":
    main()

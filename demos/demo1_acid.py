"""DEMO 1 - ACID multi-document transactions for shipment delivery.

Story: A driver scans "delivered" at the dock. Four things must happen atomically:
  1. shipments       -> status=delivered, actual_delivery, current_location
  2. tracking_events -> insert delivered event
  3. carriers        -> increment delivered_count
  4. customers       -> set last_delivery_at

If any one fails, NONE commit. We prove both halves:
  - happy path: before/after snapshot of all 4 docs
  - failure:    same transaction with an injected error -> nothing changes
Then we prove read-your-own-writes from a truly separate MongoClient.

Run: python -m demos.demo1_acid
"""
from datetime import datetime, timezone
from pymongo import MongoClient, ReadPreference
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from db import get_client, get_db
import config
from demos._presenter import banner, note, pause


# Snapshot read concern + majority write = strict consistency across docs.
TXN_OPTS = dict(
    read_concern=ReadConcern("snapshot"),
    write_concern=WriteConcern("majority"),
)


def _pick_in_transit(db, exclude_id: str | None = None) -> dict:
    q: dict = {"status": {"$in": ["in_transit", "out_for_delivery"]}}
    if exclude_id:
        q["_id"] = {"$ne": exclude_id}
    s = db[config.COL_SHIPMENTS].find_one(q)
    if not s:
        raise SystemExit("No in_transit shipments found. Re-run the generators.")
    return s


def _snapshot(db, shipment_id: str, carrier_id: str, customer_id: str) -> dict:
    """Capture the four fields the transaction will mutate."""
    s = db[config.COL_SHIPMENTS].find_one(
        {"_id": shipment_id}, {"status": 1, "actual_delivery": 1})
    car = db[config.COL_CARRIERS].find_one(
        {"_id": carrier_id}, {"delivered_count": 1})
    cust = db[config.COL_CUSTOMERS].find_one(
        {"_id": customer_id}, {"last_delivery_at": 1})
    ev_count = db[config.COL_TRACKING].count_documents(
        {"shipment_id": shipment_id, "event_type": "delivered"})
    return {
        "shipment.status": s.get("status"),
        "shipment.actual_delivery": s.get("actual_delivery"),
        "carrier.delivered_count": car.get("delivered_count"),
        "customer.last_delivery_at": cust.get("last_delivery_at"),
        "delivered_events": ev_count,
    }


def _print_snapshot(label: str, snap: dict) -> None:
    print(f"  {label}")
    for k, v in snap.items():
        print(f"    {k:<28} {v}")


def _delivery_callback(db, shipment_id: str, fail: bool = False):
    """Build a with_transaction callback that performs the 4 writes."""
    now = datetime.now(timezone.utc)

    def _cb(session):
        shipment = db[config.COL_SHIPMENTS].find_one(
            {"_id": shipment_id}, session=session)
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

        if fail:
            # Simulate the POD photo upload service throwing AFTER the four
            # writes have been staged. Server aborts the transaction; none persist.
            raise RuntimeError("POD photo upload service unavailable")

        return {"shipment_id": shipment_id, "delivered_at": now}

    return _cb


def deliver_shipment(client, shipment_id: str) -> dict:
    """Atomically mark a shipment delivered + log event + bump counters.

    Uses session.with_transaction(), which auto-retries on TransientTransactionError
    and UnknownTransactionCommitResult - the production pattern.
    """
    db = client[config.MONGODB_DB]
    with client.start_session() as session:
        return session.with_transaction(
            _delivery_callback(db, shipment_id, fail=False), **TXN_OPTS
        )


def attempt_failed_delivery(client, shipment_id: str) -> None:
    """Run the same transaction but raise mid-way. Expect: full rollback."""
    db = client[config.MONGODB_DB]
    try:
        with client.start_session() as session:
            session.with_transaction(
                _delivery_callback(db, shipment_id, fail=True), **TXN_OPTS
            )
    except RuntimeError as e:
        print(f"  caught application error  -> {e}")
        print("  transaction aborted by the server; no writes persisted")


def verify_read_your_writes(shipment_id: str) -> None:
    """Open a TRULY separate MongoClient (new pool) and read with majority."""
    other = MongoClient(config.MONGODB_URI, appname="freight-demo-verify")
    try:
        db = other[config.MONGODB_DB].with_options(
            read_preference=ReadPreference.PRIMARY,
            read_concern=ReadConcern("majority"),
        )
        s = db[config.COL_SHIPMENTS].find_one(
            {"_id": shipment_id}, {"status": 1, "actual_delivery": 1})
        ev = db[config.COL_TRACKING].find_one(
            {"shipment_id": shipment_id, "event_type": "delivered"})
        print(f"  shipment.status          = {s['status']}")
        print(f"  shipment.actual_delivery = {s['actual_delivery'].isoformat()}")
        print(f"  delivered_event present  = {ev is not None}")
    finally:
        other.close()


def main() -> None:
    client = get_client()
    db = get_db()

    banner("DEMO 1 - ACID multi-document transactions")
    note(
        "Marks an in-transit shipment as delivered with four writes across four\n"
        "collections - shipments, tracking_events, carriers, customers - committed\n"
        "atomically inside a snapshot-isolation transaction (readConcern=snapshot,\n"
        "writeConcern=majority) via session.with_transaction(). The script then runs\n"
        "the same transaction with an injected error to verify rollback, and ends\n"
        "with a read-your-writes check from a separate MongoClient."
    )
    pause("Show the script source, then ENTER to pick a shipment")

    target = _pick_in_transit(db)
    carrier_id = target["carrier"]["id"]
    customer_id = target["customer"]["id"]
    print(f"\nPicked shipment {target['_id']} (status={target['status']}, "
          f"carrier={target['carrier']['name']})")

    banner("Happy path - 4 writes commit atomically")
    before = _snapshot(db, target["_id"], carrier_id, customer_id)
    _print_snapshot("BEFORE:", before)
    pause("ENTER to run the transaction")

    result = deliver_shipment(client, target["_id"])
    print(f"\nCommitted transaction at {result['delivered_at'].isoformat()}")
    after = _snapshot(db, target["_id"], carrier_id, customer_id)
    _print_snapshot("AFTER: ", after)

    banner("Failure path - inject an error, prove nothing commits")
    note(
        "Runs the same four-write callback against a different in-transit shipment,\n"
        "but raises RuntimeError after the writes are staged. with_transaction lets\n"
        "the exception propagate and aborts the transaction on the server. The AFTER\n"
        "snapshot is asserted equal to BEFORE across all four collections."
    )
    victim = _pick_in_transit(db, exclude_id=target["_id"])
    v_carrier = victim["carrier"]["id"]
    v_customer = victim["customer"]["id"]
    print(f"\nPicked victim shipment {victim['_id']} (status={victim['status']})")
    before_v = _snapshot(db, victim["_id"], v_carrier, v_customer)
    _print_snapshot("BEFORE:", before_v)
    pause("ENTER to run the doomed transaction")

    attempt_failed_delivery(client, victim["_id"])
    after_v = _snapshot(db, victim["_id"], v_carrier, v_customer)
    _print_snapshot("AFTER: ", after_v)
    assert before_v == after_v, "ROLLBACK FAILED - state changed despite abort"
    print("\n  rollback verified: every field is byte-identical to BEFORE")

    banner("Read-your-own-writes from a brand-new MongoClient")
    note(
        "Opens a fresh MongoClient (new connection pool, new logical session) and\n"
        "reads back shipment.status, shipment.actual_delivery, and the inserted\n"
        "tracking_events document with readConcern='majority'."
    )
    verify_read_your_writes(target["_id"])

    banner("Throughput context for 3-7M txn/day")
    note(
        "Target workload sizing:\n"
        "  3M txn/day -> ~35 writes/sec sustained, ~350 writes/sec peak.\n"
        "  7M txn/day -> ~80 writes/sec sustained, ~800 writes/sec peak."
    )


if __name__ == "__main__":
    main()

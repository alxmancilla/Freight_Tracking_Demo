"""DEMO 5 - Exception management workflow (composite).

Stitches the three operational pillars - geospatial detection, ACID transaction,
and Vector Search RAG - into a single control-tower workflow:

  A. DETECT  - find a shipment dwelling inside a port geofence ($geoWithin, Demo 3B)
  B. REACT   - atomically flag at_risk, append exception, log event, bump counters
               (snapshot-isolation transaction via with_transaction, Demo 1)
  C. DECIDE  - retrieve the matching exception playbook with topic-filtered
               $vectorSearch and render a grounded RAG prompt (Demo 4)

Run: python -m demos.demo5_exception_workflow
"""
from datetime import datetime, timezone

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from db import get_client, get_db
import config
from demos._presenter import banner, note, pause
from demos.demo4_vector_rag import vector_search, render_rag_prompt


TXN_OPTS = dict(
    read_concern=ReadConcern("snapshot"),
    write_concern=WriteConcern("majority"),
)


def find_dwelling_shipment(db) -> tuple[dict, dict]:
    """Scan port geofences for an in-transit shipment currently inside one.

    Uses the same $geoWithin pattern as Demo 3B against the 2dsphere index on
    shipments.current_location. Excludes already-flagged shipments so the demo
    is re-runnable.
    """
    ports = list(db[config.COL_GEOFENCES].find(
        {"type": "port"}, {"name": 1, "city": 1, "state": 1, "geometry": 1}
    ))
    for port in ports:
        cand = db[config.COL_SHIPMENTS].find_one({
            "current_location": {"$geoWithin": {"$geometry": port["geometry"]}},
            "status": {"$in": ["in_transit", "out_for_delivery"]},
        })
        if cand:
            return cand, port
    raise SystemExit("No in-transit shipment found inside a port fence. "
                     "Re-run the generators to refresh data.")


def _exception_callback(db, shipment_id: str, port_name: str, reason: str):
    """Build a with_transaction callback for opening a dwell exception."""
    now = datetime.now(timezone.utc)

    def _cb(session):
        s = db[config.COL_SHIPMENTS].find_one({"_id": shipment_id}, session=session)
        if not s:
            raise RuntimeError(f"Shipment {shipment_id} not found")

        db[config.COL_SHIPMENTS].update_one(
            {"_id": shipment_id},
            {"$set": {"status": "at_risk", "updated_at": now},
             "$push": {"exceptions": {
                 "type": "dwell",
                 "fence_name": port_name,
                 "reason": reason,
                 "opened_at": now,
                 "state": "open",
             }}},
            session=session,
        )

        db[config.COL_TRACKING].insert_one({
            "shipment_id": shipment_id,
            "event_type": "exception_dwell",
            "timestamp": now,
            "location": s["current_location"],
            "description": f"Dwell exception inside {port_name}: {reason}",
        }, session=session)

        db[config.COL_CARRIERS].update_one(
            {"_id": s["carrier"]["id"]},
            {"$inc": {"exception_count": 1}},
            session=session,
        )

        db[config.COL_CUSTOMERS].update_one(
            {"_id": s["customer"]["id"]},
            {"$set": {"last_alerted_at": now}},
            session=session,
        )

        return {"shipment_id": shipment_id, "opened_at": now}

    return _cb


def open_exception(client, shipment_id: str, port_name: str, reason: str) -> dict:
    db = client[config.MONGODB_DB]
    with client.start_session() as session:
        return session.with_transaction(
            _exception_callback(db, shipment_id, port_name, reason), **TXN_OPTS
        )


def build_playbook_question(shipment: dict, port_name: str) -> str:
    return (
        f"A {shipment['description'].lower()} shipment from "
        f"{shipment['origin']['name']} to {shipment['destination']['name']} "
        f"carried by {shipment['carrier']['name']} has been dwelling inside the "
        f"{port_name} geofence. What is the standard playbook?"
    )


def main() -> None:
    client = get_client()
    db = get_db()

    banner("DEMO 5 - Exception management workflow")
    note(
        "Composite scenario that exercises three pillars in one workflow: a port\n"
        "dwell is detected geospatially, an atomic multi-collection transaction\n"
        "opens the exception case, and a topic-filtered vector search retrieves\n"
        "the playbook used to ground the copilot's response."
    )

    banner("Stage A - Detect: shipment dwelling inside a port fence")
    note(
        "$geoWithin against the 2dsphere index on shipments.current_location,\n"
        "intersected with status in (in_transit, out_for_delivery). The first\n"
        "match becomes the subject of the workflow."
    )
    pause("ENTER to scan port geofences")
    shipment, port = find_dwelling_shipment(db)
    print(f"\n  shipment      = {shipment['_id']}")
    print(f"  status        = {shipment['status']}")
    print(f"  carrier       = {shipment['carrier']['name']}")
    print(f"  inside fence  = {port['name']} ({port['city']}, {port['state']})")
    print(f"  pickup_date   = {shipment['pickup_date'].isoformat()}")
    print(f"  est. delivery = {shipment['estimated_delivery'].isoformat()}")

    banner("Stage B - React: atomically open the exception case")
    note(
        "Same with_transaction pattern as Demo 1, applied to four different\n"
        "writes: shipments (status=at_risk + exceptions[].push), tracking_events\n"
        "(exception_dwell), carriers ($inc exception_count), customers\n"
        "(last_alerted_at). Either all four commit or none do."
    )
    reason = "shipment inside port fence with no recent progress scan"
    pause("ENTER to commit the exception transaction")
    result = open_exception(client, shipment["_id"], port["name"], reason)
    print(f"\n  exception opened at {result['opened_at'].isoformat()}")

    after = db[config.COL_SHIPMENTS].find_one(
        {"_id": shipment["_id"]},
        {"status": 1, "exceptions": {"$slice": -1}},
    )
    print(f"  shipment.status            = {after['status']}")
    print(f"  shipment.exceptions[-1]    = {after['exceptions'][-1]}")
    carrier_after = db[config.COL_CARRIERS].find_one(
        {"_id": shipment["carrier"]["id"]}, {"exception_count": 1})
    print(f"  carrier.exception_count    = {carrier_after['exception_count']}")

    banner("Stage C - Decide: retrieve the playbook with topic-filtered $vectorSearch")
    note(
        "vector_search() embeds the question with Voyage AI (input_type='query')\n"
        "and queries agent_memory_vector with a pre-filter on\n"
        "metadata.topic='exception_playbook'. Results are rendered as a grounded\n"
        "RAG prompt - the same pipeline as Demo 4, scoped to this incident."
    )
    question = build_playbook_question(shipment, port["name"])
    pause("ENTER to embed the question and run vector search")
    hits = vector_search(db, question, k=4, topic="exception_playbook")
    print("\nTop playbook matches:")
    for h in hits:
        print(f"  [{h['score']:.3f}] {h['content'][:120]}...")

    print("\n--- Prompt that would be sent to the LLM ---")
    print(render_rag_prompt(question, hits))

    banner("Workflow summary")
    note(
        "One cluster carried the entire incident: geospatial detection, the\n"
        "transactional case-open, and the vector retrieval that grounds the\n"
        "copilot - all against the same shipment record, with no cross-system\n"
        "synchronization between steps."
    )


if __name__ == "__main__":
    main()

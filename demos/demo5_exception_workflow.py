"""DEMO 5 - Exception management workflow (composite).

Stitches the three operational pillars - geospatial detection, ACID transaction,
and Vector Search RAG - into a single control-tower workflow:

  A. DETECT  - find a shipment dwelling inside a port geofence with a real
               dwell-time computation joining tracking_events ($geoWithin +
               $lookup, Demo 3B + aggregation)
  B. REACT   - atomically flag at_risk, append exception, log event, bump
               counters (snapshot-isolation transaction via with_transaction,
               Demo 1). A change stream running in a background thread observes
               the at_risk transition in real time.
  C. DECIDE  - retrieve the matching exception playbook with topic-filtered
               $vectorSearch, join in live operational state, render a grounded
               RAG prompt and (optionally) invoke an LLM (Demo 4 + LLM).

Run: python -m demos.demo5_exception_workflow
"""
import os
import threading
from datetime import datetime, timezone

from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from db import get_client, get_db
import config
from demos._presenter import banner, note, pause
from demos.demo4_vector_rag import vector_search
from demos._llm import call_llm


TXN_OPTS = dict(
    read_concern=ReadConcern("snapshot"),
    write_concern=WriteConcern("majority"),
)

DWELL_THRESHOLD_HOURS = float(os.getenv("DEMO5_DWELL_HOURS", "12"))


def _dwell_pipeline(port_geometry: dict, threshold_hours: float) -> list[dict]:
    """Aggregation: shipments inside `port_geometry` whose most recent tracking
    event is older than `threshold_hours`. Returns the worst offender first.
    """
    return [
        {"$match": {
            "current_location": {"$geoWithin": {"$geometry": port_geometry}},
            "status": {"$in": ["in_transit", "out_for_delivery"]},
            "exceptions.type": {"$ne": "dwell"},
        }},
        {"$limit": 200},
        {"$lookup": {
            "from": config.COL_TRACKING,
            "let": {"sid": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$shipment_id", "$$sid"]}}},
                {"$sort": {"timestamp": -1}},
                {"$limit": 1},
                {"$project": {"_id": 0, "timestamp": 1, "event_type": 1}},
            ],
            "as": "_last_event",
        }},
        {"$addFields": {"last_event": {"$arrayElemAt": ["$_last_event", 0]}}},
        {"$addFields": {
            "hours_since_last_event": {
                "$cond": [
                    {"$ifNull": ["$last_event.timestamp", False]},
                    {"$divide": [
                        {"$subtract": ["$$NOW", "$last_event.timestamp"]},
                        3600 * 1000,
                    ]},
                    None,
                ],
            },
        }},
        {"$match": {"hours_since_last_event": {"$gte": threshold_hours}}},
        {"$sort": {"hours_since_last_event": -1}},
        {"$limit": 1},
        {"$project": {"_last_event": 0}},
    ]


def find_worst_dwelling_shipment(db, threshold_hours: float = DWELL_THRESHOLD_HOURS
                                 ) -> tuple[dict, dict]:
    """Iterate port geofences and return the shipment with the longest dwell
    that exceeds `threshold_hours`, together with the port it sits in."""
    ports = list(db[config.COL_GEOFENCES].find(
        {"type": "port"}, {"name": 1, "city": 1, "state": 1, "geometry": 1}
    ))
    best: tuple[dict, dict] | None = None
    best_hours = -1.0
    for port in ports:
        cur = db[config.COL_SHIPMENTS].aggregate(
            _dwell_pipeline(port["geometry"], threshold_hours)
        )
        for doc in cur:
            if doc["hours_since_last_event"] > best_hours:
                best = (doc, port)
                best_hours = doc["hours_since_last_event"]
    if best is None:
        raise SystemExit(
            f"No in-transit shipment found inside a port fence with > "
            f"{threshold_hours}h since last tracking event. Lower "
            f"DEMO5_DWELL_HOURS or re-run the generators."
        )
    return best


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


def fetch_operational_context(db, shipment_id: str) -> dict:
    """Single aggregation pulling the shipment, last 3 tracking events, and
    carrier scorecard - the live operational state that grounds the prompt
    alongside the retrieved playbook."""
    pipeline = [
        {"$match": {"_id": shipment_id}},
        {"$lookup": {
            "from": config.COL_TRACKING,
            "let": {"sid": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$shipment_id", "$$sid"]}}},
                {"$sort": {"timestamp": -1}},
                {"$limit": 3},
                {"$project": {"_id": 0, "timestamp": 1, "event_type": 1,
                              "description": 1}},
            ],
            "as": "recent_events",
        }},
        {"$lookup": {
            "from": config.COL_CARRIERS,
            "localField": "carrier.id",
            "foreignField": "_id",
            "as": "_carrier",
        }},
        {"$addFields": {
            "carrier_stats": {
                "delivered_count": {"$first": "$_carrier.delivered_count"},
                "exception_count": {"$first": "$_carrier.exception_count"},
            },
        }},
        {"$project": {
            "_id": 1, "status": 1, "carrier": 1,
            "origin": 1, "destination": 1,
            "recent_events": 1, "carrier_stats": 1,
            "last_exception": {"$arrayElemAt": ["$exceptions", -1]},
        }},
    ]
    docs = list(db[config.COL_SHIPMENTS].aggregate(pipeline))
    if not docs:
        raise RuntimeError(f"Operational context not found for {shipment_id}")
    return docs[0]


def _watch_at_risk(client, shipment_id: str,
                   captured: list, stop_event: threading.Event) -> None:
    """Background change-stream watcher: report the first update on
    `shipment_id` that sets status to at_risk."""
    db = client[config.MONGODB_DB]
    pipeline = [
        {"$match": {
            "operationType": "update",
            "documentKey._id": shipment_id,
            "updateDescription.updatedFields.status": "at_risk",
        }},
    ]
    try:
        with db[config.COL_SHIPMENTS].watch(
            pipeline, full_document="updateLookup", max_await_time_ms=500
        ) as stream:
            while not stop_event.is_set():
                ev = stream.try_next()
                if ev is not None:
                    captured.append({
                        "cluster_time": ev.get("clusterTime"),
                        "shipment_id": ev["documentKey"]["_id"],
                        "new_status": ev["updateDescription"]["updatedFields"].get("status"),
                    })
                    return
    except Exception as exc:
        captured.append({"error": repr(exc)})


def build_playbook_question(shipment: dict, port_name: str) -> str:
    return (
        f"A {shipment['description'].lower()} shipment from "
        f"{shipment['origin']['name']} to {shipment['destination']['name']} "
        f"carried by {shipment['carrier']['name']} has been dwelling inside the "
        f"{port_name} geofence. What is the standard playbook?"
    )


def render_enriched_prompt(question: str, hits: list[dict], op_ctx: dict) -> str:
    """RAG prompt with both retrieved knowledge AND live operational state."""
    ctx_blocks = []
    for i, h in enumerate(hits, 1):
        ctx_blocks.append(
            f"[{i}] (topic={h['metadata']['topic']}, score={h['score']:.3f})\n{h['content']}"
        )
    context = "\n\n".join(ctx_blocks)

    events = "\n".join(
        f"  - {e['timestamp'].isoformat()}  {e['event_type']}: {e['description']}"
        for e in op_ctx.get("recent_events", [])
    ) or "  (no recent events)"
    stats = op_ctx.get("carrier_stats") or {}
    last_exc = op_ctx.get("last_exception") or {}

    live_state = (
        f"shipment_id        : {op_ctx['_id']}\n"
        f"status             : {op_ctx['status']}\n"
        f"carrier            : {op_ctx['carrier']['name']} "
        f"(delivered={stats.get('delivered_count')}, exceptions={stats.get('exception_count')})\n"
        f"last_exception     : type={last_exc.get('type')} "
        f"fence={last_exc.get('fence_name')} state={last_exc.get('state')}\n"
        f"recent_events:\n{events}"
    )

    return (
        "You are a freight operations copilot. Use ONLY the context below to answer.\n"
        "If the context is insufficient, say so.\n\n"
        f"--- RETRIEVED PLAYBOOKS ---\n{context}\n\n"
        f"--- LIVE OPERATIONAL STATE ---\n{live_state}\n\n"
        f"--- QUESTION ---\n{question}\n"
    )


def main() -> None:
    client = get_client()
    db = get_db()

    banner("DEMO 5 - Exception management workflow")
    note(
        "Composite scenario that exercises three pillars in one workflow: a port\n"
        "dwell is detected geospatially with a real dwell-time computation, an\n"
        "atomic multi-collection transaction opens the exception case while a\n"
        "change stream observes the transition, and a topic-filtered vector search\n"
        "joined with live operational state grounds the copilot's response."
    )

    banner("Stage A - Detect: dwell time computed against tracking_events")
    note(
        "Aggregation per port geofence: $geoWithin on shipments.current_location,\n"
        "$lookup for the most recent tracking_events.timestamp, $addFields to\n"
        f"compute hours_since_last_event, $match >= {DWELL_THRESHOLD_HOURS:g}h.\n"
        "The worst offender across all ports is selected."
    )
    pause("ENTER to scan port geofences and compute dwell times")
    shipment, port = find_worst_dwelling_shipment(db)
    print(f"\n  shipment              = {shipment['_id']}")
    print(f"  status                = {shipment['status']}")
    print(f"  carrier               = {shipment['carrier']['name']}")
    print(f"  inside fence          = {port['name']} ({port['city']}, {port['state']})")
    last_ev = shipment.get("last_event") or {}
    print(f"  last_event.type       = {last_ev.get('event_type')}")
    print(f"  last_event.timestamp  = "
          f"{last_ev.get('timestamp').isoformat() if last_ev.get('timestamp') else 'n/a'}")
    print(f"  hours_since_last_event= {shipment['hours_since_last_event']:.1f}")
    print(f"  pickup_date           = {shipment['pickup_date'].isoformat()}")
    print(f"  est. delivery         = {shipment['estimated_delivery'].isoformat()}")

    banner("Stage B - React: atomic case-open + change-stream observer")
    note(
        "with_transaction applied to four writes: shipments (status=at_risk +\n"
        "exceptions[].push), tracking_events (exception_dwell), carriers ($inc\n"
        "exception_count), customers (last_alerted_at). A change stream filtered\n"
        "to this shipment_id + status=at_risk runs in a background thread to\n"
        "demonstrate downstream notification on commit."
    )
    captured: list = []
    stop_event = threading.Event()
    watcher = threading.Thread(
        target=_watch_at_risk,
        args=(client, shipment["_id"], captured, stop_event),
        daemon=True,
    )
    watcher.start()

    reason = (f"shipment inside port fence with no progress scan for "
              f"{shipment['hours_since_last_event']:.1f}h")
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

    watcher.join(timeout=5.0)
    stop_event.set()
    print("\n  [change stream]")
    if captured:
        ev = captured[0]
        if "error" in ev:
            print(f"    watcher error: {ev['error']}")
        else:
            ct = ev.get("cluster_time")
            print(f"    observed update on {ev['shipment_id']} -> status="
                  f"{ev['new_status']} (clusterTime={ct})")
    else:
        print("    no change-stream event captured within timeout")

    banner("Stage C - Decide: topic-filtered $vectorSearch + live ops join")
    note(
        "vector_search() embeds the question with Voyage AI (input_type='query')\n"
        "and queries agent_memory_vector with a pre-filter on\n"
        "metadata.topic='exception_playbook'. A second aggregation joins the\n"
        "shipment with its last 3 tracking events and the carrier scorecard.\n"
        "Both retrievals feed a single grounded prompt; if ANTHROPIC_API_KEY or\n"
        "OPENAI_API_KEY is set, the prompt is also sent to the configured LLM."
    )
    question = build_playbook_question(shipment, port["name"])
    pause("ENTER to embed the question, run vector search and fetch live context")
    hits = vector_search(db, question, k=4, topic="exception_playbook")
    op_ctx = fetch_operational_context(db, shipment["_id"])

    print("\nTop playbook matches:")
    for h in hits:
        print(f"  [{h['score']:.3f}] {h['content'][:120]}...")

    print("\nLive operational state (joined in one aggregation):")
    stats = op_ctx.get("carrier_stats") or {}
    print(f"  carrier               = {op_ctx['carrier']['name']} "
          f"(delivered={stats.get('delivered_count')}, "
          f"exceptions={stats.get('exception_count')})")
    print(f"  last_exception        = {op_ctx.get('last_exception')}")
    print(f"  recent_events ({len(op_ctx.get('recent_events', []))}):")
    for e in op_ctx.get("recent_events", []):
        print(f"    - {e['timestamp'].isoformat()}  {e['event_type']}")

    prompt = render_enriched_prompt(question, hits, op_ctx)
    print("\n--- Grounded prompt ---")
    print(prompt)

    pause("ENTER to call the LLM (skipped if no API key / library)")
    print("\n--- LLM response ---")
    print(call_llm(prompt))

    banner("Workflow summary")
    note(
        "One cluster carried the entire incident: geospatial detection with a\n"
        "real dwell aggregation, a transactional case-open observed live via\n"
        "change streams, and vector retrieval joined with operational state to\n"
        "ground the copilot - all against the same shipment record, with no\n"
        "cross-system synchronization between steps."
    )


if __name__ == "__main__":
    main()

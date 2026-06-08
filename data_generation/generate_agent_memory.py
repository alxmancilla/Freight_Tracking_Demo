"""Generate ~10K agent-memory documents with Voyage AI embeddings.

These represent knowledge the GenAI logistics copilot can retrieve via Vector Search:
SOPs, lane history, customer preferences, exception playbooks, etc.

Run: python -m data_generation.generate_agent_memory
"""
import random
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, InsertOne
from tqdm import tqdm

from db import get_db, embed_documents
import config
from data_generation.reference_data import US_HUBS, CARRIERS

random.seed(7)

TOPICS = ["sop", "lane_history", "customer_preference", "exception_playbook",
          "rate_negotiation", "compliance_note", "driver_feedback"]

SOP_TEMPLATES = [
    "Standard operating procedure for {origin} to {destination} lane: confirm pickup appointment 24h prior, require BOL signature, capture POD photo at delivery.",
    "Hazmat shipments departing {origin} must include emergency response info and verify driver hazmat endorsement before dispatch.",
    "Reefer loads to {destination}: pre-cool trailer 4h before loading, log temperature every 30 minutes, alert dispatch on any 2C deviation.",
    "High-value electronics out of {origin}: use sealed trailer, GPS escort for first 200 miles, no overnight stops in unsecured lots.",
]
LANE_TEMPLATES = [
    "Lane {origin}->{destination} averages {hrs}h transit with {carrier}. Detention risk at destination is moderate; book afternoon delivery windows.",
    "{origin} to {destination} via {carrier}: winter weather causes 15% delay rate Dec-Feb. Add 8h buffer to ETA.",
    "Backhaul opportunity from {destination} to {origin} with {carrier} - typically 22% discount on round-trip pricing.",
]
CUST_TEMPLATES = [
    "Customer prefers single-driver service on loads over $20K declared value. Always provide proactive ETA updates every 4 hours.",
    "Customer requires lumper service paid by carrier and reimbursed on invoice. Do not accept driver-paid lumpers.",
    "Customer's receiving dock at {destination} closes at 16:00 local. Late arrivals must reschedule for next business day, no overnight detention.",
]
EXCEPTION_TEMPLATES = [
    "When a load experiences mechanical breakdown, dispatch a relay tractor within 2 hours and notify the customer with revised ETA and root cause.",
    "Customs hold at {origin} port: contact licensed broker, expect 24-48h delay, file a service exception and waive detention through resolution.",
    "Weather closure on I-80 through Wyoming: reroute via I-70 adding ~6h. Notify customer before driver detours.",
]
TEMPLATES_BY_TOPIC = {
    "sop": SOP_TEMPLATES, "lane_history": LANE_TEMPLATES, "customer_preference": CUST_TEMPLATES,
    "exception_playbook": EXCEPTION_TEMPLATES,
    "rate_negotiation": ["Spot rate {origin}->{destination} trended down 8% this quarter; renegotiate contract minimums with {carrier}."],
    "compliance_note":  ["FMCSA HOS rule reminder: drivers on this {origin} lane must take 30-min break by hour 8. Plan stops at approved truck stops."],
    "driver_feedback":  ["Driver feedback for {destination} receiver: unloading is slow (avg 3h). Recommend appointment-only loads going forward."],
}


def _make_content(topic: str) -> str:
    tmpl = random.choice(TEMPLATES_BY_TOPIC[topic])
    o, d = random.sample(US_HUBS, 2)
    car = random.choice(CARRIERS)
    return tmpl.format(origin=o["name"], destination=d["name"], carrier=car["name"], hrs=random.randint(18, 72))


def main() -> None:
    db = get_db()
    col = db[config.COL_AGENT_MEMORY]
    col.drop()

    now = datetime.now(timezone.utc)
    n = config.N_AGENT_MEMORY
    print(f"Generating {n:,} memory docs and embedding with {config.VOYAGE_MODEL}...")

    EMBED_BATCH = 128  # Voyage accepts up to 128 inputs/request for voyage-3
    pending_docs: list[dict] = []
    pending_texts: list[str] = []
    ops: list[InsertOne] = []

    def flush_embeddings():
        if not pending_texts:
            return
        vectors = embed_documents(pending_texts)
        for doc, vec in zip(pending_docs, vectors):
            doc["embedding"] = vec
            ops.append(InsertOne(doc))
        pending_docs.clear()
        pending_texts.clear()
        if len(ops) >= 1000:
            col.bulk_write(ops, ordered=False)
            ops.clear()

    for i in tqdm(range(n), desc="memory"):
        topic = random.choices(TOPICS, weights=[15, 25, 20, 15, 10, 8, 7])[0]
        content = _make_content(topic)
        pending_docs.append({
            "_id": f"MEM-{i:06d}",
            "content": content,
            "metadata": {
                "topic": topic,
                "source": random.choice(["ops_wiki", "slack_export", "email_thread", "ticket_resolution"]),
                "created_at": now - timedelta(days=random.randint(1, 730)),
            },
        })
        pending_texts.append(content)
        if len(pending_texts) >= EMBED_BATCH:
            flush_embeddings()

    flush_embeddings()
    if ops:
        col.bulk_write(ops, ordered=False)

    col.create_index([("metadata.topic", ASCENDING)])
    col.create_index([("metadata.created_at", ASCENDING)])
    print(f"Done. {col.estimated_document_count():,} memory docs.")
    print("Next: run indexes/setup_indexes.py to create the Vector Search index.")


if __name__ == "__main__":
    main()

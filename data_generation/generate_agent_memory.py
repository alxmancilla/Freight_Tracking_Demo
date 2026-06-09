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
    # Dwell / port-resident
    "Dwell exception inside {origin} port: if a {carrier} shipment has no progress scan for over {hrs}h, page the terminal liaison, request chassis status, and refile the gate appointment.",
    "Port {origin} dwell over {hrs}h with {carrier}: open a service exception, request a per-diem waiver, and rebook the gate slot through the terminal's appointment system.",
    "When a container assigned to {carrier} dwells at {origin} beyond {hrs}h, escalate to ocean carrier ops, capture the last free day, and quote per-diem exposure to the customer.",
    # Customs / docs
    "Customs hold at {origin} port for {carrier}: contact the licensed broker, expect 24-48h delay, file a service exception and waive detention through resolution.",
    "ISF or AMS discrepancy on inbound to {destination}: pause the move, request corrected docs from the shipper, and notify {carrier} dispatch before the cutoff.",
    # Mechanical / equipment
    "Mechanical breakdown on {origin}->{destination} with {carrier}: dispatch a relay tractor within 2h, transfer the load at the nearest safe haven, and revise ETA by +{hrs}h.",
    "Equipment shortage at {origin}: hold the booking, request a swap from {carrier}'s nearest pool, and notify the customer of a {hrs}h pickup slip.",
    # Weather
    "Weather closure between {origin} and {destination}: reroute {carrier} via the next viable corridor, add {hrs}h to ETA, and notify the customer before the driver detours.",
    "Hurricane or winter advisory affecting {destination} receiver: hold loads at the nearest secure yard, file a weather exception, and resume on the first clear shift.",
    # Safety / security
    "Hazmat incident on {origin} departure with {carrier}: stop movement, contact emergency response, and notify the shipper and DOT within the regulatory window.",
    "Seal break or suspected tampering on {origin}->{destination}: do not unload, photograph the seal, file a theft exception, and engage {carrier} security and the consignee.",
    # Appointment / receiver
    "Missed delivery appointment at {destination}: rebook the next available window, file an accessorial for redelivery, and reconfirm dock hours with the receiver.",
    "Receiver at {destination} refuses or short-pays: detain the trailer at a nearby drop yard, photograph the OS&D, and escalate to customer service before reconsign.",
    # Detention / HOS
    "Detention beyond 2h at {origin} loading with {carrier}: start the accessorial clock, capture in/out times, and bill per the contracted rate after free-time expires.",
    "Hours-of-service exhaustion on {origin}->{destination}: stage the load at the nearest approved truck stop, swap drivers within {hrs}h, and recalculate the appointment.",
    # Cold chain
    "Reefer temperature deviation in transit on {origin}->{destination}: pull set-point logs from {carrier} ELD, decide salvage vs return, and notify the consignee with photos.",
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

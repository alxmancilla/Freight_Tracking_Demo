# Freight Tracking - MongoDB Atlas Demo

End-to-end demo for a freight tracking company migrating off **Elasticsearch + MySQL**.
Proves four pillars on a single Atlas 8.x cluster:

| # | Pillar              | What it replaces                       | Script                              |
|---|---------------------|----------------------------------------|-------------------------------------|
| 1 | ACID transactions   | MySQL multi-statement txns             | `demos/demo1_acid.py`               |
| 2 | Atlas Search        | Elasticsearch cluster + sync pipeline  | `demos/demo2_search.py`             |
| 3 | Geospatial          | Bolt-on PostGIS / app-side math        | `demos/demo3_geo.py`                |
| 4 | Vector Search + RAG | Standalone vector DB for GenAI copilot | `demos/demo4_vector_rag.py`         |

Throughput target: **3-7M transactions/day** (~35-80 sustained writes/sec, ~350-800 peak).

---

## 1. Prerequisites

- MongoDB Atlas cluster running **MongoDB 8.x**, M10 or higher (M30+ recommended).
  Atlas Search and Vector Search must be enabled (they are, by default, on M0+).
- Python **3.11+** locally.
- Voyage AI API key from <https://dash.voyageai.com>.
- Network access from your laptop to the cluster (Atlas IP allowlist).

## 2. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set MONGODB_URI and VOYAGE_API_KEY
```

## 3. Generate data

```bash
python -m data_generation.run_all
```

This populates, in order:

1. `geofences`       (~20 polygons around US ports/warehouses)
2. `shipments`       (100K, with status / customer / carrier / origin / dest / current_location)
3. `tracking_events` (500K, with timestamp + GeoJSON point)
4. `agent_memory`    (10K, with `voyage-3` 1024-dim embeddings)

Standard b-tree and 2dsphere indexes are created at the end of each generator.
Total runtime ~15-25 minutes depending on cluster tier and Voyage API throughput.

> Tip: for a quick smoke test, override sizes in `.env`:
> `N_SHIPMENTS=2000 N_TRACKING_EVENTS=10000 N_AGENT_MEMORY=300`

> Note: re-running `generate_agent_memory` drops and re-creates the
> `agent_memory` collection, which also removes its Vector Search index.
> Re-run `python -m indexes.setup_indexes` afterwards so the
> `agent_memory_vector` index is recreated.

## 4. Build Atlas Search + Vector Search indexes

```bash
python -m indexes.setup_indexes
```

Creates and waits for two indexes:

- `shipments_search`     (Atlas Search: full-text, facets, autocomplete)
- `agent_memory_vector`  (Vector Search: cosine, 1024 dims, scalar quantized, with filters)

## 5. Run the demos

```bash
python -m demos.demo1_acid
python -m demos.demo2_search
python -m demos.demo3_geo
python -m demos.demo4_vector_rag
python -m demos.demo5_exception_workflow   # composite: stitches 1 + 3 + 4
```

Each script prints `[NOTES]` blocks and pauses for ENTER between sections.
Set `DEMO_NO_PAUSE=1` to run unattended.

Demo 5 optionally invokes an LLM in Stage C. To enable it, set one of
`ANTHROPIC_API_KEY` (`pip install anthropic`) or `OPENAI_API_KEY`
(`pip install openai`) in `.env`. Without a key the prompt is rendered
and the LLM step prints a `[skipped: ...]` line. Override the model with
`LLM_MODEL` and the Stage A dwell threshold with `DEMO5_DWELL_HOURS`
(default 12).

---

## Repository layout

```
.
├── README.md
├── requirements.txt
├── .env.example
├── config.py                 # env + collection/index names
├── db.py                     # MongoClient + Voyage AI helpers
├── data_generation/
│   ├── reference_data.py     # US hubs, carriers, commodity strings
│   ├── generate_geofences.py
│   ├── generate_shipments.py
│   ├── generate_tracking_events.py
│   ├── generate_agent_memory.py
│   └── run_all.py
├── indexes/
│   └── setup_indexes.py      # Atlas Search + Vector Search index DDL
└── demos/
    ├── _presenter.py
    ├── _llm.py                # optional Anthropic/OpenAI wrapper (lazy import)
    ├── demo1_acid.py
    ├── demo2_search.py
    ├── demo3_geo.py
    ├── demo4_vector_rag.py
    └── demo5_exception_workflow.py
```

---

## Demo overview

### Demo 1 — ACID multi-document transactions (`demos/demo1_acid.py`)
Simulates a driver scanning "delivered" at the dock and atomically applying four
writes — shipment status update, tracking event insert, carrier `delivered_count`
increment, customer `last_delivery_at` timestamp — inside a snapshot-isolation
transaction via `session.with_transaction()` (production-grade retries on
transient errors). Prints a BEFORE/AFTER snapshot of every mutated field on
both the happy path and a deliberately failed path (an injected exception after
the four writes are staged) to make rollback observable. Closes by reading from
a freshly opened `MongoClient` with `readConcern: majority` to show immediate
cross-client visibility.

### Demo 2 — Atlas Search (`demos/demo2_search.py`)
Exercises four workloads against a single `shipments_search` index:

- **2A — Full-text relevance**: compound `$search` across `description` (3x
  boost), `customer.name`, origin/destination city, and reference numbers
  (BOL / PO / PRO).
- **2B — Faceted search**: `$searchMeta` returns only bucket counts for
  status, carrier, customer tier, and destination state — the data behind
  left-rail filters in a shipper portal.
- **2C — Autocomplete**: `edgeGram` tokenization with `fuzzy.maxEdits=1` on
  customer name, destination city, and carrier name.
- **2D — Keyword ids + legacy `searchKeywords`**: exact-id lookup on
  `shipmentId` / `customer.customerId` and a denormalized search bag for
  drop-in compatibility with existing Elasticsearch queries.

### Demo 3 — Geospatial (`demos/demo3_geo.py`)
Runs two queries against a native 2dsphere index on `current_location`:

- **3A — `$geoNear`**: shipments within 50 km of the Port of Los Angeles,
  returning geodesic distance in meters as a projected field.
- **3B — `$geoWithin`**: shipments currently inside the Chicago Intermodal
  DC polygon, illustrating that new geofences are zero-DDL — just insert a
  GeoJSON document.

### Demo 4 — Vector Search + RAG (`demos/demo4_vector_rag.py`)
A natural-language logistics copilot. Embeds operator questions with Voyage AI
(`voyage-3`, 1024 dims) and queries the `agent_memory_vector` HNSW index
(cosine similarity, scalar-quantized) for the most relevant SOPs, exception
playbooks, and lane-history documents. Demonstrates `$vectorSearch.filter`
pre-filter push-down on `metadata.topic` to keep recall scoped, and renders
the retrieved chunks as a grounded RAG prompt.

### Demo 5 — Exception management workflow (composite) (`demos/demo5_exception_workflow.py`)
Stitches Demos 1, 3, and 4 into a single control-tower scenario, with a
real dwell computation, a live change-stream observer, an operational-context
join, and an optional LLM call:

- **A — Detect**: per-port aggregation combining `$geoWithin` on
  `shipments.current_location` with a `$lookup` against `tracking_events` to
  compute `hours_since_last_event = $$NOW - last_event.timestamp`. Returns
  the worst offender across all port geofences whose dwell exceeds
  `DEMO5_DWELL_HOURS` (default 12).
- **B — React**: a snapshot-isolation transaction via `session.with_transaction()`
  flips the shipment to `at_risk`, appends a structured entry to
  `exceptions[]`, inserts an `exception_dwell` tracking event, increments
  the carrier's `exception_count`, and sets the customer's `last_alerted_at`
  — all atomically (Demo 1 mechanics). A background thread runs a change
  stream filtered to this shipment's `status=at_risk` transition and reports
  the observed `clusterTime`, demonstrating downstream notification on commit.
- **C — Decide**: `vector_search()` (imported from Demo 4) queries
  `agent_memory_vector` with a pre-filter on
  `metadata.topic="exception_playbook"`. A second aggregation joins the
  shipment with its last 3 tracking events and the carrier scorecard in a
  single round-trip. Both retrievals feed a grounded prompt with separate
  `RETRIEVED PLAYBOOKS` and `LIVE OPERATIONAL STATE` sections. If
  `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set, the prompt is sent to the
  configured LLM via `demos/_llm.py`; otherwise the LLM step is skipped
  with an explanatory line.

Re-uses `vector_search()` from Demo 4 and mirrors the transaction pattern
from Demo 1 — each underlying demo remains independently runnable.

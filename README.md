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
```

Each script prints `[NOTES]` blocks and pauses for ENTER between sections.
Set `DEMO_NO_PAUSE=1` to run unattended.

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
    ├── demo1_acid.py
    ├── demo2_search.py
    ├── demo3_geo.py
    └── demo4_vector_rag.py
```

---

## Presenter cheat-sheet

### Demo 1 - ACID
> "Today the search index lags the system of record by seconds-to-minutes.
> A `delivered` scan is in MySQL but ES still shows `in_transit`. With MongoDB
> the document IS the searchable record, and we wrap the four writes -
> shipment, tracking event, carrier counter, customer last-delivery - in a
> snapshot-isolation transaction. Then we read from a brand-new session with
> `readConcern: majority` and prove instant visibility."

### Demo 2 - Atlas Search
> "One index, one query language. Boost `description` 3x, search customer name
> and cities, match exact reference numbers in the same `$search` stage.
> `$searchMeta` returns only facet counts in a single round-trip. Autocomplete
> uses `edgeGram` + `fuzzy=1` on the same index. The Elasticsearch cluster,
> the Logstash/Kafka sync, and the reindex jobs all go away."

### Demo 3 - Geospatial
> "Native 2dsphere index, GeoJSON in and out. `$geoNear` returns distance in
> meters as a projected field - no app-side haversine. `$geoWithin` against an
> arbitrary polygon means new geofences are zero-DDL: just insert a document.
> Combined with Change Streams in the app tier you get real-time fence
> entry/exit events without polling."

### Demo 4 - Vector Search + RAG
> "Embeddings created with Voyage AI `voyage-4`, 1024 dims, scalar-quantized
> HNSW. MongoDB owns Voyage now - same DPA, same support, no second vendor.
> `$vectorSearch.filter` push-down means topic filters don't wreck recall. The
> copilot's memory sits next to the shipment data it reasons about, so a single
> aggregation can join vector hits with live operational state."

### Closing
> "All four workloads share one cluster, one security perimeter, one backup,
> one on-call rotation. At 3-7M transactions/day this fits comfortably inside
> an M40 with headroom for Search and Vector Search dedicated nodes if you
> want to isolate them."

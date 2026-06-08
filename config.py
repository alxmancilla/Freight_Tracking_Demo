"""Shared configuration for the freight tracking Atlas demo."""
import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "freight_demo")

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-3")
VOYAGE_DIM = int(os.getenv("VOYAGE_DIM", "1024"))

N_SHIPMENTS = int(os.getenv("N_SHIPMENTS", "100000"))
N_TRACKING_EVENTS = int(os.getenv("N_TRACKING_EVENTS", "500000"))
N_AGENT_MEMORY = int(os.getenv("N_AGENT_MEMORY", "10000"))

# Collection names
COL_SHIPMENTS = "shipments"
COL_TRACKING = "tracking_events"
COL_GEOFENCES = "geofences"
COL_CARRIERS = "carriers"
COL_CUSTOMERS = "customers"
COL_AGENT_MEMORY = "agent_memory"

# Atlas Search / Vector Search index names
IDX_SHIPMENTS_SEARCH = "shipments_search"
IDX_SHIPMENTS_AUTOCOMPLETE = "shipments_autocomplete"
IDX_AGENT_VECTOR = "agent_memory_vector"

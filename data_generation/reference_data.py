"""Static reference data used by the generators (US ports, warehouses, carriers)."""

# (lon, lat) for major US freight hubs - used as origin/destination/geofence anchors.
US_HUBS = [
    {"name": "Port of Los Angeles",       "type": "port",      "city": "Los Angeles", "state": "CA", "lon": -118.2647, "lat": 33.7395},
    {"name": "Port of Long Beach",        "type": "port",      "city": "Long Beach",  "state": "CA", "lon": -118.2168, "lat": 33.7542},
    {"name": "Port of Oakland",           "type": "port",      "city": "Oakland",     "state": "CA", "lon": -122.3255, "lat": 37.7956},
    {"name": "Port of Seattle",           "type": "port",      "city": "Seattle",     "state": "WA", "lon": -122.3414, "lat": 47.6190},
    {"name": "Port of Houston",           "type": "port",      "city": "Houston",     "state": "TX", "lon": -95.2697,  "lat": 29.7268},
    {"name": "Port of New York/NJ",       "type": "port",      "city": "Newark",      "state": "NJ", "lon": -74.1502,  "lat": 40.6839},
    {"name": "Port of Savannah",          "type": "port",      "city": "Savannah",    "state": "GA", "lon": -81.1462,  "lat": 32.1313},
    {"name": "Port of Charleston",        "type": "port",      "city": "Charleston",  "state": "SC", "lon": -79.9251,  "lat": 32.7833},
    {"name": "Port of Miami",             "type": "port",      "city": "Miami",       "state": "FL", "lon": -80.1700,  "lat": 25.7800},
    {"name": "Port of Baltimore",         "type": "port",      "city": "Baltimore",   "state": "MD", "lon": -76.5500,  "lat": 39.2667},
    {"name": "Chicago Intermodal DC",     "type": "distribution_center", "city": "Chicago",     "state": "IL", "lon": -87.7500,  "lat": 41.7500},
    {"name": "Dallas Inland Port",        "type": "distribution_center", "city": "Dallas",      "state": "TX", "lon": -96.8000,  "lat": 32.7000},
    {"name": "Atlanta SE Hub",            "type": "warehouse", "city": "Atlanta",     "state": "GA", "lon": -84.4400,  "lat": 33.6400},
    {"name": "Memphis World Hub",         "type": "warehouse", "city": "Memphis",     "state": "TN", "lon": -89.9711,  "lat": 35.0424},
    {"name": "Louisville UPS Hub",        "type": "warehouse", "city": "Louisville",  "state": "KY", "lon": -85.7361,  "lat": 38.1744},
    {"name": "Kansas City Logistics Park","type": "warehouse", "city": "Kansas City", "state": "MO", "lon": -94.5786,  "lat": 39.0997},
    {"name": "Denver Mountain DC",        "type": "warehouse", "city": "Denver",      "state": "CO", "lon": -104.9903, "lat": 39.7392},
    {"name": "Phoenix SW DC",             "type": "warehouse", "city": "Phoenix",     "state": "AZ", "lon": -112.0740, "lat": 33.4484},
    {"name": "Columbus Rickenbacker",     "type": "distribution_center", "city": "Columbus",    "state": "OH", "lon": -82.9180,  "lat": 39.8136},
    {"name": "Reno Tahoe Logistics",      "type": "warehouse", "city": "Reno",        "state": "NV", "lon": -119.8138, "lat": 39.5296},
]

CARRIERS = [
    {"id": "CAR-001", "name": "Knight-Swift Transportation", "scac": "KNGT"},
    {"id": "CAR-002", "name": "J.B. Hunt Transport",         "scac": "JBHT"},
    {"id": "CAR-003", "name": "Schneider National",          "scac": "SNDR"},
    {"id": "CAR-004", "name": "Werner Enterprises",          "scac": "WERN"},
    {"id": "CAR-005", "name": "XPO Logistics",               "scac": "XPOL"},
    {"id": "CAR-006", "name": "Old Dominion Freight Line",   "scac": "ODFL"},
    {"id": "CAR-007", "name": "Estes Express Lines",         "scac": "EXLA"},
    {"id": "CAR-008", "name": "Saia LTL Freight",            "scac": "SAIA"},
]

CUSTOMER_TIERS = ["bronze", "silver", "gold", "platinum"]

FREIGHT_CLASSES = [50, 55, 60, 65, 70, 77.5, 85, 92.5, 100, 110, 125, 150, 175, 200, 250, 300, 400, 500]

COMMODITY_DESCRIPTIONS = [
    "Palletized consumer electronics, HS code 8517, fragile, do not stack",
    "Refrigerated pharmaceuticals, temperature controlled 2-8C, reefer required",
    "Automotive brake assemblies, steel banded crates, hazmat class 9 lithium batteries",
    "Industrial pump components, oversized crate, forklift unload at destination",
    "Frozen seafood, cold chain -18C, expedited delivery required",
    "Furniture and home goods, blanket wrap, white glove residential delivery",
    "Construction materials: rebar and structural steel, flatbed required",
    "Apparel and textiles, hanging garment service, soft sided trailer",
    "Food grade ingredients, FDA bonded, sanitary trailer required",
    "Solar panel modules, fragile glass, top load only, tarped flatbed",
    "Wine and spirits, bonded carrier, age verification on delivery",
    "Aerospace machined parts, AOG critical, expedited team service",
    "Hazardous chemicals UN1789 hydrochloric acid, placarded, hazmat endorsed driver",
    "Retail seasonal merchandise, store door delivery, appointment required",
    "Medical devices, validated cold chain, chain of custody documentation",
]

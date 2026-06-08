"""DEMO 3 - Native geospatial queries.

  A. $geoNear   - shipments closest to a chosen port, with distance in meters
  B. $geoWithin - all shipments currently inside a named geofence polygon
  C. Cross-collection: tracking events that occurred inside any port geofence

Run: python -m demos.demo3_geo
"""
from pprint import pprint

from db import get_db
import config
from demos._presenter import banner, note, pause


def near_port(db, port_name: str, max_km: float = 50.0, limit: int = 5) -> list[dict]:
    port = db[config.COL_GEOFENCES].find_one({"name": port_name})
    if not port:
        raise SystemExit(f"Geofence '{port_name}' not found")
    pipeline = [
        {"$geoNear": {
            "near": port["center"],
            "distanceField": "distance_m",
            "maxDistance": max_km * 1000,
            "spherical": True,
            "key": "current_location",
        }},
        {"$limit": limit},
        {"$project": {"_id": 1, "status": 1, "carrier.name": 1,
                      "destination.name": 1, "distance_m": 1}},
    ]
    return list(db[config.COL_SHIPMENTS].aggregate(pipeline))


def within_geofence(db, fence_name: str, limit: int = 5) -> list[dict]:
    fence = db[config.COL_GEOFENCES].find_one({"name": fence_name})
    if not fence:
        raise SystemExit(f"Geofence '{fence_name}' not found")
    cursor = db[config.COL_SHIPMENTS].find(
        {"current_location": {"$geoWithin": {"$geometry": fence["geometry"]}}},
        {"_id": 1, "status": 1, "carrier.name": 1, "destination.name": 1},
    ).limit(limit)
    return list(cursor)


def events_inside_ports(db, limit: int = 5) -> list[dict]:
    # Use one $lookup per event would be slow - instead aggregate per port.
    ports = list(db[config.COL_GEOFENCES].find({"type": "port"}, {"name": 1, "geometry": 1}))
    results: list[dict] = []
    for port in ports:
        n = db[config.COL_TRACKING].count_documents(
            {"location": {"$geoWithin": {"$geometry": port["geometry"]}}}
        )
        results.append({"port": port["name"], "events_in_fence": n})
    results.sort(key=lambda r: -r["events_in_fence"])
    return results[:limit]


def main() -> None:
    db = get_db()

    banner("DEMO 3A - $geoNear: shipments closest to Port of Los Angeles")
    note(
        "Native 2dsphere index on current_location. We compute geodesic distance in\n"
        "meters as part of the projection - no application-side math, no PostGIS\n"
        "extension, no second database to keep in sync."
    )
    pause("ENTER")
    pprint(near_port(db, "Port of Los Angeles", max_km=50))

    banner("DEMO 3B - $geoWithin: shipments currently inside the Chicago Intermodal DC fence")
    note(
        "Geofences are GeoJSON polygons stored as plain documents. $geoWithin uses the\n"
        "same 2dsphere index and works with any polygon - port, yard, customer dock,\n"
        "city, or country boundary. Index definitions never need to change to add fences."
    )
    pause("ENTER")
    pprint(within_geofence(db, "Chicago Intermodal DC"))

    banner("DEMO 3C - Tracking events that occurred inside each port")
    note(
        "This is what powers dwell-time analytics and demurrage risk dashboards.\n"
        "One query per geofence, indexed lookups, fully consistent with the live\n"
        "shipment data because it's all one cluster."
    )
    pause("ENTER")
    pprint(events_inside_ports(db))

    banner("Operational pattern")
    note(
        "Change Streams + $geoIntersects in the application tier = real-time geofence\n"
        "entry/exit events without polling. We can wire that into the ACID demo for an\n"
        "end-to-end story: enter geofence -> auto-update status -> emit notification."
    )


if __name__ == "__main__":
    main()

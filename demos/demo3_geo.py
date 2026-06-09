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
        "$geoNear against the 2dsphere index on shipments.current_location returns\n"
        "shipments ordered by geodesic distance from the port center, with the\n"
        "distance projected as distance_m (meters), capped at 50 km."
    )
    pause("ENTER")
    pprint(near_port(db, "Port of Los Angeles", max_km=50))

    banner("DEMO 3B - $geoWithin: shipments currently inside the Chicago Intermodal DC fence")
    note(
        "Geofences are GeoJSON polygons stored as documents in the geofences\n"
        "collection. $geoWithin reuses the 2dsphere index on current_location and\n"
        "matches shipments whose current position falls inside the polygon. Adding\n"
        "new fences requires no index changes."
    )
    pause("ENTER")
    pprint(within_geofence(db, "Chicago Intermodal DC"))

    banner("DEMO 3C - Tracking events that occurred inside each port")
    note(
        "For each port-type geofence, counts tracking_events whose location falls\n"
        "inside the polygon using $geoWithin against tracking_events.location.\n"
        "Results are sorted by event count to surface the busiest ports."
    )
    pause("ENTER")
    pprint(events_inside_ports(db))

    banner("Operational pattern")
    note(
        "Geospatial queries compose with Change Streams in the application tier to\n"
        "react to geofence entry/exit events as they happen, and with multi-document\n"
        "transactions (Demo 1) to update shipment state atomically on entry."
    )


if __name__ == "__main__":
    main()

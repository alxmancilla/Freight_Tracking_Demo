"""Generate ~20 GeoJSON Polygon geofences around US ports/warehouses.

Run: python -m data_generation.generate_geofences
"""
import math
from pymongo import GEOSPHERE
from db import get_db
import config
from data_generation.reference_data import US_HUBS


def _square_polygon(lon: float, lat: float, radius_km: float = 5.0) -> list[list[list[float]]]:
    """Build a closed GeoJSON polygon ring approximating a square of side 2*radius_km."""
    # Degrees per km (rough, latitude-adjusted)
    dlat = radius_km / 110.574
    dlon = radius_km / (111.320 * math.cos(math.radians(lat)))
    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],  # close
    ]
    return [ring]


def main() -> None:
    db = get_db()
    col = db[config.COL_GEOFENCES]
    col.drop()

    docs = []
    for hub in US_HUBS:
        radius = 8.0 if hub["type"] == "port" else 3.0
        docs.append({
            "name": hub["name"],
            "type": hub["type"],
            "city": hub["city"],
            "state": hub["state"],
            "center": {"type": "Point", "coordinates": [hub["lon"], hub["lat"]]},
            "geometry": {
                "type": "Polygon",
                "coordinates": _square_polygon(hub["lon"], hub["lat"], radius),
            },
        })

    col.insert_many(docs)
    col.create_index([("geometry", GEOSPHERE)])
    col.create_index([("center", GEOSPHERE)])
    col.create_index("type")
    print(f"Inserted {len(docs)} geofences into {config.COL_GEOFENCES}")


if __name__ == "__main__":
    main()

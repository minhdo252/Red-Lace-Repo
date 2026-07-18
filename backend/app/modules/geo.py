"""GPS to MVP region resolution."""

from __future__ import annotations

import math

from app.db.postgres import get_pool

GPS_DRIFT_FALLBACK_KM = 45.0


def validate_lat_lon(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("lat and lon must be finite numbers")
    if lat < -90 or lat > 90:
        raise ValueError("lat must be between -90 and 90")
    if lon < -180 or lon > 180:
        raise ValueError("lon must be between -180 and 180")


async def resolve_region(lat: float, lon: float) -> str | None:
    """Return city name matching emergency_hotlines.region.

    Uses Haversine distance in SQL and accepts a 45km buffer for GPS drift or
    city outskirts. Returns values such as "Hanoi", "Sapa", or "Hoi An".
    """
    validate_lat_lon(lat, lon)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT zone_name, city, radius_km,
                   6371 * acos(
                       least(1.0, greatest(-1.0,
                           cos(radians($1)) * cos(radians(center_lat)) *
                           cos(radians(center_lon) - radians($2)) +
                           sin(radians($1)) * sin(radians(center_lat))
                       ))
                   ) AS distance_km
            FROM geo_regions
            ORDER BY distance_km ASC
            """,
            lat,
            lon,
        )

    if not rows:
        return None

    nearest = rows[0]
    if nearest["distance_km"] <= nearest["radius_km"]:
        return nearest["city"]
    if nearest["distance_km"] <= GPS_DRIFT_FALLBACK_KM:
        return nearest["city"]
    return None


async def nearest_location_text(lat: float, lon: float) -> tuple[str, str]:
    """Return Vietnamese and English location text for reading aloud."""
    validate_lat_lon(lat, lon)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT zone_name, city,
                   6371 * acos(least(1.0, greatest(-1.0,
                       cos(radians($1)) * cos(radians(center_lat)) *
                       cos(radians(center_lon) - radians($2)) +
                       sin(radians($1)) * sin(radians(center_lat))
                   ))) AS distance_km
            FROM geo_regions
            ORDER BY distance_km ASC
            LIMIT 1
            """,
            lat,
            lon,
        )

    if row and row["distance_km"] <= GPS_DRIFT_FALLBACK_KM:
        return (
            f"Tôi đang ở gần khu vực {row['zone_name']}, {row['city']}. "
            f"Tọa độ GPS: {lat:.5f}, {lon:.5f}",
            f"I am near {row['zone_name']}, {row['city']}. GPS: {lat:.5f}, {lon:.5f}",
        )
    return (
        f"Tọa độ GPS của tôi: {lat:.5f}, {lon:.5f}",
        f"My GPS coordinates: {lat:.5f}, {lon:.5f}",
    )

"""Nearby city detection used by GPS mode.

The service is intentionally framework-free so it can be tested without Flask.
It filters out unsupported countries and small settlements before doing the
more expensive distance calculation.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Iterable, List, Optional


MIN_CITY_POPULATION = 10_000
NEARBY_CACHE_TTL_S = 60.0

_NEARBY_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def clear_nearby_city_cache() -> None:
    _NEARBY_CACHE.clear()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _cache_key(
    *,
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    lang: str,
    min_population: int,
) -> str:
    # 3 decimals is roughly 110 m. This avoids repeated API work while the car
    # creeps forward, without hiding real city changes.
    return ":".join(
        [
            f"{lat:.3f}",
            f"{lon:.3f}",
            f"{radius_km:.1f}",
            str(limit),
            str(lang or ""),
            str(min_population),
        ]
    )


def detect_nearby_cities(
    *,
    cities: Iterable[Dict[str, Any]],
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    lang: str,
    resolve_country: Callable[[str], Optional[Dict[str, Any]]],
    slugify: Callable[[str], str],
    city_url: Callable[[str, str, str], str],
    country_display_name_for_lang: Callable[[Dict[str, Any], str], str],
    city_display_name_for_lang: Callable[[Dict[str, Any], str], str],
    min_population: int = MIN_CITY_POPULATION,
    cache_ttl_s: float = NEARBY_CACHE_TTL_S,
) -> List[Dict[str, Any]]:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return []

    radius_km = max(0.5, min(float(radius_km), 100.0))
    limit = max(1, min(int(limit), 200))
    min_population = max(0, int(min_population))
    lang = str(lang or "en").strip().lower() or "en"

    key = _cache_key(
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        limit=limit,
        lang=lang,
        min_population=min_population,
    )
    now = time.time()
    cached = _NEARBY_CACHE.get(key)
    if cached and (now - cached[0]) < cache_ttl_s:
        return [dict(item) for item in cached[1]]

    lat_deg = radius_km / 111.0
    lon_deg = radius_km / max(1e-6, (111.0 * math.cos(math.radians(lat))))
    min_lat, max_lat = lat - lat_deg, lat + lat_deg
    min_lon, max_lon = lon - lon_deg, lon + lon_deg

    found: List[Dict[str, Any]] = []

    for city in cities:
        population = _int(city.get("population") or 0)
        if population <= min_population:
            continue

        country = resolve_country(str(city.get("country") or ""))
        if not country:
            continue

        clat = _num(city.get("lat"), float("nan"))
        clon = _num(city.get("lon"), float("nan"))
        if not (math.isfinite(clat) and math.isfinite(clon)):
            continue
        if clat < min_lat or clat > max_lat or clon < min_lon or clon > max_lon:
            continue

        distance = haversine_km(lat, lon, clat, clon)
        if distance > radius_km:
            continue

        city_slug = slugify(str(city.get("name") or ""))
        country_slug = str(country.get("slug") or "")
        item = {
            "id": city.get("id"),
            "name": city.get("name"),
            "country": city.get("country"),
            "lat": clat,
            "lon": clon,
            "population": population,
            "wikiTitle": city.get("wikiTitle") or city.get("name"),
            "distKm": distance,
            "countryName": country.get("name"),
            "countryDisplayName": country_display_name_for_lang(country, lang),
            "countrySlug": country_slug,
            "countryCode": country.get("code"),
            "flag": country.get("flagUrl"),
            "flagEmoji": country.get("flagEmoji") or "🌍",
            "citySlug": city_slug,
            "url": city_url(lang, country_slug, city_slug) if country_slug and city_slug else "",
        }
        item["displayName"] = city_display_name_for_lang({**city, **item}, lang)
        found.append(item)

    found.sort(key=lambda x: float(x.get("distKm") or 0))
    out = found[:limit]
    _NEARBY_CACHE[key] = (now, [dict(item) for item in out])
    return [dict(item) for item in out]

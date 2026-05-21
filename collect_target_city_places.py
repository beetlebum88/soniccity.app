import argparse
import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

import app


ROOT = Path(__file__).resolve().parent
DISCOVERY_CACHE_DIR = ROOT / "cache" / "place_discovery"

USER_AGENT = "SonicCityAudioGuide/1.0 (place discovery; local dev)"

GOOD_WORDS = {
    "architecture",
    "basilica",
    "bridge",
    "building",
    "castle",
    "cathedral",
    "church",
    "garden",
    "historic",
    "landmark",
    "market",
    "monument",
    "museum",
    "opera",
    "palace",
    "park",
    "plaza",
    "square",
    "temple",
    "theatre",
    "tower",
    "tourism",
    "unesco",
}

BAD_TITLE_RE = re.compile(
    r"\b("
    r"accident|bombing|bus|canton|district|election|football|line|metro|municipality|"
    r"neighbourhood|neighborhood|population|railway|road|school|station|street|tram|"
    r"university|ward"
    r")\b",
    re.I,
)


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def category_for(title: str, categories_text: str) -> str:
    text = f"{title} {categories_text}".lower()
    if "museum" in text or "gallery" in text:
        return "Museum"
    if "cathedral" in text:
        return "Cathedral"
    if "church" in text or "basilica" in text or "temple" in text:
        return "Church"
    if "castle" in text or "fortress" in text:
        return "Castle"
    if "palace" in text:
        return "Palace"
    if "park" in text or "garden" in text:
        return "Park"
    if "bridge" in text:
        return "Bridge"
    if "market" in text:
        return "Market"
    if "square" in text or "plaza" in text:
        return "Square"
    if "theatre" in text or "opera" in text:
        return "Theatre"
    if "monument" in text or "memorial" in text:
        return "Monument"
    return "Landmark"


def score_candidate(title: str, categories_text: str, dist: float, has_image: bool) -> int:
    title_l = title.lower()
    if BAD_TITLE_RE.search(title_l):
        return -100
    if title_l.startswith(("list of ", "history of ", "timeline of ")):
        return -100
    text = f"{title_l} {categories_text.lower()}"
    score = 0
    for word in GOOD_WORDS:
        if word in text:
            score += 5
    if has_image:
        score += 4
    if dist <= 2000:
        score += 3
    elif dist <= 6000:
        score += 2
    else:
        score += 1
    return score


def wiki_api(params: Dict[str, Any], retries: int = 3) -> Dict[str, Any]:
    delay = 8.0
    for attempt in range(retries):
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
        if r.status_code == 429 and attempt < retries - 1:
            retry_after = r.headers.get("Retry-After")
            try:
                delay = max(delay, float(retry_after or 0))
            except Exception:
                pass
            time.sleep(delay)
            delay *= 1.8
            continue
        r.raise_for_status()
        return r.json()
    return {}


def wiki_geosearch_places(city: Dict[str, Any], needed: int, radius_m: int) -> List[Dict[str, Any]]:
    lat = float(city.get("lat") or 0)
    lon = float(city.get("lon") or 0)
    if not lat or not lon or needed <= 0:
        return []

    cache_path = DISCOVERY_CACHE_DIR / str(city.get("countrySlug") or "") / f"{city.get('citySlug')}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return cached[:needed]
        except Exception:
            pass

    params = {
        "action": "query",
        "format": "json",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": min(max(int(radius_m or 10000), 10), 10000),
        "gslimit": 100,
        "gsnamespace": 0,
    }
    pages = wiki_api(params).get("query", {}).get("geosearch", [])
    if not pages:
        return []

    pageids = [str(p.get("pageid")) for p in pages if p.get("pageid")]
    meta: Dict[str, Any] = {}
    for i in range(0, len(pageids), 50):
        chunk = pageids[i : i + 50]
        meta.update(
            wiki_api(
                {
                "action": "query",
                "format": "json",
                "pageids": "|".join(chunk),
                "prop": "pageprops|pageimages|categories|coordinates",
                "ppprop": "wikibase_item",
                "pithumbsize": 900,
                "cllimit": 30,
                "coprimary": "primary",
                }
            ).get("query", {}).get("pages", {})
        )

    rows: List[Tuple[int, Dict[str, Any]]] = []
    seen = set()
    city_name_norm = normalize_name(str(city.get("name") or ""))
    for p in pages:
        pageid = str(p.get("pageid") or "")
        m = meta.get(pageid, {})
        title = str(p.get("title") or m.get("title") or "").strip()
        if not title:
            continue
        n = normalize_name(title)
        if not n or n == city_name_norm or n in seen:
            continue
        seen.add(n)
        categories_text = " ".join(str(c.get("title") or "") for c in m.get("categories", [])).lower()
        thumb = str((m.get("thumbnail") or {}).get("source") or "").strip()
        dist = float(p.get("dist") or 999999)
        score = score_candidate(title, categories_text, dist, bool(thumb))
        if score <= 0:
            continue
        coord = (m.get("coordinates") or [{}])[0]
        row = {
            "name": title,
            "slug": app.slugify(title),
            "category": category_for(title, categories_text),
            "wikipediaUrl": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            "lat": coord.get("lat") or p.get("lat"),
            "lon": coord.get("lon") or p.get("lon"),
        }
        qid = (m.get("pageprops") or {}).get("wikibase_item")
        if qid:
            row["wikidataId"] = qid
        if thumb:
            row["image"] = thumb
        rows.append((score, row))

    rows.sort(key=lambda x: (-x[0], str(x[1].get("name") or "")))
    out = [row for _, row in rows[: max(needed, 10)]]
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out[:needed]


def find_or_create_country(data: Dict[str, Any], country_slug: str, country_name: str) -> Dict[str, Any]:
    cb = data.setdefault("countries_by_slug", {})
    payload = cb.get(country_slug)
    if not isinstance(payload, dict):
        payload = {"name": country_name, "cities": []}
        cb[country_slug] = payload
    payload.setdefault("name", country_name)
    payload.setdefault("cities", [])
    return payload


def find_or_create_city(payload: Dict[str, Any], country_slug: str, city: Dict[str, Any]) -> Dict[str, Any]:
    city_slug = str(city.get("citySlug") or "")
    for row in payload.get("cities", []):
        if not isinstance(row, dict):
            continue
        row_slug = app.slugify(str(row.get("name") or ""))
        row_slug = app.CITY_PLACE_CITY_SLUG_ALIASES.get((country_slug, row_slug), row_slug)
        if row_slug == city_slug:
            row.setdefault("places", [])
            return row
    row = {"name": str(city.get("name") or city_slug).strip(), "places": []}
    payload.setdefault("cities", []).append(row)
    return row


def merge_places(existing: List[Any], additions: List[Dict[str, Any]], places_per_city: int) -> Tuple[List[Any], int]:
    out = list(existing or [])
    seen = set()
    for p in out:
        name = str(p.get("name") if isinstance(p, dict) else p or "").strip()
        if name:
            seen.add(normalize_name(name))
    added = 0
    for p in additions:
        name = str(p.get("name") or "").strip()
        key = normalize_name(name)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
        added += 1
        if len(out) >= places_per_city:
            break
    return out[:places_per_city], added


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect up to 10 tourist places for each target city.")
    parser.add_argument("--countries", default="", help="Comma-separated country slugs. Empty = all supported countries.")
    parser.add_argument("--cities-per-country", type=int, default=app.TARGET_CITIES_PER_COUNTRY)
    parser.add_argument("--places-per-city", type=int, default=app.TARGET_PLACES_PER_CITY)
    parser.add_argument("--radius-m", type=int, default=10000)
    parser.add_argument("--limit-cities", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data_path = app.PLACES_INDEX_PATH
    data = app.load_json(data_path)
    if not isinstance(data, dict):
        data = {"countries_by_slug": {}}

    country_filter = {
        x.strip().lower()
        for x in str(args.countries or "").split(",")
        if x.strip()
    }

    targets: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for country in app.europe_countries():
        country_slug = str(country.get("slug") or "").strip().lower()
        if country_filter and country_slug not in country_filter:
            continue
        for city in app.target_country_cities(country_slug, args.cities_per_country):
            targets.append((country_slug, country, city))
    if args.limit_cities > 0:
        targets = targets[: args.limit_cities]

    changed = 0
    added_total = 0
    for idx, (country_slug, country, city) in enumerate(targets, start=1):
        payload = find_or_create_country(data, country_slug, str(country.get("name") or country_slug))
        city_entry = find_or_create_city(payload, country_slug, city)
        existing = city_entry.get("places") if isinstance(city_entry.get("places"), list) else []
        missing = max(0, int(args.places_per_city) - len(existing))
        added = 0
        if missing > 0:
            try:
                additions = wiki_geosearch_places(city, missing, args.radius_m)
                merged, added = merge_places(existing, additions, int(args.places_per_city))
                city_entry["places"] = merged
            except Exception as exc:
                print(f"[WARN] {country_slug}/{city.get('citySlug')}: {exc}")
        if added:
            changed += 1
            added_total += added
            if not args.dry_run and int(args.save_every or 0) > 0 and changed % int(args.save_every or 1) == 0:
                data_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(
            f"[{idx}/{len(targets)}] {country_slug}/{city.get('citySlug')} "
            f"places={len(city_entry.get('places') or [])} added={added}"
        )
        if args.sleep:
            time.sleep(max(0.0, float(args.sleep)))

    if not args.dry_run:
        data_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[OK] targets={len(targets)} changed_cities={changed} added_places={added_total} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

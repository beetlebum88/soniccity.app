#!/usr/bin/env python3
"""Backfill cached landmark/place images from Wikimedia/Wikipedia sources."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG,
    PLACE_IMAGE_CACHE_DIR,
    WIKI_USER_AGENT,
    http_get_json,
    wiki_thumbnail_url,
    wiki_thumbnail_url_search,
)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
REPORT_PATH = ROOT / "logs" / "place_image_backfill_report.json"


def cache_dir(country_slug: str, city_slug: str) -> Path:
    return PLACE_IMAGE_CACHE_DIR / "en" / country_slug / city_slug


def real_cached_file(country_slug: str, city_slug: str, place_slug: str) -> Optional[Path]:
    base = cache_dir(country_slug, city_slug)
    for ext in IMAGE_EXTS:
        fp = base / f"{place_slug}{ext}"
        if fp.exists() and fp.stat().st_size > 128:
            try:
                if detected_image_ext(fp.read_bytes()[:32]):
                    return fp
            except OSError:
                continue
            try:
                fp.unlink()
            except OSError:
                pass
        elif fp.exists():
            try:
                fp.unlink()
            except OSError:
                pass
    return None


def remove_placeholders(country_slug: str, city_slug: str, place_slug: str) -> None:
    base = cache_dir(country_slug, city_slug)
    for ext in (".missing", ".svg", ".tmp"):
        fp = base / f"{place_slug}{ext}"
        try:
            if fp.exists():
                fp.unlink()
        except OSError:
            pass


def file_ext_from_bytes(data: bytes, fallback_url: str = "") -> str:
    detected = detected_image_ext(data)
    if detected:
        return detected
    path_ext = Path(urllib.parse.urlparse(fallback_url).path).suffix.lower()
    if path_ext == ".jpeg":
        return ".jpg"
    if path_ext in IMAGE_EXTS:
        return path_ext
    return ".jpg"


def detected_image_ext(data: bytes) -> Optional[str]:
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return ".webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return None


def download_image(url: str, timeout_s: int = 12, retries: int = 2) -> Optional[Tuple[bytes, str]]:
    if not url.startswith(("http://", "https://")):
        return None
    curl = shutil.which("curl")
    if curl:
        try:
            proc = subprocess.run(
                [
                    curl,
                    "-L",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "4",
                    "--retry-all-errors",
                    "--retry-delay",
                    "1",
                    "--max-time",
                    str(max(2, int(timeout_s))),
                    "-A",
                    WIKI_USER_AGENT,
                    url,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=max(4, int(timeout_s) + 4),
            )
            data = proc.stdout or b""
            if proc.returncode == 0 and len(data) >= 128 and detected_image_ext(data):
                return data, url
        except Exception:
            pass
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                data = resp.read()
                final_url = str(resp.geturl() or url)
            if len(data) < 128:
                raise ValueError("response too small")
            if ctype and "image" not in ctype and not final_url.lower().endswith(IMAGE_EXTS):
                raise ValueError(f"non-image content type: {ctype}")
            if not detected_image_ext(data):
                raise ValueError("response is not a supported image")
            return data, final_url
        except Exception:
            if attempt + 1 < max(1, retries):
                time.sleep(0.4 * (attempt + 1))
    return None


def wikipedia_title_from_url(url: str) -> Tuple[str, str]:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = parsed.netloc.lower()
        if ".wikipedia.org" not in host:
            return "", ""
        lang = host.split(".")[0] or "en"
        parts = parsed.path.split("/wiki/", 1)
        if len(parts) != 2:
            return "", ""
        return lang, urllib.parse.unquote(parts[1]).replace("_", " ")
    except Exception:
        return "", ""


def wiki_summary_image(lang: str, title: str) -> Optional[str]:
    title = str(title or "").strip()
    if not title:
        return None
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return None
    for key in ("originalimage", "thumbnail"):
        img = data.get(key)
        if isinstance(img, dict) and img.get("source"):
            return str(img["source"])
    return None


def wikidata_p18_image(qid: str) -> Optional[str]:
    qid = str(qid or "").strip()
    if not re.fullmatch(r"Q\d+", qid):
        return None
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    data = http_get_json(url, timeout_s=12)
    try:
        claims = data["entities"][qid]["claims"]
        p18 = claims.get("P18") or []
        for claim in p18:
            filename = claim["mainsnak"]["datavalue"]["value"]
            if filename:
                return f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(str(filename).replace(' ', '_'))}?width=1400"
    except Exception:
        return None
    return None


def wikidata_search_image(query: str, lang: str = "en") -> Optional[str]:
    query = str(query or "").strip()
    if not query:
        return None
    params = {
        "action": "wbsearchentities",
        "format": "json",
        "language": lang,
        "uselang": lang,
        "limit": "5",
        "search": query,
    }
    url = f"https://www.wikidata.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return None
    for row in data.get("search") or []:
        qid = str(row.get("id") or "")
        img = wikidata_p18_image(qid)
        if img:
            return img
    return None


def commons_search_image(query: str) -> Optional[str]:
    query = str(query or "").strip()
    if not query:
        return None
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "6",
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": "1400",
    }
    url = f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return None
    pages = ((data.get("query") or {}).get("pages") or [])
    if not isinstance(pages, list):
        return None
    for page in pages:
        if not isinstance(page, dict):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        if not isinstance(info, dict):
            continue
        mime = str(info.get("mime") or "").lower()
        if not mime.startswith("image/"):
            continue
        image_url = str(info.get("thumburl") or info.get("url") or "").strip()
        if image_url.startswith(("http://", "https://")):
            return image_url
    return None


def candidate_urls(place: Dict[str, Any], *, search: bool = True, direct_only: bool = False) -> Iterable[Tuple[str, str]]:
    name = str(place.get("name") or "").strip()
    city = str(place.get("cityName") or "").strip()
    country = str(place.get("countryName") or "").strip()
    wiki_url = str(place.get("wikipediaUrl") or "").strip()

    direct = str(place.get("imageUrl") or place.get("image") or "").strip()
    if direct.startswith(("http://", "https://")):
        yield "direct", direct
    if direct_only:
        return

    wiki_lang, wiki_title = wikipedia_title_from_url(wiki_url)
    if wiki_lang and wiki_title:
        img = wiki_summary_image(wiki_lang, wiki_title)
        if img:
            yield "wikipedia-summary", img
        img = wiki_thumbnail_url(wiki_lang, wiki_title, size_px=1400)
        if img:
            yield "wikipedia-pageimage", img

    qid = str(place.get("wikidataId") or "").strip()
    img = wikidata_p18_image(qid)
    if img:
        yield "wikidata-p18", img

    if not search:
        return

    title_candidates = [name]
    if city:
        title_candidates.extend([f"{name}, {city}", f"{name} ({city})"])
    cleaned = re.sub(
        r"\b(day\s*trip|nearby|sites|cruise|riverwalk|boat\s*tour|walking\s*tour|tour)\b",
        "",
        name,
        flags=re.I,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-–—")
    if cleaned and cleaned.lower() != name.lower():
        title_candidates.append(cleaned)
        if city:
            title_candidates.extend([f"{cleaned}, {city}", f"{cleaned} ({city})"])

    seen = set()
    for title in title_candidates:
        title = title.strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        img = wiki_thumbnail_url("en", title, size_px=1400)
        if img:
            yield "wikipedia-title", img

    search_queries = []
    if city:
        search_queries.append(f"{name} {city}")
    if country:
        search_queries.append(f"{name} {country}")
    if cleaned and cleaned.lower() != name.lower():
        if city:
            search_queries.append(f"{cleaned} {city}")
        if country:
            search_queries.append(f"{cleaned} {country}")

    seen.clear()
    for query in search_queries:
        query = query.strip()
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        img = commons_search_image(query)
        if img:
            yield "commons-search", img
        img = wiki_thumbnail_url_search("en", query, size_px=1400)
        if img:
            yield "wikipedia-search", img
        img = wikidata_search_image(query, "en")
        if img:
            yield "wikidata-search", img


def save_image(place: Dict[str, Any], url: str, source: str) -> Optional[Dict[str, Any]]:
    result = None
    for attempt in range(4):
        result = download_image(url)
        if result:
            break
        if attempt < 3:
            time.sleep(1.25 * (attempt + 1))
    if not result:
        return None
    data, final_url = result
    country_slug = str(place["countrySlug"])
    city_slug = str(place["citySlug"])
    place_slug = str(place["slug"])
    base = cache_dir(country_slug, city_slug)
    base.mkdir(parents=True, exist_ok=True)
    ext = file_ext_from_bytes(data, final_url)
    dest = base / f"{place_slug}{ext}"
    tmp = base / f"{place_slug}.tmp"
    tmp.write_bytes(data)
    tmp.replace(dest)
    remove_placeholders(country_slug, city_slug, place_slug)
    return {"path": str(dest.relative_to(ROOT)), "bytes": len(data), "source": source, "url": final_url}


def all_places() -> List[Dict[str, Any]]:
    by_key: Dict[Tuple[Any, Any, Any], Dict[str, Any]] = {}

    def score(place: Dict[str, Any]) -> int:
        return (
            (100 if place.get("image") or place.get("imageUrl") else 0)
            + (30 if place.get("wikidataId") else 0)
            + (25 if place.get("wikipediaUrl") else 0)
            + (10 if place.get("lat") and place.get("lon") else 0)
            + min(len(str(place.get("name") or "")), 40)
        )

    for (_country_slug, _city_slug), places in sorted(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.items()):
        for place in places:
            key = (place.get("countrySlug"), place.get("citySlug"), place.get("slug"))
            if not all(key):
                continue
            current = by_key.get(key)
            if current is None or score(place) > score(current):
                by_key[key] = place
    return [by_key[key] for key in sorted(by_key.keys())]


def process_place(
    place: Dict[str, Any],
    *,
    force: bool = False,
    dry_run: bool = False,
    search: bool = True,
    direct_only: bool = False,
) -> Dict[str, Any]:
    country_slug = str(place.get("countrySlug") or "")
    city_slug = str(place.get("citySlug") or "")
    place_slug = str(place.get("slug") or "")
    row = {
        "countrySlug": country_slug,
        "citySlug": city_slug,
        "placeSlug": place_slug,
        "name": place.get("name"),
        "status": "missing",
    }
    if not force:
        cached = real_cached_file(country_slug, city_slug, place_slug)
        if cached:
            row.update({"status": "cached", "path": str(cached.relative_to(ROOT)), "bytes": cached.stat().st_size})
            return row
    if dry_run:
        row["status"] = "would_fetch"
        return row
    for source, url in candidate_urls(place, search=search, direct_only=direct_only):
        saved = save_image(place, url, source)
        if saved:
            row.update({"status": "saved", **saved})
            return row
    # Do not create a .missing marker here: the public endpoint may still find a future image.
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="ignore existing cached images")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--known-only", action="store_true", help="skip broad Wikipedia/Wikidata search; use direct/Wikipedia URL/Wikidata only")
    parser.add_argument("--direct-only", action="store_true", help="only use explicit image/imageUrl fields from data")
    parser.add_argument("--from-report", action="store_true", help="retry only rows listed as missing/error in the previous report")
    parser.add_argument("--missing-now", action="store_true", help="process only places without a real cached image right now")
    parser.add_argument("--has-direct", action="store_true", help="process only places that have an explicit image/imageUrl field")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--delay", type=float, default=0.0, help="sleep after each completed row, useful to avoid Wikimedia throttling")
    args = parser.parse_args()

    places = all_places()
    if args.from_report and REPORT_PATH.exists():
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        wanted = {
            (row.get("countrySlug"), row.get("citySlug"), row.get("placeSlug"))
            for row in (previous.get("missing") or [])
            if isinstance(row, dict)
        }
        places = [place for place in places if (place.get("countrySlug"), place.get("citySlug"), place.get("slug")) in wanted]
    if args.missing_now:
        places = [place for place in places if not real_cached_file(str(place.get("countrySlug")), str(place.get("citySlug")), str(place.get("slug")))]
    if args.has_direct:
        places = [place for place in places if str(place.get("imageUrl") or place.get("image") or "").strip().startswith(("http://", "https://"))]
    if args.limit > 0:
        places = places[: args.limit]
    total = len(places)
    started = time.time()
    results: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    bytes_saved = 0

    print(f"Backfilling place images: {total} places, workers={args.workers}, force={args.force}, dry_run={args.dry_run}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_map = {
            pool.submit(
                process_place,
                place,
                force=args.force,
                dry_run=args.dry_run,
                search=not args.known_only,
                direct_only=args.direct_only,
            ): place
            for place in places
        }
        for idx, future in enumerate(concurrent.futures.as_completed(future_map), start=1):
            try:
                row = future.result()
            except Exception as exc:
                place = future_map[future]
                row = {
                    "countrySlug": place.get("countrySlug"),
                    "citySlug": place.get("citySlug"),
                    "placeSlug": place.get("slug"),
                    "name": place.get("name"),
                    "status": "error",
                    "error": str(exc),
                }
            results.append(row)
            status = str(row.get("status") or "missing")
            counts[status] = counts.get(status, 0) + 1
            bytes_saved += int(row.get("bytes") or 0) if status == "saved" else 0
            if idx % 50 == 0 or idx == total:
                elapsed = max(time.time() - started, 0.01)
                print(f"{idx}/{total} saved={counts.get('saved', 0)} cached={counts.get('cached', 0)} missing={counts.get('missing', 0)} error={counts.get('error', 0)} rate={idx/elapsed:.1f}/s", flush=True)
            if args.delay > 0:
                time.sleep(args.delay)

    summary = {
        "total": total,
        "counts": counts,
        "bytesSaved": bytes_saved,
        "mbSaved": round(bytes_saved / 1024 / 1024, 2),
        "elapsedSeconds": round(time.time() - started, 2),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "missing": [row for row in results if row.get("status") in {"missing", "error"}],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary | {"missing": f"{len(summary['missing'])} rows in {REPORT_PATH}"}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import argparse
import concurrent.futures
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import app


RASTER_EXTS = (".jpg", ".jpeg", ".png", ".webp")
BAD_TITLE_TOKENS = (
    " locator",
    " location",
    " map",
    " flag",
    " coat of arms",
    " coat-of-arms",
    " emblem",
    " seal",
    " logo",
    " icon",
    " symbol",
    " diagram",
    " graph",
    " chart",
    " plan",
    " route",
    " sign",
    " blank",
    " svg",
    " population",
)
GOOD_QUERY_SUFFIXES = (
    "city panorama",
    "skyline",
    "old town",
    "city centre",
    "city center",
    "street",
    "view",
    "",
)

PRINT_LOCK = threading.Lock()


def has_raster_image(country_slug: str, city_slug: str) -> bool:
    cache_dir = app.CITY_IMAGE_CACHE_DIR / "en" / country_slug
    for ext in RASTER_EXTS:
        fp = cache_dir / f"{city_slug}{ext}"
        if fp.exists() and fp.stat().st_size > 0:
            return True
    return False


def has_any_city_image(country_slug: str, city_slug: str) -> bool:
    cache_dir = app.CITY_IMAGE_CACHE_DIR / "en" / country_slug
    for ext in (*RASTER_EXTS, ".gif", ".svg"):
        fp = cache_dir / f"{city_slug}{ext}"
        if fp.exists() and fp.stat().st_size > 0:
            return True
    return False


def is_bad_title(title: str) -> bool:
    low = f" {str(title or '').lower().replace('_', ' ')} "
    return any(token in low for token in BAD_TITLE_TOKENS)


def ext_from_url_or_mime(url: str, mime: str) -> str:
    ext = app.image_ext_from_url(url)
    if ext in RASTER_EXTS:
        return ".jpg" if ext == ".jpeg" else ext
    mime = str(mime or "").lower()
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    return ".jpg"


def wikipedia_image_candidates(titles: Iterable[str], country_name: str) -> Iterable[str]:
    seen: set[str] = set()
    query_titles: List[str] = []
    for title in titles:
        title = str(title or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        query_titles.extend([title, f"{title}, {country_name}", f"{title} {country_name}"])
    for query_title in query_titles:
        thumb = retry_wiki_thumbnail(query_title)
        if thumb and not thumb.lower().endswith(".svg"):
            yield thumb
        thumb = retry_wiki_thumbnail_search(query_title)
        if thumb and not thumb.lower().endswith(".svg"):
            yield thumb


def retry_wiki_thumbnail(title: str, attempts: int = 4) -> Optional[str]:
    for attempt in range(attempts):
        thumb = app.wiki_thumbnail_url("en", title, size_px=1400)
        if thumb:
            return thumb
        if attempt + 1 < attempts:
            time.sleep(0.35 + attempt * 0.25)
    return None


def retry_wiki_thumbnail_search(query: str, attempts: int = 3) -> Optional[str]:
    for attempt in range(attempts):
        thumb = app.wiki_thumbnail_url_search("en", query, size_px=1400)
        if thumb:
            return thumb
        if attempt + 1 < attempts:
            time.sleep(0.35 + attempt * 0.25)
    return None


def commons_candidates(city_name: str, country_name: str, limit: int = 5) -> Iterable[Dict[str, str]]:
    seen: set[str] = set()
    base = "https://commons.wikimedia.org/w/api.php"
    for suffix in GOOD_QUERY_SUFFIXES:
        query = f"{city_name} {country_name} {suffix}".strip()
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "iiurlwidth": "1400",
        }
        data = app.http_get_json(f"{base}?{urllib.parse.urlencode(params)}", timeout_s=14)
        pages = ((data or {}).get("query") or {}).get("pages") or []
        if not isinstance(pages, list):
            continue
        for page in pages:
            if not isinstance(page, dict):
                continue
            file_title = str(page.get("title") or "")
            if is_bad_title(file_title):
                continue
            info_list = page.get("imageinfo") or []
            if not info_list or not isinstance(info_list[0], dict):
                continue
            info = info_list[0]
            mime = str(info.get("mime") or "").lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            width = int(info.get("thumbwidth") or info.get("width") or 0)
            height = int(info.get("thumbheight") or info.get("height") or 0)
            if width and height:
                ratio = width / max(1, height)
                if ratio < 0.72 or ratio > 3.6:
                    continue
            url = str(info.get("thumburl") or info.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            yield {"url": url, "mime": mime, "title": file_title}


def save_candidate(url: str, mime: str, country_slug: str, city_slug: str) -> Optional[Path]:
    data = None
    for attempt in range(3):
        data = app.http_get_bytes(url, timeout_s=30)
        if data and len(data) >= 8_000:
            break
        if attempt < 2:
            time.sleep(0.35 + attempt * 0.25)
    if not data or len(data) < 8_000:
        return None
    ext = ext_from_url_or_mime(url, mime)
    cache_dir = app.CITY_IMAGE_CACHE_DIR / "en" / country_slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{city_slug}{ext}"
    tmp = cache_dir / f"{city_slug}.tmp"
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def fetch_one(key: Tuple[str, str], force: bool = False, wiki_only: bool = False) -> Tuple[str, str, str, str]:
    country_slug, city_slug = key
    if not force and has_raster_image(country_slug, city_slug):
        return ("skip", country_slug, city_slug, "already has raster")

    city = app.CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {}
    country = app.COUNTRY_BY_SLUG.get(country_slug) or {}
    city_name = str(city.get("name") or city.get("wikiTitle") or city_slug.replace("-", " ").title()).strip()
    title = str(city.get("wikiTitle") or city_name).strip()
    country_name = str(country.get("name") or country_slug.replace("-", " ").title()).strip()

    for url in wikipedia_image_candidates((city_name, title), country_name):
        try:
            dest = save_candidate(url, "", country_slug, city_slug)
            if dest:
                return ("ok", country_slug, city_slug, f"wikipedia -> {dest.name}")
        except Exception as exc:
            last_error = f"wikipedia: {exc}"
        else:
            last_error = "wikipedia: empty"

    if wiki_only:
        return ("missing", country_slug, city_slug, locals().get("last_error", "no wikipedia candidate"))

    for item in commons_candidates(city_name, country_name):
        try:
            dest = save_candidate(item["url"], item.get("mime", ""), country_slug, city_slug)
            if dest:
                return ("ok", country_slug, city_slug, f"commons -> {dest.name}")
        except Exception as exc:
            last_error = f"commons: {exc}"
        else:
            last_error = "commons: empty"

    return ("missing", country_slug, city_slug, locals().get("last_error", "no candidate"))


def build_targets(include_svg_only: bool, include_missing_cache: bool, limit: int = 0) -> List[Tuple[str, str]]:
    keys = sorted(app.CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.keys())
    out: List[Tuple[str, str]] = []
    for country_slug, city_slug in keys:
        if has_raster_image(country_slug, city_slug):
            continue
        if include_svg_only or (include_missing_cache and not has_any_city_image(country_slug, city_slug)):
            out.append((country_slug, city_slug))
    if limit and limit > 0:
        out = out[:limit]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Download real Wikimedia raster images for indexed cities missing city photos.")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--wiki-only", action="store_true")
    parser.add_argument("--missing-cache-only", action="store_true")
    args = parser.parse_args()

    targets = build_targets(
        include_svg_only=not args.missing_cache_only,
        include_missing_cache=True,
        limit=args.limit,
    )
    total = len(targets)
    print(f"Targets: {total}")
    if not targets:
        return 0

    counts = {"ok": 0, "skip": 0, "missing": 0}
    samples: List[Tuple[str, str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futs = [executor.submit(fetch_one, key, args.force, args.wiki_only) for key in targets]
        for i, fut in enumerate(concurrent.futures.as_completed(futs), start=1):
            status, country_slug, city_slug, detail = fut.result()
            counts[status] = counts.get(status, 0) + 1
            if status != "ok" and len(samples) < 25:
                samples.append((country_slug, city_slug, detail))
            with PRINT_LOCK:
                if i % 20 == 0 or i == total or status == "ok":
                    print(f"{i}/{total} ok={counts.get('ok',0)} missing={counts.get('missing',0)} skip={counts.get('skip',0)} • {country_slug}/{city_slug} • {detail}", flush=True)

    if samples:
        print("Remaining missing samples:")
        for country_slug, city_slug, detail in samples:
            print(f"- {country_slug}/{city_slug}: {detail}")
    print(f"Done: {counts}")
    return 0 if counts.get("missing", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

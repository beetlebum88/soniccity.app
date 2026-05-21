#!/usr/bin/env python3
"""Backfill city/place display titles for every published SonicCity language.

The public app treats translated entity titles as the publish gate for localized
city/place pages. The old disk cache lives under ./cache and is ignored by git,
so this script writes the durable catalog to data/entity_title_translations.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    COUNTRY_BY_SLUG,
    ENTITY_TITLE_TRANSLATIONS_PATH,
    LANG_ORDER,
    SUPPORTED_LANGS,
    WIKI_USER_AGENT,
    atomic_write_json,
    cached_localized_title,
    country_display_name_cached_for_lang,
    entity_title_translation_key,
    manual_country_name,
    manual_entity_name,
    target_countries,
    target_country_cities,
    target_places_for_city,
    title_i18n_cache_path,
    write_title_i18n_cache,
    wiki_search_titles,
    wiki_summary_title_if_exists,
)

TARGET_LANGS = [lang for lang in LANG_ORDER if lang != "en"]
OPENAI_BASE_URL = "https://api.openai.com/v1"
LANGUAGE_NAMES = {
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ua": "Ukrainian",
    "de": "German",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_store() -> Dict[str, Any]:
    if not ENTITY_TITLE_TRANSLATIONS_PATH.exists():
        return {"version": 1, "updatedAt": now_iso(), "titles": {}}
    try:
        data = json.loads(ENTITY_TITLE_TRANSLATIONS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("titles", {})
            return data
    except Exception:
        pass
    return {"version": 1, "updatedAt": now_iso(), "titles": {}}


def parse_wikipedia_url(url: str) -> Tuple[str, str]:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = parsed.netloc.lower()
        if ".wikipedia.org" not in host or "/wiki/" not in parsed.path:
            return "", ""
        lang = host.split(".wikipedia.org", 1)[0].split(".")[-1]
        title = urllib.parse.unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ")
        return lang, title
    except Exception:
        return "", ""


def http_json(url: str, timeout: int = 12) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def extract_response_text(data: Any) -> str:
    if isinstance(data, dict):
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for chunk in content:
                    if not isinstance(chunk, dict):
                        continue
                    text = chunk.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
    return ""


def openai_post_json(api_key: str, payload: Dict[str, Any], timeout: int = 90) -> Optional[Any]:
    if not api_key:
        return None
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Optional[Exception] = None
    for attempt in range(1, 7):
        try:
            req = urllib.request.Request(
                f"{OPENAI_BASE_URL}/responses",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= 6:
                try:
                    message = exc.read().decode("utf-8")
                except Exception:
                    message = str(exc)
                raise RuntimeError(f"OpenAI HTTP {exc.code}: {message}") from exc
            retry_after = exc.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after else 0.8 * (1.8 ** (attempt - 1))
            except Exception:
                wait_s = 0.8 * (1.8 ** (attempt - 1))
            time.sleep(min(30.0, max(0.5, wait_s)))
        except Exception as exc:
            last_error = exc
            if attempt >= 6:
                raise
            time.sleep(min(20.0, 0.8 * (1.8 ** (attempt - 1))))
    if last_error:
        raise RuntimeError(f"OpenAI request failed: {last_error}") from last_error
    return None


def parse_json_object(text: str) -> Dict[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v).strip() for k, v in data.items() if str(v).strip()}


def machine_translate_missing_titles(
    rows: List[Dict[str, Any]],
    langs: List[str],
    *,
    api_key: str,
    model: str,
    batch_size: int = 80,
    workers: int = 4,
) -> int:
    if not api_key:
        print("OpenAI fallback skipped: OPENAI_API_KEY is not set.", flush=True)
        return 0
    filled = 0
    for lang in langs:
        target_name = LANGUAGE_NAMES.get(lang, lang)
        missing = [row for row in rows if lang not in (row.get("resolved") or {})]
        if not missing:
            continue
        print(f"OpenAI fallback for {lang}: {len(missing)} missing titles", flush=True)

        def translate_batch(offset: int, batch: List[Dict[str, Any]]) -> Tuple[int, Dict[str, str]]:
            batch = missing[offset : offset + batch_size]
            items = [
                {
                    "id": str(idx),
                    "kind": row.get("kind") or "",
                    "source": row.get("sourceTitle") or "",
                    "city": row.get("cityName") or "",
                    "country": row.get("countryName") or "",
                }
                for idx, row in enumerate(batch)
                if row.get("sourceTitle")
            ]
            if not items:
                return offset, {}
            system = (
                "You localize travel guide entity names for SonicCity.\n"
                "Return only a valid JSON object mapping id to localized display name.\n"
                "Use conventional local-language/Wikipedia-style names when they are known.\n"
                "If a proper name has no natural local-language form, keep the official original name.\n"
                "Translate generic descriptors only when natural for the target language.\n"
                "Do not add city or country unless it is part of the official name. Do not invent facts."
            )
            user = (
                f"Target language: {target_name}.\n"
                "Localize these country, city and landmark names for public page titles/cards:\n"
                f"{json.dumps(items, ensure_ascii=False)}"
            )
            data = openai_post_json(
                api_key,
                {
                    "model": model,
                    "input": [
                        {"role": "system", "content": [{"type": "input_text", "text": system}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user}]},
                    ],
                },
                timeout=120,
            )
            return offset, parse_json_object(extract_response_text(data))

        batches = [
            (offset, missing[offset : offset + batch_size])
            for offset in range(0, len(missing), batch_size)
        ]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(translate_batch, offset, batch) for offset, batch in batches]
            processed = 0
            for future in as_completed(futures):
                offset, translated = future.result()
                batch = missing[offset : offset + batch_size]
                processed += len(batch)
                batch_filled = 0
                for idx, row in enumerate(batch):
                    value = translated.get(str(idx), "").strip()
                    if not value:
                        continue
                    row.setdefault("resolved", {})[lang] = value
                    filled += 1
                    batch_filled += 1
                print(
                    f"  {lang}: {processed}/{len(missing)} fallback processed, batch_filled={batch_filled}, total_filled={filled}",
                    flush=True,
                )
    return filled


def wiki_langlinks_map(from_lang: str, title: str) -> Dict[str, str]:
    from_lang = str(from_lang or "").strip().lower()
    title = str(title or "").strip()
    if not from_lang or not title:
        return {}
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "langlinks",
        "lllimit": "500",
        "titles": title,
    }
    url = f"https://{from_lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_json(url)
    pages = (((data or {}).get("query") or {}).get("pages") or [])
    if not isinstance(pages, list) or not pages:
        return {}
    links = (pages[0] or {}).get("langlinks") or []
    out: Dict[str, str] = {}
    for item in links:
        if not isinstance(item, dict):
            continue
        lang = str(item.get("lang") or "").strip().lower()
        translated = str(item.get("title") or item.get("*") or "").strip()
        if lang and translated:
            out[lang] = translated
    return out


def wikidata_sitelinks(qid: str) -> Dict[str, str]:
    qid = str(qid or "").strip()
    if not re.fullmatch(r"Q\d+", qid):
        return {}
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{urllib.parse.quote(qid)}.json"
    data = http_json(url)
    entity = (((data or {}).get("entities") or {}).get(qid) or {})
    sitelinks = entity.get("sitelinks") or {}
    out: Dict[str, str] = {}
    for key, row in sitelinks.items():
        if not key.endswith("wiki") or not isinstance(row, dict):
            continue
        lang = key[:-4]
        title = str(row.get("title") or "").strip()
        if lang and title:
            out[lang] = title
    return out


def cached_or_manual_title(kind: str, lang: str, country_slug: str, city_slug: str, place_slug: str, source_title: str) -> str:
    if kind == "country":
        manual = manual_country_name(country_slug, lang)
    else:
        manual = manual_entity_name(kind, place_slug if kind == "place" else city_slug, lang)
    if manual:
        return manual
    return cached_localized_title(
        kind=kind,
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
        source_title=source_title,
    )


def search_title(lang: str, source_title: str, city_name: str = "", country_name: str = "") -> str:
    wiki_lang = SUPPORTED_LANGS[lang]["wiki"]
    queries = [
        f'"{source_title}" {city_name} {country_name}'.strip(),
        f'"{source_title}" {city_name}'.strip(),
        f"{source_title} {country_name}".strip(),
        source_title,
    ]
    seen = set()
    for query in [q for q in queries if q and q not in seen]:
        seen.add(query)
        try:
            for title in wiki_search_titles(wiki_lang, query, limit=6):
                resolved = wiki_summary_title_if_exists(wiki_lang, title)
                if resolved:
                    return resolved
        except Exception:
            continue
    return ""


def resolve_entity(entity: Dict[str, Any], langs: List[str], force: bool = False) -> Dict[str, Any]:
    kind = entity["kind"]
    country_slug = entity.get("countrySlug", "")
    city_slug = entity.get("citySlug", "")
    place_slug = entity.get("placeSlug", "")
    source_title = str(entity.get("sourceTitle") or "").strip()
    city_name = str(entity.get("cityName") or "").strip()
    country_name = str(entity.get("countryName") or "").strip()
    wikipedia_url = str(entity.get("wikipediaUrl") or "").strip()
    qid = str(entity.get("wikidataId") or "").strip()
    source_wiki_lang, source_wiki_title = parse_wikipedia_url(wikipedia_url)
    if not source_wiki_title:
        source_wiki_lang, source_wiki_title = "en", source_title

    source_links: Dict[str, str] = {}
    qid_links = wikidata_sitelinks(qid) if qid else {}
    if source_wiki_title:
        source_links = wiki_langlinks_map(source_wiki_lang or "en", source_wiki_title)

    resolved: Dict[str, str] = {}
    for lang in langs:
        if not force:
            existing = cached_or_manual_title(kind, lang, country_slug, city_slug, place_slug, source_title)
            if existing:
                resolved[lang] = existing
                continue
        wiki_lang = SUPPORTED_LANGS[lang]["wiki"]
        title = (
            qid_links.get(wiki_lang)
            or source_links.get(wiki_lang)
            or wiki_summary_title_if_exists(wiki_lang, source_title)
            or search_title(lang, source_title, city_name, country_name)
        )
        if title:
            resolved[lang] = title
    return {**entity, "resolved": resolved}


def build_entities() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for country in target_countries():
        country_slug = str(country.get("slug") or "").strip().lower()
        country_name = str(country.get("name") or "").strip()
        rows.append({
            "kind": "country",
            "countrySlug": country_slug,
            "sourceTitle": country_name,
            "countryName": country_name,
        })
        for city in target_country_cities(country_slug):
            city_slug = str(city.get("citySlug") or "").strip().lower()
            city_name = str(city.get("wikiTitle") or city.get("name") or "").strip()
            rows.append({
                "kind": "city",
                "countrySlug": country_slug,
                "citySlug": city_slug,
                "sourceTitle": city_name,
                "cityName": city_name,
                "countryName": country_name,
                "wikidataId": city.get("wikidataId") or "",
                "wikipediaUrl": city.get("wikipediaUrl") or "",
            })
            for place in target_places_for_city(country_slug, city_slug):
                place_slug = str(place.get("slug") or place.get("placeSlug") or "").strip().lower()
                if not place_slug:
                    continue
                rows.append({
                    "kind": "place",
                    "countrySlug": country_slug,
                    "citySlug": city_slug,
                    "placeSlug": place_slug,
                    "sourceTitle": str(place.get("name") or "").strip(),
                    "cityName": city_name,
                    "countryName": country_name,
                    "wikidataId": place.get("wikidataId") or "",
                    "wikipediaUrl": place.get("wikipediaUrl") or "",
                })
    return rows


def write_results(store: Dict[str, Any], rows: Iterable[Dict[str, Any]], langs: List[str], dry_run: bool = False) -> Dict[str, int]:
    titles = store.setdefault("titles", {})
    counts = {"written": 0, "missing": 0}
    for row in rows:
        kind = row["kind"]
        key = entity_title_translation_key(
            kind,
            country_slug=row.get("countrySlug", ""),
            city_slug=row.get("citySlug", ""),
            place_slug=row.get("placeSlug", ""),
        )
        for lang, title in (row.get("resolved") or {}).items():
            if not title:
                continue
            titles.setdefault(lang, {}).setdefault(kind, {})[key] = title
            counts["written"] += 1
            write_title_i18n_cache(
                title_i18n_cache_path(
                    kind=kind,
                    lang=lang,
                    country_slug=row.get("countrySlug", ""),
                    city_slug=row.get("citySlug", ""),
                    place_slug=row.get("placeSlug", ""),
                ),
                title,
            )
        counts["missing"] += max(0, len(langs) - len(row.get("resolved") or {}))
    store["updatedAt"] = now_iso()
    if not dry_run:
        atomic_write_json(ENTITY_TITLE_TRANSLATIONS_PATH, store)
    return counts


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--langs", default=",".join(TARGET_LANGS), help="Internal language codes, comma-separated. Use ua for Ukrainian.")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--machine-fallback", action="store_true", help="Use OpenAI to localize names that Wikipedia/Wikidata cannot resolve.")
    parser.add_argument("--fallback-batch-size", type=int, default=80)
    parser.add_argument("--fallback-workers", type=int, default=4)
    args = parser.parse_args()

    langs = [x.strip().lower() for x in args.langs.split(",") if x.strip()]
    langs = ["ua" if x == "uk" else x for x in langs]
    langs = [x for x in langs if x in TARGET_LANGS]
    entities = build_entities()
    if args.limit > 0:
        entities = entities[: args.limit]

    print(f"Backfilling entity titles: entities={len(entities)}, langs={langs}, workers={args.workers}, force={args.force}", flush=True)
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_map = {pool.submit(resolve_entity, entity, langs, args.force): entity for entity in entities}
        for idx, future in enumerate(as_completed(future_map), 1):
            row = future.result()
            results.append(row)
            if idx % 100 == 0 or idx == len(future_map):
                found = sum(len(r.get("resolved") or {}) for r in results)
                print(f"  {idx}/{len(future_map)} entities, resolved={found}", flush=True)

    if args.machine_fallback:
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        model = os.environ.get("OPENAI_TRANSLATE_MODEL") or "gpt-5-mini"
        filled = machine_translate_missing_titles(
            results,
            langs,
            api_key=api_key,
            model=model,
            batch_size=max(10, args.fallback_batch_size),
            workers=max(1, args.fallback_workers),
        )
        print(f"OpenAI fallback filled={filled}", flush=True)

    store = load_store()
    counts = write_results(store, results, langs, dry_run=args.dry_run)
    print(f"Done. written={counts['written']} missing_slots={counts['missing']} output={ENTITY_TITLE_TRANSLATIONS_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

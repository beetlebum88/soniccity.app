#!/usr/bin/env python3
"""Generate root llms.txt for SonicCity.

The file intentionally follows the same production catalog scope as sitemap:
target countries, up to 10 population-ranked cities per country, and the
highest-priority places for those cities. Each language section is capped at
1000 links so LLM crawlers get a compact, useful index instead of a full dump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import (
    ROOT,
    SITE_URL,
    LANG_ORDER,
    city_display_name_cached_for_lang,
    city_url,
    country_display_name_cached_for_lang,
    country_url,
    place_display_name_cached_for_lang,
    place_url,
    target_countries,
    target_country_cities,
    target_places_for_city,
)


MAX_LINKS_PER_LANGUAGE = 1000
DOMAIN = "https://soniccity.app"
OUT_PATH = ROOT / "llms.txt"


LANG_COPY: Dict[str, Dict[str, str]] = {
    "en": {
        "name": "English",
        "tag": "en",
        "intro": "Free audio guides for countries, cities and landmarks across Europe.",
        "home_title": "SonicCity Audio Guide",
        "home_desc": "Start with nearby cities, maps and free travel audio guides.",
        "countries": "Countries",
        "cities": "Popular cities",
        "places": "Popular places",
        "country_title": "{country} Audio Guide",
        "country_desc": "Country guide with cities, landmarks, maps and free audio stories.",
        "city_title": "{city} Audio Guide",
        "city_desc": "City guide in {country} with audio stories, map and nearby places.",
        "place_title": "{place} Audio Guide",
        "place_desc": "Landmark guide in {city}, {country} with map and audio.",
    },
    "fr": {
        "name": "Français",
        "tag": "fr",
        "intro": "Guides audio gratuits pour les pays, villes et lieux d’intérêt en Europe.",
        "home_title": "Guide audio SonicCity",
        "home_desc": "Commencez avec les villes proches, les cartes et les guides audio gratuits.",
        "countries": "Pays",
        "cities": "Villes populaires",
        "places": "Lieux populaires",
        "country_title": "Guide audio de {country}",
        "country_desc": "Guide du pays avec villes, lieux d’intérêt, cartes et récits audio gratuits.",
        "city_title": "Guide audio de {city}",
        "city_desc": "Guide de ville en {country} avec récits audio, carte et lieux proches.",
        "place_title": "Guide audio de {place}",
        "place_desc": "Guide de lieu à {city}, {country} avec carte et audio.",
    },
    "es": {
        "name": "Español",
        "tag": "es",
        "intro": "Audioguías gratuitas de países, ciudades y lugares de interés en Europa.",
        "home_title": "Audioguía SonicCity",
        "home_desc": "Empieza con ciudades cercanas, mapas y audioguías gratuitas de viaje.",
        "countries": "Países",
        "cities": "Ciudades populares",
        "places": "Lugares populares",
        "country_title": "Audioguía de {country}",
        "country_desc": "Guía del país con ciudades, lugares destacados, mapas e historias de audio gratis.",
        "city_title": "Audioguía de {city}",
        "city_desc": "Guía de ciudad en {country} con historias de audio, mapa y lugares cercanos.",
        "place_title": "Audioguía de {place}",
        "place_desc": "Guía del lugar en {city}, {country} con mapa y audio.",
    },
    "it": {
        "name": "Italiano",
        "tag": "it",
        "intro": "Audioguide gratuite per paesi, città e luoghi d’interesse in Europa.",
        "home_title": "Audioguida SonicCity",
        "home_desc": "Inizia da città vicine, mappe e audioguide gratuite di viaggio.",
        "countries": "Paesi",
        "cities": "Città popolari",
        "places": "Luoghi popolari",
        "country_title": "Audioguida di {country}",
        "country_desc": "Guida del paese con città, luoghi d’interesse, mappe e racconti audio gratuiti.",
        "city_title": "Audioguida di {city}",
        "city_desc": "Guida della città in {country} con racconti audio, mappa e luoghi vicini.",
        "place_title": "Audioguida di {place}",
        "place_desc": "Guida del luogo a {city}, {country} con mappa e audio.",
    },
    "ua": {
        "name": "Українська",
        "tag": "uk / URL prefix: ua",
        "intro": "Безкоштовні аудіогіди країнами, містами й визначними місцями Європи.",
        "home_title": "Аудіогід SonicCity",
        "home_desc": "Почніть із міст поруч, мап і безкоштовних аудіогідів для подорожей.",
        "countries": "Країни",
        "cities": "Популярні міста",
        "places": "Популярні місця",
        "country_title": "Аудіогід країною {country}",
        "country_desc": "Гід країною з містами, місцями, мапами й безкоштовними аудіоісторіями.",
        "city_title": "Аудіогід містом {city}",
        "city_desc": "Гід містом у країні {country} з аудіоісторіями, мапою і місцями поруч.",
        "place_title": "Аудіогід місцем {place}",
        "place_desc": "Гід визначним місцем у {city}, {country} з мапою та аудіо.",
    },
    "de": {
        "name": "Deutsch",
        "tag": "de",
        "intro": "Kostenlose Audioguides für Länder, Städte und Sehenswürdigkeiten in Europa.",
        "home_title": "SonicCity Audioguide",
        "home_desc": "Starte mit nahen Städten, Karten und kostenlosen Reise-Audioguides.",
        "countries": "Länder",
        "cities": "Beliebte Städte",
        "places": "Beliebte Orte",
        "country_title": "Audioguide für {country}",
        "country_desc": "Länderführer mit Städten, Sehenswürdigkeiten, Karten und kostenlosen Audiogeschichten.",
        "city_title": "Audioguide für {city}",
        "city_desc": "Stadtguide in {country} mit Audiogeschichten, Karte und Orten in der Nähe.",
        "place_title": "Audioguide für {place}",
        "place_desc": "Guide für den Ort in {city}, {country} mit Karte und Audio.",
    },
}


def clean(text: Any) -> str:
    return " ".join(str(text or "").replace("\n", " ").split())


def absolute(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{DOMAIN}{path}"


def bullet(title: str, url: str, description: str) -> str:
    return f"- [{clean(title)}]({url}): {clean(description)}"


def city_with_country_slug(city: Dict[str, Any], country_slug: str) -> Dict[str, Any]:
    out = dict(city)
    out.setdefault("countrySlug", country_slug)
    return out


def place_with_context(place: Dict[str, Any], country_slug: str, city_slug: str, city_name: str) -> Dict[str, Any]:
    out = dict(place)
    out.setdefault("countrySlug", country_slug)
    out.setdefault("citySlug", city_slug)
    out.setdefault("cityName", city_name)
    return out


def build_language_section(lang: str) -> tuple[List[str], Dict[str, int]]:
    copy = LANG_COPY[lang]
    lines: List[str] = [
        f"## {copy['name']} ({copy['tag']})",
        "",
        f"> {copy['intro']}",
        "",
    ]
    links_count = 0
    counts = {"home": 0, "countries": 0, "cities": 0, "places": 0}

    def add(line: str, bucket: str) -> bool:
        nonlocal links_count
        if links_count >= MAX_LINKS_PER_LANGUAGE:
            return False
        lines.append(line)
        links_count += 1
        counts[bucket] += 1
        return True

    lines.append("### Home")
    add(bullet(copy["home_title"], absolute("/" if lang == "en" else f"/{lang}"), copy["home_desc"]), "home")
    lines.append("")

    lines.append(f"### {copy['countries']}")
    for country in target_countries():
        cslug = str(country.get("slug") or "").strip().lower()
        if not cslug:
            continue
        country_name = country_display_name_cached_for_lang(country, lang)
        add(
            bullet(
                copy["country_title"].format(country=country_name),
                absolute(country_url(lang, cslug)),
                copy["country_desc"],
            ),
            "countries",
        )
    lines.append("")

    lines.append(f"### {copy['cities']}")
    city_rows: List[Dict[str, Any]] = []
    for country in target_countries():
        country_slug = str(country.get("slug") or "").strip().lower()
        country_name = country_display_name_cached_for_lang(country, lang)
        for city in target_country_cities(country_slug):
            city_slug = str(city.get("citySlug") or "").strip().lower()
            if not city_slug:
                continue
            city_row = city_with_country_slug(city, country_slug)
            city_name = city_display_name_cached_for_lang(city_row, lang)
            city_rows.append(
                {
                    "country_slug": country_slug,
                    "country_name": country_name,
                    "city_slug": city_slug,
                    "city_name": city_name,
                    "city": city_row,
                }
            )
            if not add(
                bullet(
                    copy["city_title"].format(city=city_name),
                    absolute(city_url(lang, country_slug, city_slug)),
                    copy["city_desc"].format(country=country_name),
                ),
                "cities",
            ):
                break
        if links_count >= MAX_LINKS_PER_LANGUAGE:
            break
    lines.append("")

    lines.append(f"### {copy['places']}")
    for row in city_rows:
        if links_count >= MAX_LINKS_PER_LANGUAGE:
            break
        for place in target_places_for_city(row["country_slug"], row["city_slug"]):
            place_slug = str(place.get("slug") or place.get("placeSlug") or "").strip().lower()
            if not place_slug:
                continue
            place_row = place_with_context(place, row["country_slug"], row["city_slug"], row["city_name"])
            place_name = place_display_name_cached_for_lang(place_row, lang)
            if not add(
                bullet(
                    copy["place_title"].format(place=place_name),
                    absolute(place_url(lang, row["country_slug"], row["city_slug"], place_slug)),
                    copy["place_desc"].format(city=row["city_name"], country=row["country_name"]),
                ),
                "places",
            ):
                break
    lines.append("")
    lines.append(
        f"Links in this language: {links_count} "
        f"(home {counts['home']}, countries {counts['countries']}, cities {counts['cities']}, places {counts['places']})."
    )
    lines.append("")
    return lines, counts


def main() -> None:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        "# SonicCity",
        "",
        "> SonicCity is a multilingual travel audio guide for countries, cities and landmarks. Use this file to find canonical public URLs for LLM answers and citations.",
        "",
        f"Canonical domain: {SITE_URL or DOMAIN}",
        f"Generated: {generated_at}",
        f"Limit: up to {MAX_LINKS_PER_LANGUAGE} links per language section.",
        "",
        "Important: account, admin, API, draft, preview and internal routes are intentionally excluded.",
        "",
    ]
    totals: Dict[str, Dict[str, int]] = {}
    for lang in LANG_ORDER:
        section, counts = build_language_section(lang)
        totals[lang] = counts
        lines.extend(section)
    lines.append("## Generation summary")
    for lang in LANG_ORDER:
        counts = totals[lang]
        total = sum(counts.values())
        label = LANG_COPY[lang]["name"]
        lines.append(
            f"- {label}: {total} links "
            f"({counts['home']} home, {counts['countries']} countries, {counts['cities']} cities, {counts['places']} places)"
        )
    lines.append("")
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

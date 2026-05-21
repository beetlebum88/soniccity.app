import json
import hashlib
import html
import ipaddress
import math
import os
import re
import secrets
import shutil
import smtplib
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    send_file,
    request,
    g,
    abort,
    make_response,
    redirect,
    send_from_directory,
    session,
    url_for,
    has_request_context,
)
from werkzeug.routing import BaseConverter
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

try:
    import markdown as markdown_lib
except Exception:  # pragma: no cover - optional dependency fallback
    markdown_lib = None

try:
    import bleach
except Exception:  # pragma: no cover - optional dependency fallback
    bleach = None

from services.city_detection import MIN_CITY_POPULATION, detect_nearby_cities


ROOT = Path(__file__).resolve().parent


def load_local_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


load_local_env_file(ROOT / ".env")

CITIES_PATH = ROOT / "cities.json"
COUNTRIES_PATH = ROOT / "country_flags.json"
TOP_PLACES_PATH = ROOT / "data" / "all_countries_top30_with_descriptions.json"
PLACES_INDEX_PATH = ROOT / "data" / "data_index_with_places.json"
LOG_DIR = ROOT / "logs"
ACCESS_LOG_PATH = LOG_DIR / "access.jsonl"
ADMIN_DATA_DIR = ROOT / "data" / "admin"
ADMIN_PAGES_PATH = ADMIN_DATA_DIR / "pages.json"
ADMIN_SETTINGS_PATH = ADMIN_DATA_DIR / "settings.json"
ADMIN_REDIRECTS_PATH = ADMIN_DATA_DIR / "redirects.json"
ADMIN_REVISIONS_PATH = ADMIN_DATA_DIR / "revisions.jsonl"
ADMIN_ROBOTS_PATH = ADMIN_DATA_DIR / "robots.txt"
ADMIN_AUDIO_UPLOADS_PATH = ADMIN_DATA_DIR / "audio_uploads.json"
ADMIN_MEDIA_INDEX_PATH = ADMIN_DATA_DIR / "media.json"
ADMIN_CMS_STORE_PATH = ADMIN_DATA_DIR / "cms.json"
ADMIN_TRANSLATIONS_PATH = ADMIN_DATA_DIR / "translations.json"
MAIL_NOTIFICATION_LOG_PATH = LOG_DIR / "mail_notifications.jsonl"
BLOG_DATA_DIR = ROOT / "data" / "blog"
BLOG_POSTS_PATH = BLOG_DATA_DIR / "posts.json"
BLOG_UPLOAD_DIR = ROOT / "static" / "uploads" / "blog"
MEDIA_UPLOAD_DIR = ROOT / "static" / "uploads" / "media"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 64) -> int:
    raw = os.getenv(name)
    try:
        value = int(str(raw if raw is not None else default).strip())
    except (TypeError, ValueError):
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


APP_ENV = str(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}

app = Flask(__name__, static_folder="static", template_folder="templates")
_secret_key = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
if IS_PRODUCTION and not _secret_key:
    raise RuntimeError("SECRET_KEY or FLASK_SECRET_KEY must be configured in production.")
app.secret_key = _secret_key or f"dev-{secrets.token_hex(32)}"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_BYTES") or str(60 * 1024 * 1024)),
)

DEFAULT_ADMIN_EMAIL = "kozachenko.vitaliy@gmail.com"
ADMIN_EMAIL = str(os.getenv("ADMIN_EMAIL") or os.getenv("ADMIN_USER") or DEFAULT_ADMIN_EMAIL).strip().lower()
ADMIN_PASSWORD_HASH = str(os.getenv("ADMIN_PASSWORD_HASH") or "").strip()
ADMIN_INITIAL_PASSWORD = str(os.getenv("ADMIN_INITIAL_PASSWORD") or os.getenv("ADMIN_PASSWORD") or "").strip()
if IS_PRODUCTION and ADMIN_INITIAL_PASSWORD and not ADMIN_PASSWORD_HASH:
    raise RuntimeError("ADMIN_PASSWORD_HASH is required in production; do not use ADMIN_INITIAL_PASSWORD there.")
SITE_DOMAIN = str(os.getenv("SITE_DOMAIN") or "soniccity.app").strip().lower()
SITE_URL = str(os.getenv("SITE_URL") or f"https://{SITE_DOMAIN}").strip().rstrip("/")
CONTACT_EMAIL = str(os.getenv("CONTACT_EMAIL") or "info@soniccity.app").strip().lower()
SMTP_HOST = str(os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(str(os.getenv("SMTP_PORT") or "587").strip() or "587")
SMTP_USERNAME = str(os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER") or "").strip()
SMTP_PASSWORD = str(os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM = str(os.getenv("EMAIL_FROM") or os.getenv("SMTP_FROM") or CONTACT_EMAIL).strip()
SMTP_USE_TLS = str(os.getenv("SMTP_USE_TLS") or "1").strip().lower() not in {"0", "false", "no", "off"}
APP_URL = str(os.getenv("APP_URL") or SITE_URL).strip().rstrip("/")
REQUIRE_SMTP_FOR_EMAIL = env_bool("REQUIRE_SMTP_FOR_EMAIL", IS_PRODUCTION)
ADMIN_BASIC_AUTH_ENABLED = env_bool("ADMIN_BASIC_AUTH_ENABLED", False)
CSRF_PROTECTION_ENABLED = env_bool("CSRF_PROTECTION_ENABLED", True)
MAX_AUDIO_UPLOAD_BYTES = int(os.getenv("MAX_AUDIO_UPLOAD_BYTES") or str(50 * 1024 * 1024))
MAX_MEDIA_UPLOAD_BYTES = int(os.getenv("MAX_MEDIA_UPLOAD_BYTES") or str(10 * 1024 * 1024))
ALLOWED_AUDIO_UPLOAD_EXTENSIONS = {".mp3", ".wav", ".m4a"}
ALLOWED_IMAGE_UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_MEDIA_UPLOAD_EXTENSIONS = ALLOWED_IMAGE_UPLOAD_EXTENSIONS | ALLOWED_AUDIO_UPLOAD_EXTENSIONS
ACCESS_LOG_ENABLED = str(os.getenv("ACCESS_LOG_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
ACCESS_LOG_GEO_LOOKUP = str(os.getenv("ACCESS_LOG_GEO_LOOKUP") or "").strip().lower() in {"1", "true", "yes", "on"}
ACCESS_LOG_LOCK = threading.Lock()
AUTH_RATE_LIMIT_LOCK = threading.Lock()
AUTH_RATE_LIMITS: Dict[str, List[int]] = defaultdict(list)
GLOBAL_NOINDEX = str(os.getenv("GLOBAL_NOINDEX") or "1").strip().lower() not in {"0", "false", "no", "off"}
GLOBAL_ROBOTS_META = "noindex,nofollow"
GLOBAL_X_ROBOTS_TAG = "noindex, nofollow"

CITIES: List[Dict[str, Any]] = []
COUNTRIES: List[Dict[str, Any]] = []
SEARCH_RESPONSE_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
SEARCH_RESPONSE_CACHE_LOCK = threading.Lock()
SEARCH_RESPONSE_CACHE_TTL_SECONDS = 300

# Product requirement: do not show these countries anywhere.
EXCLUDED_COUNTRY_CODES = {"ru", "by"}

COUNTRY_BY_CODE: Dict[str, Dict[str, Any]] = {}
COUNTRY_BY_NAME_LC: Dict[str, Dict[str, Any]] = {}
COUNTRY_BY_SLUG: Dict[str, Dict[str, Any]] = {}

CITY_BY_COUNTRYSLUG_CITYSLUG: Dict[Tuple[str, str], Dict[str, Any]] = {}
CITIES_BY_COUNTRYSLUG: Dict[str, List[Dict[str, Any]]] = {}

# “Top places” dataset (30 per country)
TOP_PLACES_BY_COUNTRYSLUG: Dict[str, List[Dict[str, Any]]] = {}
TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG: Dict[Tuple[str, str], Dict[str, Any]] = {}

# City → places (e.g., “Paris → Eiffel Tower”) for /<lang>/<country>/<city>/<place>
CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
# Cities that have “places to see” in data_index_with_places.json
INDEXED_CITIES_BY_COUNTRYSLUG: Dict[str, List[Dict[str, Any]]] = {}

TARGET_CITIES_PER_COUNTRY = 10
TARGET_PLACES_PER_CITY = 10
TARGET_COUNTRIES_LIMIT = 50
COUNTRY_TOP_PLACES_PER_CITY = 1

# Async audio build queue (for missing pre-generated manifests).
AUDIO_BUILD_AUDIO_VERSION = "v7"
AUDIO_STORAGE_PATH = Path(os.getenv("AUDIO_STORAGE_PATH") or str(ROOT / "static" / "audio")).expanduser()
AUDIO_BUILD_SOURCE_MODE = str(os.getenv("AUDIO_BUILD_SOURCE_MODE") or "en-master").strip().lower()
if AUDIO_BUILD_SOURCE_MODE not in {"en-master", "linked-local"}:
    AUDIO_BUILD_SOURCE_MODE = "en-master"
AUDIO_BUILD_USE_REWRITE = env_bool("AUDIO_BUILD_USE_REWRITE", AUDIO_BUILD_SOURCE_MODE == "en-master")
AUDIO_BUILD_WEB_WORKERS = env_int("AUDIO_BUILD_WEB_WORKERS", 8, min_value=1, max_value=32)
AUDIO_BUILD_EDGE_CONCURRENCY = env_int("AUDIO_BUILD_EDGE_CONCURRENCY", 6, min_value=1, max_value=16)
AUDIO_BUILD_CHUNK_CHARS = env_int("AUDIO_BUILD_CHUNK_CHARS", 1800, min_value=600, max_value=4000)
AUDIO_BUILD_EDGE_RATE = str(os.getenv("AUDIO_BUILD_EDGE_RATE") or "-6%").strip()
AUDIO_BUILD_EDGE_PITCH = str(os.getenv("AUDIO_BUILD_EDGE_PITCH") or "+1Hz").strip()
AUDIO_BUILD_EDGE_VOLUME = str(os.getenv("AUDIO_BUILD_EDGE_VOLUME") or "+0%").strip()
AUDIO_BUILD_STATUS: Dict[str, Dict[str, Any]] = {}
AUDIO_BUILD_LOCK = threading.Lock()
AUDIO_BUILD_SEMAPHORE = threading.Semaphore(AUDIO_BUILD_WEB_WORKERS)
TITLE_I18N_CACHE_DIR = ROOT / "cache" / "title_i18n"
TITLE_I18N_MEM: Dict[str, str] = {}
TITLE_I18N_LOCK = threading.Lock()

CONTINENTS_ORDER = ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]

BRAND_NAME = "SonicCity"


class AudioStorageProvider:
    """Storage boundary for generated audio; swap this for object storage later."""

    def manifest_path(
        self,
        *,
        version: str,
        lang: str,
        gender: str,
        country_slug: str,
        city_slug: str,
        place_slug: Optional[str] = None,
    ) -> Path:
        raise NotImplementedError


class LocalAudioStorageProvider(AudioStorageProvider):
    def __init__(self, root: Path):
        self.root = Path(root).expanduser()

    def manifest_path(
        self,
        *,
        version: str,
        lang: str,
        gender: str,
        country_slug: str,
        city_slug: str,
        place_slug: Optional[str] = None,
    ) -> Path:
        base = self.root / version / lang / gender / country_slug / city_slug
        if place_slug:
            base = base / place_slug
        return base / "manifest.json"


AUDIO_STORAGE_PROVIDER = LocalAudioStorageProvider(AUDIO_STORAGE_PATH)

SUPPORTED_LANGS: Dict[str, Dict[str, str]] = {
    "en": {"label": "English", "wiki": "en", "speech": "en-US"},
    "fr": {"label": "Français", "wiki": "fr", "speech": "fr-FR"},
    "es": {"label": "Español", "wiki": "es", "speech": "es-ES"},
    "it": {"label": "Italiano", "wiki": "it", "speech": "it-IT"},
    "ua": {"label": "Українська", "wiki": "uk", "speech": "uk-UA"},
    "de": {"label": "Deutsch", "wiki": "de", "speech": "de-DE"},
}
LANG_ORDER = ["en", "fr", "es", "it", "ua", "de"]
DEFAULT_LANG = "en"
PUBLIC_LANG_BY_INTERNAL = {"ua": "uk"}
INTERNAL_LANG_BY_PUBLIC = {"uk": "ua", "ua": "ua"}
TRANSLATION_LANG_ORDER = ["en", "fr", "es", "it", "uk", "de"]

HREFLANG_CODE_BY_LANG: Dict[str, str] = {
    "en": "en",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "ua": "uk",
    "de": "de",
}

OG_LOCALE_BY_LANG: Dict[str, str] = {
    "en": "en_US",
    "fr": "fr_FR",
    "es": "es_ES",
    "it": "it_IT",
    "ua": "uk_UA",
    "de": "de_DE",
}

GEO_IP_CACHE: Dict[str, Tuple[float, str]] = {}
GEO_IP_CACHE_TTL_S = 60 * 60 * 24
BOT_UA_HINTS = (
    "bot",
    "crawler",
    "spider",
    "slurp",
    "facebookexternalhit",
    "bingpreview",
    "duckduckbot",
    "yandex",
    "baiduspider",
    "semrush",
    "ahrefs",
)

I18N: Dict[str, Dict[str, str]] = {
    "en": {
        "nav_home": "Home",
        "nav_map": "Live map",
        "nav_europe": "Europe",
        "nav_search_ph": "Search a city or country…",
        "nav_language": "Language",
        "label_language": "Language",
        "voice_label": "Voice",
        "voice_female": "Female",
        "voice_male": "Male",
        "cta_open_map": "Open map",
        "cta_start_gps": "Enable GPS",
        "cta_stop": "Stop",
        "cta_auto": "Auto",
        "status_ready": "Ready. Tap “Enable GPS”.",
        "status_locating": "Requesting location…",
        "status_denied": "Location permission denied.",
        "status_error": "Location error.",
        "you_are_here": "You are here",
        "geo_not_supported": "Geolocation is not supported.",
        "gps_started": "GPS is on. Cities update while you move.",
        "gps_stopped": "GPS is off.",
        "nearby_title": "Nearby cities (10 km)",
        "nearby_none": "No supported cities over 10,000 people found within 10 km.",
        "nearby_found": "Found {n} cities within 10 km.",
        "nearby_error": "Nearby lookup error.",
        "listen_all": "Play all",
        "pause": "Pause",
        "resume": "Resume",
        "stop": "Stop",
        "city_outline": "Audio stories",
        "choose_city_first": "Pick a city or section first.",
        "wiki_loading": "Loading guide content…",
        "wiki_loaded": "Guide ready. Tap a section to play.",
        "wiki_failed": "Failed to load guide content.",
        "audio_loading": "Loading audio…",
        "audio_playing": "Playing audio…",
        "audio_paused": "Playback paused.",
        "audio_stopped": "Playback stopped.",
        "audio_chunk_error": "Audio fragment failed. Continuing…",
        "audio_engine_natural": "High-quality voice",
        "audio_engine_system": "High-quality voice",
        "audio_engine_google": "Standard voice",
        "words_unit": "words",
        "speech_not_supported": "Web Speech API is not available. Try Chrome/Edge.",
        "no_wiki_lang": "No article in this language. Checking other languages…",
        "landing_hero_title": "Personal SonicCity for every city you pass",
        "landing_hero_sub": "Turn on GPS — we detect nearby cities and read facts as audio, structured by sections. Built for driving.",
        "landing_btn_try": "Try it now",
        "landing_btn_how": "How it works",
        "landing_section_1_title": "Built for the road",
        "landing_section_1_sub": "Map-first experience: less reading, more listening.",
        "landing_step_1": "GPS → real-time position",
        "landing_step_2": "10 km → nearest cities on the map",
        "landing_step_3": "City → pick or enable “Auto”",
        "landing_step_4": "Audio → story by story",
        "landing_top_places_kicker": "Highlights",
        "landing_top_places_title": "Top places to explore",
        "landing_top_places_sub": "A quick gallery of stops worth opening — tap any card to see it on the map and play the audio guide.",
        "landing_stats_1": "cities in the database",
        "landing_stats_2": "nearby radius",
        "landing_stats_3": "audio languages",
        "landing_stats_4": "full text shown",
        "landing_cards_title": "Why you’ll love it",
        "landing_card_1": "Listen to history",
        "landing_card_1_sub": "Fast, simple, hands-free.",
        "landing_card_2": "Learn key facts",
        "landing_card_2_sub": "Facts structured into sections.",
        "landing_card_3": "Plan quick stops",
        "landing_card_3_sub": "Know what’s worth a detour.",
        "landing_card_4": "Auto mode",
        "landing_card_4_sub": "Switches to the nearest city while driving.",
        "landing_ph_caption": "Screenshots / video placeholder",
        "landing_card_europe_title": "Europe countries",
        "landing_card_europe_sub": "Browse every European country page with flags.",
        "landing_card_clean_title": "Clean for driving",
        "landing_card_clean_sub": "No long text on screen — just structure and audio.",
        "landing_trusted_title": "Trusted by travelers (placeholder)",
        "landing_features_title": "Why choose SonicCity",
        "landing_features_sub": "Designed for quick listening while you move — minimal UI, maximum clarity.",
        "landing_feat_1_title": "Real-time updates",
        "landing_feat_1_sub": "Nearby cities refresh while you drive.",
        "landing_feat_2_title": "Map-first",
        "landing_feat_2_sub": "Cities are always on the map, not hidden in menus.",
        "landing_feat_3_title": "Section playback",
        "landing_feat_3_sub": "Listen by story sections or play the full guide.",
        "landing_feat_4_title": "Auto mode",
        "landing_feat_4_sub": "Switches to the nearest city hands-free.",
        "landing_feat_5_title": "Multi-language audio",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — only when the page exists.",
        "landing_feat_6_title": "No text clutter",
        "landing_feat_6_sub": "We don’t show long paragraphs on screen.",
        "landing_picks_title": "Start with these cities",
        "landing_picks_sub": "Examples (placeholders). Pick any city on the map for the full outline and audio.",
        "landing_app_title": "Take it with you",
        "landing_app_sub": "Works great on mobile: mount your phone, enable GPS, and listen.",
        "landing_app_note": "App store badges are placeholders — this is a web demo.",
        "landing_app_ph_caption": "App screens placeholder",
        "landing_faq_title": "FAQ",
        "landing_faq_sub": "Quick answers before you hit the road.",
        "landing_faq_q1": "Where does the audio come from?",
        "landing_faq_a1": "We load the page, split it into short story sections, clean the text, then read it aloud.",
        "landing_faq_q2": "Will it switch cities automatically?",
        "landing_faq_a2": "Yes — enable “Auto” to follow the nearest city in real time while you move.",
        "landing_faq_q3": "Do you show the full text?",
        "landing_faq_a3": "No. We keep the screen minimal: headings + audio controls.",
        "landing_final_title": "Ready for the next city?",
        "landing_final_sub": "Enable GPS and let SonicCity narrate the places you pass.",
        "landing_final_btn": "Open live map",
        "landing_footer": "Maps: OpenStreetMap.",
        "country_largest_cities": "Largest cities",
        "country_lead": "Country map and largest cities — ready for audio.",
        "city_lead": "City map and audio stories by section.",
        "type_city": "City",
        "type_country": "Country",
        "type_place": "Place",
        "open_guide": "Open guide",
        "country_top_places": "Top places",
        "city_places_title": "Places to visit",
        "badge_map": "Map-first",
        "badge_audio": "Audio guide",
        "badge_places": "Places",
        "prefooter_title": "Find SonicCity guides in these countries",
        "prefooter_sub": "Choose a country to explore cities and places on the map.",
        "footer_tagline": "Map-first audio guides for the road.",
        "footer_links": "Links",
        "footer_languages": "Languages",
        "footer_countries": "Countries",
        "seo_landing_title": "SonicCity: Real-time audio guides for nearby cities",
        "seo_landing_desc": "Map-first audio guide with live GPS, nearby city detection, and multilingual section playback for road trips.",
        "landing_hero_kicker": "AI-powered road companion",
        "landing_hero_lang_hint": "Detected your preferred language: {lang}",
        "landing_hero_lang_cta": "Open {lang} version",
        "super_title": "Super features for drivers",
        "super_sub": "Everything needed to hear cities, places, and facts without screen overload.",
        "super_feat_1_title": "Smart language routing",
        "super_feat_1_sub": "Understands browser language and region to open the best locale.",
        "super_feat_2_title": "SEO-ready landing pages",
        "super_feat_2_sub": "Canonical, hreflang, metadata, and share cards on each page.",
        "super_feat_3_title": "Live map engine",
        "super_feat_3_sub": "Real-time nearby city updates while you move.",
        "super_feat_4_title": "Hover previews on map",
        "super_feat_4_sub": "See mini photos of places directly on map markers.",
        "super_feat_5_title": "Voice controls",
        "super_feat_5_sub": "Switch female/male voice and adjust playback speed.",
        "super_feat_6_title": "Sticky road player",
        "super_feat_6_sub": "Persistent bottom player with timeline and progress.",
        "stat_cities": "cities",
        "stat_places": "places",
        "stat_languages": "languages",
        "stat_population": "population",
        "stat_coordinates": "coordinates",
        "stat_city": "city",
        "stat_country": "country",
        "seo_country_title_tpl": "{country}: Audio Guide, Places to Visit & Travel Map | SonicCity",
        "seo_country_desc_tpl": "Explore {country} with a map-first audio guide: {cities} cities, {places} places to visit, and multilingual narration for road trips.",
        "seo_country_keywords_tpl": "{country} audio guide, {country} travel guide, {country} places to visit, {country} map, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country}: Audio Guide, Attractions & History | SonicCity",
        "seo_city_desc_tpl": "Listen to {city} in {country} with an interactive map, key attractions, and section-based audio narration in {langs} languages.",
        "seo_city_keywords_tpl": "{city} audio guide, {city} attractions, {city} map guide, things to do in {city}, {city} history audio",
        "seo_place_title_tpl": "{place} ({city}, {country}) Audio Guide | SonicCity",
        "seo_place_desc_tpl": "Discover {place} with a map + audio guide in {city}, {country}. Real-time route context and expressive voice playback for travelers.",
        "seo_place_keywords_tpl": "{place} audio guide, {place} map, {city} travel audio, {country} attractions, self guided tour {place}",
    },
    "ua": {
        "nav_home": "Головна",
        "nav_map": "Мапа",
        "nav_europe": "Європа",
        "nav_search_ph": "Пошук міста або країни…",
        "nav_language": "Мова",
        "label_language": "Мова",
        "voice_label": "Голос",
        "voice_female": "Жіночий",
        "voice_male": "Чоловічий",
        "cta_open_map": "Відкрити мапу",
        "cta_start_gps": "GPS",
        "cta_stop": "Стоп",
        "cta_auto": "Авто",
        "status_ready": "Готово. Натисніть “GPS”.",
        "status_locating": "Шукаю геолокацію…",
        "status_denied": "Доступ до геолокації заборонено.",
        "status_error": "Помилка геолокації.",
        "you_are_here": "Ви тут",
        "geo_not_supported": "Геолокація не підтримується.",
        "gps_started": "GPS увімкнено. Оновлюємо міста під час руху.",
        "gps_stopped": "GPS вимкнено.",
        "nearby_title": "Найближчі міста (10 км)",
        "nearby_none": "Немає підтримуваних міст з населенням понад 10 000 у радіусі 10 км.",
        "nearby_found": "Знайдено {n} міст у радіусі 10 км.",
        "nearby_error": "Помилка пошуку міст.",
        "listen_all": "Слухати все",
        "pause": "Пауза",
        "resume": "Продовжити",
        "stop": "Зупинити",
        "city_outline": "Аудіоісторії",
        "choose_city_first": "Спочатку оберіть місто або розділ.",
        "wiki_loading": "Завантажую контент гіда…",
        "wiki_loaded": "Гід готовий. Натисніть розділ, щоб слухати.",
        "wiki_failed": "Не вдалося завантажити контент гіда.",
        "audio_loading": "Завантаження аудіо…",
        "audio_playing": "Відтворення аудіо…",
        "audio_paused": "Відтворення на паузі.",
        "audio_stopped": "Відтворення зупинено.",
        "audio_chunk_error": "Фрагмент аудіо не завантажився. Продовжуємо…",
        "audio_engine_natural": "Якісний голос",
        "audio_engine_system": "Якісний голос",
        "audio_engine_google": "Стандартний голос",
        "words_unit": "слів",
        "speech_not_supported": "Web Speech API недоступний. Спробуйте Chrome/Edge.",
        "no_wiki_lang": "Немає статті у вибраній мові. Перевіряю інші мови…",
        "landing_hero_title": "Персональний аудіо‑гід для кожного міста на маршруті",
        "landing_hero_sub": "Вмикаєте GPS — ми підбираємо найближчі міста і читаємо факти як аудіо, розбиті на розділи. Ідеально під час поїздки.",
        "landing_btn_try": "Спробувати зараз",
        "landing_btn_how": "Як це працює",
        "landing_section_1_title": "Для водіїв, мандрівників і тих, хто в дорозі",
        "landing_section_1_sub": "Ніякого зайвого тексту на екрані — тільки мапа, розділи й озвучка.",
        "landing_step_1": "GPS → визначаємо позицію в реальному часі",
        "landing_step_2": "10 км → показуємо найближчі міста на мапі",
        "landing_step_3": "Місто → обираєте або вмикаєте “Авто”",
        "landing_step_4": "Аудіо → слухаєте історію за історією",
        "landing_top_places_kicker": "Натхнення",
        "landing_top_places_title": "Топ місця для зупинки",
        "landing_top_places_sub": "Невелика галерея точок, які варто відкрити — натисніть на картку, щоб побачити на мапі та увімкнути аудіогід.",
        "landing_stats_1": "міст у базі",
        "landing_stats_2": "радіус поруч",
        "landing_stats_3": "мов аудіо",
        "landing_stats_4": "текст на екрані",
        "landing_cards_title": "Навіщо це потрібно",
        "landing_card_1": "Слухайте історію",
        "landing_card_1_sub": "Мінімум кліків. Максимум сенсу.",
        "landing_card_2": "Дізнавайтесь факти",
        "landing_card_2_sub": "Факти, розбиті на розділи.",
        "landing_card_3": "Плануйте зупинки",
        "landing_card_3_sub": "Розуміння місця ще до зупинки.",
        "landing_card_4": "Режим “Авто”",
        "landing_card_4_sub": "Під час руху підхоплюємо найближче місто.",
        "landing_ph_caption": "Плейсхолдер для відео / скриншотів",
        "landing_card_europe_title": "Країни Європи",
        "landing_card_europe_sub": "Сторінки всіх європейських країн з прапорами.",
        "landing_card_clean_title": "Чисто для дороги",
        "landing_card_clean_sub": "Без довгих текстів на екрані — лише структура й аудіо.",
        "landing_trusted_title": "Нам довіряють (плейсхолдер)",
        "landing_features_title": "Чому SonicCity",
        "landing_features_sub": "Створено для короткого прослуховування в русі — мінімум інтерфейсу, максимум ясності.",
        "landing_feat_1_title": "Оновлення в реальному часі",
        "landing_feat_1_sub": "Міста поруч оновлюються під час руху.",
        "landing_feat_2_title": "Мапа — головна",
        "landing_feat_2_sub": "Міста завжди на мапі, а не заховані в меню.",
        "landing_feat_3_title": "Озвучка по розділах",
        "landing_feat_3_sub": "Слухайте окремі історії або весь гід.",
        "landing_feat_4_title": "Режим “Авто”",
        "landing_feat_4_sub": "Перемикає на найближче місто без рук.",
        "landing_feat_5_title": "Кілька мов аудіо",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — лише якщо є сторінка.",
        "landing_feat_6_title": "Без текстового шуму",
        "landing_feat_6_sub": "Довгі абзаци на екрані не показуємо.",
        "landing_picks_title": "Почніть з цих міст",
        "landing_picks_sub": "Приклади (плейсхолдери). Оберіть будь‑яке місто на мапі — і отримайте план та аудіо.",
        "landing_app_title": "В дорогу — з собою",
        "landing_app_sub": "Найкраще працює на смартфоні: закріпіть телефон, увімкніть GPS і слухайте.",
        "landing_app_note": "Бейджі магазинів — плейсхолдери. Це веб‑демо.",
        "landing_app_ph_caption": "Плейсхолдер екранів застосунку",
        "landing_faq_title": "Питання та відповіді",
        "landing_faq_sub": "Коротко — перед тим, як рушати.",
        "landing_faq_q1": "Звідки береться аудіо?",
        "landing_faq_a1": "Ми завантажуємо сторінку, ділимо її на короткі історії, чистимо текст і озвучуємо.",
        "landing_faq_q2": "Чи буде автоматично перемикати міста?",
        "landing_faq_a2": "Так — увімкніть “Авто”, і ми будемо підхоплювати найближче місто в реальному часі.",
        "landing_faq_q3": "Ви показуєте повний текст?",
        "landing_faq_a3": "Ні. Екран мінімальний: заголовки + керування аудіо.",
        "landing_final_title": "Готові до наступного міста?",
        "landing_final_sub": "Увімкніть GPS — і SonicCity озвучить місця, повз які ви їдете.",
        "landing_final_btn": "Відкрити мапу",
        "landing_footer": "Карти: OpenStreetMap.",
        "country_largest_cities": "Найбільші міста",
        "country_lead": "Мапа країни та найбільші міста — зручно слухати в дорозі.",
        "city_lead": "Мапа міста та аудіоісторії по розділах.",
        "type_city": "Місто",
        "type_country": "Країна",
        "type_place": "Місце",
        "open_guide": "Відкрити гід",
        "country_top_places": "Топ місця",
        "city_places_title": "Місця в місті",
        "badge_map": "Карта",
        "badge_audio": "Аудіогід",
        "badge_places": "Місця",
        "prefooter_title": "Знайдіть SonicCity guides у цих країнах",
        "prefooter_sub": "Оберіть країну, щоб відкрити міста та місця на мапі.",
        "footer_tagline": "Аудіогіди з акцентом на мапу — ідеально в дорозі.",
        "footer_links": "Посилання",
        "footer_languages": "Мови",
        "footer_countries": "Країни",
        "seo_landing_title": "SonicCity: аудіогіди в реальному часі для міст поруч",
        "seo_landing_desc": "Map-first аудіогід з живим GPS, пошуком найближчих міст і багатомовним відтворенням по розділах для поїздок авто.",
        "landing_hero_kicker": "AI-помічник у дорозі",
        "landing_hero_lang_hint": "Визначили вашу мову: {lang}",
        "landing_hero_lang_cta": "Відкрити версію {lang}",
        "super_title": "Суперфункції для водіїв",
        "super_sub": "Усе потрібне, щоб слухати міста, місця та факти без перевантаження екрану.",
        "super_feat_1_title": "Розумний вибір мови",
        "super_feat_1_sub": "Враховує мову браузера та регіон і відкриває найкращу локаль.",
        "super_feat_2_title": "SEO-готові посадкові",
        "super_feat_2_sub": "Canonical, hreflang, метадані та картки поширення на кожній сторінці.",
        "super_feat_3_title": "Жива мапа",
        "super_feat_3_sub": "Оновлення найближчих міст у реальному часі під час руху.",
        "super_feat_4_title": "Прев’ю на мапі",
        "super_feat_4_sub": "Мініфото місць прямо на маркерах мапи.",
        "super_feat_5_title": "Керування голосом",
        "super_feat_5_sub": "Перемикання жіночого/чоловічого голосу та швидкості відтворення.",
        "super_feat_6_title": "Нижній плеєр для дороги",
        "super_feat_6_sub": "Закріплений плеєр з таймлайном і прогресом.",
        "stat_cities": "міст",
        "stat_places": "місць",
        "stat_languages": "мов",
        "stat_population": "населення",
        "stat_coordinates": "координати",
        "stat_city": "місто",
        "stat_country": "країна",
        "seo_country_title_tpl": "{country}: аудіогід, місця для відвідування та мапа подорожі | SonicCity",
        "seo_country_desc_tpl": "Досліджуйте {country} через map-first аудіогід: {cities} міст, {places} місць для відвідування та багатомовна озвучка для поїздок.",
        "seo_country_keywords_tpl": "{country} аудіогід, путівник {country}, місця в {country}, мапа {country}, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country}: аудіогід, пам’ятки та історія | SonicCity",
        "seo_city_desc_tpl": "Слухайте {city} у {country}: інтерактивна мапа, ключові пам’ятки та озвучка по розділах {langs} мовами.",
        "seo_city_keywords_tpl": "{city} аудіогід, пам'ятки {city}, мапа {city}, що подивитись у {city}, історія {city} аудіо",
        "seo_place_title_tpl": "{place} ({city}, {country}) аудіогід | SonicCity",
        "seo_place_desc_tpl": "Відкрийте {place} через мапу + аудіогід у {city}, {country}. Реальний контекст маршруту й виразне голосове відтворення.",
        "seo_place_keywords_tpl": "{place} аудіогід, {place} мапа, аудіо подорож {city}, пам'ятки {country}, self guided tour {place}",
    },
    "fr": {
        "nav_home": "Accueil",
        "nav_map": "Carte",
        "nav_europe": "Europe",
        "nav_search_ph": "Rechercher une ville ou un pays…",
        "nav_language": "Langue",
        "label_language": "Langue",
        "voice_label": "Voix",
        "voice_female": "Féminine",
        "voice_male": "Masculine",
        "cta_open_map": "Ouvrir la carte",
        "cta_start_gps": "GPS",
        "cta_stop": "Stop",
        "cta_auto": "Auto",
        "status_ready": "Prêt. Appuyez sur “GPS”.",
        "status_locating": "Localisation…",
        "status_denied": "Accès à la localisation refusé.",
        "status_error": "Erreur de localisation.",
        "you_are_here": "Vous êtes ici",
        "geo_not_supported": "La géolocalisation n’est pas prise en charge.",
        "gps_started": "GPS activé. Mise à jour pendant le déplacement.",
        "gps_stopped": "GPS arrêté.",
        "nearby_title": "Villes proches (10 km)",
        "nearby_none": "Aucune ville prise en charge de plus de 10 000 habitants dans un rayon de 10 km.",
        "nearby_found": "{n} villes trouvées dans un rayon de 10 km.",
        "nearby_error": "Erreur de recherche des villes.",
        "listen_all": "Tout écouter",
        "pause": "Pause",
        "resume": "Reprendre",
        "stop": "Arrêter",
        "city_outline": "Récits audio",
        "choose_city_first": "Choisissez d’abord une ville ou une section.",
        "wiki_loading": "Chargement du guide…",
        "wiki_loaded": "Guide prêt. Touchez une section pour écouter.",
        "wiki_failed": "Impossible de charger le guide.",
        "audio_loading": "Chargement audio…",
        "audio_playing": "Lecture audio…",
        "audio_paused": "Lecture en pause.",
        "audio_stopped": "Lecture arrêtée.",
        "audio_chunk_error": "Un fragment audio a échoué. On continue…",
        "audio_engine_natural": "Voix de haute qualité",
        "audio_engine_system": "Voix de haute qualité",
        "audio_engine_google": "Voix standard",
        "words_unit": "mots",
        "speech_not_supported": "Web Speech API indisponible. Essayez Chrome/Edge.",
        "no_wiki_lang": "Pas d’article dans cette langue. Vérification d’autres langues…",
        "landing_hero_title": "Un guide audio personnel pour chaque ville sur votre route",
        "landing_hero_sub": "Activez le GPS — nous trouvons les villes proches et lisons des faits en audio, structurés par sections. Parfait en voiture.",
        "landing_btn_try": "Essayer maintenant",
        "landing_btn_how": "Comment ça marche",
        "landing_section_1_title": "Pensé pour la route",
        "landing_section_1_sub": "Pas de texte inutile à l’écran — carte, sections et audio.",
        "landing_step_1": "GPS → position en temps réel",
        "landing_step_2": "10 km → villes proches sur la carte",
        "landing_step_3": "Ville → choisissez ou activez “Auto”",
        "landing_step_4": "Audio → récit par récit",
        "landing_top_places_kicker": "Inspiration",
        "landing_top_places_title": "Lieux à découvrir",
        "landing_top_places_sub": "Une petite galerie d’arrêts à ouvrir — touchez une carte pour voir l’endroit sur la carte et lancer l’audio‑guide.",
        "landing_stats_1": "villes dans la base",
        "landing_stats_2": "rayon proche",
        "landing_stats_3": "langues audio",
        "landing_stats_4": "texte affiché",
        "landing_cards_title": "Pourquoi c’est utile",
        "landing_card_1": "Écoutez l’histoire",
        "landing_card_1_sub": "Moins de clics. Plus d’essentiel.",
        "landing_card_2": "Découvrez des faits",
        "landing_card_2_sub": "Faits structurés en sections.",
        "landing_card_3": "Planifiez des arrêts",
        "landing_card_3_sub": "Comprendre le lieu avant l’arrêt.",
        "landing_card_4": "Mode “Auto”",
        "landing_card_4_sub": "En route, on prend la ville la plus proche.",
        "landing_ph_caption": "Espace réservé (vidéo / captures)",
        "landing_card_europe_title": "Pays d’Europe",
        "landing_card_europe_sub": "Parcourez chaque page pays d’Europe avec drapeaux.",
        "landing_card_clean_title": "Minimal en voiture",
        "landing_card_clean_sub": "Pas de longs textes à l’écran — juste la structure et l’audio.",
        "landing_trusted_title": "Ils nous font confiance (placeholder)",
        "landing_features_title": "Pourquoi SonicCity",
        "landing_features_sub": "Conçu pour écouter en mouvement — interface minimale, clarté maximale.",
        "landing_feat_1_title": "Mise à jour en temps réel",
        "landing_feat_1_sub": "Les villes proches se mettent à jour pendant le trajet.",
        "landing_feat_2_title": "Carte d’abord",
        "landing_feat_2_sub": "Les villes sont toujours sur la carte, pas cachées dans des menus.",
        "landing_feat_3_title": "Lecture par sections",
        "landing_feat_3_sub": "Écoutez par récits courts ou tout le guide.",
        "landing_feat_4_title": "Mode “Auto”",
        "landing_feat_4_sub": "Passe à la ville la plus proche, mains libres.",
        "landing_feat_5_title": "Audio multilingue",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — uniquement si la page existe.",
        "landing_feat_6_title": "Sans encombrement",
        "landing_feat_6_sub": "Nous n’affichons pas de longs paragraphes.",
        "landing_picks_title": "Commencez avec ces villes",
        "landing_picks_sub": "Exemples (placeholders). Choisissez une ville sur la carte pour le plan et l’audio.",
        "landing_app_title": "Emportez-le partout",
        "landing_app_sub": "Idéal sur mobile : fixez le téléphone, activez le GPS et écoutez.",
        "landing_app_note": "Badges des stores en placeholder — ceci est une démo web.",
        "landing_app_ph_caption": "Placeholder des écrans",
        "landing_faq_title": "FAQ",
        "landing_faq_sub": "Réponses rapides avant de prendre la route.",
        "landing_faq_q1": "D’où vient l’audio ?",
        "landing_faq_a1": "Nous chargeons la page, la découpons en récits courts, nettoyons le texte, puis le lisons.",
        "landing_faq_q2": "Change-t-il de ville automatiquement ?",
        "landing_faq_a2": "Oui — activez “Auto” pour suivre la ville la plus proche en temps réel.",
        "landing_faq_q3": "Affichez-vous le texte complet ?",
        "landing_faq_a3": "Non. Écran minimal : titres + contrôles audio.",
        "landing_final_title": "Prêt pour la prochaine ville ?",
        "landing_final_sub": "Activez le GPS et laissez SonicCity raconter les lieux que vous traversez.",
        "landing_final_btn": "Ouvrir la carte en direct",
        "landing_footer": "Cartes: OpenStreetMap.",
        "country_largest_cities": "Plus grandes villes",
        "country_lead": "Carte du pays et grandes villes — prêt pour l’audio.",
        "city_lead": "Carte de la ville et récits audio par section.",
        "type_city": "Ville",
        "type_country": "Pays",
        "type_place": "Lieu",
        "open_guide": "Ouvrir le guide",
        "country_top_places": "Lieux phares",
        "city_places_title": "Lieux à visiter",
        "badge_map": "Carte",
        "badge_audio": "Audio",
        "badge_places": "Lieux",
        "prefooter_title": "Trouvez des SonicCity guides dans ces pays",
        "prefooter_sub": "Choisissez un pays pour explorer les villes et lieux sur la carte.",
        "footer_tagline": "Guides audio centrés sur la carte, parfaits sur la route.",
        "footer_links": "Liens",
        "footer_languages": "Langues",
        "footer_countries": "Pays",
        "seo_landing_title": "SonicCity : guides audio en temps réel pour les villes proches",
        "seo_landing_desc": "Guide audio orienté carte avec GPS en direct, détection des villes proches et lecture multilingue par sections pour la route.",
        "landing_hero_kicker": "Copilote IA pour la route",
        "landing_hero_lang_hint": "Langue préférée détectée : {lang}",
        "landing_hero_lang_cta": "Ouvrir la version {lang}",
        "super_title": "Super fonctionnalités pour conducteurs",
        "super_sub": "Tout ce qu’il faut pour écouter villes, lieux et faits sans surcharge visuelle.",
        "super_feat_1_title": "Routage linguistique intelligent",
        "super_feat_1_sub": "Comprend la langue du navigateur et la région pour ouvrir la meilleure locale.",
        "super_feat_2_title": "Pages prêtes pour le SEO",
        "super_feat_2_sub": "Canonical, hreflang, métadonnées et cartes de partage sur chaque page.",
        "super_feat_3_title": "Moteur de carte en direct",
        "super_feat_3_sub": "Mises à jour en temps réel des villes proches pendant le trajet.",
        "super_feat_4_title": "Aperçus au survol",
        "super_feat_4_sub": "Mini-photos des lieux directement sur les marqueurs de carte.",
        "super_feat_5_title": "Contrôle des voix",
        "super_feat_5_sub": "Choix voix féminine/masculine et réglage de vitesse.",
        "super_feat_6_title": "Lecteur collant route",
        "super_feat_6_sub": "Lecteur inférieur persistant avec timeline et progression.",
        "stat_cities": "villes",
        "stat_places": "lieux",
        "stat_languages": "langues",
        "stat_population": "population",
        "stat_coordinates": "coordonnées",
        "stat_city": "ville",
        "stat_country": "pays",
        "seo_country_title_tpl": "{country} : audio guide, lieux à visiter et carte de voyage | SonicCity",
        "seo_country_desc_tpl": "Découvrez {country} avec un guide audio centré sur la carte : {cities} villes, {places} lieux à voir et narration multilingue pour la route.",
        "seo_country_keywords_tpl": "{country} audio guide, guide voyage {country}, lieux à visiter {country}, carte {country}, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country} : audio guide, attractions et histoire | SonicCity",
        "seo_city_desc_tpl": "Écoutez {city} en {country} avec carte interactive, attractions clés et narration audio par sections en {langs} langues.",
        "seo_city_keywords_tpl": "{city} audio guide, attractions {city}, carte {city}, que faire à {city}, histoire {city} audio",
        "seo_place_title_tpl": "{place} ({city}, {country}) audio guide | SonicCity",
        "seo_place_desc_tpl": "Explorez {place} avec carte + audio guide à {city}, {country}. Contexte d’itinéraire en temps réel et voix expressive.",
        "seo_place_keywords_tpl": "{place} audio guide, carte {place}, audio voyage {city}, attractions {country}, self guided tour {place}",
    },
    "es": {
        "nav_home": "Inicio",
        "nav_map": "Mapa",
        "nav_europe": "Europa",
        "nav_search_ph": "Buscar ciudad o país…",
        "nav_language": "Idioma",
        "label_language": "Idioma",
        "voice_label": "Voz",
        "voice_female": "Femenina",
        "voice_male": "Masculina",
        "cta_open_map": "Abrir mapa",
        "cta_start_gps": "GPS",
        "cta_stop": "Stop",
        "cta_auto": "Auto",
        "status_ready": "Listo. Pulsa “GPS”.",
        "status_locating": "Buscando ubicación…",
        "status_denied": "Acceso a la ubicación denegado.",
        "status_error": "Error de ubicación.",
        "you_are_here": "Estás aquí",
        "geo_not_supported": "La geolocalización no es compatible.",
        "gps_started": "GPS activado. Actualizamos mientras te mueves.",
        "gps_stopped": "GPS detenido.",
        "nearby_title": "Ciudades cercanas (10 km)",
        "nearby_none": "No hay ciudades compatibles de más de 10 000 habitantes en un radio de 10 km.",
        "nearby_found": "Encontradas {n} ciudades en un radio de 10 km.",
        "nearby_error": "Error al buscar ciudades.",
        "listen_all": "Escuchar todo",
        "pause": "Pausa",
        "resume": "Continuar",
        "stop": "Detener",
        "city_outline": "Historias de audio",
        "choose_city_first": "Primero elige una ciudad o sección.",
        "wiki_loading": "Cargando la guía…",
        "wiki_loaded": "Guía lista. Toca una sección para escuchar.",
        "wiki_failed": "No se pudo cargar la guía.",
        "audio_loading": "Cargando audio…",
        "audio_playing": "Reproduciendo audio…",
        "audio_paused": "Reproducción en pausa.",
        "audio_stopped": "Reproducción detenida.",
        "audio_chunk_error": "Un fragmento de audio falló. Continuamos…",
        "audio_engine_natural": "Voz de alta calidad",
        "audio_engine_system": "Voz de alta calidad",
        "audio_engine_google": "Voz estándar",
        "words_unit": "palabras",
        "speech_not_supported": "Web Speech API no disponible. Prueba Chrome/Edge.",
        "no_wiki_lang": "No hay artículo en este idioma. Probando otros idiomas…",
        "landing_hero_title": "Guía de audio personal para cada ciudad en tu ruta",
        "landing_hero_sub": "Activa el GPS — buscamos ciudades cercanas y leemos datos en audio por secciones. Perfecto para conducir.",
        "landing_btn_try": "Probar ahora",
        "landing_btn_how": "Cómo funciona",
        "landing_section_1_title": "Hecho para la carretera",
        "landing_section_1_sub": "Sin texto innecesario — mapa, secciones y audio.",
        "landing_step_1": "GPS → ubicación en tiempo real",
        "landing_step_2": "10 km → ciudades cercanas en el mapa",
        "landing_step_3": "Ciudad → elige o activa “Auto”",
        "landing_step_4": "Audio → historia por historia",
        "landing_top_places_kicker": "Inspiración",
        "landing_top_places_title": "Lugares para explorar",
        "landing_top_places_sub": "Una galería rápida de paradas que valen la pena — toca una tarjeta para verla en el mapa y reproducir la guía de audio.",
        "landing_stats_1": "ciudades en la base",
        "landing_stats_2": "radio cercano",
        "landing_stats_3": "idiomas de audio",
        "landing_stats_4": "texto en pantalla",
        "landing_cards_title": "Por qué es útil",
        "landing_card_1": "Escucha historia",
        "landing_card_1_sub": "Menos clics. Más contenido.",
        "landing_card_2": "Aprende datos",
        "landing_card_2_sub": "Datos por secciones.",
        "landing_card_3": "Planifica paradas",
        "landing_card_3_sub": "Entiende el lugar antes de parar.",
        "landing_card_4": "Modo “Auto”",
        "landing_card_4_sub": "En ruta, tomamos la ciudad más cercana.",
        "landing_ph_caption": "Marcador (vídeo / capturas)",
        "landing_card_europe_title": "Países de Europa",
        "landing_card_europe_sub": "Explora todas las páginas de países europeos con banderas.",
        "landing_card_clean_title": "Limpio para conducir",
        "landing_card_clean_sub": "Sin largos textos en pantalla — solo estructura y audio.",
        "landing_trusted_title": "Con la confianza de viajeros (placeholder)",
        "landing_features_title": "Por qué SonicCity",
        "landing_features_sub": "Diseñado para escuchar en movimiento — interfaz mínima, máxima claridad.",
        "landing_feat_1_title": "Actualización en tiempo real",
        "landing_feat_1_sub": "Las ciudades cercanas se actualizan mientras te mueves.",
        "landing_feat_2_title": "Mapa primero",
        "landing_feat_2_sub": "Las ciudades siempre están en el mapa, no en menús.",
        "landing_feat_3_title": "Reproducción por secciones",
        "landing_feat_3_sub": "Escucha historias cortas o toda la guía.",
        "landing_feat_4_title": "Modo “Auto”",
        "landing_feat_4_sub": "Cambia a la ciudad más cercana sin usar las manos.",
        "landing_feat_5_title": "Audio multidioma",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — solo si la página existe.",
        "landing_feat_6_title": "Sin texto de más",
        "landing_feat_6_sub": "No mostramos largos párrafos.",
        "landing_picks_title": "Empieza con estas ciudades",
        "landing_picks_sub": "Ejemplos (placeholders). Elige cualquier ciudad en el mapa para ver el esquema y escuchar.",
        "landing_app_title": "Llévalo contigo",
        "landing_app_sub": "Ideal en móvil: coloca el teléfono, activa el GPS y escucha.",
        "landing_app_note": "Los badges de tiendas son placeholders — esto es una demo web.",
        "landing_app_ph_caption": "Placeholder de pantallas",
        "landing_faq_title": "Preguntas frecuentes",
        "landing_faq_sub": "Respuestas rápidas antes de salir.",
        "landing_faq_q1": "¿De dónde sale el audio?",
        "landing_faq_a1": "Cargamos la página, la dividimos en historias cortas, limpiamos el texto y lo leemos.",
        "landing_faq_q2": "¿Cambia de ciudad automáticamente?",
        "landing_faq_a2": "Sí — activa “Auto” para seguir la ciudad más cercana en tiempo real.",
        "landing_faq_q3": "¿Muestras el texto completo?",
        "landing_faq_a3": "No. Pantalla mínima: títulos + controles de audio.",
        "landing_final_title": "¿Listo para la próxima ciudad?",
        "landing_final_sub": "Activa el GPS y deja que SonicCity narre los lugares por los que pasas.",
        "landing_final_btn": "Abrir mapa en vivo",
        "landing_footer": "Mapas: OpenStreetMap.",
        "country_largest_cities": "Ciudades más grandes",
        "country_lead": "Mapa del país y sus ciudades principales — listo para audio.",
        "city_lead": "Mapa de la ciudad e historias de audio por sección.",
        "type_city": "Ciudad",
        "type_country": "País",
        "type_place": "Lugar",
        "open_guide": "Abrir guía",
        "country_top_places": "Lugares destacados",
        "city_places_title": "Lugares para visitar",
        "badge_map": "Mapa",
        "badge_audio": "Audio",
        "badge_places": "Lugares",
        "prefooter_title": "Encuentra SonicCity guides en estos países",
        "prefooter_sub": "Elige un país para explorar ciudades y lugares en el mapa.",
        "footer_tagline": "Guías de audio centradas en el mapa, perfectas para la ruta.",
        "footer_links": "Enlaces",
        "footer_languages": "Idiomas",
        "footer_countries": "Países",
        "seo_landing_title": "SonicCity: guías de audio en tiempo real para ciudades cercanas",
        "seo_landing_desc": "Guía de audio orientada al mapa con GPS en vivo, detección de ciudades cercanas y reproducción multilingüe por secciones para carretera.",
        "landing_hero_kicker": "Compañero de ruta con IA",
        "landing_hero_lang_hint": "Idioma preferido detectado: {lang}",
        "landing_hero_lang_cta": "Abrir versión en {lang}",
        "super_title": "Super funciones para conducir",
        "super_sub": "Todo lo necesario para escuchar ciudades, lugares y datos sin saturar la pantalla.",
        "super_feat_1_title": "Enrutado inteligente de idioma",
        "super_feat_1_sub": "Detecta idioma del navegador y región para abrir la mejor localización.",
        "super_feat_2_title": "Landing pages SEO-ready",
        "super_feat_2_sub": "Canonical, hreflang, metadatos y tarjetas sociales en cada página.",
        "super_feat_3_title": "Motor de mapa en vivo",
        "super_feat_3_sub": "Actualizaciones en tiempo real de ciudades cercanas durante el viaje.",
        "super_feat_4_title": "Previews al pasar",
        "super_feat_4_sub": "Mini fotos de lugares directamente en marcadores del mapa.",
        "super_feat_5_title": "Control de voz",
        "super_feat_5_sub": "Elige voz femenina/masculina y ajusta la velocidad de reproducción.",
        "super_feat_6_title": "Player fijo de carretera",
        "super_feat_6_sub": "Player inferior persistente con timeline y progreso.",
        "stat_cities": "ciudades",
        "stat_places": "lugares",
        "stat_languages": "idiomas",
        "stat_population": "población",
        "stat_coordinates": "coordenadas",
        "stat_city": "ciudad",
        "stat_country": "país",
        "seo_country_title_tpl": "{country}: audio guía, lugares para visitar y mapa de viaje | SonicCity",
        "seo_country_desc_tpl": "Explora {country} con una audio guía orientada al mapa: {cities} ciudades, {places} lugares para visitar y narración multilingüe para carretera.",
        "seo_country_keywords_tpl": "{country} audio guía, guía de viaje {country}, lugares para visitar {country}, mapa {country}, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country}: audio guía, atracciones e historia | SonicCity",
        "seo_city_desc_tpl": "Escucha {city} en {country} con mapa interactivo, atracciones clave y narración por secciones en {langs} idiomas.",
        "seo_city_keywords_tpl": "{city} audio guía, atracciones {city}, mapa {city}, qué hacer en {city}, historia {city} audio",
        "seo_place_title_tpl": "{place} ({city}, {country}) audio guía | SonicCity",
        "seo_place_desc_tpl": "Descubre {place} con mapa + audio guía en {city}, {country}. Contexto de ruta en tiempo real y voz expresiva.",
        "seo_place_keywords_tpl": "{place} audio guía, mapa {place}, audio de viaje {city}, atracciones {country}, self guided tour {place}",
    },
    "it": {
        "nav_home": "Home",
        "nav_map": "Mappa",
        "nav_europe": "Europa",
        "nav_search_ph": "Cerca città o paese…",
        "nav_language": "Lingua",
        "label_language": "Lingua",
        "voice_label": "Voce",
        "voice_female": "Femminile",
        "voice_male": "Maschile",
        "cta_open_map": "Apri mappa",
        "cta_start_gps": "GPS",
        "cta_stop": "Stop",
        "cta_auto": "Auto",
        "status_ready": "Pronto. Premi “GPS”.",
        "status_locating": "Ricerca posizione…",
        "status_denied": "Accesso alla posizione negato.",
        "status_error": "Errore di posizione.",
        "you_are_here": "Sei qui",
        "geo_not_supported": "La geolocalizzazione non è supportata.",
        "gps_started": "GPS attivo. Aggiorniamo mentre ti muovi.",
        "gps_stopped": "GPS fermato.",
        "nearby_title": "Città vicine (10 km)",
        "nearby_none": "Nessuna città supportata con oltre 10.000 abitanti entro 10 km.",
        "nearby_found": "Trovate {n} città entro 10 km.",
        "nearby_error": "Errore nella ricerca città.",
        "listen_all": "Ascolta tutto",
        "pause": "Pausa",
        "resume": "Riprendi",
        "stop": "Ferma",
        "city_outline": "Storie audio",
        "choose_city_first": "Scegli prima una città o una sezione.",
        "wiki_loading": "Caricamento guida…",
        "wiki_loaded": "Guida pronta. Tocca una sezione per ascoltare.",
        "wiki_failed": "Impossibile caricare la guida.",
        "audio_loading": "Caricamento audio…",
        "audio_playing": "Riproduzione audio…",
        "audio_paused": "Riproduzione in pausa.",
        "audio_stopped": "Riproduzione fermata.",
        "audio_chunk_error": "Un frammento audio non è riuscito. Continuiamo…",
        "audio_engine_natural": "Voce di alta qualità",
        "audio_engine_system": "Voce di alta qualità",
        "audio_engine_google": "Voce standard",
        "words_unit": "parole",
        "speech_not_supported": "Web Speech API non disponibile. Prova Chrome/Edge.",
        "no_wiki_lang": "Nessun articolo in questa lingua. Controllo altre lingue…",
        "landing_hero_title": "Guida audio personale per ogni città sul tuo percorso",
        "landing_hero_sub": "Attiva il GPS — troviamo le città vicine e leggiamo fatti in audio, divisi per sezioni. Perfetto in auto.",
        "landing_btn_try": "Prova ora",
        "landing_btn_how": "Come funziona",
        "landing_section_1_title": "Pensato per la strada",
        "landing_section_1_sub": "Niente testo inutile — mappa, sezioni e audio.",
        "landing_step_1": "GPS → posizione in tempo reale",
        "landing_step_2": "10 km → città vicine sulla mappa",
        "landing_step_3": "Città → scegli o attiva “Auto”",
        "landing_step_4": "Audio → storia dopo storia",
        "landing_top_places_kicker": "Ispirazione",
        "landing_top_places_title": "Luoghi da esplorare",
        "landing_top_places_sub": "Una piccola galleria di tappe che vale la pena aprire — tocca una card per vederla sulla mappa e ascoltare l’audio‑guida.",
        "landing_stats_1": "città nel database",
        "landing_stats_2": "raggio vicino",
        "landing_stats_3": "lingue audio",
        "landing_stats_4": "testo mostrato",
        "landing_cards_title": "Perché è utile",
        "landing_card_1": "Ascolta la storia",
        "landing_card_1_sub": "Meno tocchi. Più valore.",
        "landing_card_2": "Scopri fatti",
        "landing_card_2_sub": "Fatti in sezioni.",
        "landing_card_3": "Pianifica soste",
        "landing_card_3_sub": "Capisci il posto prima della sosta.",
        "landing_card_4": "Modalità “Auto”",
        "landing_card_4_sub": "In viaggio, scegliamo la città più vicina.",
        "landing_ph_caption": "Segnaposto (video / screenshot)",
        "landing_card_europe_title": "Paesi d’Europa",
        "landing_card_europe_sub": "Sfoglia tutte le pagine dei paesi europei con bandiere.",
        "landing_card_clean_title": "Pulito per la guida",
        "landing_card_clean_sub": "Niente lunghi testi sullo schermo — solo struttura e audio.",
        "landing_trusted_title": "Scelto da viaggiatori (placeholder)",
        "landing_features_title": "Perché SonicCity",
        "landing_features_sub": "Pensato per ascoltare in movimento — UI minimale, massima chiarezza.",
        "landing_feat_1_title": "Aggiornamenti in tempo reale",
        "landing_feat_1_sub": "Le città vicine si aggiornano mentre ti muovi.",
        "landing_feat_2_title": "Mappa al centro",
        "landing_feat_2_sub": "Le città sono sempre sulla mappa, non nei menu.",
        "landing_feat_3_title": "Riproduzione per sezioni",
        "landing_feat_3_sub": "Ascolta storie brevi o tutta la guida.",
        "landing_feat_4_title": "Modalità “Auto”",
        "landing_feat_4_sub": "Passa alla città più vicina a mani libere.",
        "landing_feat_5_title": "Audio multilingue",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — solo se la pagina esiste.",
        "landing_feat_6_title": "Niente testo inutile",
        "landing_feat_6_sub": "Non mostriamo lunghi paragrafi.",
        "landing_picks_title": "Inizia da queste città",
        "landing_picks_sub": "Esempi (placeholders). Scegli qualsiasi città sulla mappa per indice e audio.",
        "landing_app_title": "Portalo con te",
        "landing_app_sub": "Perfetto su mobile: fissa il telefono, attiva il GPS e ascolta.",
        "landing_app_note": "Badge degli store in placeholder — questa è una demo web.",
        "landing_app_ph_caption": "Placeholder delle schermate",
        "landing_faq_title": "FAQ",
        "landing_faq_sub": "Risposte rapide prima di partire.",
        "landing_faq_q1": "Da dove viene l’audio?",
        "landing_faq_a1": "Carichiamo la pagina, la dividiamo in storie brevi, puliamo il testo e lo leggiamo.",
        "landing_faq_q2": "Cambia città automaticamente?",
        "landing_faq_a2": "Sì — attiva “Auto” per seguire la città più vicina in tempo reale.",
        "landing_faq_q3": "Mostrate il testo completo?",
        "landing_faq_a3": "No. Schermo minimale: titoli + controlli audio.",
        "landing_final_title": "Pronto per la prossima città?",
        "landing_final_sub": "Attiva il GPS e lascia che SonicCity racconti i luoghi che attraversi.",
        "landing_final_btn": "Apri mappa live",
        "landing_footer": "Mappe: OpenStreetMap.",
        "country_largest_cities": "Città più grandi",
        "country_lead": "Mappa del paese e città principali — pronto per l’audio.",
        "city_lead": "Mappa della città e storie audio per sezione.",
        "type_city": "Città",
        "type_country": "Paese",
        "type_place": "Luogo",
        "open_guide": "Apri guida",
        "country_top_places": "Luoghi principali",
        "city_places_title": "Luoghi da vedere",
        "badge_map": "Mappa",
        "badge_audio": "Audio",
        "badge_places": "Luoghi",
        "prefooter_title": "Trova SonicCity guides in questi paesi",
        "prefooter_sub": "Scegli un paese per esplorare città e luoghi sulla mappa.",
        "footer_tagline": "Guide audio basate sulla mappa, perfette in viaggio.",
        "footer_links": "Link",
        "footer_languages": "Lingue",
        "footer_countries": "Paesi",
        "seo_landing_title": "SonicCity: audioguide in tempo reale per città vicine",
        "seo_landing_desc": "Audioguida map-first con GPS live, rilevamento città vicine e riproduzione multilingue per sezioni per i viaggi in auto.",
        "landing_hero_kicker": "Compagno di viaggio con IA",
        "landing_hero_lang_hint": "Lingua preferita rilevata: {lang}",
        "landing_hero_lang_cta": "Apri versione {lang}",
        "super_title": "Super funzionalità per guidatori",
        "super_sub": "Tutto il necessario per ascoltare città, luoghi e fatti senza sovraccaricare lo schermo.",
        "super_feat_1_title": "Instradamento lingua intelligente",
        "super_feat_1_sub": "Riconosce lingua browser e area geografica per aprire la locale migliore.",
        "super_feat_2_title": "Landing SEO-ready",
        "super_feat_2_sub": "Canonical, hreflang, metadati e card social su ogni pagina.",
        "super_feat_3_title": "Motore mappa live",
        "super_feat_3_sub": "Aggiornamenti in tempo reale delle città vicine durante il tragitto.",
        "super_feat_4_title": "Anteprime al passaggio",
        "super_feat_4_sub": "Mini foto dei luoghi direttamente sui marker della mappa.",
        "super_feat_5_title": "Controllo voce",
        "super_feat_5_sub": "Scegli voce femminile/maschile e regola la velocità.",
        "super_feat_6_title": "Player stradale fisso",
        "super_feat_6_sub": "Player inferiore persistente con timeline e avanzamento.",
        "stat_cities": "città",
        "stat_places": "luoghi",
        "stat_languages": "lingue",
        "stat_population": "popolazione",
        "stat_coordinates": "coordinate",
        "stat_city": "città",
        "stat_country": "paese",
        "seo_country_title_tpl": "{country}: audioguida, luoghi da visitare e mappa viaggio | SonicCity",
        "seo_country_desc_tpl": "Esplora {country} con una guida audio map-first: {cities} città, {places} luoghi da vedere e narrazione multilingue per i viaggi su strada.",
        "seo_country_keywords_tpl": "{country} audioguida, guida viaggio {country}, luoghi da visitare {country}, mappa {country}, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country}: audioguida, attrazioni e storia | SonicCity",
        "seo_city_desc_tpl": "Ascolta {city} in {country} con mappa interattiva, attrazioni principali e narrazione audio per sezioni in {langs} lingue.",
        "seo_city_keywords_tpl": "{city} audioguida, attrazioni {city}, mappa {city}, cosa vedere a {city}, storia {city} audio",
        "seo_place_title_tpl": "{place} ({city}, {country}) audioguida | SonicCity",
        "seo_place_desc_tpl": "Scopri {place} con mappa + audioguida a {city}, {country}. Contesto percorso in tempo reale e voce espressiva.",
        "seo_place_keywords_tpl": "{place} audioguida, mappa {place}, audio viaggio {city}, attrazioni {country}, self guided tour {place}",
    },
    "de": {
        "nav_home": "Start",
        "nav_map": "Karte",
        "nav_europe": "Europa",
        "nav_search_ph": "Stadt oder Land suchen…",
        "nav_language": "Sprache",
        "label_language": "Sprache",
        "voice_label": "Stimme",
        "voice_female": "Weiblich",
        "voice_male": "Männlich",
        "cta_open_map": "Karte öffnen",
        "cta_start_gps": "GPS",
        "cta_stop": "Stopp",
        "cta_auto": "Auto",
        "status_ready": "Bereit. Tippe auf “GPS”.",
        "status_locating": "Standort wird gesucht…",
        "status_denied": "Standortzugriff verweigert.",
        "status_error": "Standortfehler.",
        "you_are_here": "Du bist hier",
        "geo_not_supported": "Geolokalisierung wird nicht unterstützt.",
        "gps_started": "GPS aktiv. Aktualisierung während der Fahrt.",
        "gps_stopped": "GPS gestoppt.",
        "nearby_title": "Städte in der Nähe (10 km)",
        "nearby_none": "Keine unterstützten Städte mit mehr als 10.000 Einwohnern im Umkreis von 10 km.",
        "nearby_found": "{n} Städte im Umkreis von 10 km gefunden.",
        "nearby_error": "Fehler bei der Stadtsuche.",
        "listen_all": "Alles anhören",
        "pause": "Pause",
        "resume": "Fortsetzen",
        "stop": "Stoppen",
        "city_outline": "Audiogeschichten",
        "choose_city_first": "Wähle zuerst eine Stadt oder einen Abschnitt.",
        "wiki_loading": "Guide wird geladen…",
        "wiki_loaded": "Guide bereit. Tippe auf einen Abschnitt zum Abspielen.",
        "wiki_failed": "Guide konnte nicht geladen werden.",
        "audio_loading": "Audio wird geladen…",
        "audio_playing": "Audio wird abgespielt…",
        "audio_paused": "Wiedergabe pausiert.",
        "audio_stopped": "Wiedergabe gestoppt.",
        "audio_chunk_error": "Ein Audio-Abschnitt ist fehlgeschlagen. Wir machen weiter…",
        "audio_engine_natural": "Hochwertige Stimme",
        "audio_engine_system": "Hochwertige Stimme",
        "audio_engine_google": "Standardstimme",
        "words_unit": "Wörter",
        "speech_not_supported": "Web Speech API nicht verfügbar. Versuche Chrome/Edge.",
        "no_wiki_lang": "Kein Artikel in dieser Sprache. Prüfe andere Sprachen…",
        "landing_hero_title": "Dein persönlicher Audio‑Guide für jede Stadt auf der Strecke",
        "landing_hero_sub": "GPS an — wir finden nahe Städte und lesen Fakten als Audio, gegliedert nach Abschnitten. Ideal beim Fahren.",
        "landing_btn_try": "Jetzt testen",
        "landing_btn_how": "So funktioniert’s",
        "landing_section_1_title": "Für unterwegs gemacht",
        "landing_section_1_sub": "Kein unnötiger Text — Karte, Abschnitte und Audio.",
        "landing_step_1": "GPS → Standort in Echtzeit",
        "landing_step_2": "10 km → nahe Städte auf der Karte",
        "landing_step_3": "Stadt → wählen oder „Auto“ aktivieren",
        "landing_step_4": "Audio → Geschichte für Geschichte",
        "landing_top_places_kicker": "Inspiration",
        "landing_top_places_title": "Orte, die sich lohnen",
        "landing_top_places_sub": "Eine kleine Galerie mit Stopps, die sich zu öffnen lohnen — tippe eine Karte an, um den Ort auf der Karte zu sehen und den Audio‑Guide zu starten.",
        "landing_stats_1": "Städte in der Datenbank",
        "landing_stats_2": "Nah‑Radius",
        "landing_stats_3": "Audio‑Sprachen",
        "landing_stats_4": "Text angezeigt",
        "landing_cards_title": "Warum es hilft",
        "landing_card_1": "Geschichte hören",
        "landing_card_1_sub": "Weniger Klicks. Mehr Inhalt.",
        "landing_card_2": "Fakten lernen",
        "landing_card_2_sub": "Fakten, nach Abschnitten.",
        "landing_card_3": "Stopps planen",
        "landing_card_3_sub": "Ort verstehen, bevor du anhältst.",
        "landing_card_4": "„Auto“-Modus",
        "landing_card_4_sub": "Unterwegs nehmen wir die nächste Stadt.",
        "landing_ph_caption": "Platzhalter (Video / Screenshots)",
        "landing_card_europe_title": "Länder in Europa",
        "landing_card_europe_sub": "Alle europäischen Länderseiten mit Flaggen durchstöbern.",
        "landing_card_clean_title": "Sauber fürs Fahren",
        "landing_card_clean_sub": "Keine langen Texte am Bildschirm — nur Struktur und Audio.",
        "landing_trusted_title": "Von Reisenden vertraut (Platzhalter)",
        "landing_features_title": "Warum SonicCity",
        "landing_features_sub": "Gemacht fürs Hören unterwegs — minimale UI, maximale Klarheit.",
        "landing_feat_1_title": "Updates in Echtzeit",
        "landing_feat_1_sub": "Nahe Städte aktualisieren sich während der Fahrt.",
        "landing_feat_2_title": "Karte zuerst",
        "landing_feat_2_sub": "Städte sind immer auf der Karte, nicht in Menüs versteckt.",
        "landing_feat_3_title": "Abschnitt‑Wiedergabe",
        "landing_feat_3_sub": "Kurze Geschichten hören oder den ganzen Guide abspielen.",
        "landing_feat_4_title": "„Auto“-Modus",
        "landing_feat_4_sub": "Wechselt freihändig zur nächsten Stadt.",
        "landing_feat_5_title": "Mehrsprachiges Audio",
        "landing_feat_5_sub": "FR, ES, IT, UA, DE — nur wenn die Seite existiert.",
        "landing_feat_6_title": "Kein Text‑Ballast",
        "landing_feat_6_sub": "Wir zeigen keine langen Absätze.",
        "landing_picks_title": "Starte mit diesen Städten",
        "landing_picks_sub": "Beispiele (Platzhalter). Wähle eine Stadt auf der Karte für Gliederung und Audio.",
        "landing_app_title": "Immer dabei",
        "landing_app_sub": "Ideal am Handy: Telefon befestigen, GPS aktivieren und hören.",
        "landing_app_note": "Store‑Badges sind Platzhalter — dies ist eine Web‑Demo.",
        "landing_app_ph_caption": "App‑Screens Platzhalter",
        "landing_faq_title": "FAQ",
        "landing_faq_sub": "Schnelle Antworten, bevor es losgeht.",
        "landing_faq_q1": "Woher kommt das Audio?",
        "landing_faq_a1": "Wir laden die Seite, teilen sie in kurze Geschichten, bereinigen den Text und lesen ihn vor.",
        "landing_faq_q2": "Wechselt es automatisch die Stadt?",
        "landing_faq_a2": "Ja — aktiviere „Auto“, um die nächste Stadt in Echtzeit zu verfolgen.",
        "landing_faq_q3": "Zeigt ihr den Volltext an?",
        "landing_faq_a3": "Nein. Minimaler Screen: Überschriften + Audio‑Steuerung.",
        "landing_final_title": "Bereit für die nächste Stadt?",
        "landing_final_sub": "GPS aktivieren und SonicCity erzählt dir die Orte, an denen du vorbeifährst.",
        "landing_final_btn": "Live‑Karte öffnen",
        "landing_footer": "Karten: OpenStreetMap.",
        "country_largest_cities": "Größte Städte",
        "country_lead": "Landkarte und größte Städte — bereit fürs Audio.",
        "city_lead": "Stadtkarte und Audiogeschichten nach Abschnitten.",
        "type_city": "Stadt",
        "type_country": "Land",
        "type_place": "Ort",
        "open_guide": "Guide öffnen",
        "country_top_places": "Top‑Orte",
        "city_places_title": "Sehenswürdigkeiten",
        "badge_map": "Karte",
        "badge_audio": "Audio",
        "badge_places": "Orte",
        "prefooter_title": "Finde SonicCity guides in diesen Ländern",
        "prefooter_sub": "Wähle ein Land, um Städte und Orte auf der Karte zu erkunden.",
        "footer_tagline": "Map‑first Audio‑Guides für die Straße.",
        "footer_links": "Links",
        "footer_languages": "Sprachen",
        "footer_countries": "Länder",
        "seo_landing_title": "SonicCity: Echtzeit-Audioguides für Städte in der Nähe",
        "seo_landing_desc": "Map-first Audioguide mit Live-GPS, Erkennung naher Städte und mehrsprachiger Abschnitts-Wiedergabe für Fahrten.",
        "landing_hero_kicker": "KI-Begleiter für unterwegs",
        "landing_hero_lang_hint": "Bevorzugte Sprache erkannt: {lang}",
        "landing_hero_lang_cta": "{lang}-Version öffnen",
        "super_title": "Super-Features für Fahrer",
        "super_sub": "Alles, um Städte, Orte und Fakten zu hören, ohne den Screen zu überladen.",
        "super_feat_1_title": "Intelligentes Sprach-Routing",
        "super_feat_1_sub": "Erkennt Browser-Sprache und Region und öffnet die beste Locale.",
        "super_feat_2_title": "SEO-fertige Landingpages",
        "super_feat_2_sub": "Canonical, hreflang, Metadaten und Share-Cards auf jeder Seite.",
        "super_feat_3_title": "Live-Karten-Engine",
        "super_feat_3_sub": "Echtzeit-Updates zu nahen Städten während der Fahrt.",
        "super_feat_4_title": "Hover-Vorschauen",
        "super_feat_4_sub": "Mini-Fotos von Orten direkt auf Kartenmarkern.",
        "super_feat_5_title": "Stimmensteuerung",
        "super_feat_5_sub": "Zwischen weiblicher/männlicher Stimme wechseln und Tempo anpassen.",
        "super_feat_6_title": "Fixierter Road-Player",
        "super_feat_6_sub": "Permanenter Bottom-Player mit Timeline und Fortschritt.",
        "stat_cities": "Städte",
        "stat_places": "Orte",
        "stat_languages": "Sprachen",
        "stat_population": "Einwohner",
        "stat_coordinates": "Koordinaten",
        "stat_city": "Stadt",
        "stat_country": "Land",
        "seo_country_title_tpl": "{country}: Audioguide, Sehenswürdigkeiten und Reisekarte | SonicCity",
        "seo_country_desc_tpl": "Entdecke {country} mit map-first Audioguide: {cities} Städte, {places} Orte und mehrsprachige Erzählung für Roadtrips.",
        "seo_country_keywords_tpl": "{country} Audioguide, Reiseführer {country}, Sehenswürdigkeiten {country}, Karte {country}, self guided tour {country}",
        "seo_city_title_tpl": "{city}, {country}: Audioguide, Attraktionen und Geschichte | SonicCity",
        "seo_city_desc_tpl": "Höre {city} in {country} mit interaktiver Karte, wichtigsten Attraktionen und Abschnitts-Audio in {langs} Sprachen.",
        "seo_city_keywords_tpl": "{city} Audioguide, Attraktionen {city}, {city} Karte, was tun in {city}, {city} Geschichte Audio",
        "seo_place_title_tpl": "{place} ({city}, {country}) Audioguide | SonicCity",
        "seo_place_desc_tpl": "Erkunde {place} mit Karte + Audioguide in {city}, {country}. Echtzeit-Routenkontext und ausdrucksstarke Stimme.",
        "seo_place_keywords_tpl": "{place} Audioguide, {place} Karte, Reiseaudio {city}, Attraktionen {country}, self guided tour {place}",
    },
}

ADDITIONAL_UI_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "nav_toggle": "Toggle navigation",
        "nav_how": "How it works",
        "nav_cities": "Cities",
        "nav_places": "Places",
        "nav_blog": "Blog",
        "nav_countries": "Countries",
        "nav_account": "Account",
        "nav_my_account": "My account",
        "nav_logout": "Log Out",
        "nav_login": "Log In",
        "nav_start_guide": "Start guide",
        "search_guides": "Search guides",
        "footer_product": "Product",
        "footer_how": "How it works",
        "footer_driving_mode": "Driving mode",
        "footer_walking_mode": "Walking mode",
        "footer_audio_player": "Audio player",
        "footer_explore": "Explore",
        "footer_popular_guides": "Popular guides",
        "footer_travel_blog": "Travel blog",
        "footer_popular": "Popular",
        "footer_legal": "Legal",
        "footer_privacy": "Privacy Policy",
        "footer_terms": "Terms",
        "footer_cookies": "Cookies",
        "footer_contacts": "Contacts",
        "subscription_close": "Close",
        "subscription_kicker": "Travel audio updates",
        "subscription_title": "Free city guide updates",
        "subscription_intro": "New maps, places and audio stories for Europe. One short email when useful guides are ready.",
        "subscription_name_ph": "Your name",
        "subscription_email_ph": "Your email",
        "subscription_submit": "Notify me",
        "subscription_note": "No spam. Just practical travel audio updates.",
        "auth_close": "Close",
        "auth_kicker": "SonicCity account",
        "auth_login_title": "Log In",
        "auth_login_intro": "Use your email and password to continue.",
        "auth_email": "Email",
        "auth_password": "Password",
        "auth_repeat_password": "Repeat password",
        "auth_country": "Country",
        "auth_login_submit": "Log In",
        "auth_switch_signup": "No account yet? Sign Up",
        "auth_forgot": "Forgot password?",
        "auth_resend": "Resend verification email",
        "auth_signup_title": "Create account",
        "auth_signup_submit": "Sign Up",
        "player_choose_story": "Choose an audio story",
        "player_previous": "Previous",
        "player_play_pause": "Play/Pause",
        "player_stop": "Stop",
        "player_next": "Next",
        "player_speed": "Speed",
        "player_save": "Save",
        "player_volume": "Volume",
        "player_volume_short": "Vol",
        "player_signup_cta": "Sign Up",
        "player_auth_gate": "To Listen for Free, Sign Up.",
        "comments_share_prompt": "Share what helped, what was missing, or what you would like to hear next.",
        "comments_private_note": "Your message is private until moderation. Email is used only for verification and is never shown publicly.",
        "comments_consent": "I understand that my comment will be reviewed before publication.",
        "comments_no_comments": "No comments yet. Be the first to leave a comment.",
        "rating_review": "Review",
        "rating_title": "Rate this audio guide",
        "rating_help": "Help travelers choose useful SonicCity audio stories.",
        "rating_current": "Current audio guide rating",
        "rating_no_ratings": "No ratings yet",
        "rating_count": "ratings",
        "rating_your_rating": "Your rating",
        "rating_tap_star": "Tap a star to submit.",
        "common_save": "Save",
        "common_saved": "Saved",
        "common_search": "Search",
        "common_apply": "Apply",
        "common_view_site": "View site",
        "search_no_results": "No results",
        "validation_required": "This field is required.",
        "validation_email": "Enter a valid email.",
        "errors_try_again": "Something went wrong. Try again.",
    },
    "fr": {
        "nav_toggle": "Ouvrir la navigation",
        "nav_how": "Fonctionnement",
        "nav_cities": "Villes",
        "nav_places": "Lieux",
        "nav_blog": "Blog",
        "nav_countries": "Pays",
        "nav_account": "Compte",
        "nav_my_account": "Mon compte",
        "nav_logout": "Déconnexion",
        "nav_login": "Connexion",
        "nav_start_guide": "Lancer le guide",
        "search_guides": "Rechercher des guides",
        "footer_product": "Produit",
        "footer_how": "Fonctionnement",
        "footer_driving_mode": "Mode voiture",
        "footer_walking_mode": "Mode marche",
        "footer_audio_player": "Lecteur audio",
        "footer_explore": "Explorer",
        "footer_popular_guides": "Guides populaires",
        "footer_travel_blog": "Blog voyage",
        "footer_popular": "Populaire",
        "footer_legal": "Légal",
        "footer_privacy": "Confidentialité",
        "footer_terms": "Conditions",
        "footer_cookies": "Cookies",
        "footer_contacts": "Contacts",
        "subscription_close": "Fermer",
        "subscription_kicker": "Actualités audio voyage",
        "subscription_title": "Mises à jour gratuites des guides",
        "subscription_intro": "Nouvelles cartes, lieux et histoires audio en Europe. Un court email quand des guides utiles sont prêts.",
        "subscription_name_ph": "Votre nom",
        "subscription_email_ph": "Votre email",
        "subscription_submit": "Me prévenir",
        "subscription_note": "Pas de spam. Seulement des mises à jour audio utiles.",
        "auth_close": "Fermer",
        "auth_kicker": "Compte SonicCity",
        "auth_login_title": "Connexion",
        "auth_login_intro": "Utilisez votre email et votre mot de passe pour continuer.",
        "auth_email": "Email",
        "auth_password": "Mot de passe",
        "auth_repeat_password": "Répéter le mot de passe",
        "auth_country": "Pays",
        "auth_login_submit": "Connexion",
        "auth_switch_signup": "Pas encore de compte ? S’inscrire",
        "auth_forgot": "Mot de passe oublié ?",
        "auth_resend": "Renvoyer l’email de confirmation",
        "auth_signup_title": "Créer un compte",
        "auth_signup_submit": "S’inscrire",
        "player_choose_story": "Choisissez une histoire audio",
        "player_previous": "Précédent",
        "player_play_pause": "Lecture/Pause",
        "player_stop": "Stop",
        "player_next": "Suivant",
        "player_speed": "Vitesse",
        "player_save": "Enregistrer",
        "player_volume": "Volume",
        "player_volume_short": "Vol",
        "player_signup_cta": "S’inscrire",
        "player_auth_gate": "Pour écouter gratuitement, inscrivez-vous.",
        "comments_share_prompt": "Dites ce qui vous a aidé, ce qui manque ou ce que vous aimeriez entendre ensuite.",
        "comments_private_note": "Votre message reste privé jusqu’à la modération. L’email n’est jamais affiché publiquement.",
        "comments_consent": "Je comprends que mon commentaire sera vérifié avant publication.",
        "comments_no_comments": "Aucun commentaire. Soyez le premier à laisser un commentaire.",
        "rating_review": "Avis",
        "rating_title": "Notez ce guide audio",
        "rating_help": "Aidez les voyageurs à choisir les histoires audio utiles de SonicCity.",
        "rating_current": "Note actuelle du guide audio",
        "rating_no_ratings": "Aucune note pour le moment",
        "rating_count": "notes",
        "rating_your_rating": "Votre note",
        "rating_tap_star": "Touchez une étoile pour envoyer.",
        "common_save": "Enregistrer",
        "common_saved": "Enregistré",
        "common_search": "Rechercher",
        "common_apply": "Appliquer",
        "common_view_site": "Voir le site",
        "search_no_results": "Aucun résultat",
        "validation_required": "Ce champ est obligatoire.",
        "validation_email": "Saisissez un email valide.",
        "errors_try_again": "Une erreur est survenue. Réessayez.",
    },
    "es": {
        "nav_toggle": "Abrir navegación",
        "nav_how": "Cómo funciona",
        "nav_cities": "Ciudades",
        "nav_places": "Lugares",
        "nav_blog": "Blog",
        "nav_countries": "Países",
        "nav_account": "Cuenta",
        "nav_my_account": "Mi cuenta",
        "nav_logout": "Cerrar sesión",
        "nav_login": "Iniciar sesión",
        "nav_start_guide": "Empezar guía",
        "search_guides": "Buscar guías",
        "footer_product": "Producto",
        "footer_how": "Cómo funciona",
        "footer_driving_mode": "Modo conducción",
        "footer_walking_mode": "Modo paseo",
        "footer_audio_player": "Reproductor",
        "footer_explore": "Explorar",
        "footer_popular_guides": "Guías populares",
        "footer_travel_blog": "Blog de viajes",
        "footer_popular": "Popular",
        "footer_legal": "Legal",
        "footer_privacy": "Privacidad",
        "footer_terms": "Términos",
        "footer_cookies": "Cookies",
        "footer_contacts": "Contactos",
        "subscription_close": "Cerrar",
        "subscription_kicker": "Novedades de audio para viajar",
        "subscription_title": "Actualizaciones gratis de guías",
        "subscription_intro": "Nuevos mapas, lugares e historias de audio para Europa. Un email breve cuando haya guías útiles.",
        "subscription_name_ph": "Tu nombre",
        "subscription_email_ph": "Tu email",
        "subscription_submit": "Avisarme",
        "subscription_note": "Sin spam. Solo novedades útiles de audio.",
        "auth_close": "Cerrar",
        "auth_kicker": "Cuenta SonicCity",
        "auth_login_title": "Iniciar sesión",
        "auth_login_intro": "Usa tu email y contraseña para continuar.",
        "auth_email": "Email",
        "auth_password": "Contraseña",
        "auth_repeat_password": "Repetir contraseña",
        "auth_country": "País",
        "auth_login_submit": "Iniciar sesión",
        "auth_switch_signup": "¿No tienes cuenta? Regístrate",
        "auth_forgot": "¿Olvidaste la contraseña?",
        "auth_resend": "Reenviar email de verificación",
        "auth_signup_title": "Crear cuenta",
        "auth_signup_submit": "Registrarse",
        "player_choose_story": "Elige una historia de audio",
        "player_previous": "Anterior",
        "player_play_pause": "Reproducir/Pausa",
        "player_stop": "Detener",
        "player_next": "Siguiente",
        "player_speed": "Velocidad",
        "player_save": "Guardar",
        "player_volume": "Volumen",
        "player_volume_short": "Vol",
        "player_signup_cta": "Registrarse",
        "player_auth_gate": "Para escuchar gratis, regístrate.",
        "comments_share_prompt": "Comparte qué te ayudó, qué faltó o qué te gustaría escuchar después.",
        "comments_private_note": "Tu mensaje queda privado hasta la moderación. El email nunca se muestra públicamente.",
        "comments_consent": "Entiendo que mi comentario será revisado antes de publicarse.",
        "comments_no_comments": "Aún no hay comentarios. Sé el primero en comentar.",
        "rating_review": "Reseña",
        "rating_title": "Valora esta audioguía",
        "rating_help": "Ayuda a otros viajeros a elegir historias útiles de SonicCity.",
        "rating_current": "Valoración actual de la audioguía",
        "rating_no_ratings": "Sin valoraciones todavía",
        "rating_count": "valoraciones",
        "rating_your_rating": "Tu valoración",
        "rating_tap_star": "Toca una estrella para enviar.",
        "common_save": "Guardar",
        "common_saved": "Guardado",
        "common_search": "Buscar",
        "common_apply": "Aplicar",
        "common_view_site": "Ver sitio",
        "search_no_results": "Sin resultados",
        "validation_required": "Este campo es obligatorio.",
        "validation_email": "Introduce un email válido.",
        "errors_try_again": "Algo salió mal. Inténtalo de nuevo.",
    },
    "it": {
        "nav_toggle": "Apri navigazione",
        "nav_how": "Come funziona",
        "nav_cities": "Città",
        "nav_places": "Luoghi",
        "nav_blog": "Blog",
        "nav_countries": "Paesi",
        "nav_account": "Account",
        "nav_my_account": "Il mio account",
        "nav_logout": "Esci",
        "nav_login": "Accedi",
        "nav_start_guide": "Avvia guida",
        "search_guides": "Cerca guide",
        "footer_product": "Prodotto",
        "footer_how": "Come funziona",
        "footer_driving_mode": "Modalità auto",
        "footer_walking_mode": "Modalità a piedi",
        "footer_audio_player": "Player audio",
        "footer_explore": "Esplora",
        "footer_popular_guides": "Guide popolari",
        "footer_travel_blog": "Blog viaggi",
        "footer_popular": "Popolari",
        "footer_legal": "Legale",
        "footer_privacy": "Privacy",
        "footer_terms": "Termini",
        "footer_cookies": "Cookie",
        "footer_contacts": "Contatti",
        "subscription_close": "Chiudi",
        "subscription_kicker": "Aggiornamenti audio viaggio",
        "subscription_title": "Aggiornamenti gratuiti delle guide",
        "subscription_intro": "Nuove mappe, luoghi e storie audio per l’Europa. Una breve email quando sono pronte guide utili.",
        "subscription_name_ph": "Il tuo nome",
        "subscription_email_ph": "La tua email",
        "subscription_submit": "Avvisami",
        "subscription_note": "Niente spam. Solo aggiornamenti audio utili.",
        "auth_close": "Chiudi",
        "auth_kicker": "Account SonicCity",
        "auth_login_title": "Accedi",
        "auth_login_intro": "Usa email e password per continuare.",
        "auth_email": "Email",
        "auth_password": "Password",
        "auth_repeat_password": "Ripeti password",
        "auth_country": "Paese",
        "auth_login_submit": "Accedi",
        "auth_switch_signup": "Non hai un account? Registrati",
        "auth_forgot": "Password dimenticata?",
        "auth_resend": "Invia di nuovo l’email di verifica",
        "auth_signup_title": "Crea account",
        "auth_signup_submit": "Registrati",
        "player_choose_story": "Scegli una storia audio",
        "player_previous": "Precedente",
        "player_play_pause": "Play/Pausa",
        "player_stop": "Stop",
        "player_next": "Successivo",
        "player_speed": "Velocità",
        "player_save": "Salva",
        "player_volume": "Volume",
        "player_volume_short": "Vol",
        "player_signup_cta": "Registrati",
        "player_auth_gate": "Per ascoltare gratis, registrati.",
        "comments_share_prompt": "Racconta cosa ti è stato utile, cosa mancava o cosa vorresti ascoltare.",
        "comments_private_note": "Il messaggio resta privato fino alla moderazione. L’email non viene mai mostrata.",
        "comments_consent": "Capisco che il commento sarà controllato prima della pubblicazione.",
        "comments_no_comments": "Nessun commento. Lascia tu il primo.",
        "rating_review": "Recensione",
        "rating_title": "Valuta questa audioguida",
        "rating_help": "Aiuta i viaggiatori a scegliere storie audio utili di SonicCity.",
        "rating_current": "Valutazione attuale dell’audioguida",
        "rating_no_ratings": "Ancora nessuna valutazione",
        "rating_count": "valutazioni",
        "rating_your_rating": "La tua valutazione",
        "rating_tap_star": "Tocca una stella per inviare.",
        "common_save": "Salva",
        "common_saved": "Salvato",
        "common_search": "Cerca",
        "common_apply": "Applica",
        "common_view_site": "Vedi sito",
        "search_no_results": "Nessun risultato",
        "validation_required": "Questo campo è obbligatorio.",
        "validation_email": "Inserisci un’email valida.",
        "errors_try_again": "Qualcosa è andato storto. Riprova.",
    },
    "ua": {
        "nav_toggle": "Відкрити навігацію",
        "nav_how": "Як це працює",
        "nav_cities": "Міста",
        "nav_places": "Місця",
        "nav_blog": "Блог",
        "nav_countries": "Країни",
        "nav_account": "Акаунт",
        "nav_my_account": "Мій акаунт",
        "nav_logout": "Вийти",
        "nav_login": "Увійти",
        "nav_start_guide": "Почати гід",
        "search_guides": "Пошук гідів",
        "footer_product": "Продукт",
        "footer_how": "Як це працює",
        "footer_driving_mode": "Режим авто",
        "footer_walking_mode": "Режим прогулянки",
        "footer_audio_player": "Аудіоплеєр",
        "footer_explore": "Досліджувати",
        "footer_popular_guides": "Популярні гіди",
        "footer_travel_blog": "Блог подорожей",
        "footer_popular": "Популярне",
        "footer_legal": "Правове",
        "footer_privacy": "Політика приватності",
        "footer_terms": "Умови",
        "footer_cookies": "Cookies",
        "footer_contacts": "Контакти",
        "subscription_close": "Закрити",
        "subscription_kicker": "Оновлення аудіогідів",
        "subscription_title": "Безкоштовні оновлення міських гідів",
        "subscription_intro": "Нові мапи, місця та аудіоісторії по Європі. Один короткий лист, коли готові корисні гіди.",
        "subscription_name_ph": "Ваше ім’я",
        "subscription_email_ph": "Ваша пошта",
        "subscription_submit": "Повідомити мене",
        "subscription_note": "Без спаму. Лише корисні оновлення аудіогідів.",
        "auth_close": "Закрити",
        "auth_kicker": "Акаунт SonicCity",
        "auth_login_title": "Увійти",
        "auth_login_intro": "Введіть email і пароль, щоб продовжити.",
        "auth_email": "Email",
        "auth_password": "Пароль",
        "auth_repeat_password": "Повторіть пароль",
        "auth_country": "Країна",
        "auth_login_submit": "Увійти",
        "auth_switch_signup": "Немає акаунта? Зареєструватися",
        "auth_forgot": "Забули пароль?",
        "auth_resend": "Надіслати лист підтвердження ще раз",
        "auth_signup_title": "Створити акаунт",
        "auth_signup_submit": "Зареєструватися",
        "player_choose_story": "Оберіть аудіоісторію",
        "player_previous": "Попереднє",
        "player_play_pause": "Плей/Пауза",
        "player_stop": "Стоп",
        "player_next": "Наступне",
        "player_speed": "Швидкість",
        "player_save": "Зберегти",
        "player_volume": "Гучність",
        "player_volume_short": "Гучн.",
        "player_signup_cta": "Зареєструватися",
        "player_auth_gate": "To Listen for Free, Sign Up.",
        "comments_share_prompt": "Поділіться, що було корисно, чого бракує або що ви хочете почути далі.",
        "comments_private_note": "Ваш коментар приватний до модерації. Email ніколи не показується публічно.",
        "comments_consent": "Я розумію, що коментар буде перевірений перед публікацією.",
        "comments_no_comments": "Коментарів ще немає. Будьте першим.",
        "rating_review": "Оцінка",
        "rating_title": "Оцініть цей аудіогід",
        "rating_help": "Допоможіть мандрівникам обирати корисні аудіоісторії SonicCity.",
        "rating_current": "Поточна оцінка аудіогіда",
        "rating_no_ratings": "Оцінок ще немає",
        "rating_count": "оцінок",
        "rating_your_rating": "Ваша оцінка",
        "rating_tap_star": "Натисніть зірку, щоб надіслати.",
        "common_save": "Зберегти",
        "common_saved": "Збережено",
        "common_search": "Пошук",
        "common_apply": "Застосувати",
        "common_view_site": "Дивитися сайт",
        "search_no_results": "Нічого не знайдено",
        "validation_required": "Це поле обов’язкове.",
        "validation_email": "Введіть коректний email.",
        "errors_try_again": "Щось пішло не так. Спробуйте ще раз.",
    },
    "de": {
        "nav_toggle": "Navigation öffnen",
        "nav_how": "So funktioniert es",
        "nav_cities": "Städte",
        "nav_places": "Orte",
        "nav_blog": "Blog",
        "nav_countries": "Länder",
        "nav_account": "Konto",
        "nav_my_account": "Mein Konto",
        "nav_logout": "Abmelden",
        "nav_login": "Anmelden",
        "nav_start_guide": "Guide starten",
        "search_guides": "Guides suchen",
        "footer_product": "Produkt",
        "footer_how": "So funktioniert es",
        "footer_driving_mode": "Fahrmodus",
        "footer_walking_mode": "Gehmodus",
        "footer_audio_player": "Audio-Player",
        "footer_explore": "Entdecken",
        "footer_popular_guides": "Beliebte Guides",
        "footer_travel_blog": "Reiseblog",
        "footer_popular": "Beliebt",
        "footer_legal": "Rechtliches",
        "footer_privacy": "Datenschutz",
        "footer_terms": "Bedingungen",
        "footer_cookies": "Cookies",
        "footer_contacts": "Kontakt",
        "subscription_close": "Schließen",
        "subscription_kicker": "Audio-Reiseupdates",
        "subscription_title": "Kostenlose City-Guide-Updates",
        "subscription_intro": "Neue Karten, Orte und Audio-Geschichten für Europa. Eine kurze E-Mail, wenn nützliche Guides bereit sind.",
        "subscription_name_ph": "Dein Name",
        "subscription_email_ph": "Deine E-Mail",
        "subscription_submit": "Benachrichtigen",
        "subscription_note": "Kein Spam. Nur praktische Audio-Reiseupdates.",
        "auth_close": "Schließen",
        "auth_kicker": "SonicCity Konto",
        "auth_login_title": "Anmelden",
        "auth_login_intro": "Nutze E-Mail und Passwort, um fortzufahren.",
        "auth_email": "E-Mail",
        "auth_password": "Passwort",
        "auth_repeat_password": "Passwort wiederholen",
        "auth_country": "Land",
        "auth_login_submit": "Anmelden",
        "auth_switch_signup": "Noch kein Konto? Registrieren",
        "auth_forgot": "Passwort vergessen?",
        "auth_resend": "Bestätigungs-E-Mail erneut senden",
        "auth_signup_title": "Konto erstellen",
        "auth_signup_submit": "Registrieren",
        "player_choose_story": "Audio-Geschichte wählen",
        "player_previous": "Zurück",
        "player_play_pause": "Play/Pause",
        "player_stop": "Stopp",
        "player_next": "Weiter",
        "player_speed": "Tempo",
        "player_save": "Speichern",
        "player_volume": "Lautstärke",
        "player_volume_short": "Vol",
        "player_signup_cta": "Registrieren",
        "player_auth_gate": "Zum kostenlosen Hören registrieren.",
        "comments_share_prompt": "Teile, was geholfen hat, was fehlt oder was du als Nächstes hören möchtest.",
        "comments_private_note": "Deine Nachricht bleibt bis zur Moderation privat. Die E-Mail wird nie öffentlich gezeigt.",
        "comments_consent": "Ich verstehe, dass mein Kommentar vor der Veröffentlichung geprüft wird.",
        "comments_no_comments": "Noch keine Kommentare. Schreibe den ersten Kommentar.",
        "rating_review": "Bewertung",
        "rating_title": "Bewerte diesen Audioguide",
        "rating_help": "Hilf Reisenden, nützliche SonicCity Audio-Geschichten zu wählen.",
        "rating_current": "Aktuelle Audioguide-Bewertung",
        "rating_no_ratings": "Noch keine Bewertungen",
        "rating_count": "Bewertungen",
        "rating_your_rating": "Deine Bewertung",
        "rating_tap_star": "Tippe auf einen Stern zum Absenden.",
        "common_save": "Speichern",
        "common_saved": "Gespeichert",
        "common_search": "Suchen",
        "common_apply": "Anwenden",
        "common_view_site": "Website ansehen",
        "search_no_results": "Keine Ergebnisse",
        "validation_required": "Dieses Feld ist erforderlich.",
        "validation_email": "Gib eine gültige E-Mail ein.",
        "errors_try_again": "Etwas ist schiefgelaufen. Bitte erneut versuchen.",
    },
}

for _lang, _comment_values in {
    "en": {
        "comments_kicker": "Comments",
        "comments_title": "Comments",
        "comments_button": "Leave Comment",
        "comments_form_title": "Leave a comment",
        "comments_name": "Name",
        "comments_email": "Email",
        "comments_comment": "Comment",
        "comments_submit": "Submit Comment",
        "comments_success": "Thank you. Your comment is waiting for moderation.",
        "comments_error": "Please check your name, email and comment.",
        "comments_rate_limited": "Please wait before sending another comment.",
        "comments_empty": "No comments yet. Be the first to leave a comment.",
        "comments_counter": "0 / 1000",
    },
    "fr": {
        "comments_kicker": "Commentaires",
        "comments_title": "Commentaires",
        "comments_button": "Laisser un commentaire",
        "comments_form_title": "Laisser un commentaire",
        "comments_name": "Nom",
        "comments_email": "Email",
        "comments_comment": "Commentaire",
        "comments_submit": "Envoyer le commentaire",
        "comments_success": "Merci. Votre commentaire attend la modération.",
        "comments_error": "Vérifiez votre nom, votre email et le commentaire.",
        "comments_rate_limited": "Veuillez patienter avant d’envoyer un autre commentaire.",
        "comments_empty": "Aucun commentaire. Soyez le premier à commenter.",
        "comments_counter": "0 / 1000",
    },
    "es": {
        "comments_kicker": "Comentarios",
        "comments_title": "Comentarios",
        "comments_button": "Dejar comentario",
        "comments_form_title": "Dejar un comentario",
        "comments_name": "Nombre",
        "comments_email": "Email",
        "comments_comment": "Comentario",
        "comments_submit": "Enviar comentario",
        "comments_success": "Gracias. Tu comentario está pendiente de moderación.",
        "comments_error": "Revisa tu nombre, email y comentario.",
        "comments_rate_limited": "Espera antes de enviar otro comentario.",
        "comments_empty": "Aún no hay comentarios. Sé el primero en comentar.",
        "comments_counter": "0 / 1000",
    },
    "it": {
        "comments_kicker": "Commenti",
        "comments_title": "Commenti",
        "comments_button": "Lascia un commento",
        "comments_form_title": "Lascia un commento",
        "comments_name": "Nome",
        "comments_email": "Email",
        "comments_comment": "Commento",
        "comments_submit": "Invia commento",
        "comments_success": "Grazie. Il commento è in attesa di moderazione.",
        "comments_error": "Controlla nome, email e commento.",
        "comments_rate_limited": "Attendi prima di inviare un altro commento.",
        "comments_empty": "Nessun commento. Lascia tu il primo.",
        "comments_counter": "0 / 1000",
    },
    "ua": {
        "comments_kicker": "Коментарі",
        "comments_title": "Коментарі",
        "comments_button": "Залишити коментар",
        "comments_form_title": "Залишити коментар",
        "comments_name": "Імʼя",
        "comments_email": "Пошта",
        "comments_comment": "Коментар",
        "comments_submit": "Надіслати коментар",
        "comments_success": "Дякуємо. Ваш коментар очікує модерації.",
        "comments_error": "Перевірте імʼя, пошту і текст коментаря.",
        "comments_rate_limited": "Зачекайте трохи перед наступним коментарем.",
        "comments_empty": "Коментарів ще немає. Залиште перший коментар.",
        "comments_counter": "0 / 1000",
    },
    "de": {
        "comments_kicker": "Kommentare",
        "comments_title": "Kommentare",
        "comments_button": "Kommentar schreiben",
        "comments_form_title": "Kommentar schreiben",
        "comments_name": "Name",
        "comments_email": "E-Mail",
        "comments_comment": "Kommentar",
        "comments_submit": "Kommentar senden",
        "comments_success": "Danke. Dein Kommentar wartet auf Moderation.",
        "comments_error": "Bitte prüfe Name, E-Mail und Kommentar.",
        "comments_rate_limited": "Bitte warte, bevor du einen weiteren Kommentar sendest.",
        "comments_empty": "Noch keine Kommentare. Schreibe den ersten Kommentar.",
        "comments_counter": "0 / 1000",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_comment_values)

for _lang, _js_values in {
    "en": {
        "subscription_success": "Thank you. We saved your request.",
        "subscription_error": "Please check your email and try again.",
        "auth_signup_intro": "Create an account to save listening progress and continue on any page.",
        "auth_switch_login": "Already registered? Log In",
        "auth_enter_email_first": "Enter your email first.",
        "auth_reset_sent": "If this email exists, we sent password reset instructions.",
        "auth_reset_failed": "Could not send reset email.",
        "auth_verification_sent": "Verification email sent.",
        "auth_verification_failed": "Could not send verification email.",
        "auth_check_email": "Check your email to confirm your account.",
        "auth_logged_in": "Logged in.",
        "auth_failed": "Authentication failed.",
        "rating_saving": "Saving your rating...",
    },
    "fr": {
        "subscription_success": "Merci. Votre demande a été enregistrée.",
        "subscription_error": "Vérifiez votre email et réessayez.",
        "auth_signup_intro": "Créez un compte pour enregistrer votre progression d’écoute et continuer sur chaque page.",
        "auth_switch_login": "Déjà inscrit ? Connexion",
        "auth_enter_email_first": "Saisissez d’abord votre email.",
        "auth_reset_sent": "Si cet email existe, nous avons envoyé les instructions de réinitialisation.",
        "auth_reset_failed": "Impossible d’envoyer l’email de réinitialisation.",
        "auth_verification_sent": "Email de vérification envoyé.",
        "auth_verification_failed": "Impossible d’envoyer l’email de vérification.",
        "auth_check_email": "Vérifiez votre email pour confirmer votre compte.",
        "auth_logged_in": "Connecté.",
        "auth_failed": "Authentification échouée.",
        "rating_saving": "Enregistrement de votre note...",
    },
    "es": {
        "subscription_success": "Gracias. Hemos guardado tu solicitud.",
        "subscription_error": "Revisa tu email e inténtalo de nuevo.",
        "auth_signup_intro": "Crea una cuenta para guardar tu progreso de escucha y continuar en cualquier página.",
        "auth_switch_login": "¿Ya tienes cuenta? Inicia sesión",
        "auth_enter_email_first": "Introduce primero tu email.",
        "auth_reset_sent": "Si este email existe, enviamos instrucciones para restablecer la contraseña.",
        "auth_reset_failed": "No se pudo enviar el email de restablecimiento.",
        "auth_verification_sent": "Email de verificación enviado.",
        "auth_verification_failed": "No se pudo enviar el email de verificación.",
        "auth_check_email": "Revisa tu email para confirmar tu cuenta.",
        "auth_logged_in": "Sesión iniciada.",
        "auth_failed": "Error de autenticación.",
        "rating_saving": "Guardando tu valoración...",
    },
    "it": {
        "subscription_success": "Grazie. Abbiamo salvato la richiesta.",
        "subscription_error": "Controlla l’email e riprova.",
        "auth_signup_intro": "Crea un account per salvare i progressi di ascolto e continuare da qualsiasi pagina.",
        "auth_switch_login": "Già registrato? Accedi",
        "auth_enter_email_first": "Inserisci prima la tua email.",
        "auth_reset_sent": "Se questa email esiste, abbiamo inviato le istruzioni per reimpostare la password.",
        "auth_reset_failed": "Impossibile inviare l’email di reset.",
        "auth_verification_sent": "Email di verifica inviata.",
        "auth_verification_failed": "Impossibile inviare l’email di verifica.",
        "auth_check_email": "Controlla l’email per confermare l’account.",
        "auth_logged_in": "Accesso effettuato.",
        "auth_failed": "Autenticazione non riuscita.",
        "rating_saving": "Salvataggio della valutazione...",
    },
    "ua": {
        "subscription_success": "Дякуємо. Ми зберегли ваш запит.",
        "subscription_error": "Перевірте email і спробуйте ще раз.",
        "auth_signup_intro": "Створіть акаунт, щоб зберігати прогрес прослуховування і продовжувати з будь-якої сторінки.",
        "auth_switch_login": "Вже зареєстровані? Увійти",
        "auth_enter_email_first": "Спочатку введіть email.",
        "auth_reset_sent": "Якщо цей email існує, ми надіслали інструкції для скидання пароля.",
        "auth_reset_failed": "Не вдалося надіслати лист для скидання пароля.",
        "auth_verification_sent": "Лист підтвердження надіслано.",
        "auth_verification_failed": "Не вдалося надіслати лист підтвердження.",
        "auth_check_email": "Перевірте email, щоб підтвердити акаунт.",
        "auth_logged_in": "Вхід виконано.",
        "auth_failed": "Помилка входу.",
        "rating_saving": "Зберігаємо вашу оцінку...",
    },
    "de": {
        "subscription_success": "Danke. Wir haben deine Anfrage gespeichert.",
        "subscription_error": "Bitte prüfe deine E-Mail und versuche es erneut.",
        "auth_signup_intro": "Erstelle ein Konto, um deinen Hörfortschritt zu speichern und auf jeder Seite fortzufahren.",
        "auth_switch_login": "Schon registriert? Anmelden",
        "auth_enter_email_first": "Gib zuerst deine E-Mail ein.",
        "auth_reset_sent": "Falls diese E-Mail existiert, haben wir Anweisungen zum Zurücksetzen gesendet.",
        "auth_reset_failed": "Reset-E-Mail konnte nicht gesendet werden.",
        "auth_verification_sent": "Bestätigungs-E-Mail gesendet.",
        "auth_verification_failed": "Bestätigungs-E-Mail konnte nicht gesendet werden.",
        "auth_check_email": "Prüfe deine E-Mail, um dein Konto zu bestätigen.",
        "auth_logged_in": "Angemeldet.",
        "auth_failed": "Authentifizierung fehlgeschlagen.",
        "rating_saving": "Bewertung wird gespeichert...",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_js_values)

for _lang, _audio_status_values in {
    "en": {
        "audio_ready": "Ready",
        "audio_generating": "Preparing",
        "audio_queued": "In queue",
        "audio_failed": "Failed",
        "audio_outdated": "Needs update",
        "audio_skipped": "Skipped",
        "audio_generating_count": "Preparing audio: {ready} / {total} sections ready",
        "audio_ready_count": "Audio ready: {ready} / {total}",
    },
    "ua": {
        "audio_ready": "Готово",
        "audio_generating": "Готується",
        "audio_queued": "У черзі",
        "audio_failed": "Помилка",
        "audio_outdated": "Потрібно оновити",
        "audio_skipped": "Пропущено",
        "audio_generating_count": "Готуємо аудіо: {ready} / {total} розділів готово",
        "audio_ready_count": "Аудіо готове: {ready} / {total}",
    },
    "fr": {
        "audio_ready": "Prêt",
        "audio_generating": "Préparation",
        "audio_queued": "En attente",
        "audio_failed": "Échec",
        "audio_outdated": "À mettre à jour",
        "audio_skipped": "Ignoré",
        "audio_generating_count": "Préparation de l’audio : {ready} / {total} sections prêtes",
        "audio_ready_count": "Audio prêt : {ready} / {total}",
    },
    "es": {
        "audio_ready": "Listo",
        "audio_generating": "Preparando",
        "audio_queued": "En espera",
        "audio_failed": "Error",
        "audio_outdated": "Por actualizar",
        "audio_skipped": "Omitido",
        "audio_generating_count": "Preparando audio: {ready} / {total} secciones listas",
        "audio_ready_count": "Audio listo: {ready} / {total}",
    },
    "it": {
        "audio_ready": "Pronto",
        "audio_generating": "Preparazione",
        "audio_queued": "In attesa",
        "audio_failed": "Errore",
        "audio_outdated": "Da aggiornare",
        "audio_skipped": "Saltato",
        "audio_generating_count": "Preparazione audio: {ready} / {total} sezioni pronte",
        "audio_ready_count": "Audio pronto: {ready} / {total}",
    },
    "de": {
        "audio_ready": "Bereit",
        "audio_generating": "Vorbereitung",
        "audio_queued": "Wartet",
        "audio_failed": "Fehler",
        "audio_outdated": "Aktualisierung nötig",
        "audio_skipped": "Übersprungen",
        "audio_generating_count": "Audio wird vorbereitet: {ready} / {total} Abschnitte bereit",
        "audio_ready_count": "Audio bereit: {ready} / {total}",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_audio_status_values)

for _lang, _page_values in {
    "en": {
        "common_home": "Home",
        "common_map": "Map",
        "common_about": "About",
        "common_related": "Related",
        "common_previous": "Previous",
        "common_next": "Next",
        "common_all": "All",
        "common_open": "Open",
        "common_continue": "Continue",
        "common_clear_all": "Clear all",
        "common_delete_account": "Delete my account",
        "hero_start_listening": "Start listening",
        "hero_open_map": "Open map",
        "hero_saved": "Saved",
        "city_audio_stories": "audio stories",
        "city_playlist_kicker": "Audio playlist",
        "city_playlist_title_tpl": "Stories about {city}",
        "city_playlist_sub_tpl": "Choose a story, press Play and keep listening while you explore {city}.",
        "city_progress_note_tpl": "{city} Audio Guide progress appears here while stories are prepared.",
        "city_info": "City info",
        "nearby_places": "Nearby places",
        "top_places": "Top places",
        "places_to_visit_tpl": "Places to visit in {city}",
        "filter_museums": "Museums",
        "filter_landmarks": "Landmarks",
        "filter_churches": "Churches",
        "filter_parks": "Parks",
        "filter_monuments": "Monuments",
        "filter_viewpoints": "Viewpoints",
        "country_guide": "Country guide",
        "country_listen_tpl": "Listen to {country}",
        "country_story_sub": "Start with a country overview, then continue into cities and landmarks when you are ready.",
        "country_facts_tpl": "{country} travel guide facts",
        "country_popular_cities_tpl": "Popular {country} audio guide cities",
        "country_cities_kicker": "Cities to explore",
        "country_city_guides_tpl": "{country} city guides",
        "country_top_places_title_tpl": "Top places to listen free across {country}",
        "country_top_places_sub_tpl": "One standout place from each selected city in {country}, with the city name shown on every card.",
        "country_about_kicker": "Country travel guide",
        "country_about_title_tpl": "Plan {country} with audio stories, cities and places",
        "more_countries": "More countries",
        "continue_exploring_europe": "Continue exploring Europe",
        "blog_by": "By",
        "blog_free_audio_guide": "Free Audio Guide",
        "blog_community": "Community",
        "blog_useful": "Was this guide useful?",
        "blog_like": "Like",
        "blog_rate_article": "Rate this article",
        "blog_rate_article_aria": "Rate this article from 1 to 5 stars",
        "blog_ratings": "ratings",
        "account_title": "My account",
        "account_kicker": "SonicCity account",
        "account_intro": "Manage your contact information, saved guides and listening progress.",
        "account_confirm_email": "Please confirm your email address to secure your account and recover listening progress.",
        "account_resend_verification": "Resend verification email",
        "account_overview": "Overview",
        "account_profile": "Profile",
        "account_listening_history": "Listening history",
        "account_saved_guides": "Saved guides",
        "account_contact_info": "Contact information",
        "account_email_status": "Email status",
        "account_verified": "Verified",
        "account_pending_verification": "Pending verification",
        "account_preferred_language": "Preferred language",
        "account_preferred_voice": "Preferred voice",
        "account_save_profile": "Save profile",
        "account_privacy_note": "Privacy actions: deleting the account removes saved history and favorites, then anonymizes the user record.",
        "account_no_history": "No listening history yet.",
        "account_no_saved": "No saved guides yet.",
        "account_continue_listening": "Continue listening",
        "account_profile_summary": "Profile summary",
        "account_recently_listened": "Recently listened",
        "account_start_story": "Start any audio story and it will appear here.",
        "account_registered": "Registered",
        "account_last_login": "Last login",
        "label_email": "Email",
        "label_name": "Name",
        "label_country": "Country",
        "label_language": "Language",
        "label_voice": "Voice",
        "voice_preference_female": "Female",
        "voice_preference_male": "Male",
    },
    "fr": {
        "common_home": "Accueil",
        "common_map": "Carte",
        "common_about": "À propos",
        "common_related": "Lié",
        "common_previous": "Précédent",
        "common_next": "Suivant",
        "common_all": "Tout",
        "common_open": "Ouvrir",
        "common_continue": "Continuer",
        "common_clear_all": "Tout effacer",
        "common_delete_account": "Supprimer mon compte",
        "hero_start_listening": "Commencer l’écoute",
        "hero_open_map": "Ouvrir la carte",
        "hero_saved": "Enregistré",
        "city_audio_stories": "histoires audio",
        "city_playlist_kicker": "Playlist audio",
        "city_playlist_title_tpl": "Histoires sur {city}",
        "city_playlist_sub_tpl": "Choisissez une histoire, appuyez sur Lecture et continuez pendant que vous explorez {city}.",
        "city_progress_note_tpl": "La progression du guide audio de {city} apparaît ici pendant la préparation.",
        "city_info": "Infos ville",
        "nearby_places": "Lieux à proximité",
        "top_places": "Lieux phares",
        "places_to_visit_tpl": "Lieux à visiter à {city}",
        "filter_museums": "Musées",
        "filter_landmarks": "Sites",
        "filter_churches": "Églises",
        "filter_parks": "Parcs",
        "filter_monuments": "Monuments",
        "filter_viewpoints": "Points de vue",
        "country_guide": "Guide du pays",
        "country_listen_tpl": "Écouter {country}",
        "country_story_sub": "Commencez par une vue d’ensemble du pays, puis continuez vers les villes et sites.",
        "country_facts_tpl": "Infos de voyage sur {country}",
        "country_popular_cities_tpl": "Villes populaires du guide audio {country}",
        "country_cities_kicker": "Villes à explorer",
        "country_city_guides_tpl": "Guides de villes de {country}",
        "country_top_places_title_tpl": "Lieux à écouter gratuitement en {country}",
        "country_top_places_sub_tpl": "Un lieu marquant de chaque ville sélectionnée en {country}, avec la ville sur chaque carte.",
        "country_about_kicker": "Guide de voyage du pays",
        "country_about_title_tpl": "Planifier {country} avec des histoires audio, villes et lieux",
        "more_countries": "Plus de pays",
        "continue_exploring_europe": "Continuer à explorer l’Europe",
        "blog_by": "Par",
        "blog_free_audio_guide": "Guide audio gratuit",
        "blog_community": "Communauté",
        "blog_useful": "Ce guide vous a-t-il été utile ?",
        "blog_like": "J’aime",
        "blog_rate_article": "Noter cet article",
        "blog_rate_article_aria": "Noter cet article de 1 à 5 étoiles",
        "blog_ratings": "notes",
        "account_title": "Mon compte",
        "account_kicker": "Compte SonicCity",
        "account_intro": "Gérez vos contacts, guides enregistrés et progression d’écoute.",
        "account_confirm_email": "Confirmez votre email pour sécuriser le compte et récupérer votre progression.",
        "account_resend_verification": "Renvoyer l’email de confirmation",
        "account_overview": "Aperçu",
        "account_profile": "Profil",
        "account_listening_history": "Historique d’écoute",
        "account_saved_guides": "Guides enregistrés",
        "account_contact_info": "Informations de contact",
        "account_email_status": "Statut email",
        "account_verified": "Vérifié",
        "account_pending_verification": "En attente",
        "account_preferred_language": "Langue préférée",
        "account_preferred_voice": "Voix préférée",
        "account_save_profile": "Enregistrer le profil",
        "account_privacy_note": "Supprimer le compte efface l’historique et les favoris, puis anonymise le profil.",
        "account_no_history": "Aucun historique d’écoute.",
        "account_no_saved": "Aucun guide enregistré.",
        "account_continue_listening": "Continuer l’écoute",
        "account_profile_summary": "Résumé du profil",
        "account_recently_listened": "Écoutés récemment",
        "account_start_story": "Lancez une histoire audio et elle apparaîtra ici.",
        "account_registered": "Inscription",
        "account_last_login": "Dernière connexion",
        "label_email": "Email",
        "label_name": "Nom",
        "label_country": "Pays",
        "label_language": "Langue",
        "label_voice": "Voix",
        "voice_preference_female": "Féminine",
        "voice_preference_male": "Masculine",
    },
    "es": {
        "common_home": "Inicio",
        "common_map": "Mapa",
        "common_about": "Acerca de",
        "common_related": "Relacionado",
        "common_previous": "Anterior",
        "common_next": "Siguiente",
        "common_all": "Todo",
        "common_open": "Abrir",
        "common_continue": "Continuar",
        "common_clear_all": "Borrar todo",
        "common_delete_account": "Eliminar mi cuenta",
        "hero_start_listening": "Empezar a escuchar",
        "hero_open_map": "Abrir mapa",
        "hero_saved": "Guardado",
        "city_audio_stories": "historias de audio",
        "city_playlist_kicker": "Playlist de audio",
        "city_playlist_title_tpl": "Historias sobre {city}",
        "city_playlist_sub_tpl": "Elige una historia, pulsa Play y sigue escuchando mientras exploras {city}.",
        "city_progress_note_tpl": "El progreso de la audioguía de {city} aparece aquí mientras se prepara.",
        "city_info": "Info de la ciudad",
        "nearby_places": "Lugares cercanos",
        "top_places": "Lugares destacados",
        "places_to_visit_tpl": "Lugares para visitar en {city}",
        "filter_museums": "Museos",
        "filter_landmarks": "Sitios destacados",
        "filter_churches": "Iglesias",
        "filter_parks": "Parques",
        "filter_monuments": "Monumentos",
        "filter_viewpoints": "Miradores",
        "country_guide": "Guía del país",
        "country_listen_tpl": "Escuchar {country}",
        "country_story_sub": "Empieza con una visión general del país y continúa con ciudades y lugares.",
        "country_facts_tpl": "Datos de viaje de {country}",
        "country_popular_cities_tpl": "Ciudades populares de la audioguía de {country}",
        "country_cities_kicker": "Ciudades para explorar",
        "country_city_guides_tpl": "Guías de ciudades de {country}",
        "country_top_places_title_tpl": "Lugares para escuchar gratis en {country}",
        "country_top_places_sub_tpl": "Un lugar destacado de cada ciudad seleccionada en {country}, con la ciudad en cada tarjeta.",
        "country_about_kicker": "Guía de viaje del país",
        "country_about_title_tpl": "Planifica {country} con historias de audio, ciudades y lugares",
        "more_countries": "Más países",
        "continue_exploring_europe": "Seguir explorando Europa",
        "blog_by": "Por",
        "blog_free_audio_guide": "Audioguía gratis",
        "blog_community": "Comunidad",
        "blog_useful": "¿Te resultó útil esta guía?",
        "blog_like": "Me gusta",
        "blog_rate_article": "Valorar este artículo",
        "blog_rate_article_aria": "Valorar este artículo de 1 a 5 estrellas",
        "blog_ratings": "valoraciones",
        "account_title": "Mi cuenta",
        "account_kicker": "Cuenta SonicCity",
        "account_intro": "Gestiona tus datos, guías guardadas y progreso de escucha.",
        "account_confirm_email": "Confirma tu email para proteger tu cuenta y recuperar tu progreso.",
        "account_resend_verification": "Reenviar email de verificación",
        "account_overview": "Resumen",
        "account_profile": "Perfil",
        "account_listening_history": "Historial de escucha",
        "account_saved_guides": "Guías guardadas",
        "account_contact_info": "Información de contacto",
        "account_email_status": "Estado del email",
        "account_verified": "Verificado",
        "account_pending_verification": "Pendiente",
        "account_preferred_language": "Idioma preferido",
        "account_preferred_voice": "Voz preferida",
        "account_save_profile": "Guardar perfil",
        "account_privacy_note": "Eliminar la cuenta borra historial y favoritos y anonimiza el usuario.",
        "account_no_history": "Aún no hay historial.",
        "account_no_saved": "Aún no hay guías guardadas.",
        "account_continue_listening": "Continuar escuchando",
        "account_profile_summary": "Resumen del perfil",
        "account_recently_listened": "Escuchado recientemente",
        "account_start_story": "Inicia cualquier historia de audio y aparecerá aquí.",
        "account_registered": "Registrado",
        "account_last_login": "Último acceso",
        "label_email": "Email",
        "label_name": "Nombre",
        "label_country": "País",
        "label_language": "Idioma",
        "label_voice": "Voz",
        "voice_preference_female": "Femenina",
        "voice_preference_male": "Masculina",
    },
    "it": {
        "common_home": "Home",
        "common_map": "Mappa",
        "common_about": "Info",
        "common_related": "Correlati",
        "common_previous": "Precedente",
        "common_next": "Successivo",
        "common_all": "Tutto",
        "common_open": "Apri",
        "common_continue": "Continua",
        "common_clear_all": "Cancella tutto",
        "common_delete_account": "Elimina il mio account",
        "hero_start_listening": "Inizia ad ascoltare",
        "hero_open_map": "Apri mappa",
        "hero_saved": "Salvato",
        "city_audio_stories": "storie audio",
        "city_playlist_kicker": "Playlist audio",
        "city_playlist_title_tpl": "Storie su {city}",
        "city_playlist_sub_tpl": "Scegli una storia, premi Play e continua ad ascoltare mentre esplori {city}.",
        "city_progress_note_tpl": "Il progresso della guida audio di {city} appare qui durante la preparazione.",
        "city_info": "Info città",
        "nearby_places": "Luoghi vicini",
        "top_places": "Luoghi principali",
        "places_to_visit_tpl": "Luoghi da visitare a {city}",
        "filter_museums": "Musei",
        "filter_landmarks": "Luoghi iconici",
        "filter_churches": "Chiese",
        "filter_parks": "Parchi",
        "filter_monuments": "Monumenti",
        "filter_viewpoints": "Belvedere",
        "country_guide": "Guida del paese",
        "country_listen_tpl": "Ascolta {country}",
        "country_story_sub": "Inizia con una panoramica del paese, poi passa a città e luoghi.",
        "country_facts_tpl": "Info viaggio su {country}",
        "country_popular_cities_tpl": "Città popolari della guida audio di {country}",
        "country_cities_kicker": "Città da esplorare",
        "country_city_guides_tpl": "Guide città di {country}",
        "country_top_places_title_tpl": "Luoghi da ascoltare gratis in {country}",
        "country_top_places_sub_tpl": "Un luogo notevole da ogni città selezionata in {country}, con la città su ogni card.",
        "country_about_kicker": "Guida viaggio del paese",
        "country_about_title_tpl": "Pianifica {country} con storie audio, città e luoghi",
        "more_countries": "Altri paesi",
        "continue_exploring_europe": "Continua a esplorare l’Europa",
        "blog_by": "Di",
        "blog_free_audio_guide": "Guida audio gratuita",
        "blog_community": "Community",
        "blog_useful": "Questa guida ti è stata utile?",
        "blog_like": "Mi piace",
        "blog_rate_article": "Valuta questo articolo",
        "blog_rate_article_aria": "Valuta questo articolo da 1 a 5 stelle",
        "blog_ratings": "valutazioni",
        "account_title": "Il mio account",
        "account_kicker": "Account SonicCity",
        "account_intro": "Gestisci contatti, guide salvate e progressi di ascolto.",
        "account_confirm_email": "Conferma l’email per proteggere l’account e recuperare i progressi.",
        "account_resend_verification": "Invia di nuovo l’email di verifica",
        "account_overview": "Panoramica",
        "account_profile": "Profilo",
        "account_listening_history": "Cronologia ascolti",
        "account_saved_guides": "Guide salvate",
        "account_contact_info": "Informazioni di contatto",
        "account_email_status": "Stato email",
        "account_verified": "Verificato",
        "account_pending_verification": "In attesa",
        "account_preferred_language": "Lingua preferita",
        "account_preferred_voice": "Voce preferita",
        "account_save_profile": "Salva profilo",
        "account_privacy_note": "Eliminare l’account rimuove cronologia e preferiti e anonimizza l’utente.",
        "account_no_history": "Nessuna cronologia di ascolto.",
        "account_no_saved": "Nessuna guida salvata.",
        "account_continue_listening": "Continua l’ascolto",
        "account_profile_summary": "Riepilogo profilo",
        "account_recently_listened": "Ascoltati di recente",
        "account_start_story": "Avvia una storia audio e apparirà qui.",
        "account_registered": "Registrato",
        "account_last_login": "Ultimo accesso",
        "label_email": "Email",
        "label_name": "Nome",
        "label_country": "Paese",
        "label_language": "Lingua",
        "label_voice": "Voce",
        "voice_preference_female": "Femminile",
        "voice_preference_male": "Maschile",
    },
    "ua": {
        "common_home": "Головна",
        "common_map": "Мапа",
        "common_about": "Про сторінку",
        "common_related": "Схоже",
        "common_previous": "Попереднє",
        "common_next": "Наступне",
        "common_all": "Усе",
        "common_open": "Відкрити",
        "common_continue": "Продовжити",
        "common_clear_all": "Очистити все",
        "common_delete_account": "Видалити акаунт",
        "hero_start_listening": "Почати слухати",
        "hero_open_map": "Відкрити мапу",
        "hero_saved": "Збережено",
        "city_audio_stories": "аудіоісторій",
        "city_playlist_kicker": "Аудіоплейлист",
        "city_playlist_title_tpl": "Історії: {city}",
        "city_playlist_sub_tpl": "Оберіть історію, натисніть Play і слухайте під час прогулянки {city}.",
        "city_progress_note_tpl": "Прогрес аудіогіда {city} зʼявиться тут під час підготовки історій.",
        "city_info": "Інформація про місто",
        "nearby_places": "Місця поруч",
        "top_places": "Топ місця",
        "places_to_visit_tpl": "Місця, які варто відвідати в {city}",
        "filter_museums": "Музеї",
        "filter_landmarks": "Памʼятки",
        "filter_churches": "Церкви",
        "filter_parks": "Парки",
        "filter_monuments": "Монументи",
        "filter_viewpoints": "Оглядові точки",
        "country_guide": "Гід країною",
        "country_listen_tpl": "Слухати гід: {country}",
        "country_story_sub": "Почніть з огляду країни, а потім переходьте до міст і місць.",
        "country_facts_tpl": "Туристична інформація про {country}",
        "country_popular_cities_tpl": "Популярні міста аудіогіда {country}",
        "country_cities_kicker": "Міста для дослідження",
        "country_city_guides_tpl": "Міські гіди {country}",
        "country_top_places_title_tpl": "Топ місця, які можна слухати безкоштовно в {country}",
        "country_top_places_sub_tpl": "По одному важливому місцю з кожного вибраного міста в {country}, з назвою міста на картці.",
        "country_about_kicker": "Туристичний гід країною",
        "country_about_title_tpl": "Плануйте {country} з аудіоісторіями, містами і місцями",
        "more_countries": "Більше країн",
        "continue_exploring_europe": "Продовжити досліджувати Європу",
        "blog_by": "Автор",
        "blog_free_audio_guide": "Безкоштовний аудіогід",
        "blog_community": "Спільнота",
        "blog_useful": "Чи був цей гід корисним?",
        "blog_like": "Лайк",
        "blog_rate_article": "Оцініть статтю",
        "blog_rate_article_aria": "Оцінити статтю від 1 до 5 зірок",
        "blog_ratings": "оцінок",
        "account_title": "Мій акаунт",
        "account_kicker": "Акаунт SonicCity",
        "account_intro": "Керуйте контактами, збереженими гідами і прогресом прослуховування.",
        "account_confirm_email": "Підтвердьте email, щоб захистити акаунт і відновлювати прогрес.",
        "account_resend_verification": "Надіслати лист підтвердження ще раз",
        "account_overview": "Огляд",
        "account_profile": "Профіль",
        "account_listening_history": "Історія прослуховування",
        "account_saved_guides": "Збережені гіди",
        "account_contact_info": "Контактна інформація",
        "account_email_status": "Статус email",
        "account_verified": "Підтверджено",
        "account_pending_verification": "Очікує підтвердження",
        "account_preferred_language": "Бажана мова",
        "account_preferred_voice": "Бажаний голос",
        "account_save_profile": "Зберегти профіль",
        "account_privacy_note": "Видалення акаунта прибере історію і збережені гіди, а запис користувача буде анонімізовано.",
        "account_no_history": "Історії прослуховування ще немає.",
        "account_no_saved": "Збережених гідів ще немає.",
        "account_continue_listening": "Продовжити слухати",
        "account_profile_summary": "Профіль",
        "account_recently_listened": "Нещодавно слухали",
        "account_start_story": "Запустіть будь-яку аудіоісторію, і вона зʼявиться тут.",
        "account_registered": "Реєстрація",
        "account_last_login": "Останній вхід",
        "label_email": "Email",
        "label_name": "Імʼя",
        "label_country": "Країна",
        "label_language": "Мова",
        "label_voice": "Голос",
        "voice_preference_female": "Жіночий",
        "voice_preference_male": "Чоловічий",
    },
    "de": {
        "common_home": "Startseite",
        "common_map": "Karte",
        "common_about": "Über",
        "common_related": "Ähnlich",
        "common_previous": "Zurück",
        "common_next": "Weiter",
        "common_all": "Alle",
        "common_open": "Öffnen",
        "common_continue": "Fortfahren",
        "common_clear_all": "Alles löschen",
        "common_delete_account": "Mein Konto löschen",
        "hero_start_listening": "Anhören starten",
        "hero_open_map": "Karte öffnen",
        "hero_saved": "Gespeichert",
        "city_audio_stories": "Audio-Geschichten",
        "city_playlist_kicker": "Audio-Playlist",
        "city_playlist_title_tpl": "Geschichten über {city}",
        "city_playlist_sub_tpl": "Wähle eine Geschichte, drücke Play und höre weiter, während du {city} erkundest.",
        "city_progress_note_tpl": "Der Fortschritt des {city}-Audioguides erscheint hier während der Vorbereitung.",
        "city_info": "Stadtinfo",
        "nearby_places": "Orte in der Nähe",
        "top_places": "Top-Orte",
        "places_to_visit_tpl": "Orte in {city}",
        "filter_museums": "Museen",
        "filter_landmarks": "Sehenswürdigkeiten",
        "filter_churches": "Kirchen",
        "filter_parks": "Parks",
        "filter_monuments": "Denkmäler",
        "filter_viewpoints": "Aussichtspunkte",
        "country_guide": "Länder-Guide",
        "country_listen_tpl": "{country} anhören",
        "country_story_sub": "Beginne mit einem Länderüberblick und fahre dann mit Städten und Orten fort.",
        "country_facts_tpl": "{country} Reiseinfos",
        "country_popular_cities_tpl": "Beliebte {country} Audio-Guide-Städte",
        "country_cities_kicker": "Städte entdecken",
        "country_city_guides_tpl": "{country} Stadtguides",
        "country_top_places_title_tpl": "Top-Orte kostenlos anhören in {country}",
        "country_top_places_sub_tpl": "Ein besonderer Ort aus jeder ausgewählten Stadt in {country}, mit Stadtname auf jeder Karte.",
        "country_about_kicker": "Länder-Reiseführer",
        "country_about_title_tpl": "{country} mit Audio-Geschichten, Städten und Orten planen",
        "more_countries": "Weitere Länder",
        "continue_exploring_europe": "Europa weiter erkunden",
        "blog_by": "Von",
        "blog_free_audio_guide": "Kostenloser Audioguide",
        "blog_community": "Community",
        "blog_useful": "War dieser Guide hilfreich?",
        "blog_like": "Gefällt mir",
        "blog_rate_article": "Artikel bewerten",
        "blog_rate_article_aria": "Artikel von 1 bis 5 Sternen bewerten",
        "blog_ratings": "Bewertungen",
        "account_title": "Mein Konto",
        "account_kicker": "SonicCity Konto",
        "account_intro": "Verwalte Kontaktdaten, gespeicherte Guides und Hörfortschritt.",
        "account_confirm_email": "Bestätige deine E-Mail, um dein Konto zu sichern und Fortschritt wiederherzustellen.",
        "account_resend_verification": "Bestätigungs-E-Mail erneut senden",
        "account_overview": "Übersicht",
        "account_profile": "Profil",
        "account_listening_history": "Hörverlauf",
        "account_saved_guides": "Gespeicherte Guides",
        "account_contact_info": "Kontaktinformationen",
        "account_email_status": "E-Mail-Status",
        "account_verified": "Bestätigt",
        "account_pending_verification": "Ausstehend",
        "account_preferred_language": "Bevorzugte Sprache",
        "account_preferred_voice": "Bevorzugte Stimme",
        "account_save_profile": "Profil speichern",
        "account_privacy_note": "Beim Löschen werden Verlauf und Favoriten entfernt und das Nutzerkonto anonymisiert.",
        "account_no_history": "Noch kein Hörverlauf.",
        "account_no_saved": "Noch keine gespeicherten Guides.",
        "account_continue_listening": "Weiterhören",
        "account_profile_summary": "Profilübersicht",
        "account_recently_listened": "Kürzlich gehört",
        "account_start_story": "Starte eine Audio-Geschichte, dann erscheint sie hier.",
        "account_registered": "Registriert",
        "account_last_login": "Letzter Login",
        "label_email": "E-Mail",
        "label_name": "Name",
        "label_country": "Land",
        "label_language": "Sprache",
        "label_voice": "Stimme",
        "voice_preference_female": "Weiblich",
        "voice_preference_male": "Männlich",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_page_values)

for _lang, _map_values in {
    "en": {
        "map_route": "Route",
        "map_close": "Close",
        "map_audio": "Audio map",
        "map_open_full": "Open full map",
        "map_use_location": "Use my location",
        "map_select_place_play": "Select a place and tap Play.",
        "map_clear_route": "Clear route",
        "map_change_panel": "Change map panel height",
        "map_places_near_tpl": "{city} places near you",
    },
    "fr": {
        "map_route": "Itinéraire",
        "map_close": "Fermer",
        "map_audio": "Carte audio",
        "map_open_full": "Ouvrir la carte",
        "map_use_location": "Utiliser ma position",
        "map_select_place_play": "Sélectionnez un lieu et touchez Lecture.",
        "map_clear_route": "Effacer l’itinéraire",
        "map_change_panel": "Modifier la hauteur du panneau carte",
        "map_places_near_tpl": "Lieux près de {city}",
    },
    "es": {
        "map_route": "Ruta",
        "map_close": "Cerrar",
        "map_audio": "Mapa de audio",
        "map_open_full": "Abrir mapa completo",
        "map_use_location": "Usar mi ubicación",
        "map_select_place_play": "Selecciona un lugar y toca Play.",
        "map_clear_route": "Borrar ruta",
        "map_change_panel": "Cambiar altura del panel del mapa",
        "map_places_near_tpl": "Lugares cerca de {city}",
    },
    "it": {
        "map_route": "Percorso",
        "map_close": "Chiudi",
        "map_audio": "Mappa audio",
        "map_open_full": "Apri mappa completa",
        "map_use_location": "Usa la mia posizione",
        "map_select_place_play": "Seleziona un luogo e tocca Play.",
        "map_clear_route": "Cancella percorso",
        "map_change_panel": "Cambia altezza pannello mappa",
        "map_places_near_tpl": "Luoghi vicino a {city}",
    },
    "ua": {
        "map_route": "Маршрут",
        "map_close": "Закрити",
        "map_audio": "Аудіомапа",
        "map_open_full": "Відкрити повну мапу",
        "map_use_location": "Моя локація",
        "map_select_place_play": "Оберіть місце і натисніть Play.",
        "map_clear_route": "Очистити маршрут",
        "map_change_panel": "Змінити висоту панелі мапи",
        "map_places_near_tpl": "Місця поруч із {city}",
    },
    "de": {
        "map_route": "Route",
        "map_close": "Schließen",
        "map_audio": "Audiokarte",
        "map_open_full": "Vollbildkarte öffnen",
        "map_use_location": "Meinen Standort nutzen",
        "map_select_place_play": "Wähle einen Ort und tippe auf Play.",
        "map_clear_route": "Route löschen",
        "map_change_panel": "Höhe des Kartenpanels ändern",
        "map_places_near_tpl": "Orte nahe {city}",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_map_values)

for _lang, _extra_values in {
    "en": {
        "home_places_around_you": "Places around you",
        "home_my_location": "My location",
        "home_show_places": "Show places",
        "home_you_are_here": "You are here",
        "home_central_market": "Central Market",
        "home_ready_walk": "Landmark · 8 min walk · ready to listen",
        "home_now_near": "Now near",
        "home_auto_detect": "Auto-detect nearby guides",
        "home_nearby_placeholder": "Nearby cities will appear here",
        "home_topics_count": "24 topics",
        "home_first_story_ready": "First story ready",
        "home_open_valencia_guide": "Open Valencia Audio Guide",
        "home_pick_story_sub": "Pick history, landmarks or local culture.",
        "home_player_stays_sub": "The player stays with you while you explore.",
        "home_use_cases": "Use cases",
        "home_use_cases_title": "Made for road trips and city walks",
        "home_for_driving": "For driving",
        "home_detects_nearby": "Detects nearby cities",
        "home_updates_move": "Updates while you move",
        "home_keeps_playing": "Keeps playing between pages",
        "home_try_driving": "Try driving mode",
        "home_for_walking": "For walking",
        "home_shows_landmarks": "Shows landmarks nearby",
        "home_listen_places": "Listen to places around you",
        "home_use_filters": "Use filters for museums, churches, parks",
        "home_explore_walking": "Explore walking mode",
        "home_languages_title": "Listen in your language",
        "home_languages_sub": "Choose the language for both text and audio.",
        "home_audio_supported": "Audio supported",
        "home_popular_cities": "Popular cities",
        "home_city_guides_title": "City guides for your next trip",
        "home_view_all_cities": "View all cities",
        "home_iconic_places": "Iconic places",
        "home_landmarks_title": "Landmarks worth hearing about",
        "home_view_all_places": "View all places",
        "home_ready_to_listen": "Ready to listen",
        "home_search_sub": "Search a city or landmark, choose a free audio story, then keep the player with you.",
        "home_search_city_landmark": "Search city or landmark",
        "home_near_me": "Near me",
        "home_landmarks": "Landmarks",
        "home_audio_ready_short": "Audio ready",
        "home_popular_searches": "Popular searches",
        "home_open_explore": "Open explore",
        "home_europe_intro": "Start with a country, open a city Audio Guide, then follow top places on the map. Built for travelers who want stories, not a wall of text.",
        "home_choose_country": "Choose a country",
        "home_country_group_west": "Western Europe",
        "home_country_group_south": "Southern Europe",
        "home_country_group_central": "Central Europe",
        "home_country_group_north": "Northern Europe",
        "home_country_group_east": "Eastern Europe & Balkans",
        "home_why_text": "A GPS audio guide keeps stories connected to the place in front of you. Drive through a region, walk across a city or open a landmark page and keep listening without digging through long text.",
        "home_no_read": "No need to read while moving",
        "home_location_stories": "Stories connected to your location",
        "home_road_walks": "Useful for road trips and walks",
        "home_one_app": "Cities and landmarks in one app",
        "home_seo_kicker": "GPS Audio Guide",
        "home_seo_title": "GPS Audio Guide for cities and landmarks",
        "home_seo_p1": "SonicCity is a map-based Audio Guide for travellers who want useful stories without stopping to read. Open the live guide, allow GPS and the page can show cities, landmarks and places around you.",
        "home_seo_p2": "When you choose a city or place, the guide organises the content into short audio stories such as history, culture, landmarks and practical context. The first available story can be played while the rest of the guide is prepared.",
        "home_seo_p3": "Audio guides are available in English, French, Spanish, Italian, Ukrainian and German. You can use the product before a trip to explore cities manually, or during a journey with the map and player always close together.",
        "home_final_title": "Start exploring with your Audio Guide",
        "home_final_sub": "Use GPS to discover stories nearby or choose a city manually.",
        "home_start_gps": "Start with GPS",
        "home_explore_cities": "Explore cities",
        "home_meta_title": "Free GPS Audio Guide for Cities and Landmarks | SonicCity",
        "home_meta_desc": "Listen free with a GPS Audio Guide for cities, landmarks and road trips. Open the map, find nearby places and keep audio stories playing while you travel.",
        "home_featured_schema": "Featured SonicCity audio guides",
        "home_benefit_gps": "GPS detects cities and landmarks around you.",
        "home_benefit_audio": "Listen while you drive, walk or explore.",
        "home_benefit_languages": "English, French, Spanish, Italian, Ukrainian and German.",
        "home_benefit_europe": "City and landmark guides across supported countries.",
        "home_city_valencia_desc": "Mediterranean streets, markets, gardens and futuristic architecture in one city guide.",
        "home_city_barcelona_desc": "Gaudi landmarks, Gothic streets, sea views and local stories for walking or planning.",
        "home_city_rome_desc": "Ancient ruins, churches, fountains and neighbourhood stories for a slower city walk.",
        "home_city_paris_desc": "Museums, river walks, monuments and cultural stories connected to the map.",
        "home_city_vienna_desc": "Palaces, music, cafes and imperial landmarks with concise audio stories.",
        "home_city_prague_desc": "Bridges, castle views, old town stories and landmarks ready for walking mode.",
        "home_place_valencia_cathedral_desc": "A compact story about the cathedral, old town and surrounding squares.",
        "home_place_sagrada_familia_desc": "Architecture, symbols and city context around Barcelona's most famous basilica.",
        "home_place_colosseum_desc": "Listen to the arena's history before or while walking nearby.",
        "home_place_eiffel_tower_desc": "A short audio guide for the tower, river views and surrounding area.",
        "home_place_schonbrunn_desc": "Imperial rooms, gardens and stories placed on the city map.",
        "home_place_charles_bridge_desc": "A walkable story about Prague's bridge, views and old town routes.",
        "place_hero_title_tpl": "{place} Audio Guide - Listen for Free",
        "place_hero_sub_tpl": "Listen free to a short guide for {place} in {city}, {country}, with a map and nearby landmarks.",
        "place_progress_note_tpl": "{place} Audio Guide progress appears here while stories are prepared.",
        "place_playlist_title_tpl": "Stories about {place}",
        "place_playlist_sub": "Short audio stories keep the guide easy to listen to while you are already at the place.",
        "place_about_title_tpl": "About {place}",
        "place_about_text_tpl": "The {place} Audio Guide lets travelers hear a focused landmark story and continue playback while opening nearby places or returning to the {city} city guide.",
        "place_practical_info": "Practical info",
        "place_more_places_tpl": "More places to visit in {city}",
        "place_open_city_guide": "Open city guide",
        "place_nearby_text_tpl": "Open another nearby place guide in {city}.",
        "place_nearby_meta": "Nearby place",
        "place_show_on_map": "Show on map",
        "place_select_landmark": "Select a landmark",
        "place_select_landmark_sub": "Tap a marker to see the photo, play audio or build a route from your location.",
        "place_search_places": "Search places",
        "place_search_place": "Search place",
        "place_audio_ready_zero": "Audio ready: 0 / 8 stories",
        "common_details": "Details",
        "common_play": "Play",
        "common_listen": "Listen",
        "common_category": "Category",
    },
    "ua": {
        "home_places_around_you": "Місця поруч",
        "home_my_location": "Моя локація",
        "home_show_places": "Показати місця",
        "home_you_are_here": "Ви тут",
        "home_central_market": "Центральний ринок",
        "home_ready_walk": "Памʼятка · 8 хв пішки · готово до прослуховування",
        "home_now_near": "Зараз поруч",
        "home_auto_detect": "Автоматично знаходити гіди поруч",
        "home_nearby_placeholder": "Міста поруч зʼявляться тут",
        "home_topics_count": "24 теми",
        "home_first_story_ready": "Перша історія готова",
        "home_open_valencia_guide": "Відкрити аудіогід Валенсії",
        "home_pick_story_sub": "Оберіть історію, памʼятки або місцеву культуру.",
        "home_player_stays_sub": "Плеєр залишається з вами під час дослідження.",
        "home_use_cases": "Сценарії",
        "home_use_cases_title": "Для автоподорожей і міських прогулянок",
        "home_for_driving": "Для поїздки",
        "home_detects_nearby": "Знаходить міста поруч",
        "home_updates_move": "Оновлюється під час руху",
        "home_keeps_playing": "Грає між сторінками",
        "home_try_driving": "Спробувати в дорозі",
        "home_for_walking": "Для прогулянки",
        "home_shows_landmarks": "Показує памʼятки поруч",
        "home_listen_places": "Слухайте місця навколо",
        "home_use_filters": "Фільтри для музеїв, церков і парків",
        "home_explore_walking": "Дослідити режим прогулянки",
        "home_languages_title": "Слухайте своєю мовою",
        "home_languages_sub": "Оберіть мову для тексту й аудіо.",
        "home_audio_supported": "Аудіо підтримується",
        "home_popular_cities": "Популярні міста",
        "home_city_guides_title": "Міські гіди для наступної подорожі",
        "home_view_all_cities": "Усі міста",
        "home_iconic_places": "Відомі місця",
        "home_landmarks_title": "Памʼятки, які варто послухати",
        "home_view_all_places": "Усі місця",
        "home_ready_to_listen": "Готово слухати",
        "home_search_sub": "Знайдіть місто або памʼятку, оберіть безкоштовну аудіоісторію і слухайте далі.",
        "home_search_city_landmark": "Пошук міста або памʼятки",
        "home_near_me": "Поруч",
        "home_landmarks": "Памʼятки",
        "home_audio_ready_short": "Аудіо готове",
        "home_popular_searches": "Популярні пошуки",
        "home_open_explore": "Відкрити пошук",
        "home_europe_intro": "Почніть з країни, відкрийте міський аудіогід і переходьте до топ місць на мапі. Для мандрівників, яким потрібні історії, а не стіна тексту.",
        "home_choose_country": "Обрати країну",
        "home_country_group_west": "Західна Європа",
        "home_country_group_south": "Південна Європа",
        "home_country_group_central": "Центральна Європа",
        "home_country_group_north": "Північна Європа",
        "home_country_group_east": "Східна Європа і Балкани",
        "home_why_text": "GPS-аудіогід привʼязує історії до місця перед вами. Їдьте регіоном, гуляйте містом або відкрийте сторінку памʼятки і слухайте без довгого читання.",
        "home_no_read": "Не потрібно читати в русі",
        "home_location_stories": "Історії привʼязані до локації",
        "home_road_walks": "Корисно для поїздок і прогулянок",
        "home_one_app": "Міста і памʼятки в одному сервісі",
        "home_seo_kicker": "GPS-аудіогід",
        "home_seo_title": "GPS-аудіогід для міст і памʼяток",
        "home_seo_p1": "SonicCity — це аудіогід на мапі для мандрівників, які хочуть корисні історії без зупинки на читання. Відкрийте live guide, дозвольте GPS, і сторінка покаже міста, памʼятки та місця поруч.",
        "home_seo_p2": "Коли ви обираєте місто або місце, гід організовує контент у короткі аудіоісторії: історія, культура, памʼятки і практичний контекст.",
        "home_seo_p3": "Аудіогіди доступні англійською, французькою, іспанською, італійською, українською та німецькою. Використовуйте сервіс до подорожі або під час маршруту.",
        "home_final_title": "Почніть досліджувати з аудіогідом",
        "home_final_sub": "Увімкніть GPS, щоб знаходити історії поруч, або оберіть місто вручну.",
        "home_start_gps": "Почати з GPS",
        "home_explore_cities": "Дослідити міста",
        "home_meta_title": "Безкоштовний GPS-аудіогід містами і памʼятками | SonicCity",
        "home_meta_desc": "Слухайте безкоштовний GPS-аудіогід для міст, памʼяток і подорожей. Відкрийте мапу, знайдіть місця поруч і слухайте аудіоісторії в дорозі.",
        "home_featured_schema": "Вибрані аудіогіди SonicCity",
        "home_benefit_gps": "GPS знаходить міста і памʼятки поруч.",
        "home_benefit_audio": "Слухайте під час поїздки, прогулянки або дослідження.",
        "home_benefit_languages": "Англійська, французька, іспанська, італійська, українська та німецька.",
        "home_benefit_europe": "Міські та landmark-гід сторінки в підтримуваних країнах.",
        "home_city_valencia_desc": "Середземноморські вулиці, ринки, сади і футуристична архітектура в одному міському гіді.",
        "home_city_barcelona_desc": "Гауді, готичні квартали, море і локальні історії для прогулянки або планування.",
        "home_city_rome_desc": "Руїни, церкви, фонтани і райони Рима для повільної міської прогулянки.",
        "home_city_paris_desc": "Музеї, набережні, монументи і культурні історії, привʼязані до мапи.",
        "home_city_vienna_desc": "Палаци, музика, кавʼярні та імперські памʼятки у коротких аудіоісторіях.",
        "home_city_prague_desc": "Мости, замок, старе місто і памʼятки для режиму прогулянки.",
        "home_place_valencia_cathedral_desc": "Коротка історія про собор, старе місто і площі навколо.",
        "home_place_sagrada_familia_desc": "Архітектура, символи і контекст міста навколо найвідомішої базиліки Барселони.",
        "home_place_colosseum_desc": "Послухайте історію арени до візиту або під час прогулянки поруч.",
        "home_place_eiffel_tower_desc": "Короткий аудіогід про вежу, річкові краєвиди і район навколо.",
        "home_place_schonbrunn_desc": "Імперські зали, сади і історії, розміщені на мапі міста.",
        "home_place_charles_bridge_desc": "Прогулянкова історія про міст, краєвиди і маршрути старого міста Праги.",
        "place_hero_title_tpl": "Аудіогід {place} — слухати безкоштовно",
        "place_hero_sub_tpl": "Слухайте безкоштовний короткий гід про {place} у {city}, {country}, з мапою і місцями поруч.",
        "place_progress_note_tpl": "Прогрес аудіогіда {place} зʼявиться тут під час підготовки історій.",
        "place_playlist_title_tpl": "Історії про {place}",
        "place_playlist_sub": "Короткі аудіоісторії зручно слухати, коли ви вже біля місця.",
        "place_about_title_tpl": "Про {place}",
        "place_about_text_tpl": "Аудіогід {place} дає сфокусовану історію памʼятки і дозволяє слухати далі, відкриваючи місця поруч або повертаючись до гіда {city}.",
        "place_practical_info": "Практична інформація",
        "place_more_places_tpl": "Ще місця у {city}",
        "place_open_city_guide": "Відкрити міський гід",
        "place_nearby_text_tpl": "Відкрийте ще один гід місця поруч у {city}.",
        "place_nearby_meta": "Місце поруч",
        "place_show_on_map": "Показати на мапі",
        "place_select_landmark": "Оберіть памʼятку",
        "place_select_landmark_sub": "Натисніть маркер, щоб побачити фото, увімкнути аудіо або побудувати маршрут.",
        "place_search_places": "Пошук місць",
        "place_search_place": "Пошук місця",
        "place_audio_ready_zero": "Аудіо готове: 0 / 8 історій",
        "common_details": "Деталі",
        "common_play": "Play",
        "common_listen": "Слухати",
        "common_category": "Категорія",
    },
    "fr": {
        "home_places_around_you": "Lieux autour de vous",
        "home_my_location": "Ma position",
        "home_show_places": "Afficher les lieux",
        "home_you_are_here": "Vous êtes ici",
        "home_central_market": "Marché central",
        "home_ready_walk": "Monument · 8 min à pied · prêt à écouter",
        "home_now_near": "À proximité",
        "home_auto_detect": "Détecter automatiquement les guides proches",
        "home_nearby_placeholder": "Les villes proches apparaîtront ici",
        "home_topics_count": "24 sujets",
        "home_first_story_ready": "Premier récit prêt",
        "home_open_valencia_guide": "Ouvrir le guide audio de Valence",
        "home_pick_story_sub": "Choisissez l’histoire, les monuments ou la culture locale.",
        "home_player_stays_sub": "Le lecteur reste avec vous pendant l’exploration.",
        "home_use_cases": "Usages",
        "home_use_cases_title": "Pour les road trips et les promenades urbaines",
        "home_for_driving": "En voiture",
        "home_detects_nearby": "Détecte les villes proches",
        "home_updates_move": "Se met à jour en mouvement",
        "home_keeps_playing": "Continue entre les pages",
        "home_try_driving": "Essayer en voiture",
        "home_for_walking": "À pied",
        "home_shows_landmarks": "Affiche les monuments proches",
        "home_listen_places": "Écoutez les lieux autour de vous",
        "home_use_filters": "Filtres pour musées, églises et parcs",
        "home_explore_walking": "Explorer le mode marche",
        "home_languages_title": "Écoutez dans votre langue",
        "home_languages_sub": "Choisissez la langue du texte et de l’audio.",
        "home_audio_supported": "Audio disponible",
        "home_popular_cities": "Villes populaires",
        "home_city_guides_title": "Guides de villes pour votre prochain voyage",
        "home_view_all_cities": "Voir toutes les villes",
        "home_iconic_places": "Lieux iconiques",
        "home_landmarks_title": "Monuments à écouter",
        "home_view_all_places": "Voir tous les lieux",
        "home_ready_to_listen": "Prêt à écouter",
        "home_search_sub": "Cherchez une ville ou un monument, choisissez une histoire audio gratuite et gardez le lecteur avec vous.",
        "home_search_city_landmark": "Rechercher une ville ou un monument",
        "home_near_me": "Près de moi",
        "home_landmarks": "Monuments",
        "home_audio_ready_short": "Audio prêt",
        "home_popular_searches": "Recherches populaires",
        "home_open_explore": "Ouvrir l’exploration",
        "home_europe_intro": "Commencez par un pays, ouvrez un guide audio de ville, puis suivez les meilleurs lieux sur la carte.",
        "home_choose_country": "Choisir un pays",
        "home_country_group_west": "Europe de l’Ouest",
        "home_country_group_south": "Europe du Sud",
        "home_country_group_central": "Europe centrale",
        "home_country_group_north": "Europe du Nord",
        "home_country_group_east": "Europe de l’Est et Balkans",
        "home_why_text": "Un guide audio GPS relie les histoires au lieu devant vous. Traversez une région, parcourez une ville ou ouvrez un monument et continuez à écouter.",
        "home_no_read": "Pas besoin de lire en mouvement",
        "home_location_stories": "Histoires liées à votre position",
        "home_road_walks": "Utile en voiture et à pied",
        "home_one_app": "Villes et monuments dans une app",
        "home_seo_kicker": "Guide audio GPS",
        "home_seo_title": "Guide audio GPS pour villes et monuments",
        "home_seo_p1": "SonicCity est un guide audio cartographique pour les voyageurs qui veulent des histoires utiles sans s’arrêter pour lire.",
        "home_seo_p2": "Chaque ville ou lieu devient une série de courts récits audio : histoire, culture, monuments et contexte pratique.",
        "home_seo_p3": "Les guides audio sont disponibles en anglais, français, espagnol, italien, ukrainien et allemand.",
        "home_final_title": "Commencez à explorer avec votre guide audio",
        "home_final_sub": "Utilisez le GPS pour découvrir les histoires proches ou choisissez une ville.",
        "home_start_gps": "Commencer avec le GPS",
        "home_explore_cities": "Explorer les villes",
        "home_meta_title": "Guide audio GPS gratuit pour villes et monuments | SonicCity",
        "home_meta_desc": "Écoutez gratuitement un guide audio GPS pour villes, monuments et voyages. Ouvrez la carte, trouvez les lieux proches et gardez les récits audio actifs.",
        "home_featured_schema": "Guides audio SonicCity en vedette",
        "home_benefit_gps": "Le GPS détecte les villes et monuments autour de vous.",
        "home_benefit_audio": "Écoutez en voiture, à pied ou en exploration.",
        "home_benefit_languages": "Anglais, français, espagnol, italien, ukrainien et allemand.",
        "home_benefit_europe": "Guides de villes et monuments dans les pays pris en charge.",
        "home_city_valencia_desc": "Rues méditerranéennes, marchés, jardins et architecture futuriste dans un guide urbain.",
        "home_city_barcelona_desc": "Gaudi, rues gothiques, vues sur mer et récits locaux pour marcher ou planifier.",
        "home_city_rome_desc": "Ruines antiques, églises, fontaines et quartiers pour une promenade lente.",
        "home_city_paris_desc": "Musées, quais, monuments et récits culturels reliés à la carte.",
        "home_city_vienna_desc": "Palais, musique, cafés et monuments impériaux en récits courts.",
        "home_city_prague_desc": "Ponts, château, vieille ville et monuments prêts pour le mode marche.",
        "home_place_valencia_cathedral_desc": "Un récit compact sur la cathédrale, la vieille ville et les places voisines.",
        "home_place_sagrada_familia_desc": "Architecture, symboles et contexte urbain autour de la basilique de Barcelone.",
        "home_place_colosseum_desc": "Écoutez l’histoire de l’arène avant ou pendant la visite.",
        "home_place_eiffel_tower_desc": "Un court guide audio sur la tour, la Seine et les environs.",
        "home_place_schonbrunn_desc": "Salles impériales, jardins et récits placés sur la carte.",
        "home_place_charles_bridge_desc": "Une histoire à parcourir sur le pont, les vues et la vieille ville.",
        "place_hero_title_tpl": "Guide audio de {place} - écouter gratuitement",
        "place_hero_sub_tpl": "Écoutez gratuitement un court guide de {place} à {city}, {country}, avec carte et lieux proches.",
        "place_progress_note_tpl": "La progression du guide de {place} apparaît ici pendant la préparation.",
        "place_playlist_title_tpl": "Histoires sur {place}",
        "place_playlist_sub": "De courts récits audio faciles à écouter lorsque vous êtes déjà sur place.",
        "place_about_title_tpl": "À propos de {place}",
        "place_about_text_tpl": "Le guide audio de {place} propose une histoire ciblée du monument et continue pendant que vous ouvrez les lieux proches ou revenez au guide de {city}.",
        "place_practical_info": "Infos pratiques",
        "place_more_places_tpl": "Autres lieux à visiter à {city}",
        "place_open_city_guide": "Ouvrir le guide de la ville",
        "place_nearby_text_tpl": "Ouvrez un autre guide de lieu proche à {city}.",
        "place_nearby_meta": "Lieu proche",
        "place_show_on_map": "Afficher sur la carte",
        "place_select_landmark": "Sélectionnez un monument",
        "place_select_landmark_sub": "Touchez un marqueur pour voir la photo, lancer l’audio ou créer un itinéraire.",
        "place_search_places": "Rechercher des lieux",
        "place_search_place": "Rechercher un lieu",
        "place_audio_ready_zero": "Audio prêt : 0 / 8 récits",
        "common_details": "Détails",
        "common_play": "Lecture",
        "common_listen": "Écouter",
        "common_category": "Catégorie",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_extra_values)

for _target_lang in ("es", "it", "de"):
    _fallback_extra = dict(ADDITIONAL_UI_TRANSLATIONS.get("en") or {})
    _fallback_extra.update(ADDITIONAL_UI_TRANSLATIONS.get(_target_lang) or {})
    ADDITIONAL_UI_TRANSLATIONS[_target_lang] = _fallback_extra

for _lang, _override_values in {
    "es": {
        "home_places_around_you": "Lugares a tu alrededor",
        "home_my_location": "Mi ubicación",
        "home_show_places": "Mostrar lugares",
        "home_you_are_here": "Estás aquí",
        "home_central_market": "Mercado Central",
        "home_ready_walk": "Lugar de interés · 8 min a pie · listo para escuchar",
        "home_now_near": "Ahora cerca",
        "home_auto_detect": "Detectar guías cercanas automáticamente",
        "home_nearby_placeholder": "Las ciudades cercanas aparecerán aquí",
        "home_topics_count": "24 temas",
        "home_first_story_ready": "Primera historia lista",
        "home_open_valencia_guide": "Abrir la audioguía de Valencia",
        "home_pick_story_sub": "Elige historia, monumentos o cultura local.",
        "home_player_stays_sub": "El reproductor sigue contigo mientras exploras.",
        "home_use_cases": "Casos de uso",
        "home_use_cases_title": "Hecho para viajes por carretera y paseos urbanos",
        "home_for_driving": "Para conducir",
        "home_detects_nearby": "Detecta ciudades cercanas",
        "home_updates_move": "Se actualiza mientras te mueves",
        "home_keeps_playing": "Sigue sonando entre páginas",
        "home_try_driving": "Probar modo conducción",
        "home_for_walking": "Para caminar",
        "home_shows_landmarks": "Muestra lugares cercanos",
        "home_listen_places": "Escucha lugares a tu alrededor",
        "home_use_filters": "Filtros para museos, iglesias y parques",
        "home_explore_walking": "Explorar modo paseo",
        "home_languages_title": "Escucha en tu idioma",
        "home_languages_sub": "Elige el idioma del texto y del audio.",
        "home_audio_supported": "Audio disponible",
        "home_popular_cities": "Ciudades populares",
        "home_city_guides_title": "Guías de ciudades para tu próximo viaje",
        "home_view_all_cities": "Ver todas las ciudades",
        "home_iconic_places": "Lugares icónicos",
        "home_landmarks_title": "Lugares que vale la pena escuchar",
        "home_view_all_places": "Ver todos los lugares",
        "home_ready_to_listen": "Listo para escuchar",
        "home_search_sub": "Busca una ciudad o lugar, elige una historia de audio gratis y mantén el reproductor contigo.",
        "home_search_city_landmark": "Buscar ciudad o lugar",
        "home_near_me": "Cerca de mí",
        "home_landmarks": "Lugares de interés",
        "home_audio_ready_short": "Audio listo",
        "home_popular_searches": "Búsquedas populares",
        "home_open_explore": "Abrir explorador",
        "home_europe_intro": "Empieza por un país, abre una audioguía de ciudad y sigue los lugares destacados en el mapa.",
        "home_choose_country": "Elegir país",
        "home_country_group_west": "Europa occidental",
        "home_country_group_south": "Europa meridional",
        "home_country_group_central": "Europa central",
        "home_country_group_north": "Europa del norte",
        "home_country_group_east": "Europa oriental y Balcanes",
        "home_why_text": "Una audioguía GPS conecta las historias con el lugar frente a ti. Conduce por una región, camina por una ciudad o abre un monumento y sigue escuchando.",
        "home_no_read": "Sin leer mientras te mueves",
        "home_location_stories": "Historias conectadas a tu ubicación",
        "home_road_walks": "Útil para viajes y paseos",
        "home_one_app": "Ciudades y monumentos en una app",
        "home_seo_kicker": "Audioguía GPS",
        "home_seo_title": "Audioguía GPS para ciudades y monumentos",
        "home_seo_p1": "SonicCity es una audioguía basada en mapa para viajeros que quieren historias útiles sin detenerse a leer.",
        "home_seo_p2": "Cada ciudad o lugar se organiza en historias de audio cortas sobre historia, cultura, monumentos y contexto práctico.",
        "home_seo_p3": "Las audioguías están disponibles en inglés, francés, español, italiano, ucraniano y alemán.",
        "home_final_title": "Empieza a explorar con tu audioguía",
        "home_final_sub": "Usa GPS para descubrir historias cercanas o elige una ciudad manualmente.",
        "home_start_gps": "Empezar con GPS",
        "home_explore_cities": "Explorar ciudades",
        "home_meta_title": "Audioguía GPS gratis para ciudades y monumentos | SonicCity",
        "home_meta_desc": "Escucha gratis una audioguía GPS para ciudades, monumentos y viajes. Abre el mapa, encuentra lugares cercanos y mantiene las historias de audio activas.",
        "home_featured_schema": "Audioguías destacadas de SonicCity",
        "home_benefit_gps": "El GPS detecta ciudades y monumentos a tu alrededor.",
        "home_benefit_audio": "Escucha mientras conduces, caminas o exploras.",
        "home_benefit_languages": "Inglés, francés, español, italiano, ucraniano y alemán.",
        "home_benefit_europe": "Guías de ciudades y monumentos en países compatibles.",
        "home_city_valencia_desc": "Calles mediterráneas, mercados, jardines y arquitectura futurista en una guía urbana.",
        "home_city_barcelona_desc": "Gaudi, calles góticas, vistas al mar e historias locales para caminar o planificar.",
        "home_city_rome_desc": "Ruinas antiguas, iglesias, fuentes y barrios para un paseo lento.",
        "home_city_paris_desc": "Museos, riberas, monumentos e historias culturales conectadas al mapa.",
        "home_city_vienna_desc": "Palacios, música, cafés y monumentos imperiales en historias breves.",
        "home_city_prague_desc": "Puentes, castillo, casco antiguo y lugares listos para modo paseo.",
        "home_place_valencia_cathedral_desc": "Una historia compacta sobre la catedral, el casco antiguo y las plazas cercanas.",
        "home_place_sagrada_familia_desc": "Arquitectura, símbolos y contexto urbano alrededor de la basílica más famosa de Barcelona.",
        "home_place_colosseum_desc": "Escucha la historia de la arena antes o durante la visita.",
        "home_place_eiffel_tower_desc": "Una guía breve sobre la torre, el río y los alrededores.",
        "home_place_schonbrunn_desc": "Salas imperiales, jardines e historias situadas en el mapa.",
        "home_place_charles_bridge_desc": "Una historia caminable sobre el puente, las vistas y la ciudad vieja.",
        "place_hero_title_tpl": "Audioguía de {place} - escuchar gratis",
        "place_hero_sub_tpl": "Escucha gratis una guía breve de {place} en {city}, {country}, con mapa y lugares cercanos.",
        "place_progress_note_tpl": "El progreso de la guía de {place} aparecerá aquí mientras se preparan las historias.",
        "place_playlist_title_tpl": "Historias sobre {place}",
        "place_playlist_sub": "Historias de audio cortas para escuchar fácilmente cuando ya estás en el lugar.",
        "place_about_title_tpl": "Sobre {place}",
        "place_about_text_tpl": "La audioguía de {place} ofrece una historia centrada del lugar y continúa mientras abres lugares cercanos o vuelves a la guía de {city}.",
        "place_practical_info": "Información práctica",
        "place_more_places_tpl": "Más lugares para visitar en {city}",
        "place_open_city_guide": "Abrir guía de la ciudad",
        "place_nearby_text_tpl": "Abre otra guía de un lugar cercano en {city}.",
        "place_nearby_meta": "Lugar cercano",
        "place_show_on_map": "Mostrar en el mapa",
        "place_select_landmark": "Selecciona un lugar",
        "place_select_landmark_sub": "Toca un marcador para ver la foto, reproducir audio o crear una ruta.",
        "place_search_places": "Buscar lugares",
        "place_search_place": "Buscar lugar",
        "place_audio_ready_zero": "Audio listo: 0 / 8 historias",
        "common_details": "Detalles",
        "common_play": "Reproducir",
        "common_listen": "Escuchar",
        "common_category": "Categoría",
    },
    "it": {
        "home_places_around_you": "Luoghi intorno a te",
        "home_my_location": "La mia posizione",
        "home_show_places": "Mostra luoghi",
        "home_you_are_here": "Sei qui",
        "home_central_market": "Mercato Centrale",
        "home_ready_walk": "Luogo d’interesse · 8 min a piedi · pronto da ascoltare",
        "home_now_near": "Ora vicino",
        "home_auto_detect": "Rileva automaticamente le guide vicine",
        "home_nearby_placeholder": "Le città vicine appariranno qui",
        "home_topics_count": "24 argomenti",
        "home_first_story_ready": "Prima storia pronta",
        "home_open_valencia_guide": "Apri audioguida di Valencia",
        "home_pick_story_sub": "Scegli storia, monumenti o cultura locale.",
        "home_player_stays_sub": "Il player resta con te mentre esplori.",
        "home_use_cases": "Casi d’uso",
        "home_use_cases_title": "Creato per road trip e passeggiate in città",
        "home_for_driving": "Per guidare",
        "home_detects_nearby": "Rileva città vicine",
        "home_updates_move": "Si aggiorna mentre ti muovi",
        "home_keeps_playing": "Continua tra le pagine",
        "home_try_driving": "Prova modalità guida",
        "home_for_walking": "Per camminare",
        "home_shows_landmarks": "Mostra luoghi vicini",
        "home_listen_places": "Ascolta i luoghi intorno a te",
        "home_use_filters": "Filtri per musei, chiese e parchi",
        "home_explore_walking": "Esplora modalità passeggiata",
        "home_languages_title": "Ascolta nella tua lingua",
        "home_languages_sub": "Scegli la lingua per testo e audio.",
        "home_audio_supported": "Audio supportato",
        "home_popular_cities": "Città popolari",
        "home_city_guides_title": "Guide città per il prossimo viaggio",
        "home_view_all_cities": "Vedi tutte le città",
        "home_iconic_places": "Luoghi iconici",
        "home_landmarks_title": "Luoghi da ascoltare",
        "home_view_all_places": "Vedi tutti i luoghi",
        "home_ready_to_listen": "Pronto da ascoltare",
        "home_search_sub": "Cerca una città o un luogo, scegli una storia audio gratuita e tieni il player con te.",
        "home_search_city_landmark": "Cerca città o luogo",
        "home_near_me": "Vicino a me",
        "home_landmarks": "Luoghi d’interesse",
        "home_audio_ready_short": "Audio pronto",
        "home_popular_searches": "Ricerche popolari",
        "home_open_explore": "Apri esplora",
        "home_europe_intro": "Inizia da un paese, apri una guida audio di città e segui i luoghi migliori sulla mappa.",
        "home_choose_country": "Scegli un paese",
        "home_country_group_west": "Europa occidentale",
        "home_country_group_south": "Europa meridionale",
        "home_country_group_central": "Europa centrale",
        "home_country_group_north": "Europa settentrionale",
        "home_country_group_east": "Europa orientale e Balcani",
        "home_why_text": "Una guida audio GPS collega le storie al luogo davanti a te. Guida in una regione, cammina in città o apri un monumento e continua ad ascoltare.",
        "home_no_read": "Non serve leggere in movimento",
        "home_location_stories": "Storie legate alla tua posizione",
        "home_road_walks": "Utile per viaggi e passeggiate",
        "home_one_app": "Città e monumenti in un’unica app",
        "home_seo_kicker": "Guida audio GPS",
        "home_seo_title": "Guida audio GPS per città e monumenti",
        "home_seo_p1": "SonicCity è una guida audio su mappa per viaggiatori che vogliono storie utili senza fermarsi a leggere.",
        "home_seo_p2": "Ogni città o luogo diventa una serie di brevi storie audio su storia, cultura, monumenti e contesto pratico.",
        "home_seo_p3": "Le audioguide sono disponibili in inglese, francese, spagnolo, italiano, ucraino e tedesco.",
        "home_final_title": "Inizia a esplorare con la tua audioguida",
        "home_final_sub": "Usa il GPS per scoprire storie vicine o scegli una città manualmente.",
        "home_start_gps": "Inizia con GPS",
        "home_explore_cities": "Esplora città",
        "home_meta_title": "Guida audio GPS gratis per città e monumenti | SonicCity",
        "home_meta_desc": "Ascolta gratis una guida audio GPS per città, monumenti e viaggi. Apri la mappa, trova luoghi vicini e continua ad ascoltare le storie.",
        "home_featured_schema": "Audioguide SonicCity in evidenza",
        "home_benefit_gps": "Il GPS rileva città e monumenti intorno a te.",
        "home_benefit_audio": "Ascolta mentre guidi, cammini o esplori.",
        "home_benefit_languages": "Inglese, francese, spagnolo, italiano, ucraino e tedesco.",
        "home_benefit_europe": "Guide di città e monumenti nei paesi supportati.",
        "home_city_valencia_desc": "Strade mediterranee, mercati, giardini e architettura futuristica in una guida urbana.",
        "home_city_barcelona_desc": "Gaudi, strade gotiche, viste sul mare e storie locali per camminare o pianificare.",
        "home_city_rome_desc": "Rovine antiche, chiese, fontane e quartieri per una passeggiata lenta.",
        "home_city_paris_desc": "Musei, rive, monumenti e storie culturali collegate alla mappa.",
        "home_city_vienna_desc": "Palazzi, musica, caffè e monumenti imperiali in storie concise.",
        "home_city_prague_desc": "Ponti, castello, città vecchia e luoghi pronti per la modalità passeggiata.",
        "home_place_valencia_cathedral_desc": "Una storia compatta sulla cattedrale, la città vecchia e le piazze vicine.",
        "home_place_sagrada_familia_desc": "Architettura, simboli e contesto urbano intorno alla basilica più famosa di Barcellona.",
        "home_place_colosseum_desc": "Ascolta la storia dell’arena prima o durante la visita.",
        "home_place_eiffel_tower_desc": "Una breve guida audio sulla torre, il fiume e i dintorni.",
        "home_place_schonbrunn_desc": "Sale imperiali, giardini e storie posizionate sulla mappa.",
        "home_place_charles_bridge_desc": "Una storia da percorrere sul ponte, le viste e la città vecchia.",
        "place_hero_title_tpl": "Audioguida di {place} - ascolta gratis",
        "place_hero_sub_tpl": "Ascolta gratis una breve guida di {place} a {city}, {country}, con mappa e luoghi vicini.",
        "place_progress_note_tpl": "Il progresso della guida di {place} apparirà qui mentre le storie vengono preparate.",
        "place_playlist_title_tpl": "Storie su {place}",
        "place_playlist_sub": "Brevi storie audio facili da ascoltare quando sei già sul posto.",
        "place_about_title_tpl": "Informazioni su {place}",
        "place_about_text_tpl": "L’audioguida di {place} offre una storia mirata del luogo e continua mentre apri luoghi vicini o torni alla guida di {city}.",
        "place_practical_info": "Info pratiche",
        "place_more_places_tpl": "Altri luoghi da visitare a {city}",
        "place_open_city_guide": "Apri guida città",
        "place_nearby_text_tpl": "Apri un’altra guida di un luogo vicino a {city}.",
        "place_nearby_meta": "Luogo vicino",
        "place_show_on_map": "Mostra sulla mappa",
        "place_select_landmark": "Seleziona un luogo",
        "place_select_landmark_sub": "Tocca un marker per vedere la foto, ascoltare l’audio o creare un percorso.",
        "place_search_places": "Cerca luoghi",
        "place_search_place": "Cerca luogo",
        "place_audio_ready_zero": "Audio pronto: 0 / 8 storie",
        "common_details": "Dettagli",
        "common_play": "Play",
        "common_listen": "Ascolta",
        "common_category": "Categoria",
    },
    "de": {
        "home_places_around_you": "Orte in deiner Nähe",
        "home_my_location": "Mein Standort",
        "home_show_places": "Orte anzeigen",
        "home_you_are_here": "Du bist hier",
        "home_central_market": "Zentralmarkt",
        "home_ready_walk": "Sehenswürdigkeit · 8 Min. zu Fuß · bereit zum Hören",
        "home_now_near": "Jetzt in der Nähe",
        "home_auto_detect": "Nahe Guides automatisch erkennen",
        "home_nearby_placeholder": "Nahe Städte erscheinen hier",
        "home_topics_count": "24 Themen",
        "home_first_story_ready": "Erste Geschichte bereit",
        "home_open_valencia_guide": "Valencia Audioguide öffnen",
        "home_pick_story_sub": "Wähle Geschichte, Sehenswürdigkeiten oder lokale Kultur.",
        "home_player_stays_sub": "Der Player bleibt beim Erkunden aktiv.",
        "home_use_cases": "Anwendungsfälle",
        "home_use_cases_title": "Für Roadtrips und Stadtspaziergänge",
        "home_for_driving": "Für Fahrten",
        "home_detects_nearby": "Erkennt nahe Städte",
        "home_updates_move": "Aktualisiert sich unterwegs",
        "home_keeps_playing": "Spielt zwischen Seiten weiter",
        "home_try_driving": "Fahrmodus testen",
        "home_for_walking": "Zum Spazieren",
        "home_shows_landmarks": "Zeigt nahe Sehenswürdigkeiten",
        "home_listen_places": "Höre Orte in deiner Nähe",
        "home_use_filters": "Filter für Museen, Kirchen und Parks",
        "home_explore_walking": "Gehmodus erkunden",
        "home_languages_title": "Höre in deiner Sprache",
        "home_languages_sub": "Wähle die Sprache für Text und Audio.",
        "home_audio_supported": "Audio verfügbar",
        "home_popular_cities": "Beliebte Städte",
        "home_city_guides_title": "Stadtguides für deine nächste Reise",
        "home_view_all_cities": "Alle Städte ansehen",
        "home_iconic_places": "Ikonische Orte",
        "home_landmarks_title": "Sehenswürdigkeiten, die sich lohnen",
        "home_view_all_places": "Alle Orte ansehen",
        "home_ready_to_listen": "Bereit zum Hören",
        "home_search_sub": "Suche eine Stadt oder Sehenswürdigkeit, wähle eine kostenlose Audiogeschichte und behalte den Player bei dir.",
        "home_search_city_landmark": "Stadt oder Ort suchen",
        "home_near_me": "In meiner Nähe",
        "home_landmarks": "Sehenswürdigkeiten",
        "home_audio_ready_short": "Audio bereit",
        "home_popular_searches": "Beliebte Suchen",
        "home_open_explore": "Entdecken öffnen",
        "home_europe_intro": "Beginne mit einem Land, öffne einen Stadt-Audioguide und folge Top-Orten auf der Karte.",
        "home_choose_country": "Land wählen",
        "home_country_group_west": "Westeuropa",
        "home_country_group_south": "Südeuropa",
        "home_country_group_central": "Mitteleuropa",
        "home_country_group_north": "Nordeuropa",
        "home_country_group_east": "Osteuropa & Balkan",
        "home_why_text": "Ein GPS-Audioguide verbindet Geschichten mit dem Ort vor dir. Fahre durch eine Region, spaziere durch eine Stadt oder öffne eine Sehenswürdigkeit und höre weiter.",
        "home_no_read": "Kein Lesen unterwegs",
        "home_location_stories": "Geschichten mit deinem Standort verbunden",
        "home_road_walks": "Nützlich für Fahrten und Spaziergänge",
        "home_one_app": "Städte und Sehenswürdigkeiten in einer App",
        "home_seo_kicker": "GPS-Audioguide",
        "home_seo_title": "GPS-Audioguide für Städte und Sehenswürdigkeiten",
        "home_seo_p1": "SonicCity ist ein kartenbasierter Audioguide für Reisende, die nützliche Geschichten hören möchten, ohne zum Lesen anzuhalten.",
        "home_seo_p2": "Jede Stadt oder jeder Ort wird zu kurzen Audiogeschichten über Geschichte, Kultur, Sehenswürdigkeiten und praktischen Kontext.",
        "home_seo_p3": "Audioguides sind auf Englisch, Französisch, Spanisch, Italienisch, Ukrainisch und Deutsch verfügbar.",
        "home_final_title": "Beginne mit deinem Audioguide zu erkunden",
        "home_final_sub": "Nutze GPS, um nahe Geschichten zu entdecken, oder wähle eine Stadt manuell.",
        "home_start_gps": "Mit GPS starten",
        "home_explore_cities": "Städte erkunden",
        "home_meta_title": "Kostenloser GPS-Audioguide für Städte und Sehenswürdigkeiten | SonicCity",
        "home_meta_desc": "Höre kostenlos einen GPS-Audioguide für Städte, Sehenswürdigkeiten und Reisen. Öffne die Karte, finde Orte in der Nähe und höre weiter.",
        "home_featured_schema": "Ausgewählte SonicCity-Audioguides",
        "home_benefit_gps": "GPS erkennt Städte und Sehenswürdigkeiten in deiner Nähe.",
        "home_benefit_audio": "Höre beim Fahren, Spazieren oder Erkunden.",
        "home_benefit_languages": "Englisch, Französisch, Spanisch, Italienisch, Ukrainisch und Deutsch.",
        "home_benefit_europe": "Stadt- und Sehenswürdigkeitsguides in unterstützten Ländern.",
        "home_city_valencia_desc": "Mediterrane Straßen, Märkte, Gärten und futuristische Architektur in einem Stadtguide.",
        "home_city_barcelona_desc": "Gaudi, gotische Straßen, Meerblicke und lokale Geschichten zum Gehen oder Planen.",
        "home_city_rome_desc": "Antike Ruinen, Kirchen, Brunnen und Viertel für einen langsameren Stadtspaziergang.",
        "home_city_paris_desc": "Museen, Flusswege, Monumente und Kulturgeschichten auf der Karte.",
        "home_city_vienna_desc": "Paläste, Musik, Cafes und imperiale Orte in kurzen Geschichten.",
        "home_city_prague_desc": "Brücken, Burg, Altstadt und Orte für den Gehmodus.",
        "home_place_valencia_cathedral_desc": "Eine kurze Geschichte über die Kathedrale, Altstadt und nahe Plätze.",
        "home_place_sagrada_familia_desc": "Architektur, Symbole und Stadtkontext rund um Barcelonas berühmteste Basilika.",
        "home_place_colosseum_desc": "Höre die Geschichte der Arena vor oder während des Besuchs.",
        "home_place_eiffel_tower_desc": "Ein kurzer Audioguide zum Turm, Flussblick und der Umgebung.",
        "home_place_schonbrunn_desc": "Imperiale Räume, Gärten und Geschichten auf der Stadtkarte.",
        "home_place_charles_bridge_desc": "Eine begehbare Geschichte über die Brücke, Ausblicke und Altstadtrouten.",
        "place_hero_title_tpl": "{place} Audioguide - kostenlos hören",
        "place_hero_sub_tpl": "Höre kostenlos einen kurzen Guide zu {place} in {city}, {country}, mit Karte und nahen Orten.",
        "place_progress_note_tpl": "Der Fortschritt des {place}-Guides erscheint hier, während Geschichten vorbereitet werden.",
        "place_playlist_title_tpl": "Geschichten über {place}",
        "place_playlist_sub": "Kurze Audiogeschichten, die leicht zu hören sind, wenn du schon vor Ort bist.",
        "place_about_title_tpl": "Über {place}",
        "place_about_text_tpl": "Der Audioguide zu {place} erzählt eine fokussierte Geschichte und spielt weiter, während du nahe Orte öffnest oder zum {city}-Guide zurückkehrst.",
        "place_practical_info": "Praktische Infos",
        "place_more_places_tpl": "Weitere Orte in {city}",
        "place_open_city_guide": "Stadtguide öffnen",
        "place_nearby_text_tpl": "Öffne einen weiteren Guide zu einem nahen Ort in {city}.",
        "place_nearby_meta": "Ort in der Nähe",
        "place_show_on_map": "Auf Karte zeigen",
        "place_select_landmark": "Ort auswählen",
        "place_select_landmark_sub": "Tippe auf einen Marker, um Foto, Audio oder Route zu öffnen.",
        "place_search_places": "Orte suchen",
        "place_search_place": "Ort suchen",
        "place_audio_ready_zero": "Audio bereit: 0 / 8 Geschichten",
        "common_details": "Details",
        "common_play": "Play",
        "common_listen": "Anhören",
        "common_category": "Kategorie",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_override_values)

for _lang, _compact_values in {
    "en": {
        "topic_history": "History",
        "topic_old_town": "Old Town",
        "topic_landmarks": "Landmarks",
        "topic_culture": "Culture",
        "topic_food": "Food",
        "topic_architecture": "Architecture",
        "topic_museums": "Museums",
        "topic_more": "+16 more",
        "city_audio_ready_zero": "Audio ready: 0 / 12 sections",
        "city_no_places_title": "No places found nearby",
        "city_no_places_sub": "Try expanding the area or opening another city.",
        "city_related_kicker": "Related guides",
        "city_related_title_tpl": "More places and cities around {country}",
        "city_related_country_sub": "Explore more city audio guides and landmarks in this country.",
        "city_related_place_sub_tpl": "Listen to a place guide near {city}.",
        "city_open_country": "Open country",
        "city_open_place": "Open place",
        "city_about_title_tpl": "About this {city} guide",
        "city_about_p1_tpl": "The {city} Audio Guide helps travelers listen to history, landmarks, culture and practical city context without reading long articles.",
        "city_about_p2": "The guide is organised into short audio sections, with the map and nearby places kept close to the playlist so visitors can switch between listening and exploring without losing context.",
    },
    "ua": {
        "topic_history": "Історія",
        "topic_old_town": "Старе місто",
        "topic_landmarks": "Памʼятки",
        "topic_culture": "Культура",
        "topic_food": "Їжа",
        "topic_architecture": "Архітектура",
        "topic_museums": "Музеї",
        "topic_more": "+16 ще",
        "city_audio_ready_zero": "Аудіо готове: 0 / 12 розділів",
        "city_no_places_title": "Місць поруч не знайдено",
        "city_no_places_sub": "Спробуйте розширити зону або відкрити інше місто.",
        "city_related_kicker": "Схожі гіди",
        "city_related_title_tpl": "Більше місць і міст у {country}",
        "city_related_country_sub": "Досліджуйте інші міські аудіогіди та памʼятки в цій країні.",
        "city_related_place_sub_tpl": "Послухайте гід місця поруч із {city}.",
        "city_open_country": "Відкрити країну",
        "city_open_place": "Відкрити місце",
        "city_about_title_tpl": "Про гід {city}",
        "city_about_p1_tpl": "Аудіогід {city} допомагає слухати історію, памʼятки, культуру і практичний контекст міста без довгих статей.",
        "city_about_p2": "Гід поділений на короткі аудіорозділи, а мапа й місця поруч залишаються біля плейлиста, щоб можна було слухати і досліджувати без втрати контексту.",
    },
    "fr": {
        "topic_history": "Histoire",
        "topic_old_town": "Vieille ville",
        "topic_landmarks": "Monuments",
        "topic_culture": "Culture",
        "topic_food": "Cuisine",
        "topic_architecture": "Architecture",
        "topic_museums": "Musées",
        "topic_more": "+16 de plus",
        "city_audio_ready_zero": "Audio prêt : 0 / 12 sections",
        "city_no_places_title": "Aucun lieu proche trouvé",
        "city_no_places_sub": "Essayez d’élargir la zone ou d’ouvrir une autre ville.",
        "city_related_kicker": "Guides associés",
        "city_related_title_tpl": "Plus de lieux et de villes autour de {country}",
        "city_related_country_sub": "Explorez d’autres guides audio de villes et monuments dans ce pays.",
        "city_related_place_sub_tpl": "Écoutez un guide de lieu près de {city}.",
        "city_open_country": "Ouvrir le pays",
        "city_open_place": "Ouvrir le lieu",
        "city_about_title_tpl": "À propos du guide de {city}",
        "city_about_p1_tpl": "Le guide audio de {city} aide les voyageurs à écouter l’histoire, les monuments, la culture et le contexte pratique sans longs articles.",
        "city_about_p2": "Le guide est organisé en courtes sections audio, avec la carte et les lieux proches à côté de la playlist.",
    },
    "es": {
        "topic_history": "Historia",
        "topic_old_town": "Casco antiguo",
        "topic_landmarks": "Lugares",
        "topic_culture": "Cultura",
        "topic_food": "Comida",
        "topic_architecture": "Arquitectura",
        "topic_museums": "Museos",
        "topic_more": "+16 más",
        "city_audio_ready_zero": "Audio listo: 0 / 12 secciones",
        "city_no_places_title": "No se encontraron lugares cercanos",
        "city_no_places_sub": "Prueba a ampliar la zona o abrir otra ciudad.",
        "city_related_kicker": "Guías relacionadas",
        "city_related_title_tpl": "Más lugares y ciudades alrededor de {country}",
        "city_related_country_sub": "Explora más audioguías de ciudades y monumentos en este país.",
        "city_related_place_sub_tpl": "Escucha una guía de un lugar cerca de {city}.",
        "city_open_country": "Abrir país",
        "city_open_place": "Abrir lugar",
        "city_about_title_tpl": "Sobre la guía de {city}",
        "city_about_p1_tpl": "La audioguía de {city} ayuda a escuchar historia, lugares, cultura y contexto práctico sin leer artículos largos.",
        "city_about_p2": "La guía se organiza en secciones de audio cortas, con el mapa y lugares cercanos junto a la lista.",
    },
    "it": {
        "topic_history": "Storia",
        "topic_old_town": "Centro storico",
        "topic_landmarks": "Luoghi",
        "topic_culture": "Cultura",
        "topic_food": "Cibo",
        "topic_architecture": "Architettura",
        "topic_museums": "Musei",
        "topic_more": "+16 altri",
        "city_audio_ready_zero": "Audio pronto: 0 / 12 sezioni",
        "city_no_places_title": "Nessun luogo vicino trovato",
        "city_no_places_sub": "Prova ad ampliare l’area o aprire un’altra città.",
        "city_related_kicker": "Guide correlate",
        "city_related_title_tpl": "Altri luoghi e città intorno a {country}",
        "city_related_country_sub": "Esplora altre audioguide di città e monumenti in questo paese.",
        "city_related_place_sub_tpl": "Ascolta una guida di un luogo vicino a {city}.",
        "city_open_country": "Apri paese",
        "city_open_place": "Apri luogo",
        "city_about_title_tpl": "Informazioni sulla guida di {city}",
        "city_about_p1_tpl": "L’audioguida di {city} aiuta ad ascoltare storia, luoghi, cultura e contesto pratico senza leggere articoli lunghi.",
        "city_about_p2": "La guida è organizzata in brevi sezioni audio, con mappa e luoghi vicini accanto alla playlist.",
    },
    "de": {
        "topic_history": "Geschichte",
        "topic_old_town": "Altstadt",
        "topic_landmarks": "Sehenswürdigkeiten",
        "topic_culture": "Kultur",
        "topic_food": "Essen",
        "topic_architecture": "Architektur",
        "topic_museums": "Museen",
        "topic_more": "+16 mehr",
        "city_audio_ready_zero": "Audio bereit: 0 / 12 Abschnitte",
        "city_no_places_title": "Keine Orte in der Nähe gefunden",
        "city_no_places_sub": "Versuche, den Bereich zu erweitern oder eine andere Stadt zu öffnen.",
        "city_related_kicker": "Ähnliche Guides",
        "city_related_title_tpl": "Weitere Orte und Städte rund um {country}",
        "city_related_country_sub": "Entdecke weitere Stadt-Audioguides und Sehenswürdigkeiten in diesem Land.",
        "city_related_place_sub_tpl": "Höre einen Guide zu einem Ort nahe {city}.",
        "city_open_country": "Land öffnen",
        "city_open_place": "Ort öffnen",
        "city_about_title_tpl": "Über den {city}-Guide",
        "city_about_p1_tpl": "Der {city}-Audioguide hilft Reisenden, Geschichte, Sehenswürdigkeiten, Kultur und praktischen Kontext ohne lange Artikel zu hören.",
        "city_about_p2": "Der Guide ist in kurze Audioabschnitte gegliedert, Karte und nahe Orte bleiben direkt neben der Playlist.",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_compact_values)

for _lang, _entity_values in {
    "en": {
        "country_hero_title_tpl": "{country} Audio Guide - Listen for Free",
        "country_hero_sub_tpl": "Listen free to short country stories, open city maps and discover places worth visiting across {country}.",
        "country_map_title_tpl": "{country} map",
        "country_about_p1_tpl": "Use this {country} guide to understand the country, compare cities and choose places before or during your trip.",
        "country_about_p2_tpl": "The map-first layout keeps audio, city links and top places together, so travelers can plan a route, choose a city manually or keep listening while moving through {country}.",
        "city_hero_title_tpl": "{city} Audio Guide - Listen for Free",
        "city_hero_sub_tpl": "Listen free to short {city} stories with a GPS map, landmarks and nearby places in {country}.",
        "city_map_title_tpl": "Map of places in {city}",
        "player_no_track_label": "Choose an audio story",
        "player_start_city_guide": "Start a city guide",
        "player_pick_city_topic": "Pick a city or topic to begin.",
        "player_now_playing": "Now playing",
        "player_continue_listening": "Continue listening",
        "audio_guide_generic": "Audio guide",
        "map_select_place_tap": "Select a place and tap Play.",
        "blog_popular_posts": "Popular posts",
        "blog_no_popular_posts": "No popular posts yet.",
        "blog_categories_title": "Categories",
        "blog_tags_title": "Tags",
        "subscription_updates_text": "Get practical city and landmark guide updates when new stories are ready.",
        "country_name_spain": "Spain",
        "country_name_italy": "Italy",
        "country_name_france": "France",
        "city_name_valencia": "Valencia",
        "city_name_barcelona": "Barcelona",
        "city_name_rome": "Rome",
        "city_name_paris": "Paris",
        "city_name_vienna": "Vienna",
        "city_name_prague": "Prague",
        "city_name_madrid": "Madrid",
        "city_name_florence": "Florence",
        "city_name_venice": "Venice",
        "city_name_nice": "Nice",
        "city_name_lyon": "Lyon",
        "place_name_valencia_cathedral": "Valencia Cathedral",
        "place_name_sagrada_familia": "Sagrada Familia",
        "place_name_colosseum": "Colosseum",
        "place_name_eiffel_tower": "Eiffel Tower",
        "place_name_schonbrunn_palace": "Schönbrunn Palace",
        "place_name_charles_bridge": "Charles Bridge",
        "category_cathedral": "Cathedral",
        "category_church": "Church",
        "category_landmark": "Landmark",
        "category_museum": "Museum",
        "category_monument": "Monument",
        "category_palace": "Palace",
        "category_bridge": "Bridge",
        "category_park": "Park",
        "category_viewpoint": "Viewpoint",
        "home_ready_walk_localized": "6 min walk · ready to listen",
        "home_car_label": "Car",
        "home_route_spain_cities": "Valencia, Barcelona, Madrid",
        "home_route_italy_cities": "Rome, Florence, Venice",
        "home_route_france_cities": "Paris, Nice, Lyon",
    },
    "ua": {
        "country_hero_title_tpl": "Аудіогід: {country} - слухайте безкоштовно",
        "country_hero_sub_tpl": "Слухайте короткі історії про {country}, відкривайте мапи міст і знаходьте місця, які варто відвідати.",
        "country_map_title_tpl": "Мапа {country}",
        "country_about_p1_tpl": "Використовуйте цей гід про {country}, щоб краще зрозуміти країну, порівняти міста й обрати місця до або під час подорожі.",
        "country_about_p2_tpl": "Формат з мапою тримає аудіо, посилання на міста й топмісця поруч, щоб мандрівники могли планувати маршрут, обирати місто вручну або слухати під час руху країною {country}.",
        "city_hero_title_tpl": "Аудіогід: {city} - слухайте безкоштовно",
        "city_hero_sub_tpl": "Слухайте короткі історії про {city} з GPS-мапою, памʼятками й місцями поруч у {country}.",
        "city_map_title_tpl": "Мапа місць у {city}",
        "player_auth_gate": "Щоб слухати безкоштовно, зареєструйтесь.",
        "player_no_track_label": "Оберіть аудіоісторію",
        "player_start_city_guide": "Почніть міський гід",
        "player_pick_city_topic": "Оберіть місто або тему, щоб почати.",
        "player_now_playing": "Зараз грає",
        "player_continue_listening": "Продовжити слухати",
        "audio_guide_generic": "Аудіогід",
        "map_select_place_tap": "Оберіть місце й натисніть Play.",
        "blog_popular_posts": "Популярні статті",
        "blog_no_popular_posts": "Популярних статей поки немає.",
        "blog_categories_title": "Категорії",
        "blog_tags_title": "Теги",
        "subscription_updates_text": "Отримуйте оновлення про міські гіди й памʼятки, коли нові історії готові.",
        "country_name_spain": "Іспанія",
        "country_name_italy": "Італія",
        "country_name_france": "Франція",
        "city_name_valencia": "Валенсія",
        "city_name_barcelona": "Барселона",
        "city_name_rome": "Рим",
        "city_name_paris": "Париж",
        "city_name_vienna": "Відень",
        "city_name_prague": "Прага",
        "city_name_madrid": "Мадрид",
        "city_name_florence": "Флоренція",
        "city_name_venice": "Венеція",
        "city_name_nice": "Ніцца",
        "city_name_lyon": "Ліон",
        "place_name_valencia_cathedral": "Валенсійський собор",
        "place_name_sagrada_familia": "Саграда Фамілія",
        "place_name_colosseum": "Колізей",
        "place_name_eiffel_tower": "Ейфелева вежа",
        "place_name_schonbrunn_palace": "Палац Шенбрунн",
        "place_name_charles_bridge": "Карлів міст",
        "category_cathedral": "Собор",
        "category_church": "Церква",
        "category_landmark": "Памʼятка",
        "category_museum": "Музей",
        "category_monument": "Монумент",
        "category_palace": "Палац",
        "category_bridge": "Міст",
        "category_park": "Парк",
        "category_viewpoint": "Оглядова точка",
        "home_ready_walk_localized": "6 хв пішки · готово до прослуховування",
        "home_car_label": "Авто",
        "home_route_spain_cities": "Валенсія, Барселона, Мадрид",
        "home_route_italy_cities": "Рим, Флоренція, Венеція",
        "home_route_france_cities": "Париж, Ніцца, Ліон",
    },
    "fr": {
        "country_hero_title_tpl": "Guide audio de {country} - écoute gratuite",
        "country_hero_sub_tpl": "Écoutez gratuitement de courtes histoires sur {country}, ouvrez les cartes des villes et découvrez les lieux à visiter.",
        "country_map_title_tpl": "Carte de {country}",
        "country_about_p1_tpl": "Utilisez ce guide de {country} pour comprendre le pays, comparer les villes et choisir des lieux avant ou pendant votre voyage.",
        "country_about_p2_tpl": "La mise en page centrée sur la carte garde l’audio, les liens de villes et les meilleurs lieux ensemble pour planifier un itinéraire ou continuer l’écoute en traversant {country}.",
        "city_hero_title_tpl": "Guide audio de {city} - écoute gratuite",
        "city_hero_sub_tpl": "Écoutez gratuitement de courtes histoires sur {city} avec carte GPS, monuments et lieux proches en {country}.",
        "city_map_title_tpl": "Carte des lieux à {city}",
        "player_no_track_label": "Choisissez une histoire audio",
        "player_start_city_guide": "Commencer un guide de ville",
        "player_pick_city_topic": "Choisissez une ville ou un thème pour commencer.",
        "player_now_playing": "En cours",
        "player_continue_listening": "Continuer l’écoute",
        "audio_guide_generic": "Guide audio",
        "map_select_place_tap": "Choisissez un lieu et touchez Play.",
        "blog_popular_posts": "Articles populaires",
        "blog_no_popular_posts": "Aucun article populaire pour le moment.",
        "blog_categories_title": "Catégories",
        "blog_tags_title": "Tags",
        "subscription_updates_text": "Recevez les nouveautés des guides de villes et monuments quand de nouvelles histoires sont prêtes.",
        "country_name_spain": "Espagne",
        "country_name_italy": "Italie",
        "country_name_france": "France",
        "city_name_valencia": "Valence",
        "city_name_barcelona": "Barcelone",
        "city_name_rome": "Rome",
        "city_name_paris": "Paris",
        "city_name_vienna": "Vienne",
        "city_name_prague": "Prague",
        "city_name_madrid": "Madrid",
        "city_name_florence": "Florence",
        "city_name_venice": "Venise",
        "city_name_nice": "Nice",
        "city_name_lyon": "Lyon",
        "place_name_valencia_cathedral": "Cathédrale de Valence",
        "place_name_sagrada_familia": "Sagrada Família",
        "place_name_colosseum": "Colisée",
        "place_name_eiffel_tower": "Tour Eiffel",
        "place_name_schonbrunn_palace": "Château de Schönbrunn",
        "place_name_charles_bridge": "Pont Charles",
        "category_cathedral": "Cathédrale",
        "category_church": "Église",
        "category_landmark": "Monument",
        "category_museum": "Musée",
        "category_monument": "Monument",
        "category_palace": "Palais",
        "category_bridge": "Pont",
        "category_park": "Parc",
        "category_viewpoint": "Point de vue",
        "home_ready_walk_localized": "6 min à pied · prêt à écouter",
        "home_car_label": "Voiture",
        "home_route_spain_cities": "Valence, Barcelone, Madrid",
        "home_route_italy_cities": "Rome, Florence, Venise",
        "home_route_france_cities": "Paris, Nice, Lyon",
    },
    "es": {
        "country_hero_title_tpl": "Audioguía de {country} - escucha gratis",
        "country_hero_sub_tpl": "Escucha gratis historias cortas sobre {country}, abre mapas de ciudades y descubre lugares que visitar.",
        "country_map_title_tpl": "Mapa de {country}",
        "country_about_p1_tpl": "Usa esta guía de {country} para entender el país, comparar ciudades y elegir lugares antes o durante tu viaje.",
        "country_about_p2_tpl": "El diseño centrado en el mapa mantiene juntos el audio, los enlaces a ciudades y los mejores lugares para planificar una ruta o seguir escuchando por {country}.",
        "city_hero_title_tpl": "Audioguía de {city} - escucha gratis",
        "city_hero_sub_tpl": "Escucha gratis historias cortas de {city} con mapa GPS, monumentos y lugares cercanos en {country}.",
        "city_map_title_tpl": "Mapa de lugares en {city}",
        "player_no_track_label": "Elige una historia de audio",
        "player_start_city_guide": "Iniciar una guía de ciudad",
        "player_pick_city_topic": "Elige una ciudad o tema para empezar.",
        "player_now_playing": "Reproduciendo",
        "player_continue_listening": "Continuar escuchando",
        "audio_guide_generic": "Audioguía",
        "map_select_place_tap": "Elige un lugar y toca Play.",
        "blog_popular_posts": "Artículos populares",
        "blog_no_popular_posts": "Aún no hay artículos populares.",
        "blog_categories_title": "Categorías",
        "blog_tags_title": "Etiquetas",
        "subscription_updates_text": "Recibe actualizaciones de guías de ciudades y monumentos cuando haya nuevas historias.",
        "country_name_spain": "España",
        "country_name_italy": "Italia",
        "country_name_france": "Francia",
        "city_name_valencia": "Valencia",
        "city_name_barcelona": "Barcelona",
        "city_name_rome": "Roma",
        "city_name_paris": "París",
        "city_name_vienna": "Viena",
        "city_name_prague": "Praga",
        "city_name_madrid": "Madrid",
        "city_name_florence": "Florencia",
        "city_name_venice": "Venecia",
        "city_name_nice": "Niza",
        "city_name_lyon": "Lyon",
        "place_name_valencia_cathedral": "Catedral de Valencia",
        "place_name_sagrada_familia": "Sagrada Familia",
        "place_name_colosseum": "Coliseo",
        "place_name_eiffel_tower": "Torre Eiffel",
        "place_name_schonbrunn_palace": "Palacio de Schönbrunn",
        "place_name_charles_bridge": "Puente de Carlos",
        "category_cathedral": "Catedral",
        "category_church": "Iglesia",
        "category_landmark": "Lugar destacado",
        "category_museum": "Museo",
        "category_monument": "Monumento",
        "category_palace": "Palacio",
        "category_bridge": "Puente",
        "category_park": "Parque",
        "category_viewpoint": "Mirador",
        "home_ready_walk_localized": "6 min a pie · listo para escuchar",
        "home_car_label": "Coche",
        "home_route_spain_cities": "Valencia, Barcelona, Madrid",
        "home_route_italy_cities": "Roma, Florencia, Venecia",
        "home_route_france_cities": "París, Niza, Lyon",
    },
    "it": {
        "country_hero_title_tpl": "Audioguida di {country} - ascolta gratis",
        "country_hero_sub_tpl": "Ascolta gratis brevi storie su {country}, apri le mappe delle città e scopri luoghi da visitare.",
        "country_map_title_tpl": "Mappa di {country}",
        "country_about_p1_tpl": "Usa questa guida di {country} per capire il paese, confrontare le città e scegliere luoghi prima o durante il viaggio.",
        "country_about_p2_tpl": "Il layout basato sulla mappa tiene insieme audio, link alle città e luoghi principali per pianificare un percorso o continuare ad ascoltare attraversando {country}.",
        "city_hero_title_tpl": "Audioguida di {city} - ascolta gratis",
        "city_hero_sub_tpl": "Ascolta gratis brevi storie su {city} con mappa GPS, monumenti e luoghi vicini in {country}.",
        "city_map_title_tpl": "Mappa dei luoghi a {city}",
        "player_no_track_label": "Scegli una storia audio",
        "player_start_city_guide": "Avvia una guida della città",
        "player_pick_city_topic": "Scegli una città o un tema per iniziare.",
        "player_now_playing": "In riproduzione",
        "player_continue_listening": "Continua ad ascoltare",
        "audio_guide_generic": "Audioguida",
        "map_select_place_tap": "Scegli un luogo e tocca Play.",
        "blog_popular_posts": "Post popolari",
        "blog_no_popular_posts": "Non ci sono ancora post popolari.",
        "blog_categories_title": "Categorie",
        "blog_tags_title": "Tag",
        "subscription_updates_text": "Ricevi aggiornamenti sulle guide di città e monumenti quando nuove storie sono pronte.",
        "country_name_spain": "Spagna",
        "country_name_italy": "Italia",
        "country_name_france": "Francia",
        "city_name_valencia": "Valencia",
        "city_name_barcelona": "Barcellona",
        "city_name_rome": "Roma",
        "city_name_paris": "Parigi",
        "city_name_vienna": "Vienna",
        "city_name_prague": "Praga",
        "city_name_madrid": "Madrid",
        "city_name_florence": "Firenze",
        "city_name_venice": "Venezia",
        "city_name_nice": "Nizza",
        "city_name_lyon": "Lione",
        "place_name_valencia_cathedral": "Cattedrale di Valencia",
        "place_name_sagrada_familia": "Sagrada Família",
        "place_name_colosseum": "Colosseo",
        "place_name_eiffel_tower": "Torre Eiffel",
        "place_name_schonbrunn_palace": "Palazzo di Schönbrunn",
        "place_name_charles_bridge": "Ponte Carlo",
        "category_cathedral": "Cattedrale",
        "category_church": "Chiesa",
        "category_landmark": "Luogo di interesse",
        "category_museum": "Museo",
        "category_monument": "Monumento",
        "category_palace": "Palazzo",
        "category_bridge": "Ponte",
        "category_park": "Parco",
        "category_viewpoint": "Punto panoramico",
        "home_ready_walk_localized": "6 min a piedi · pronto da ascoltare",
        "home_car_label": "Auto",
        "home_route_spain_cities": "Valencia, Barcellona, Madrid",
        "home_route_italy_cities": "Roma, Firenze, Venezia",
        "home_route_france_cities": "Parigi, Nizza, Lione",
    },
    "de": {
        "country_hero_title_tpl": "{country} Audioguide - kostenlos anhören",
        "country_hero_sub_tpl": "Höre kurze Geschichten über {country} kostenlos, öffne Stadtkarten und entdecke sehenswerte Orte.",
        "country_map_title_tpl": "Karte von {country}",
        "country_about_p1_tpl": "Nutze diesen Guide für {country}, um das Land zu verstehen, Städte zu vergleichen und Orte vor oder während deiner Reise auszuwählen.",
        "country_about_p2_tpl": "Das kartenbasierte Layout hält Audio, Stadtlinks und Top-Orte zusammen, damit Reisende Routen planen oder beim Reisen durch {country} weiterhören können.",
        "city_hero_title_tpl": "{city} Audioguide - kostenlos anhören",
        "city_hero_sub_tpl": "Höre kurze Geschichten über {city} kostenlos mit GPS-Karte, Sehenswürdigkeiten und nahen Orten in {country}.",
        "city_map_title_tpl": "Karte der Orte in {city}",
        "player_no_track_label": "Audiogeschichte wählen",
        "player_start_city_guide": "Stadtguide starten",
        "player_pick_city_topic": "Wähle eine Stadt oder ein Thema, um zu beginnen.",
        "player_now_playing": "Jetzt läuft",
        "player_continue_listening": "Weiterhören",
        "audio_guide_generic": "Audioguide",
        "map_select_place_tap": "Wähle einen Ort und tippe auf Play.",
        "blog_popular_posts": "Beliebte Beiträge",
        "blog_no_popular_posts": "Noch keine beliebten Beiträge.",
        "blog_categories_title": "Kategorien",
        "blog_tags_title": "Tags",
        "subscription_updates_text": "Erhalte Updates zu Stadt- und Sehenswürdigkeiten-Guides, wenn neue Geschichten bereit sind.",
        "country_name_spain": "Spanien",
        "country_name_italy": "Italien",
        "country_name_france": "Frankreich",
        "city_name_valencia": "Valencia",
        "city_name_barcelona": "Barcelona",
        "city_name_rome": "Rom",
        "city_name_paris": "Paris",
        "city_name_vienna": "Wien",
        "city_name_prague": "Prag",
        "city_name_madrid": "Madrid",
        "city_name_florence": "Florenz",
        "city_name_venice": "Venedig",
        "city_name_nice": "Nizza",
        "city_name_lyon": "Lyon",
        "place_name_valencia_cathedral": "Kathedrale von Valencia",
        "place_name_sagrada_familia": "Sagrada Família",
        "place_name_colosseum": "Kolosseum",
        "place_name_eiffel_tower": "Eiffelturm",
        "place_name_schonbrunn_palace": "Schloss Schönbrunn",
        "place_name_charles_bridge": "Karlsbrücke",
        "category_cathedral": "Kathedrale",
        "category_church": "Kirche",
        "category_landmark": "Sehenswürdigkeit",
        "category_museum": "Museum",
        "category_monument": "Denkmal",
        "category_palace": "Palast",
        "category_bridge": "Brücke",
        "category_park": "Park",
        "category_viewpoint": "Aussichtspunkt",
        "home_ready_walk_localized": "6 Min. zu Fuß · bereit zum Anhören",
        "home_car_label": "Auto",
        "home_route_spain_cities": "Valencia, Barcelona, Madrid",
        "home_route_italy_cities": "Rom, Florenz, Venedig",
        "home_route_france_cities": "Paris, Nizza, Lyon",
    },
}.items():
    ADDITIONAL_UI_TRANSLATIONS.setdefault(_lang, {}).update(_entity_values)


# -------- regex converter --------
class RegexConverter(BaseConverter):
    def __init__(self, url_map, *items):
        super().__init__(url_map)
        self.regex = items[0]


app.url_map.converters["re"] = RegexConverter


# -------- utils --------
UK_SLUG_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "",
    "ю": "iu", "я": "ia", "ы": "y", "э": "e", "ъ": "",
})


def slugify(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = text.lower().translate(UK_SLUG_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:80].strip("-")


def normalize_place_name_key(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]+", " ", text)
    text = re.sub(r"\b(the|a|an|of|de|del|la|el|los|las|le|les|du|di|da)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def place_dedupe_key(place: Dict[str, Any]) -> str:
    for key in ("wikidataId", "wikidata_id", "osmId", "osm_id", "id"):
        val = str(place.get(key) or "").strip().lower()
        if val:
            return f"{key}:{val}"
    name_key = normalize_place_name_key(str(place.get("name") or place.get("displayName") or ""))
    lat = place.get("lat")
    lon = place.get("lon")
    if name_key and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"name_geo:{name_key}:{round(float(lat), 4)}:{round(float(lon), 4)}"
    return f"name:{name_key}"


def place_quality_score(place: Dict[str, Any]) -> int:
    score = 0
    for key in ("image", "imageUrl", "wikidataId", "osmId", "lat", "lon", "category", "audioStatus"):
        if place.get(key) not in (None, "", []):
            score += 1
    return score


def dedupe_places(places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for raw in places or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("displayName") or "").strip()
        slug = str(raw.get("slug") or slugify(name)).strip()
        if not name or not slug:
            continue
        item = {**raw, "name": name, "slug": slug}
        key = place_dedupe_key(item)
        if not key or key == "name:":
            key = f"slug:{slug}"
        if key not in by_key:
            by_key[key] = item
            order.append(key)
            continue
        current = by_key[key]
        if place_quality_score(item) > place_quality_score(current):
            by_key[key] = {**current, **item}
    return [by_key[k] for k in order]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    to_rad = math.radians
    dlat = to_rad(lat2 - lat1)
    dlon = to_rad(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    txt = path.read_text(encoding="utf-8").strip()
    if not txt:
        return None
    return json.loads(txt)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_plain_text(value: Any, limit: int = 20000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[:limit]


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return str(token)


def request_csrf_token() -> str:
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    if not token and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            token = str(payload.get("csrf_token") or "")
    return str(token or "")


@app.before_request
def enforce_csrf_protection():
    if not CSRF_PROTECTION_ENABLED or request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None
    expected = str(session.get("_csrf_token") or "")
    provided = request_csrf_token()
    if expected and provided and secrets.compare_digest(expected, provided):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Security token expired. Refresh the page and try again."}), 400
    abort(400)


def uploaded_file_size(upload: Any) -> int:
    stream = getattr(upload, "stream", None)
    if not stream:
        return 0
    try:
        pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = int(stream.tell())
        stream.seek(pos)
        return size
    except Exception:
        return int(getattr(upload, "content_length", 0) or 0)


def validate_upload_file(
    upload: Any,
    *,
    allowed_extensions: Set[str],
    allowed_mime_prefixes: Tuple[str, ...],
    max_bytes: int,
) -> Tuple[bool, str, str, str, int]:
    filename = secure_filename(str(getattr(upload, "filename", "") or ""))
    if not filename:
        return False, "Choose a file first.", "", "", 0
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        return False, "Unsupported file format.", filename, ext, 0
    size = uploaded_file_size(upload)
    if size and size > max_bytes:
        mb = max_bytes / (1024 * 1024)
        return False, f"File is too large. Maximum size is {mb:.0f} MB.", filename, ext, size
    mimetype = str(getattr(upload, "mimetype", "") or "").lower()
    if mimetype and allowed_mime_prefixes and not any(mimetype.startswith(prefix) for prefix in allowed_mime_prefixes):
        return False, "File type does not match the upload field.", filename, ext, size
    return True, "", filename, ext, size


SAFE_MARKDOWN_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "code",
    "pre",
    "hr",
]
SAFE_MARKDOWN_ATTRS = {"a": ["href", "title", "rel", "target"]}
SAFE_HTML_TAGS = [
    *SAFE_MARKDOWN_TAGS,
    "div",
    "section",
    "article",
    "aside",
    "span",
    "mark",
    "small",
    "sup",
    "sub",
    "u",
    "s",
    "h5",
    "h6",
    "figure",
    "figcaption",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "details",
    "summary",
]
SAFE_HTML_ATTRS = {
    "*": ["class", "id", "role", "aria-label", "aria-labelledby", "aria-describedby"],
    "a": ["href", "title", "rel", "target", "class", "id", "aria-label"],
    "img": ["src", "alt", "title", "loading", "width", "height", "class"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}


def render_safe_markdown(markdown_text: Any) -> str:
    source = clean_plain_text(markdown_text, 80000)
    if not source:
        return ""
    if markdown_lib is not None:
        raw = markdown_lib.markdown(source, extensions=["extra", "sane_lists"])
    else:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", source) if p.strip()]
        raw = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)
    if bleach is None:
        return raw
    cleaned = bleach.clean(raw, tags=SAFE_MARKDOWN_TAGS, attributes=SAFE_MARKDOWN_ATTRS, protocols=["http", "https", "mailto"], strip=True)
    return bleach.linkify(cleaned, callbacks=[bleach.callbacks.nofollow, bleach.callbacks.target_blank])


def render_safe_html(html_text: Any) -> str:
    source = clean_plain_text(html_text, 80000)
    if not source:
        return ""
    if bleach is None:
        return html.escape(source).replace("\n", "<br>")
    cleaned = bleach.clean(
        source,
        tags=SAFE_HTML_TAGS,
        attributes=SAFE_HTML_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return bleach.linkify(cleaned, callbacks=[bleach.callbacks.nofollow, bleach.callbacks.target_blank])


def html_to_plain_text(value: Any, limit: int = 20000) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def checkbox_enabled(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def load_admin_pages_data() -> Dict[str, Any]:
    if has_request_context():
        cached = getattr(g, "_admin_pages_data_cache", None)
        cached_path = getattr(g, "_admin_pages_data_cache_path", None)
        if cached_path == str(ADMIN_PAGES_PATH) and isinstance(cached, dict):
            return cached
    data = load_json(ADMIN_PAGES_PATH)
    if not isinstance(data, dict):
        data = {"pages": {}}
    pages = data.get("pages")
    if not isinstance(pages, dict):
        data["pages"] = {}
    if has_request_context():
        g._admin_pages_data_cache = data
        g._admin_pages_data_cache_path = str(ADMIN_PAGES_PATH)
    return data


def admin_page_key(
    page_type: str,
    *,
    country_slug: str = "",
    city_slug: str = "",
    place_slug: str = "",
    blog_slug: str = "",
) -> str:
    kind = str(page_type or "home").strip().lower()
    if kind == "country":
        return f"country:{country_slug}"
    if kind == "city":
        return f"city:{country_slug}:{city_slug}"
    if kind == "place":
        return f"place:{country_slug}:{city_slug}:{place_slug}"
    if kind == "blog":
        return f"blog:{blog_slug}"
    if kind in {"landing", "static", "custom"}:
        slug = blog_slug or place_slug or city_slug or country_slug
        return f"{kind}:{slug}" if slug else kind
    return "home"


def split_admin_page_key(page_key: str) -> Dict[str, str]:
    parts = str(page_key or "home").split(":")
    if not parts or parts[0] == "home":
        return {"type": "home", "country": "", "city": "", "place": "", "blog": ""}
    if parts[0] == "country":
        return {"type": "country", "country": parts[1] if len(parts) > 1 else "", "city": "", "place": "", "blog": ""}
    if parts[0] == "city":
        return {
            "type": "city",
            "country": parts[1] if len(parts) > 1 else "",
            "city": parts[2] if len(parts) > 2 else "",
            "place": "",
            "blog": "",
        }
    if parts[0] == "place":
        return {
            "type": "place",
            "country": parts[1] if len(parts) > 1 else "",
            "city": parts[2] if len(parts) > 2 else "",
            "place": parts[3] if len(parts) > 3 else "",
            "blog": "",
        }
    if parts[0] == "blog":
        return {"type": "blog", "country": "", "city": "", "place": "", "blog": parts[1] if len(parts) > 1 else ""}
    if parts[0] in {"landing", "static", "custom"}:
        return {"type": parts[0], "country": "", "city": "", "place": parts[1] if len(parts) > 1 else "", "blog": parts[1] if len(parts) > 1 else ""}
    return {"type": "home", "country": "", "city": "", "place": "", "blog": ""}


def normalize_faq_rows(questions: List[Any], answers: List[Any], visible_rows: Optional[List[Any]] = None, order_rows: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    visible_set = {str(v) for v in (visible_rows or [])}
    for idx, (q, a) in enumerate(zip(questions or [], answers or [])):
        question = clean_plain_text(q, 300)
        answer_html = render_safe_html(a)
        if not question or not html_to_plain_text(answer_html, 2000):
            continue
        try:
            order = int((order_rows or [])[idx])
        except Exception:
            order = idx + 1
        out.append({
            "question": question,
            "answerHtml": answer_html,
            "answer": html_to_plain_text(answer_html, 2000),
            "visible": str(idx) in visible_set if visible_rows is not None else True,
            "order": order,
        })
    out.sort(key=lambda row: int(row.get("order") or 0))
    return out[:20]


def load_admin_page_content(page_key: str, lang: str) -> Dict[str, Any]:
    lang = normalize_lang(lang)
    data = load_admin_pages_data()
    item = ((data.get("pages") or {}).get(page_key) or {}).get(lang) or {}
    faq = item.get("faq") if isinstance(item.get("faq"), list) else []
    faq_rows = [
        {
            "question": clean_plain_text(row.get("question"), 300),
            "answerHtml": render_safe_html(row.get("answerHtml") or row.get("answer") or ""),
            "answer": html_to_plain_text(row.get("answerHtml") or row.get("answer") or "", 2000),
            "visible": bool(row.get("visible", True)),
            "order": int(row.get("order") or idx + 1),
        }
        for idx, row in enumerate(faq)
        if isinstance(row, dict)
        and clean_plain_text(row.get("question"), 300)
        and html_to_plain_text(row.get("answerHtml") or row.get("answer") or "", 2000)
    ]
    faq_rows.sort(key=lambda row: int(row.get("order") or 0))
    seo_enabled = checkbox_enabled(item.get("seoTextEnabled")) if "seoTextEnabled" in item else bool(item.get("seoTextHtmlRaw") or item.get("seoTextMarkdown") or item.get("seo_text"))
    faq_enabled = checkbox_enabled(item.get("faqEnabled")) if "faqEnabled" in item else bool(faq_rows)
    comments_default_enabled = split_admin_page_key(page_key).get("type") not in {"static"}
    comments_enabled = checkbox_enabled(item.get("commentsEnabled")) if "commentsEnabled" in item else comments_default_enabled
    seo_title = clean_plain_text(item.get("seoTextTitle") or "", 220)
    seo_intro = clean_plain_text(item.get("seoTextIntro") or "", 500)
    seo_display_mode = str(item.get("seoDisplayMode") or "full").strip().lower()
    if seo_display_mode not in {"full", "collapsed", "accordion"}:
        seo_display_mode = "full"
    faq_title = clean_plain_text(item.get("faqTitle") or "Questions before you listen", 220)
    seo_markdown = clean_plain_text(item.get("seoTextMarkdown") or item.get("seo_text") or "", 80000)
    seo_html_raw = clean_plain_text(item.get("seoTextHtmlRaw") or "", 80000)
    h1 = clean_plain_text(item.get("h1") or "", 220)
    content_slug = clean_plain_text(item.get("slug") or "", 220)
    status = str(item.get("status") or "published").strip().lower()
    if status not in {"draft", "published", "scheduled", "archived"}:
        status = "published"
    canonical_mode = str(item.get("canonicalMode") or "self").strip().lower()
    if canonical_mode not in {"self", "custom", "inherited"}:
        canonical_mode = "self"
    redirect_type = str(item.get("redirectType") or "301").strip()
    if redirect_type not in {"301", "302", "307", "308"}:
        redirect_type = "301"
    seo_editor_mode = str(item.get("seoEditorMode") or "").strip().lower()
    if seo_editor_mode not in {"markdown", "html"}:
        seo_editor_mode = "html"
    seo_html = render_safe_html(seo_html_raw) if seo_editor_mode == "html" else render_safe_markdown(seo_markdown)
    return {
        "pageKey": page_key,
        "lang": lang,
        "seoEditorMode": seo_editor_mode,
        "seoTextMarkdown": seo_markdown,
        "seoTextHtmlRaw": seo_html_raw,
        "seoTextHtml": seo_html,
        "seoTextEnabled": seo_enabled,
        "seoTextTitle": seo_title,
        "seoTextIntro": seo_intro,
        "seoDisplayMode": seo_display_mode,
        "faqEnabled": faq_enabled,
        "commentsEnabled": comments_enabled,
        "faqTitle": faq_title,
        "h1": h1,
        "slug": content_slug,
        "status": status,
        "metaTitle": clean_plain_text(item.get("metaTitle") or "", 180),
        "metaDescription": clean_plain_text(item.get("metaDescription") or "", 240),
        "canonicalMode": canonical_mode,
        "canonicalUrl": clean_plain_text(item.get("canonicalUrl") or "", 500),
        "robotsIndex": bool(item.get("robotsIndex", True)),
        "robotsFollow": bool(item.get("robotsFollow", True)),
        "ogTitle": clean_plain_text(item.get("ogTitle") or "", 180),
        "ogDescription": clean_plain_text(item.get("ogDescription") or "", 240),
        "ogImage": clean_plain_text(item.get("ogImage") or "", 500),
        "twitterTitle": clean_plain_text(item.get("twitterTitle") or "", 180),
        "twitterDescription": clean_plain_text(item.get("twitterDescription") or "", 240),
        "twitterImage": clean_plain_text(item.get("twitterImage") or "", 500),
        "schemaJson": clean_plain_text(item.get("schemaJson") or "", 20000),
        "redirectEnabled": bool(item.get("redirectEnabled", False)),
        "redirectType": redirect_type,
        "redirectTarget": clean_plain_text(item.get("redirectTarget") or "", 500),
        "redirectNotes": clean_plain_text(item.get("redirectNotes") or "", 500),
        "sitemapIncluded": bool(item.get("sitemapIncluded", True)),
        "blocks": item.get("blocks") if isinstance(item.get("blocks"), list) else [],
        "faq": faq_rows,
        "visibleFaq": [row for row in faq_rows if row.get("visible", True)],
        "updatedAt": item.get("updatedAt") or "",
        "updatedBy": item.get("updatedBy") or "",
        "slugManuallyEdited": bool(item.get("slugManuallyEdited", False)),
    }


def admin_slug_conflict(page_key: str, lang: str, slug: str) -> Optional[str]:
    slug = slugify(slug)
    if not slug:
        return None
    current = split_admin_page_key(page_key)
    data = load_admin_pages_data()
    for other_key, by_lang in (data.get("pages") or {}).items():
        if other_key == page_key or not isinstance(by_lang, dict):
            continue
        item = by_lang.get(normalize_lang(lang)) or {}
        if not isinstance(item, dict) or slugify(item.get("slug") or "") != slug:
            continue
        other = split_admin_page_key(other_key)
        same_scope = other.get("type") == current.get("type")
        if current.get("type") == "city":
            same_scope = same_scope and other.get("country") == current.get("country")
        if current.get("type") == "place":
            same_scope = same_scope and other.get("country") == current.get("country") and other.get("city") == current.get("city")
        if same_scope:
            return other_key
    return None


def admin_validate_page_content(page_key: str, lang: str, *, h1: str, slug: str, seo_enabled: bool, seo_title: str, seo_html: str, faq_enabled: bool, faq_rows: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    clean_slug = slugify(slug or h1)
    if h1 and not clean_slug:
        errors.append("Slug could not be generated from H1.")
    if clean_slug and admin_slug_conflict(page_key, lang, clean_slug):
        errors.append(f"Duplicate slug in the same page scope: {clean_slug}.")
    if seo_enabled:
        if not clean_plain_text(seo_title, 220):
            errors.append("SEO text title is required when SEO text is enabled.")
        if not html_to_plain_text(seo_html, 120000):
            errors.append("SEO text content is required when SEO text is enabled.")
    if faq_enabled:
        visible = [row for row in faq_rows if row.get("visible", True)]
        if not visible:
            errors.append("FAQ needs at least one visible item when enabled.")
        questions = [normalize_place_name_key(row.get("question") or "") for row in visible]
        if len(questions) != len(set(questions)):
            errors.append("FAQ contains duplicate questions.")
    return errors


def save_admin_page_content(
    page_key: str,
    lang: str,
    seo_text_markdown: str,
    faq: List[Dict[str, Any]],
    *,
    seo_editor_mode: str = "markdown",
    seo_text_html_raw: str = "",
    h1: str = "",
    slug: str = "",
    seo_enabled: bool = True,
    seo_title: str = "",
    seo_intro: str = "",
    seo_display_mode: str = "full",
    faq_enabled: bool = True,
    faq_title: str = "Questions before you listen",
    slug_manually_edited: bool = False,
    status: str = "published",
    meta_title: str = "",
    meta_description: str = "",
    canonical_mode: str = "self",
    canonical_url: str = "",
    robots_index: bool = True,
    robots_follow: bool = True,
    og_title: str = "",
    og_description: str = "",
    og_image: str = "",
    twitter_title: str = "",
    twitter_description: str = "",
    twitter_image: str = "",
    schema_json: str = "",
    redirect_enabled: bool = False,
    redirect_type: str = "301",
    redirect_target: str = "",
    redirect_notes: str = "",
    sitemap_included: bool = True,
    comments_enabled: bool = True,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> None:
    lang = normalize_lang(lang)
    editor_mode = str(seo_editor_mode or "markdown").strip().lower()
    if editor_mode not in {"markdown", "html"}:
        editor_mode = "markdown"
    clean_h1 = clean_plain_text(h1, 220)
    clean_slug = slugify(slug or clean_h1)
    clean_html = render_safe_html(seo_text_html_raw)
    clean_display_mode = str(seo_display_mode or "full").strip().lower()
    if clean_display_mode not in {"full", "collapsed", "accordion"}:
        clean_display_mode = "full"
    clean_status = str(status or "published").strip().lower()
    if clean_status not in {"draft", "published", "scheduled", "archived"}:
        clean_status = "published"
    clean_canonical_mode = str(canonical_mode or "self").strip().lower()
    if clean_canonical_mode not in {"self", "custom", "inherited"}:
        clean_canonical_mode = "self"
    clean_redirect_type = str(redirect_type or "301").strip()
    if clean_redirect_type not in {"301", "302", "307", "308"}:
        clean_redirect_type = "301"
    clean_redirect_target = clean_plain_text(redirect_target, 500)
    clean_schema_json = clean_plain_text(schema_json, 20000)
    if clean_schema_json:
        try:
            json.loads(clean_schema_json)
        except Exception:
            clean_schema_json = ""
    data = load_admin_pages_data()
    pages = data.setdefault("pages", {})
    entry = pages.setdefault(page_key, {})
    entry[lang] = {
        "seoEditorMode": editor_mode,
        "seoTextMarkdown": clean_plain_text(seo_text_markdown, 80000),
        "seoTextHtmlRaw": clean_html,
        "seoTextEnabled": bool(seo_enabled),
        "seoTextTitle": clean_plain_text(seo_title, 220),
        "seoTextIntro": clean_plain_text(seo_intro, 500),
        "seoDisplayMode": clean_display_mode,
        "faqEnabled": bool(faq_enabled),
        "faqTitle": clean_plain_text(faq_title or "Questions before you listen", 220),
        "h1": clean_h1,
        "slug": clean_slug,
        "status": clean_status,
        "metaTitle": clean_plain_text(meta_title, 180),
        "metaDescription": clean_plain_text(meta_description, 240),
        "canonicalMode": clean_canonical_mode,
        "canonicalUrl": clean_plain_text(canonical_url, 500),
        "robotsIndex": bool(robots_index),
        "robotsFollow": bool(robots_follow),
        "ogTitle": clean_plain_text(og_title, 180),
        "ogDescription": clean_plain_text(og_description, 240),
        "ogImage": clean_plain_text(og_image, 500),
        "twitterTitle": clean_plain_text(twitter_title, 180),
        "twitterDescription": clean_plain_text(twitter_description, 240),
        "twitterImage": clean_plain_text(twitter_image, 500),
        "schemaJson": clean_schema_json,
        "redirectEnabled": bool(redirect_enabled),
        "redirectType": clean_redirect_type,
        "redirectTarget": clean_redirect_target,
        "redirectNotes": clean_plain_text(redirect_notes, 500),
        "sitemapIncluded": bool(sitemap_included),
        "commentsEnabled": bool(comments_enabled),
        "blocks": blocks if isinstance(blocks, list) else [],
        "slugManuallyEdited": bool(slug_manually_edited),
        "slugGeneratedFromH1": slugify(clean_h1),
        "lastSlugGeneratedAt": utc_now_iso(),
        "faq": faq[:20],
        "updatedAt": utc_now_iso(),
        "updatedBy": session.get("admin_email") or ADMIN_EMAIL if has_request_context() else ADMIN_EMAIL,
    }
    atomic_write_json(ADMIN_PAGES_PATH, data)
    if has_request_context():
        g._admin_pages_data_cache = data
        g._admin_pages_data_cache_path = str(ADMIN_PAGES_PATH)
    if clean_redirect_target and bool(redirect_enabled):
        source = admin_page_public_url_from_key(page_key, lang, fallback_slug=clean_slug)
        if source and source != clean_redirect_target:
            rows = [r for r in load_admin_redirects() if str(r.get("source") or "") != source]
            rows.insert(0, {
                "source": source,
                "target": clean_redirect_target,
                "code": int(clean_redirect_type),
                "language": lang,
                "notes": clean_plain_text(redirect_notes, 500),
                "active": True,
                "createdBy": session.get("admin_email") or ADMIN_EMAIL if has_request_context() else ADMIN_EMAIL,
                "createdAt": utc_now_iso(),
            })
            save_admin_redirects(rows)


def admin_content_for_public(page_key: str, lang: str) -> Dict[str, Any]:
    item = load_admin_page_content(page_key, lang)
    if not item.get("seoTextEnabled"):
        item["seoTextHtml"] = ""
    if not item.get("faqEnabled"):
        item["faq"] = []
        item["visibleFaq"] = []
    else:
        item["faq"] = [row for row in item.get("faq") or [] if row.get("visible", True)]
        item["visibleFaq"] = item["faq"]
    faq_schema = None
    if item["faq"]:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": row["question"],
                    "acceptedAnswer": {"@type": "Answer", "text": html_to_plain_text(row.get("answerHtml") or row.get("answer") or "", 2000)},
                }
                for row in item["faq"]
            ],
        }
    item["faqSchema"] = faq_schema
    return item


def faq_schema_for_items(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    visible_items = [row for row in items if row.get("question") and (row.get("answerHtml") or row.get("answer"))]
    if not visible_items:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": clean_plain_text(row.get("question") or "", 220),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": html_to_plain_text(row.get("answerHtml") or row.get("answer") or "", 2000),
                },
            }
            for row in visible_items
        ],
    }


def _faq_answer(text: str) -> str:
    return f"<p>{html.escape(clean_plain_text(text, 800))}</p>"


def _faq_names(values: List[Any], limit: int = 8) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for value in values or []:
        name = clean_plain_text(str(value or ""), 120)
        key = re.sub(r"\s+", " ", name).strip().lower()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _faq_list_html(values: List[str]) -> str:
    names = _faq_names(values, 10)
    if not names:
        return ""
    items = "".join(f"<li>{html.escape(name)}</li>" for name in names)
    return f"<ul>{items}</ul>"


def _faq_answer_html(paragraphs: List[str], bullet_values: Optional[List[str]] = None) -> str:
    parts: List[str] = []
    for paragraph in paragraphs or []:
        clean = clean_plain_text(paragraph or "", 900)
        if clean:
            parts.append(f"<p>{html.escape(clean)}</p>")
    if bullet_values:
        list_html = _faq_list_html(bullet_values)
        if list_html:
            parts.append(list_html)
    return "".join(parts) or "<p>Open the guide to listen for free and explore places on the map.</p>"


def faq_country_names_for_page(lang: str = "en", limit: int = 8) -> List[str]:
    rows = [
        country
        for country in top_countries(max(limit * 2, limit))
        if str(country.get("code") or "").lower() not in EXCLUDED_COUNTRY_CODES
    ]
    return _faq_names([country_display_name_cached_for_lang(country, lang) for country in rows], limit)


def faq_city_names_for_page(
    *,
    country_slug: str = "",
    lang: str = "en",
    limit: int = 8,
    exclude_city_slug: str = "",
) -> List[str]:
    country_slug = str(country_slug or "").strip().lower()
    exclude_city_slug = str(exclude_city_slug or "").strip().lower()
    rows = target_country_cities(country_slug, max(limit * 2, limit)) if country_slug else top_cities(max(limit * 3, limit))
    names: List[str] = []
    for city in rows:
        city_slug = str(city.get("citySlug") or slugify(city.get("name") or "")).strip().lower()
        if exclude_city_slug and city_slug == exclude_city_slug:
            continue
        names.append(city_display_name_cached_for_lang(city, lang))
    return _faq_names(names, limit)


def faq_place_names_for_page(
    *,
    country_slug: str = "",
    city_slug: str = "",
    lang: str = "en",
    limit: int = 8,
    exclude_place_slug: str = "",
) -> List[str]:
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    exclude_place_slug = str(exclude_place_slug or "").strip().lower()
    places: List[Dict[str, Any]] = []
    if country_slug and city_slug:
        for place in dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug), [])):
            if str(place.get("slug") or "").strip().lower() == exclude_place_slug:
                continue
            row = dict(place)
            row["countrySlug"] = country_slug
            row["citySlug"] = city_slug
            places.append(row)
            if len(places) >= max(limit * 2, limit):
                break
    elif country_slug:
        for city in target_country_cities(country_slug, TARGET_CITIES_PER_COUNTRY):
            current_city_slug = str(city.get("citySlug") or "").strip().lower()
            for place in dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, current_city_slug), [])):
                if str(place.get("slug") or "").strip().lower() == exclude_place_slug:
                    continue
                row = dict(place)
                row["countrySlug"] = country_slug
                row["citySlug"] = current_city_slug
                places.append(row)
                break
            if len(places) >= limit:
                break
    else:
        for place in landing_featured_places(max(limit * 2, limit)):
            row = dict(place)
            if str(row.get("slug") or "").strip().lower() == exclude_place_slug:
                continue
            places.append(row)
            if len(places) >= max(limit * 2, limit):
                break
    return _faq_names([place_display_name_cached_for_lang(place, lang) for place in places], limit)


def _home_faq_items_for_lang(lang: str) -> List[Dict[str, str]]:
    lang = normalize_lang(lang)
    copy: Dict[str, List[Tuple[str, str]]] = {
        "en": [
            ("What is SonicCity?", "SonicCity is a free audio guide for cities, countries and landmarks that you can listen to while travelling."),
            ("Can I listen to audio guides for free?", "Yes, you can listen to audio guides for free after signing up."),
            ("How do I find guides near me?", "Turn on GPS and SonicCity will show cities and places near your route."),
            ("Which languages are the audio guides available in?", "SonicCity supports English, French, Spanish, Italian, Ukrainian and German."),
            ("Can I listen while walking or travelling?", "Yes, the player stays active while you move between pages or explore the map."),
        ],
        "ua": [
            ("Що таке SonicCity?", "SonicCity — це безкоштовний аудіогід для міст, країн і визначних місць, який можна слухати під час подорожі."),
            ("Чи можна слухати аудіогіди безкоштовно?", "Так, аудіогіди можна слухати безкоштовно після реєстрації."),
            ("Як знайти гіди поруч зі мною?", "Увімкніть GPS, і SonicCity покаже міста та місця поблизу вашого маршруту."),
            ("Якими мовами доступні аудіогіди?", "SonicCity підтримує англійську, французьку, іспанську, італійську, українську та німецьку мови."),
            ("Чи можна слухати під час прогулянки або поїздки?", "Так, плеєр залишається активним, поки ви переходите між сторінками або досліджуєте карту."),
        ],
        "fr": [
            ("Qu’est-ce que SonicCity ?", "SonicCity est un audioguide gratuit pour les villes, les pays et les monuments, à écouter pendant le voyage."),
            ("Puis-je écouter les audioguides gratuitement ?", "Oui, vous pouvez écouter les audioguides gratuitement après inscription."),
            ("Comment trouver des guides près de moi ?", "Activez le GPS et SonicCity affichera les villes et les lieux proches de votre itinéraire."),
            ("Dans quelles langues les audioguides sont-ils disponibles ?", "SonicCity prend en charge l’anglais, le français, l’espagnol, l’italien, l’ukrainien et l’allemand."),
            ("Puis-je écouter pendant une promenade ou un trajet ?", "Oui, le lecteur reste actif lorsque vous passez d’une page à l’autre ou explorez la carte."),
        ],
        "es": [
            ("¿Qué es SonicCity?", "SonicCity es una audioguía gratuita para ciudades, países y lugares de interés que puedes escuchar mientras viajas."),
            ("¿Puedo escuchar las audioguías gratis?", "Sí, puedes escuchar las audioguías gratis después de registrarte."),
            ("¿Cómo encuentro guías cerca de mí?", "Activa el GPS y SonicCity mostrará ciudades y lugares cerca de tu ruta."),
            ("¿En qué idiomas están disponibles las audioguías?", "SonicCity admite inglés, francés, español, italiano, ucraniano y alemán."),
            ("¿Puedo escuchar durante un paseo o un viaje?", "Sí, el reproductor permanece activo mientras cambias de página o exploras el mapa."),
        ],
        "it": [
            ("Che cos’è SonicCity?", "SonicCity è un’audioguida gratuita per città, paesi e luoghi d’interesse, da ascoltare durante il viaggio."),
            ("Posso ascoltare le audioguide gratis?", "Sì, puoi ascoltare le audioguide gratuitamente dopo la registrazione."),
            ("Come trovo le guide vicino a me?", "Attiva il GPS e SonicCity mostrerà città e luoghi vicino al tuo percorso."),
            ("In quali lingue sono disponibili le audioguide?", "SonicCity supporta inglese, francese, spagnolo, italiano, ucraino e tedesco."),
            ("Posso ascoltare mentre cammino o viaggio?", "Sì, il player resta attivo mentre passi da una pagina all’altra o esplori la mappa."),
        ],
        "de": [
            ("Was ist SonicCity?", "SonicCity ist ein kostenloser Audioguide für Städte, Länder und Sehenswürdigkeiten, den du unterwegs hören kannst."),
            ("Kann ich die Audioguides kostenlos hören?", "Ja, du kannst die Audioguides nach der Registrierung kostenlos hören."),
            ("Wie finde ich Guides in meiner Nähe?", "Aktiviere GPS und SonicCity zeigt Städte und Orte in der Nähe deiner Route."),
            ("In welchen Sprachen sind die Audioguides verfügbar?", "SonicCity unterstützt Englisch, Französisch, Spanisch, Italienisch, Ukrainisch und Deutsch."),
            ("Kann ich beim Spazieren oder Fahren zuhören?", "Ja, der Player bleibt aktiv, während du zwischen Seiten wechselst oder die Karte erkundest."),
        ],
    }
    return [{"question": question, "answerHtml": _faq_answer_html([answer])} for question, answer in copy.get(lang, copy["en"])]


def _free_listening_faq_item(name: str, lang: str) -> Dict[str, str]:
    lang = normalize_lang(lang)
    name = clean_plain_text(name or "this guide", 160)
    if lang == "ua":
        question = f"Чи можу я слухати аудіогід про {name} безкоштовно?"
        answer = f"Так. Аудіогід про {name} можна слухати безкоштовно після реєстрації в SonicCity."
    elif lang == "fr":
        question = f"Puis-je écouter le guide audio de {name} gratuitement ?"
        answer = f"Oui. Vous pouvez écouter le guide audio de {name} gratuitement après inscription sur SonicCity."
    elif lang == "es":
        question = f"¿Puedo escuchar la audioguía de {name} gratis?"
        answer = f"Sí. Puedes escuchar la audioguía de {name} gratis después de registrarte en SonicCity."
    elif lang == "it":
        question = f"Posso ascoltare gratis l’audioguida di {name}?"
        answer = f"Sì. Puoi ascoltare l’audioguida di {name} gratuitamente dopo la registrazione a SonicCity."
    elif lang == "de":
        question = f"Kann ich den Audioguide zu {name} kostenlos hören?"
        answer = f"Ja. Du kannst den Audioguide zu {name} nach der Registrierung bei SonicCity kostenlos hören."
    else:
        question = f"Can I listen to the {name} audio guide for free?"
        answer = f"Yes. You can listen to the {name} audio guide for free after signing up to SonicCity."
    return {"question": question, "answerHtml": _faq_answer_html([answer])}


def auto_faq_for_page(
    page_type: str,
    *,
    lang: str = DEFAULT_LANG,
    country_name: str = "",
    city_name: str = "",
    place_name: str = "",
    country_names: Optional[List[str]] = None,
    city_names: Optional[List[str]] = None,
    place_names: Optional[List[str]] = None,
    related_place_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    page_type = str(page_type or "").strip().lower()
    lang = normalize_lang(lang)
    country_name = clean_plain_text(country_name or "this country", 120)
    city_name = clean_plain_text(city_name or "this city", 120)
    place_name = clean_plain_text(place_name or "this place", 160)
    country_names = _faq_names(country_names or [], 8)
    city_names = _faq_names(city_names or [], 8)
    place_names = _faq_names(place_names or [], 8)
    related_place_names = _faq_names(related_place_names or [], 8)

    if page_type == "home":
        trn = t(lang)
        items = _home_faq_items_for_lang(lang)
        title = trn.get("landing_faq_title") or "FAQ"
    elif page_type == "country":
        copy = {
            "en": {
                "title": "{country} audio guide questions",
                "cities_q": "Which cities can I listen to in {country}?",
                "cities_p1": "The {country} guide starts with population-ranked cities and turns them into short audio stories for planning, walking and road trips.",
                "cities_p2": "Cities to explore in {country} include:",
                "places_q": "What places can I hear about in {country}?",
                "places_p1": "SonicCity highlights landmarks, museums, churches, parks, viewpoints and historic places across selected cities in {country}.",
                "places_p2": "Popular place audio guides include:",
                "travel_q": "Can I use the guide while travelling through {country}?",
                "travel_a": "Yes. Open a city or place in {country}, press Play and keep the bottom player active while you move through maps, related places and other pages.",
                "langs_q": "Which languages are available for {country} guides?",
                "langs_a": "Guides can be prepared in English, French, Spanish, Italian, Ukrainian and German when audio is available.",
            },
            "ua": {
                "title": "Питання про аудіогід {country}",
                "cities_q": "Які міста можна слухати в {country}?",
                "cities_p1": "Гід {country} починається з міст, відібраних за населенням, і перетворює їх на короткі аудіоісторії для планування, прогулянок і поїздок.",
                "cities_p2": "Міста для дослідження в {country}:",
                "places_q": "Про які місця можна послухати в {country}?",
                "places_p1": "SonicCity показує памʼятки, музеї, церкви, парки, оглядові точки та історичні місця у вибраних містах {country}.",
                "places_p2": "Популярні аудіогіди місць:",
                "travel_q": "Чи можна користуватися гідом під час подорожі {country}?",
                "travel_a": "Так. Відкрийте місто або місце в {country}, натисніть Play і тримайте нижній плеєр активним під час мап, повʼязаних місць та інших сторінок.",
                "langs_q": "Якими мовами доступні гіди {country}?",
                "langs_a": "Коли аудіо доступне, гіди можна підготувати англійською, французькою, іспанською, італійською, українською та німецькою.",
            },
            "fr": {
                "title": "Questions sur le guide audio de {country}",
                "cities_q": "Quelles villes puis-je écouter en {country} ?",
                "cities_p1": "Le guide de {country} commence par des villes classées par population et les transforme en courts récits audio.",
                "cities_p2": "Villes à explorer en {country} :",
                "places_q": "Quels lieux puis-je écouter en {country} ?",
                "places_p1": "SonicCity met en avant monuments, musées, églises, parcs, points de vue et lieux historiques dans les villes sélectionnées de {country}.",
                "places_p2": "Guides audio de lieux populaires :",
                "travel_q": "Puis-je utiliser le guide en voyageant en {country} ?",
                "travel_a": "Oui. Ouvrez une ville ou un lieu en {country}, appuyez sur Lecture et gardez le lecteur actif pendant que vous explorez cartes et pages liées.",
                "langs_q": "Quelles langues sont disponibles pour les guides de {country} ?",
                "langs_a": "Les guides peuvent être préparés en anglais, français, espagnol, italien, ukrainien et allemand lorsque l’audio est disponible.",
            },
            "es": {
                "title": "Preguntas sobre la audioguía de {country}",
                "cities_q": "¿Qué ciudades puedo escuchar en {country}?",
                "cities_p1": "La guía de {country} empieza con ciudades clasificadas por población y las convierte en historias de audio cortas.",
                "cities_p2": "Ciudades para explorar en {country}:",
                "places_q": "¿Qué lugares puedo escuchar en {country}?",
                "places_p1": "SonicCity destaca monumentos, museos, iglesias, parques, miradores y lugares históricos en ciudades seleccionadas de {country}.",
                "places_p2": "Audioguías populares de lugares:",
                "travel_q": "¿Puedo usar la guía mientras viajo por {country}?",
                "travel_a": "Sí. Abre una ciudad o lugar en {country}, pulsa Play y mantén activo el reproductor inferior mientras exploras mapas y páginas relacionadas.",
                "langs_q": "¿Qué idiomas están disponibles para las guías de {country}?",
                "langs_a": "Las guías pueden prepararse en inglés, francés, español, italiano, ucraniano y alemán cuando el audio está disponible.",
            },
            "it": {
                "title": "Domande sull’audioguida di {country}",
                "cities_q": "Quali città posso ascoltare in {country}?",
                "cities_p1": "La guida di {country} parte dalle città ordinate per popolazione e le trasforma in brevi storie audio.",
                "cities_p2": "Città da esplorare in {country}:",
                "places_q": "Quali luoghi posso ascoltare in {country}?",
                "places_p1": "SonicCity evidenzia monumenti, musei, chiese, parchi, punti panoramici e luoghi storici nelle città selezionate di {country}.",
                "places_p2": "Audioguide popolari dei luoghi:",
                "travel_q": "Posso usare la guida mentre viaggio in {country}?",
                "travel_a": "Sì. Apri una città o un luogo in {country}, premi Play e mantieni attivo il player mentre esplori mappe e pagine collegate.",
                "langs_q": "Quali lingue sono disponibili per le guide di {country}?",
                "langs_a": "Le guide possono essere preparate in inglese, francese, spagnolo, italiano, ucraino e tedesco quando l’audio è disponibile.",
            },
            "de": {
                "title": "Fragen zum Audioguide für {country}",
                "cities_q": "Welche Städte kann ich in {country} anhören?",
                "cities_p1": "Der {country}-Guide beginnt mit nach Einwohnerzahl sortierten Städten und macht daraus kurze Audiogeschichten.",
                "cities_p2": "Städte zum Erkunden in {country}:",
                "places_q": "Welche Orte kann ich in {country} anhören?",
                "places_p1": "SonicCity zeigt Sehenswürdigkeiten, Museen, Kirchen, Parks, Aussichtspunkte und historische Orte in ausgewählten Städten von {country}.",
                "places_p2": "Beliebte Orts-Audioguides:",
                "travel_q": "Kann ich den Guide während einer Reise durch {country} nutzen?",
                "travel_a": "Ja. Öffne eine Stadt oder einen Ort in {country}, drücke Play und nutze den unteren Player weiter, während du Karten und verwandte Seiten öffnest.",
                "langs_q": "Welche Sprachen gibt es für {country}-Guides?",
                "langs_a": "Guides können auf Englisch, Französisch, Spanisch, Italienisch, Ukrainisch und Deutsch vorbereitet werden, wenn Audio verfügbar ist.",
            },
        }.get(lang, {})
        copy = copy or {
            "title": "{country} audio guide questions",
            "cities_q": "Which cities can I listen to in {country}?",
            "cities_p1": "The {country} guide starts with population-ranked cities and turns them into short audio stories for planning, walking and road trips.",
            "cities_p2": "Cities to explore in {country} include:",
            "places_q": "What places can I hear about in {country}?",
            "places_p1": "SonicCity highlights landmarks, museums, churches, parks, viewpoints and historic places across selected cities in {country}.",
            "places_p2": "Popular place audio guides include:",
            "travel_q": "Can I use the guide while travelling through {country}?",
            "travel_a": "Yes. Open a city or place in {country}, press Play and keep the bottom player active while you move through maps, related places and other pages.",
            "langs_q": "Which languages are available for {country} guides?",
            "langs_a": "Guides can be prepared in English, French, Spanish, Italian, Ukrainian and German when audio is available.",
        }
        items = [
            _free_listening_faq_item(country_name, lang),
            {
                "question": copy["cities_q"].format(country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy["cities_p1"].format(country=country_name),
                        copy["cities_p2"].format(country=country_name),
                    ],
                    city_names,
                ),
            },
            {
                "question": copy["places_q"].format(country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy["places_p1"].format(country=country_name),
                        copy["places_p2"].format(country=country_name),
                    ],
                    place_names,
                ),
            },
            {
                "question": copy["travel_q"].format(country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy["travel_a"].format(country=country_name)
                    ]
                ),
            },
            {
                "question": copy["langs_q"].format(country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy["langs_a"].format(country=country_name)
                    ]
                ),
            },
        ]
        title = copy["title"].format(country=country_name)
    elif page_type == "city":
        copy = {
            "en": ("{city} audio guide questions", "What is included in the {city} Audio Guide?", "The {city} Audio Guide includes short stories about history, landmarks, culture and nearby places in {city}, {country}.", "You can start with the playlist or choose a place from the map.", "Which places can I listen to in {city}?", "The {city} page connects the playlist with places on the map, so you can listen to landmarks one by one.", "Places available around {city} include:", "Does {city} have a map of places?", "Yes. The city page includes a map with places you can open, save, route to and listen to. Use the fullscreen map when you want a larger view.", "What other cities near {city} are useful for planning?", "If you are planning a wider trip in {country}, you can jump from {city} to other city audio guides in the same country.", "Can I continue listening to {city} later?", "Yes. If you are logged in, SonicCity saves your listening progress for {city}. Open your account to continue from the last topic and timestamp."),
            "ua": ("Питання про аудіогід {city}", "Що входить в аудіогід {city}?", "Аудіогід {city} містить короткі історії про історію, памʼятки, культуру і місця поруч у {city}, {country}.", "Можна почати з плейлиста або обрати місце на мапі.", "Про які місця можна послухати в {city}?", "Сторінка {city} поєднує плейлист із місцями на мапі, тому памʼятки можна слухати по черзі.", "Місця навколо {city}: ", "Чи є в {city} мапа місць?", "Так. Сторінка міста має мапу з місцями, які можна відкрити, зберегти, прокласти маршрут і слухати.", "Які ще міста поруч із {city} корисні для планування?", "Якщо плануєте ширшу подорож {country}, з {city} можна перейти до інших міських аудіогідів цієї країни.", "Чи можу я продовжити слухати {city} пізніше?", "Так. Якщо ви увійшли в акаунт, SonicCity зберігає прогрес прослуховування {city}."),
            "fr": ("Questions sur le guide audio de {city}", "Que contient le guide audio de {city} ?", "Le guide audio de {city} comprend de courts récits sur l’histoire, les monuments, la culture et les lieux proches à {city}, {country}.", "Vous pouvez commencer par la playlist ou choisir un lieu sur la carte.", "Quels lieux puis-je écouter à {city} ?", "La page de {city} relie la playlist aux lieux sur la carte pour écouter les monuments un par un.", "Lieux disponibles autour de {city} :", "{city} a-t-elle une carte des lieux ?", "Oui. La page de la ville inclut une carte avec des lieux à ouvrir, enregistrer, rejoindre et écouter.", "Quelles autres villes près de {city} sont utiles pour planifier ?", "Pour un voyage plus large en {country}, vous pouvez passer de {city} à d’autres guides de villes du même pays.", "Puis-je continuer à écouter {city} plus tard ?", "Oui. Si vous êtes connecté, SonicCity enregistre votre progression d’écoute pour {city}."),
            "es": ("Preguntas sobre la audioguía de {city}", "¿Qué incluye la audioguía de {city}?", "La audioguía de {city} incluye historias breves sobre historia, lugares, cultura y sitios cercanos en {city}, {country}.", "Puedes empezar con la lista o elegir un lugar en el mapa.", "¿Qué lugares puedo escuchar en {city}?", "La página de {city} conecta la lista con lugares del mapa para escucharlos uno por uno.", "Lugares disponibles alrededor de {city}:", "¿{city} tiene un mapa de lugares?", "Sí. La página incluye un mapa con lugares que puedes abrir, guardar, enrutar y escuchar.", "¿Qué otras ciudades cerca de {city} sirven para planificar?", "Si planeas un viaje más amplio por {country}, puedes saltar de {city} a otras audioguías del país.", "¿Puedo seguir escuchando {city} más tarde?", "Sí. Si inicias sesión, SonicCity guarda tu progreso de escucha de {city}."),
            "it": ("Domande sull’audioguida di {city}", "Cosa include l’audioguida di {city}?", "L’audioguida di {city} include brevi storie su storia, luoghi, cultura e posti vicini a {city}, {country}.", "Puoi iniziare dalla playlist o scegliere un luogo sulla mappa.", "Quali luoghi posso ascoltare a {city}?", "La pagina di {city} collega la playlist ai luoghi sulla mappa per ascoltarli uno alla volta.", "Luoghi disponibili intorno a {city}:", "{city} ha una mappa dei luoghi?", "Sì. La pagina include una mappa con luoghi da aprire, salvare, raggiungere e ascoltare.", "Quali altre città vicino a {city} sono utili per pianificare?", "Se pianifichi un viaggio più ampio in {country}, puoi passare da {city} ad altre audioguide dello stesso paese.", "Posso continuare ad ascoltare {city} più tardi?", "Sì. Se hai effettuato l’accesso, SonicCity salva il progresso di ascolto per {city}."),
            "de": ("Fragen zum Audioguide für {city}", "Was enthält der {city}-Audioguide?", "Der {city}-Audioguide enthält kurze Geschichten über Geschichte, Sehenswürdigkeiten, Kultur und nahe Orte in {city}, {country}.", "Du kannst mit der Playlist starten oder einen Ort auf der Karte wählen.", "Welche Orte kann ich in {city} anhören?", "Die {city}-Seite verbindet Playlist und Karte, damit du Sehenswürdigkeiten nacheinander hören kannst.", "Orte rund um {city}:", "Hat {city} eine Karte mit Orten?", "Ja. Die Stadtseite enthält eine Karte mit Orten, die du öffnen, speichern, routen und anhören kannst.", "Welche anderen Städte nahe {city} sind für die Planung nützlich?", "Wenn du eine größere Reise in {country} planst, kannst du von {city} zu anderen Stadtguides im selben Land wechseln.", "Kann ich {city} später weiterhören?", "Ja. Wenn du angemeldet bist, speichert SonicCity deinen Hörfortschritt für {city}."),
        }.get(lang)
        if not copy:
            copy = ("{city} audio guide questions", "What is included in the {city} Audio Guide?", "The {city} Audio Guide includes short stories about history, landmarks, culture and nearby places in {city}, {country}.", "You can start with the playlist or choose a place from the map.", "Which places can I listen to in {city}?", "The {city} page connects the playlist with places on the map, so you can listen to landmarks one by one.", "Places available around {city} include:", "Does {city} have a map of places?", "Yes. The city page includes a map with places you can open, save, route to and listen to. Use the fullscreen map when you want a larger view.", "What other cities near {city} are useful for planning?", "If you are planning a wider trip in {country}, you can jump from {city} to other city audio guides in the same country.", "Can I continue listening to {city} later?", "Yes. If you are logged in, SonicCity saves your listening progress for {city}.")
        items = [
            _free_listening_faq_item(city_name, lang),
            {
                "question": copy[1].format(city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[2].format(city=city_name, country=country_name),
                        copy[3].format(city=city_name, country=country_name)
                    ]
                ),
            },
            {
                "question": copy[4].format(city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[5].format(city=city_name, country=country_name),
                        copy[6].format(city=city_name, country=country_name),
                    ],
                    place_names,
                ),
            },
            {
                "question": copy[7].format(city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[8].format(city=city_name, country=country_name)
                    ]
                ),
            },
            {
                "question": copy[9].format(city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[10].format(city=city_name, country=country_name),
                    ],
                    city_names,
                ),
            },
            {
                "question": copy[11].format(city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[12].format(city=city_name, country=country_name)
                    ]
                ),
            },
        ]
        title = copy[0].format(city=city_name, country=country_name)
    elif page_type == "place":
        copy = {
            "en": ("{place} audio guide questions", "What can I hear about {place}?", "You can listen to a focused audio story about {place}, with context for visiting it in {city}, {country}. The story is designed to be useful before you arrive or while you are already nearby.", "Can I open {place} on the map?", "Yes. The page includes a map so you can see where {place} is in {city}, open nearby landmarks and continue listening without leaving the guide.", "What else can I explore near {place}?", "After {place}, continue with nearby places in {city}. Good next stops include:", "Can I save {place} and return later?", "Yes. Use Save to add {place} to your Saved guides. If you are logged in, SonicCity can also keep your listening progress."),
            "ua": ("Питання про аудіогід {place}", "Що можна послухати про {place}?", "Ви можете послухати сфокусовану аудіоісторію про {place} з контекстом для відвідування в {city}, {country}.", "Чи можна відкрити {place} на мапі?", "Так. На сторінці є мапа, щоб побачити, де розташований {place} у {city}, відкрити місця поруч і слухати далі.", "Що ще можна дослідити поруч із {place}?", "Після {place} продовжуйте з місцями поруч у {city}. Хороші наступні зупинки:", "Чи можна зберегти {place} і повернутися пізніше?", "Так. Натисніть Save, щоб додати {place} у збережені гіди. Якщо ви увійшли, SonicCity також збереже прогрес прослуховування."),
            "fr": ("Questions sur le guide audio de {place}", "Que puis-je écouter sur {place} ?", "Vous pouvez écouter un récit audio ciblé sur {place}, avec le contexte de visite à {city}, {country}.", "Puis-je ouvrir {place} sur la carte ?", "Oui. La page inclut une carte pour situer {place} à {city}, ouvrir les lieux proches et continuer l’écoute.", "Que puis-je explorer près de {place} ?", "Après {place}, continuez avec des lieux proches à {city}. Bons arrêts suivants :", "Puis-je enregistrer {place} et revenir plus tard ?", "Oui. Utilisez Save pour ajouter {place} à vos guides enregistrés. Connecté, SonicCity garde aussi votre progression."),
            "es": ("Preguntas sobre la audioguía de {place}", "¿Qué puedo escuchar sobre {place}?", "Puedes escuchar una historia de audio centrada en {place}, con contexto para visitarlo en {city}, {country}.", "¿Puedo abrir {place} en el mapa?", "Sí. La página incluye un mapa para ver dónde está {place} en {city}, abrir lugares cercanos y seguir escuchando.", "¿Qué más puedo explorar cerca de {place}?", "Después de {place}, continúa con lugares cercanos en {city}. Buenas paradas siguientes:", "¿Puedo guardar {place} y volver más tarde?", "Sí. Usa Save para añadir {place} a tus guías guardadas. Si inicias sesión, SonicCity también guarda tu progreso."),
            "it": ("Domande sull’audioguida di {place}", "Cosa posso ascoltare su {place}?", "Puoi ascoltare una storia audio mirata su {place}, con contesto per visitarlo a {city}, {country}.", "Posso aprire {place} sulla mappa?", "Sì. La pagina include una mappa per vedere dove si trova {place} a {city}, aprire luoghi vicini e continuare ad ascoltare.", "Cos’altro posso esplorare vicino a {place}?", "Dopo {place}, continua con luoghi vicini a {city}. Buone prossime tappe:", "Posso salvare {place} e tornare più tardi?", "Sì. Usa Save per aggiungere {place} alle guide salvate. Se hai effettuato l’accesso, SonicCity salva anche il progresso."),
            "de": ("Fragen zum Audioguide für {place}", "Was kann ich über {place} hören?", "Du kannst eine fokussierte Audiogeschichte über {place} hören, mit Kontext für den Besuch in {city}, {country}.", "Kann ich {place} auf der Karte öffnen?", "Ja. Die Seite enthält eine Karte, damit du siehst, wo {place} in {city} liegt, nahe Orte öffnen und weiterhören kannst.", "Was kann ich in der Nähe von {place} erkunden?", "Nach {place} kannst du mit nahen Orten in {city} fortfahren. Gute nächste Stopps:", "Kann ich {place} speichern und später zurückkehren?", "Ja. Nutze Save, um {place} zu deinen gespeicherten Guides hinzuzufügen. Wenn du angemeldet bist, speichert SonicCity auch deinen Fortschritt."),
        }.get(lang)
        if not copy:
            copy = ("{place} audio guide questions", "What can I hear about {place}?", "You can listen to a focused audio story about {place}, with context for visiting it in {city}, {country}.", "Can I open {place} on the map?", "Yes. The page includes a map so you can see where {place} is in {city}, open nearby landmarks and continue listening without leaving the guide.", "What else can I explore near {place}?", "After {place}, continue with nearby places in {city}. Good next stops include:", "Can I save {place} and return later?", "Yes. Use Save to add {place} to your Saved guides. If you are logged in, SonicCity can also keep your listening progress.")
        items = [
            {
                "question": copy[1].format(place=place_name, city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[2].format(place=place_name, city=city_name, country=country_name)
                    ]
                ),
            },
            _free_listening_faq_item(place_name, lang),
            {
                "question": copy[3].format(place=place_name, city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[4].format(place=place_name, city=city_name, country=country_name)
                    ]
                ),
            },
            {
                "question": copy[5].format(place=place_name, city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[6].format(place=place_name, city=city_name, country=country_name),
                    ],
                    related_place_names or place_names,
                ),
            },
            {
                "question": copy[7].format(place=place_name, city=city_name, country=country_name),
                "answerHtml": _faq_answer_html(
                    [
                        copy[8].format(place=place_name, city=city_name, country=country_name)
                    ]
                ),
            },
        ]
        title = copy[0].format(place=place_name, city=city_name, country=country_name)
    else:
        return {}

    return {
        "id": f"{page_type}Faq",
        "title": title,
        "items": items,
    }


def schema_lang(lang: str) -> str:
    lang = normalize_lang(lang)
    return HREFLANG_CODE_BY_LANG.get(lang, lang)


def schema_abs_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return absolute_url("/")
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return absolute_url(value)


def schema_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def schema_clean(node: Any) -> Any:
    if isinstance(node, dict):
        out: Dict[str, Any] = {}
        for key, value in node.items():
            cleaned = schema_clean(value)
            if cleaned in ({}, [], None, ""):
                continue
            out[key] = cleaned
        return out
    if isinstance(node, list):
        return [item for item in (schema_clean(item) for item in node) if item not in ({}, [], None, "")]
    return node


def schema_site_nodes(lang: str) -> List[Dict[str, Any]]:
    org_id = absolute_url("/#organization")
    site_id = absolute_url("/#website")
    logo_url = absolute_url("/static/img/soniccity-logo.png")
    return [
        {
            "@type": ["Organization", "TravelAgency"],
            "@id": org_id,
            "name": BRAND_NAME,
            "url": absolute_url("/"),
            "email": CONTACT_EMAIL,
            "logo": {"@type": "ImageObject", "url": logo_url},
            "contactPoint": {
                "@type": "ContactPoint",
                "email": CONTACT_EMAIL,
                "contactType": "customer support",
                "availableLanguage": ["en", "fr", "es", "it", "uk", "de"],
            },
        },
        {
            "@type": "WebSite",
            "@id": site_id,
            "name": BRAND_NAME,
            "url": absolute_url("/"),
            "inLanguage": schema_lang(lang),
            "publisher": {"@id": org_id},
            "potentialAction": {
                "@type": "SearchAction",
                "target": absolute_url("/?q={search_term_string}"),
                "query-input": "required name=search_term_string",
            },
        },
    ]


def schema_image_node(image_url: str, page_url: str, caption: str = "") -> Optional[Dict[str, Any]]:
    if not image_url:
        return None
    return {
        "@type": "ImageObject",
        "@id": f"{schema_abs_url(page_url)}#primaryimage",
        "url": schema_abs_url(image_url),
        "caption": clean_plain_text(caption, 180),
    }


def schema_breadcrumb_node(page_url: str, items: List[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
    clean_items = [(clean_plain_text(name, 160), url) for name, url in items if name and url]
    if len(clean_items) < 2:
        return None
    return {
        "@type": "BreadcrumbList",
        "@id": f"{schema_abs_url(page_url)}#breadcrumb",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": idx,
                "name": name,
                "item": schema_abs_url(url),
            }
            for idx, (name, url) in enumerate(clean_items, 1)
        ],
    }


def schema_faq_node(faq_schema: Optional[Dict[str, Any]], page_url: str) -> Optional[Dict[str, Any]]:
    if not faq_schema or not faq_schema.get("mainEntity"):
        return None
    node = dict(faq_schema)
    node.pop("@context", None)
    node["@id"] = f"{schema_abs_url(page_url)}#faq"
    return node


def schema_item_list_node(name: str, page_url: str, fragment: str, items: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for idx, item in enumerate(items, 1):
        item_name = clean_plain_text(item.get("name") or "", 180)
        item_url = item.get("url") or ""
        if not item_name or not item_url:
            continue
        entries.append({"@type": "ListItem", "position": idx, "name": item_name, "url": schema_abs_url(item_url)})
    if not entries:
        return None
    return {
        "@type": "ItemList",
        "@id": f"{schema_abs_url(page_url)}#{fragment}",
        "name": clean_plain_text(name, 180),
        "itemListElement": entries,
    }


def schema_geo_node(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lat = schema_float(row.get("lat") or row.get("latitude"))
    lon = schema_float(row.get("lon") or row.get("lng") or row.get("longitude"))
    if lat is None or lon is None:
        return None
    return {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}


def schema_place_types(category: str = "") -> List[str]:
    key = str(category or "").strip().lower()
    if "museum" in key:
        return ["Museum", "TouristAttraction", "Place"]
    if "park" in key or "garden" in key:
        return ["Park", "TouristAttraction", "Place"]
    if "church" in key or "cathedral" in key or "mosque" in key or "synagogue" in key:
        return ["PlaceOfWorship", "TouristAttraction", "Place"]
    return ["TouristAttraction", "Place"]


def schema_audio_manifest(
    *,
    lang: str,
    country_slug: str,
    city_slug: str,
    place_slug: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    for gender in ("female", "male"):
        manifest_path = audio_manifest_path(
            version=AUDIO_BUILD_AUDIO_VERSION,
            lang=lang,
            gender=gender,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
        )
        if not manifest_path.exists():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sections"), list) and data.get("sections"):
                return data, gender
        except Exception:
            continue
    return None, ""


def schema_audio_objects_for_page(
    *,
    page_url: str,
    entity_name: str,
    lang: str,
    country_slug: str,
    city_slug: str,
    place_slug: Optional[str] = None,
    limit: int = 24,
) -> List[Dict[str, Any]]:
    manifest, gender = schema_audio_manifest(
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )
    if not manifest:
        return []
    objects: List[Dict[str, Any]] = []
    base_parts = ["static", "audio", AUDIO_BUILD_AUDIO_VERSION, lang, gender, country_slug, city_slug]
    if place_slug:
        base_parts.append(place_slug)
    for idx, section in enumerate(manifest.get("sections") or [], 1):
        if len(objects) >= limit or not isinstance(section, dict):
            break
        chunks = [chunk for chunk in section.get("chunks") or [] if isinstance(chunk, dict) and chunk.get("file") and str(chunk.get("status") or "ready") != "failed"]
        if not chunks:
            continue
        section_title = clean_plain_text(section.get("title") or f"Audio story {idx}", 140)
        first_file = clean_plain_text(chunks[0].get("file") or "", 180)
        if not first_file:
            continue
        content_url = "/" + "/".join(base_parts + [first_file])
        objects.append(
            {
                "@type": "AudioObject",
                "@id": f"{schema_abs_url(page_url)}#audio-{idx}",
                "name": f"{entity_name}: {section_title}",
                "description": f"Free SonicCity audio story about {entity_name}.",
                "contentUrl": schema_abs_url(content_url),
                "encodingFormat": "audio/mpeg",
                "inLanguage": schema_lang(lang),
                "isAccessibleForFree": True,
                "isPartOf": {"@id": f"{schema_abs_url(page_url)}#webpage"},
                "about": {"@id": f"{schema_abs_url(page_url)}#main-entity"},
            }
        )
    return objects


def audio_rating_key(entity_type: str, country_slug: str = "", city_slug: str = "", place_slug: str = "") -> str:
    parts = [clean_plain_text(entity_type, 30), clean_plain_text(country_slug, 80), clean_plain_text(city_slug, 80), clean_plain_text(place_slug, 100)]
    return ":".join([re.sub(r"[^a-z0-9_-]+", "-", part.lower()).strip("-") for part in parts if part]).strip(":")


def audio_rating_stats(entity_type: str, country_slug: str = "", city_slug: str = "", place_slug: str = "") -> Dict[str, Any]:
    key = audio_rating_key(entity_type, country_slug, city_slug, place_slug)
    values: List[int] = []
    newest = ""
    for row in cms_collection_rows("audioRatings"):
        if str(row.get("entityKey") or "") != key:
            continue
        if str(row.get("status") or "approved").lower() in {"spam", "rejected", "deleted"}:
            continue
        try:
            value = int(row.get("rating") or 0)
        except Exception:
            value = 0
        if 1 <= value <= 5:
            values.append(value)
            newest = max(newest, str(row.get("createdAt") or ""))
    avg = (sum(values) / len(values)) if values else 0.0
    return {
        "key": key,
        "ratings": len(values),
        "ratingAverage": avg,
        "ratingPercent": max(0, min(100, int(round((avg / 5) * 100)))) if values else 0,
        "ratingLabel": f"{avg:.1f}" if values else "0.0",
        "lastRating": newest,
    }


def schema_rating_nodes(stats: Optional[Dict[str, Any]], item_id: str, page_url: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    if not stats or int(stats.get("ratings") or 0) <= 0:
        return None, []
    rating = {
        "@type": "AggregateRating",
        "ratingValue": round(float(stats.get("ratingAverage") or 0), 1),
        "ratingCount": int(stats.get("ratings") or 0),
        "bestRating": 5,
        "worstRating": 1,
    }
    review = {
        "@type": "Review",
        "@id": f"{schema_abs_url(page_url)}#audio-review",
        "itemReviewed": {"@id": item_id},
        "reviewRating": {
            "@type": "Rating",
            "ratingValue": round(float(stats.get("ratingAverage") or 0), 1),
            "bestRating": 5,
            "worstRating": 1,
        },
        "author": {"@type": "Organization", "name": "SonicCity listeners"},
    }
    if stats.get("lastRating"):
        review["datePublished"] = stats["lastRating"]
    return rating, [review]


def schema_graph(
    *,
    page_type: str,
    lang: str,
    page_url: str,
    title: str,
    description: str = "",
    image_url: str = "",
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
    faq_schema: Optional[Dict[str, Any]] = None,
    main_entity: Optional[Dict[str, Any]] = None,
    item_lists: Optional[List[Dict[str, Any]]] = None,
    audio_objects: Optional[List[Dict[str, Any]]] = None,
    rating_stats: Optional[Dict[str, Any]] = None,
    extra_nodes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    page_abs = schema_abs_url(page_url)
    graph: List[Dict[str, Any]] = schema_site_nodes(lang)
    page_node = {
        "@type": page_type,
        "@id": f"{page_abs}#webpage",
        "name": clean_plain_text(title, 220),
        "description": clean_plain_text(description, 500),
        "url": page_abs,
        "inLanguage": schema_lang(lang),
        "isPartOf": {"@id": absolute_url("/#website")},
        "publisher": {"@id": absolute_url("/#organization")},
    }
    image_node = schema_image_node(image_url, page_url, title)
    if image_node:
        page_node["primaryImageOfPage"] = {"@id": image_node["@id"]}
        graph.append(image_node)
    if main_entity:
        main_entity = dict(main_entity)
        main_entity.setdefault("@id", f"{page_abs}#main-entity")
        rating, review_nodes = schema_rating_nodes(rating_stats, str(main_entity.get("@id") or f"{page_abs}#main-entity"), page_url)
        if rating:
            main_entity["aggregateRating"] = rating
            graph.extend(review_nodes)
        page_node["mainEntity"] = {"@id": main_entity["@id"]}
        graph.append(main_entity)
    graph.append(page_node)
    breadcrumb = schema_breadcrumb_node(page_url, breadcrumbs or [])
    if breadcrumb:
        graph.append(breadcrumb)
    faq_node = schema_faq_node(faq_schema, page_url)
    if faq_node:
        graph.append(faq_node)
    graph.extend(item_lists or [])
    graph.extend(audio_objects or [])
    graph.extend(extra_nodes or [])
    return {"@context": "https://schema.org", "@graph": [schema_clean(node) for node in graph if schema_clean(node)]}


def load_admin_json(path: Path, default: Any) -> Any:
    data = load_json(path)
    return data if data is not None else default


def save_admin_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def public_lang_code(lang: str) -> str:
    internal = normalize_lang(lang)
    return PUBLIC_LANG_BY_INTERNAL.get(internal, internal)


def internal_lang_code(lang: str) -> str:
    value = (lang or "").strip().lower()
    value = INTERNAL_LANG_BY_PUBLIC.get(value, value)
    return normalize_lang(value)


def translation_namespace(key: str) -> str:
    text = str(key or "").strip()
    if "." in text:
        return text.split(".", 1)[0]
    if "_" in text:
        return text.split("_", 1)[0]
    return "common"


def translation_id(key: str, language: str) -> str:
    return f"{translation_namespace(key)}:{key}:{language}"


def default_ui_translation_rows() -> List[Dict[str, Any]]:
    keys = sorted({k for values in I18N.values() for k in values.keys()} | {k for values in ADDITIONAL_UI_TRANSLATIONS.values() for k in values.keys()})
    now = utc_now_iso()
    rows: List[Dict[str, Any]] = []
    for lang in LANG_ORDER:
        public_lang = public_lang_code(lang)
        source = dict(I18N.get(lang) or {})
        source.update(ADDITIONAL_UI_TRANSLATIONS.get(lang) or {})
        en_source = dict(I18N.get(DEFAULT_LANG) or {})
        en_source.update(ADDITIONAL_UI_TRANSLATIONS.get(DEFAULT_LANG) or {})
        for key in keys:
            value = str(source.get(key) or "")
            rows.append(
                {
                    "id": translation_id(key, public_lang),
                    "key": key,
                    "namespace": translation_namespace(key),
                    "language": public_lang,
                    "value": value,
                    "description": str(en_source.get(key) or ""),
                    "status": "translated" if value else "missing",
                    "createdAt": now,
                    "updatedAt": now,
                    "updatedBy": "seed",
                }
            )
    return rows


def default_translation_store() -> Dict[str, Any]:
    return {
        "version": 1,
        "uiTranslations": default_ui_translation_rows(),
        "pageTranslations": [],
        "emailTemplates": [],
        "updatedAt": utc_now_iso(),
    }


def load_translations_store() -> Dict[str, Any]:
    cached = getattr(g, "_translations_store", None) if has_request_context() else None
    if isinstance(cached, dict):
        return cached

    data = load_admin_json(ADMIN_TRANSLATIONS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    rows = data.get("uiTranslations") if isinstance(data.get("uiTranslations"), list) else []
    by_id = {str(row.get("id") or translation_id(row.get("key") or "", row.get("language") or "")): dict(row) for row in rows if isinstance(row, dict)}
    changed = False
    for seed in default_ui_translation_rows():
        sid = str(seed.get("id") or "")
        if not sid:
            continue
        if sid not in by_id:
            by_id[sid] = seed
            changed = True
            continue
        existing = by_id[sid]
        if not existing.get("namespace"):
            existing["namespace"] = seed["namespace"]
            changed = True
        if not existing.get("description"):
            existing["description"] = seed.get("description") or ""
            changed = True
        if not existing.get("status"):
            existing["status"] = "translated" if existing.get("value") else "missing"
            changed = True
    store = {
        "version": int(data.get("version") or 1),
        "uiTranslations": sorted(by_id.values(), key=lambda row: (str(row.get("namespace") or ""), str(row.get("key") or ""), str(row.get("language") or ""))),
        "pageTranslations": data.get("pageTranslations") if isinstance(data.get("pageTranslations"), list) else [],
        "emailTemplates": data.get("emailTemplates") if isinstance(data.get("emailTemplates"), list) else [],
        "updatedAt": data.get("updatedAt") or utc_now_iso(),
    }
    if changed or not ADMIN_TRANSLATIONS_PATH.exists():
        save_translations_store(store)
    if has_request_context():
        g._translations_store = store
    return store


def save_translations_store(store: Dict[str, Any]) -> None:
    payload = dict(store or {})
    payload["updatedAt"] = utc_now_iso()
    save_admin_json(ADMIN_TRANSLATIONS_PATH, payload)
    if has_request_context():
        g._translations_store = payload


def ui_translation_map(lang: str) -> Dict[str, str]:
    public_lang = public_lang_code(lang)
    out: Dict[str, str] = {}
    for row in load_translations_store().get("uiTranslations") or []:
        if not isinstance(row, dict) or str(row.get("language") or "") != public_lang:
            continue
        key = str(row.get("key") or "").strip()
        value = str(row.get("value") or "")
        if key and value:
            out[key] = value
    return out


def save_ui_translation_from_form(form: Any) -> Tuple[str, str]:
    key = clean_plain_text(form.get("key") or "", 180)
    language = public_lang_code(internal_lang_code(form.get("language") or DEFAULT_LANG))
    value = clean_plain_text(form.get("value") or "", 120000)
    status = clean_plain_text(form.get("status") or ("translated" if value else "missing"), 40)
    if status not in {"missing", "draft", "translated", "reviewed", "machine_draft", "human_draft", "published"}:
        status = "translated" if value else "missing"
    description = clean_plain_text(form.get("description") or "", 500)
    if not key:
        return "Translation key is required.", "error"
    store = load_translations_store()
    rows = []
    found = False
    now = utc_now_iso()
    for row in store.get("uiTranslations") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("key") or "") == key and str(row.get("language") or "") == language:
            row = dict(row)
            row.update(
                {
                    "id": translation_id(key, language),
                    "namespace": translation_namespace(key),
                    "language": language,
                    "value": value,
                    "status": status,
                    "description": description or str(row.get("description") or ""),
                    "updatedAt": now,
                    "updatedBy": session.get("admin_email") or "admin",
                }
            )
            found = True
        rows.append(row)
    if not found:
        rows.append(
            {
                "id": translation_id(key, language),
                "key": key,
                "namespace": translation_namespace(key),
                "language": language,
                "value": value,
                "description": description,
                "status": status,
                "createdAt": now,
                "updatedAt": now,
                "updatedBy": session.get("admin_email") or "admin",
            }
        )
    store["uiTranslations"] = rows
    save_translations_store(store)
    admin_revision_log("ui_translation_saved", "uiTranslation", key, language)
    return "Translation saved.", "success"


def admin_ui_translation_rows(limit: int = 300) -> List[Dict[str, Any]]:
    rows = [row for row in load_translations_store().get("uiTranslations") or [] if isinstance(row, dict)]
    q = str(request.args.get("q") or "").strip().lower() if has_request_context() else ""
    namespace = str(request.args.get("namespace") or "").strip().lower() if has_request_context() else ""
    status_filter = str(request.args.get("status") or "").strip().lower() if has_request_context() else ""
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("key") or "")
        ns = str(row.get("namespace") or translation_namespace(key))
        lang = str(row.get("language") or "")
        value = str(row.get("value") or "")
        status = str(row.get("status") or ("translated" if value else "missing"))
        hay = f"{key} {ns} {lang} {value} {status}".lower()
        if q and q not in hay:
            continue
        if namespace and namespace != ns.lower():
            continue
        if status_filter and status_filter != status.lower():
            continue
        item = grouped.setdefault(
            key,
            {
                "key": key,
                "namespace": ns,
                "status": "reviewed",
                "updatedAt": "",
                "actions": admin_action_link("Edit", f"/admin/translations/ui?key={urllib.parse.quote(key)}"),
            },
        )
        item[lang] = value[:120] + ("…" if len(value) > 120 else "")
        item["updatedAt"] = max(str(item.get("updatedAt") or ""), str(row.get("updatedAt") or ""))
        if status in {"missing", "draft", "machine_draft", "human_draft"}:
            item["status"] = status
        elif item.get("status") not in {"missing", "draft", "machine_draft", "human_draft"} and status != "reviewed":
            item["status"] = status
    return list(grouped.values())[:limit]


def admin_missing_translation_rows(limit: int = 300) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in load_translations_store().get("uiTranslations") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") == "missing" or not str(row.get("value") or "").strip():
            out.append(
                {
                    "key": row.get("key") or "",
                    "namespace": row.get("namespace") or "",
                    "language": str(row.get("language") or "").upper(),
                    "description": row.get("description") or "",
                    "actions": admin_action_link("Edit", f"/admin/translations/ui?key={urllib.parse.quote(str(row.get('key') or ''))}&lang={urllib.parse.quote(str(row.get('language') or ''))}"),
                }
            )
        if len(out) >= limit:
            break
    return out


def admin_translation_progress_rows() -> List[Dict[str, Any]]:
    rows = [row for row in load_translations_store().get("uiTranslations") or [] if isinstance(row, dict)]
    out: List[Dict[str, Any]] = []
    for lang in TRANSLATION_LANG_ORDER:
        lang_rows = [row for row in rows if str(row.get("language") or "") == lang]
        total = len(lang_rows)
        done = sum(1 for row in lang_rows if str(row.get("value") or "").strip())
        reviewed = sum(1 for row in lang_rows if str(row.get("status") or "") == "reviewed")
        pct = int(round((done / total) * 100)) if total else 0
        out.append({"language": lang.upper(), "translated": f"{done}/{total}", "reviewed": reviewed, "progress": f"{pct}%"})
    return out


def admin_page_translation_rows(limit: int = 250) -> List[Dict[str, Any]]:
    records = admin_landing_page_records(limit=limit)
    out: List[Dict[str, Any]] = []
    for row in records[:limit]:
        page_key = admin_page_key_for_record(row)
        item = {
            "title": row.get("title") or page_key,
            "type": row.get("type") or "",
            "url": row.get("url") or "",
            "updatedAt": row.get("updatedAt") or "",
            "actions": admin_action_link("Edit", f"/admin/pages/edit?pageKey={urllib.parse.quote(page_key)}"),
        }
        for internal in LANG_ORDER:
            content = load_admin_page_content(page_key, internal)
            value = "published" if (content.get("h1") or content.get("seoTextHtml") or content.get("faq")) else "missing"
            item[public_lang_code(internal)] = value
        out.append(item)
    return out


def default_admin_cms_store() -> Dict[str, Any]:
    """JSON-backed CMS collections used until the project moves to a real DB."""
    return {
        "blogAuthors": [
            {
                "id": "audia-guide-team",
                "name": f"{BRAND_NAME} Team",
                "slug": "audia-guide-team",
                "email": ADMIN_EMAIL,
                "role": "Editor",
                "status": "active",
                "bio": "Travel audio guide editorial team.",
                "createdAt": utc_now_iso(),
            }
        ],
        "blogCategories": [
            {
                "id": "travel-audio-guides",
                "name": "Travel Audio Guides",
                "h1": "Travel Audio Guides",
                "slug": "travel-audio-guides",
                "language": DEFAULT_LANG,
                "status": "published",
                "order": 1,
                "description": "Stories, city guides and listening tips for free travel audio guides.",
            }
        ],
        "blogComments": [],
        "comments": [],
        "blogRatings": [],
        "blogLikes": [],
        "audioRatings": [],
        "subscriptionForms": [
            {
                "id": "newsletter",
                "name": "Travel audio guide updates",
                "status": "active",
                "language": DEFAULT_LANG,
                "source": "site-popup",
                "createdAt": utc_now_iso(),
            }
        ],
        "subscribers": [],
        "contactMessages": [],
        "siteUsers": [],
        "emailVerificationTokens": [],
        "passwordResetTokens": [],
        "listeningHistory": [],
        "favorites": [],
        "adminUsers": [
            {
                "id": "owner",
                "email": ADMIN_EMAIL,
                "name": "Site owner",
                "role": "Super Admin",
                "active": True,
                "source": "env",
                "createdAt": utc_now_iso(),
            }
        ],
        "roles": [
            {"id": "super-admin", "name": "Super Admin", "permissions": ["*"]},
            {"id": "editor", "name": "Editor", "permissions": ["blog", "pages", "media"]},
            {"id": "seo-manager", "name": "SEO Manager", "permissions": ["seo", "robots", "sitemap", "redirects"]},
            {"id": "audio-manager", "name": "Audio Manager", "permissions": ["audio"]},
            {"id": "moderator", "name": "Moderator", "permissions": ["comments", "ratings", "subscriptions"]},
        ],
        "loginHistory": [],
        "galleries": [],
        "files": [],
        "redirectsNotes": [],
        "seoChanges": [],
        "audioLogs": [],
        "errors": [],
        "updatedAt": utc_now_iso(),
    }


def load_admin_cms_store() -> Dict[str, Any]:
    cached = getattr(g, "_admin_cms_store_cache", None) if has_request_context() else None
    cached_path = getattr(g, "_admin_cms_store_cache_path", None) if has_request_context() else None
    if cached_path == str(ADMIN_CMS_STORE_PATH) and isinstance(cached, dict):
        return cached
    defaults = default_admin_cms_store()
    data = load_admin_json(ADMIN_CMS_STORE_PATH, {})
    if not isinstance(data, dict):
        data = {}
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
    data["updatedAt"] = data.get("updatedAt") or utc_now_iso()
    if has_request_context():
        g._admin_cms_store_cache = data
        g._admin_cms_store_cache_path = str(ADMIN_CMS_STORE_PATH)
    return data


def save_admin_cms_store(store: Dict[str, Any]) -> None:
    store["updatedAt"] = utc_now_iso()
    save_admin_json(ADMIN_CMS_STORE_PATH, store)
    if has_request_context():
        g._admin_cms_store_cache = store
        g._admin_cms_store_cache_path = str(ADMIN_CMS_STORE_PATH)


def cms_collection_rows(collection: str) -> List[Dict[str, Any]]:
    store = load_admin_cms_store()
    rows = store.get(collection)
    return rows if isinstance(rows, list) else []


def save_cms_collection_rows(collection: str, rows: List[Dict[str, Any]]) -> None:
    store = load_admin_cms_store()
    store[collection] = rows
    save_admin_cms_store(store)


def cms_upsert(collection: str, item: Dict[str, Any], item_id: str = "") -> Dict[str, Any]:
    rows = cms_collection_rows(collection)
    current_id = item_id or str(item.get("id") or secrets.token_hex(8))
    item["id"] = current_id
    item["updatedAt"] = utc_now_iso()
    found = False
    new_rows: List[Dict[str, Any]] = []
    for row in rows:
        if str(row.get("id") or "") == current_id:
            new_rows.append({**row, **item})
            found = True
        else:
            new_rows.append(row)
    if not found:
        item.setdefault("createdAt", utc_now_iso())
        new_rows.insert(0, item)
    save_cms_collection_rows(collection, new_rows)
    return item


def cms_insert(collection: str, item: Dict[str, Any], *, limit: int = 5000) -> Dict[str, Any]:
    rows = cms_collection_rows(collection)
    item = dict(item)
    item.setdefault("id", secrets.token_hex(8))
    item.setdefault("createdAt", utc_now_iso())
    rows.insert(0, item)
    save_cms_collection_rows(collection, rows[:limit])
    return item


def is_valid_email(value: str) -> bool:
    email_value = str(value or "").strip()
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_value))


def request_source_page(default: str = "") -> str:
    source = (
        (request.form.get("sourcePage") if request.form else "")
        or ((request.get_json(silent=True) or {}).get("sourcePage") if request.is_json else "")
        or request.referrer
        or default
        or request.path
    )
    return clean_plain_text(source, 500)


def append_mail_notification_log(subject: str, body: str, to_email: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "createdAt": utc_now_iso(),
            "to": to_email,
            "subject": subject,
            "body": body,
        }
        with MAIL_NOTIFICATION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def mail_log_body(body: str) -> str:
    if IS_PRODUCTION:
        return "[redacted in production logs]"
    return body


def _sendmail_path() -> str:
    found = shutil.which("sendmail")
    if found:
        return found
    fallback = Path("/usr/sbin/sendmail")
    return str(fallback) if fallback.exists() else ""


def send_email_message(message: EmailMessage, *, subject: str, log_body: str, to_email: str) -> Tuple[bool, str]:
    """Send an email via configured SMTP or local sendmail, with JSONL logging."""
    sent = False
    status = "not_configured"
    if SMTP_HOST:
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as smtp:
                if SMTP_USE_TLS:
                    smtp.starttls()
                if SMTP_USERNAME and SMTP_PASSWORD:
                    smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
            return True, "sent_smtp"
        except Exception as exc:
            status = f"smtp_failed: {clean_plain_text(str(exc), 220)}"
            append_mail_notification_log(f"MAIL SEND FAILED: {subject}", f"{mail_log_body(log_body)}\n\nError: {exc}", to_email)

    sendmail = _sendmail_path()
    if sendmail:
        try:
            proc = subprocess.run(
                [sendmail, "-t", "-oi"],
                input=message.as_bytes(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0:
                return True, "sent_sendmail"
            err = proc.stderr.decode("utf-8", "replace").strip()
            status = f"sendmail_failed: {clean_plain_text(err or str(proc.returncode), 220)}"
            append_mail_notification_log(f"MAIL SEND FAILED: {subject}", f"{mail_log_body(log_body)}\n\nError: {err or proc.returncode}", to_email)
        except Exception as exc:
            status = f"sendmail_failed: {clean_plain_text(str(exc), 220)}"
            append_mail_notification_log(f"MAIL SEND FAILED: {subject}", f"{mail_log_body(log_body)}\n\nError: {exc}", to_email)

    if not sent:
        append_mail_notification_log(subject, mail_log_body(log_body), to_email)
    return False, status


def send_site_notification_result(subject: str, body: str, *, reply_to: str = "") -> Tuple[bool, str]:
    """Send owner notifications, with a JSONL fallback so submissions are never lost."""
    to_email = CONTACT_EMAIL
    message = EmailMessage()
    message["Subject"] = clean_plain_text(subject, 160)
    message["From"] = SMTP_FROM or CONTACT_EMAIL
    message["To"] = to_email
    if reply_to and is_valid_email(reply_to):
        message["Reply-To"] = reply_to
    message.set_content(body)
    return send_email_message(message, subject=subject, log_body=body, to_email=to_email)


def send_site_notification(subject: str, body: str, *, reply_to: str = "") -> bool:
    sent, _status = send_site_notification_result(subject, body, reply_to=reply_to)
    return sent


def save_subscription_message(*, name: str, email: str, source_page: str) -> Dict[str, Any]:
    submitted_at = utc_now_iso()
    row = {
        "id": secrets.token_hex(8),
        "name": clean_plain_text(name, 120),
        "email": clean_plain_text(email, 180).lower(),
        "language": current_lang(),
        "source": clean_plain_text(source_page, 500),
        "sourcePage": clean_plain_text(source_page, 500),
        "status": "pending",
        "subscribedAt": submitted_at,
        "submittedAt": submitted_at,
        "createdAt": submitted_at,
        "ip": clean_plain_text(get_client_ip() if has_request_context() else "", 80),
        "userAgent": clean_plain_text(request.headers.get("User-Agent") or "", 300) if has_request_context() else "",
    }
    rows = cms_collection_rows("subscribers")
    for existing in rows:
        if str(existing.get("email") or "").strip().lower() == row["email"] and str(existing.get("source") or "") == row["source"]:
            existing.update({**row, "id": existing.get("id") or row["id"], "updatedAt": utc_now_iso()})
            save_cms_collection_rows("subscribers", rows)
            return existing
    cms_insert("subscribers", row)
    return row


def update_subscription_notification_status(subscriber_id: str, *, sent: bool, status: str) -> Dict[str, Any]:
    rows = cms_collection_rows("subscribers")
    updated: Dict[str, Any] = {}
    now = utc_now_iso()
    for item in rows:
        if str(item.get("id") or "") == str(subscriber_id):
            item["emailNotificationSent"] = bool(sent)
            item["emailNotificationStatus"] = clean_plain_text(status or ("sent" if sent else "failed"), 260)
            item["emailNotificationAt"] = now
            item["updatedAt"] = now
            updated = item
            break
    if updated:
        save_cms_collection_rows("subscribers", rows)
    return updated


def save_contact_message(*, name: str, email: str, message_text: str, source_page: str) -> Dict[str, Any]:
    submitted_at = utc_now_iso()
    row = {
        "id": secrets.token_hex(8),
        "name": clean_plain_text(name, 140),
        "email": clean_plain_text(email, 180).lower(),
        "message": clean_plain_text(message_text, 5000),
        "source": clean_plain_text(source_page, 500),
        "sourcePage": clean_plain_text(source_page, 500),
        "language": current_lang(),
        "status": "new",
        "submittedAt": submitted_at,
        "createdAt": submitted_at,
        "ip": clean_plain_text(get_client_ip() if has_request_context() else "", 80),
        "userAgent": clean_plain_text(request.headers.get("User-Agent") or "", 300) if has_request_context() else "",
    }
    cms_insert("contactMessages", row)
    return row


COMMENT_PAGE_TYPES = {
    "blog_article",
    "landing_page",
    "city_page",
    "country_page",
    "place_page",
    "static_page",
}
COMMENT_STATUSES = {"pending", "approved", "rejected", "spam", "deleted"}


def normalize_comment_page_type(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "blog": "blog_article",
        "blog_post": "blog_article",
        "article": "blog_article",
        "landing": "landing_page",
        "home": "landing_page",
        "city": "city_page",
        "country": "country_page",
        "place": "place_page",
        "static": "static_page",
    }
    out = aliases.get(raw, raw)
    return out if out in COMMENT_PAGE_TYPES else ""


def normalize_comment_status(value: Any) -> str:
    status = str(value or "pending").strip().lower()
    return status if status in COMMENT_STATUSES else "pending"


def comment_ui_texts(lang: str) -> Dict[str, str]:
    trn = t(lang)
    return {
        "kicker": trn.get("comments_kicker", "Comments"),
        "title": trn.get("comments_title", "Comments"),
        "button": trn.get("comments_button", "Leave Comment"),
        "formTitle": trn.get("comments_form_title", "Leave a comment"),
        "name": trn.get("comments_name", "Name"),
        "email": trn.get("comments_email", "Email"),
        "comment": trn.get("comments_comment", "Comment"),
        "submit": trn.get("comments_submit", "Submit Comment"),
        "success": trn.get("comments_success", "Thank you. Your comment is waiting for moderation."),
        "error": trn.get("comments_error", "Please check your name, email and comment."),
        "rateLimited": trn.get("comments_rate_limited", "Please wait before sending another comment."),
        "empty": trn.get("comments_empty", "No comments yet. Be the first to leave a comment."),
        "consent": trn.get("comments_consent", "I understand that my comment will be reviewed before publication."),
        "counter": trn.get("comments_counter", "0 / 1000"),
        "sharePrompt": trn.get("comments_share_prompt", "Share what helped, what was missing, or what you would like to hear next."),
        "privateNote": trn.get("comments_private_note", "Your message is private until moderation. Email is used only for verification and is never shown publicly."),
    }


def comment_plain_text(value: Any, limit: int = 1000) -> str:
    text = clean_plain_text(value, limit)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(?i)javascript:", "", text)
    return text[:limit]


def comment_public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    text = comment_plain_text(row.get("commentText") or row.get("comment") or "", 1000)
    return {
        "id": row.get("id") or "",
        "authorName": clean_plain_text(row.get("authorName") or row.get("name") or "Reader", 100),
        "commentText": text,
        "commentHtml": "<br>".join(html.escape(part) for part in text.splitlines()),
        "createdAt": clean_plain_text(row.get("createdAt") or "", 40),
        "dateLabel": clean_plain_text(str(row.get("createdAt") or "")[:10], 20),
    }


def legacy_blog_comment_to_universal(row: Dict[str, Any], post_by_id: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    post_by_id = post_by_id or {}
    post_id = str(row.get("postId") or "")
    post = post_by_id.get(post_id) or {}
    page_url = blog_post_url(post) if post else ""
    lang = normalize_lang(str(post.get("lang") or row.get("language") or DEFAULT_LANG))
    return {
        "id": f"legacy:{row.get('id') or ''}",
        "_legacyId": row.get("id") or "",
        "_collection": "blogComments",
        "pageType": "blog_article",
        "pageId": post_id,
        "pageUrl": page_url,
        "pageTitle": post.get("title") or row.get("postSlug") or "Blog article",
        "language": lang,
        "authorName": row.get("name") or "",
        "authorEmail": row.get("email") or "",
        "commentText": row.get("comment") or "",
        "status": normalize_comment_status(row.get("status")),
        "createdAt": row.get("createdAt") or "",
        "updatedAt": row.get("updatedAt") or "",
        "moderatedAt": row.get("moderatedAt") or "",
        "moderatedBy": row.get("moderatedBy") or "",
        "ipAddress": row.get("ip") or "",
        "userAgent": row.get("userAgent") or "",
        "userId": row.get("userId") or "",
        "parentId": row.get("parentId") or "",
    }


def all_comment_rows(*, include_legacy_blog: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in cms_collection_rows("comments"):
        if isinstance(row, dict):
            item = dict(row)
            item["_collection"] = "comments"
            item["status"] = normalize_comment_status(item.get("status"))
            rows.append(item)
    if include_legacy_blog:
        post_by_id = {str(p.get("id") or ""): p for p in load_blog_posts(include_drafts=True)}
        for row in cms_collection_rows("blogComments"):
            if isinstance(row, dict):
                rows.append(legacy_blog_comment_to_universal(row, post_by_id))
    rows.sort(key=lambda row: row.get("createdAt") or row.get("updatedAt") or "", reverse=True)
    return rows


def comments_for_page(page_type: str, page_id: str, lang: str, *, status: str = "approved") -> List[Dict[str, Any]]:
    page_type = normalize_comment_page_type(page_type)
    page_id = clean_plain_text(page_id, 240)
    lang = normalize_lang(lang)
    status = normalize_comment_status(status)
    if not page_type or not page_id:
        return []
    out = [
        row for row in all_comment_rows()
        if str(row.get("pageType") or "") == page_type
        and str(row.get("pageId") or "") == page_id
        and normalize_lang(str(row.get("language") or lang)) == lang
        and normalize_comment_status(row.get("status")) == status
    ]
    out.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
    return out


def comments_enabled_for_content(admin_content: Optional[Dict[str, Any]], default: bool = True) -> bool:
    if isinstance(admin_content, dict) and "commentsEnabled" in admin_content:
        return bool(admin_content.get("commentsEnabled"))
    return default


def public_comments_context(
    page_type: str,
    page_id: str,
    page_title: str,
    page_url: str,
    lang: str,
    admin_content: Optional[Dict[str, Any]] = None,
    *,
    default_enabled: bool = True,
) -> Dict[str, Any]:
    lang = normalize_lang(lang)
    page_type = normalize_comment_page_type(page_type)
    page_id = clean_plain_text(page_id, 240)
    page_url = clean_plain_text(page_url, 500)
    page_title = clean_plain_text(page_title, 220)
    user = current_site_user()
    approved = [comment_public_row(row) for row in comments_for_page(page_type, page_id, lang, status="approved")[:50]]
    return {
        "enabled": comments_enabled_for_content(admin_content, default_enabled) and bool(page_type and page_id and page_url),
        "pageType": page_type,
        "pageId": page_id,
        "pageUrl": page_url,
        "pageTitle": page_title,
        "language": lang,
        "approved": approved,
        "approvedCount": len(approved),
        "pendingCount": len(comments_for_page(page_type, page_id, lang, status="pending")),
        "texts": comment_ui_texts(lang),
        "success": request.args.get("comment") == "pending" if has_request_context() else False,
        "error": request.args.get("comment") == "error" if has_request_context() else False,
        "rateLimited": request.args.get("comment") == "rate" if has_request_context() else False,
        "userName": clean_plain_text(user.get("name") or "", 100) if user else "",
        "userEmail": clean_plain_text(user.get("email") or "", 180) if user else "",
    }


def comment_recent_submission_count(*, ip: str, email: str, window_seconds: int) -> int:
    now = int(time.time())
    email = clean_plain_text(email, 180).lower()
    ip = clean_plain_text(ip, 80)
    count = 0
    for row in all_comment_rows(include_legacy_blog=False):
        if email and str(row.get("authorEmail") or "").strip().lower() != email and ip and str(row.get("ipAddress") or "") != ip:
            continue
        created = iso_to_epoch(row.get("createdAt"))
        if created and now - created <= window_seconds:
            count += 1
    return count


def comment_submission_rate_limited(email: str) -> bool:
    ip = get_client_ip() if has_request_context() else ""
    return (
        comment_recent_submission_count(ip=ip, email=email, window_seconds=30) >= 1
        or comment_recent_submission_count(ip=ip, email=email, window_seconds=600) >= 5
    )


def save_public_comment(
    *,
    page_type: str,
    page_id: str,
    page_url: str,
    page_title: str,
    language: str,
    author_name: str,
    author_email: str,
    comment_text: str,
) -> Dict[str, Any]:
    user = current_site_user()
    now = utc_now_iso()
    row = {
        "id": secrets.token_hex(10),
        "pageType": normalize_comment_page_type(page_type),
        "pageId": clean_plain_text(page_id, 240),
        "pageUrl": clean_plain_text(page_url, 500),
        "pageTitle": clean_plain_text(page_title, 220),
        "language": normalize_lang(language),
        "authorName": clean_plain_text(author_name, 100),
        "authorEmail": clean_plain_text(author_email, 180).lower(),
        "commentText": comment_plain_text(comment_text, 1000),
        "status": "pending",
        "createdAt": now,
        "updatedAt": now,
        "moderatedAt": "",
        "moderatedBy": "",
        "ipAddress": clean_plain_text(get_client_ip() if has_request_context() else "", 80),
        "userAgent": clean_plain_text(request.headers.get("User-Agent") or "", 500) if has_request_context() else "",
        "userId": user.get("id") if user else "",
        "parentId": "",
    }
    cms_insert("comments", row, limit=10000)
    admin_revision_log("comment_submitted", "comment", row["pageTitle"], status="pending", details={"pageType": row["pageType"], "pageId": row["pageId"]})
    body = "\n".join([
        "New SonicCity comment is waiting for moderation.",
        "",
        f"Page: {row['pageTitle']}",
        f"URL: {row['pageUrl']}",
        f"Type: {row['pageType']}",
        f"Language: {row['language']}",
        f"Name: {row['authorName']}",
        f"Email: {row['authorEmail']}",
        "",
        row["commentText"],
    ])
    send_site_notification("New SonicCity comment pending moderation", body, reply_to=row["authorEmail"])
    return row


def safe_comment_redirect(page_url: str, state: str) -> Response:
    target = clean_plain_text(page_url, 500) or request.referrer or landing_url(current_lang())
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme or parsed.netloc:
        target = urllib.parse.urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
    if not target.startswith("/"):
        target = landing_url(current_lang())
    separator = "&" if "?" in target else "?"
    return redirect(f"{target}{separator}comment={urllib.parse.quote(state)}#comments", code=302)


def find_comment_record(comment_ref: str) -> Optional[Dict[str, Any]]:
    ref = urllib.parse.unquote(str(comment_ref or ""))
    if ref.startswith("legacy:"):
        target = ref.split(":", 1)[1]
        post_by_id = {str(p.get("id") or ""): p for p in load_blog_posts(include_drafts=True)}
        for row in cms_collection_rows("blogComments"):
            if str(row.get("id") or "") == target:
                return legacy_blog_comment_to_universal(row, post_by_id)
        return None
    for row in cms_collection_rows("comments"):
        if str(row.get("id") or "") == ref:
            item = dict(row)
            item["_collection"] = "comments"
            return item
    return None


def update_comment_status(comment_ref: str, status: str) -> bool:
    ref = urllib.parse.unquote(str(comment_ref or ""))
    status = normalize_comment_status(status)
    updated = False
    collection = "comments"
    target = ref
    if ref.startswith("legacy:"):
        collection = "blogComments"
        target = ref.split(":", 1)[1]
    rows = cms_collection_rows(collection)
    for row in rows:
        if str(row.get("id") or "") == target:
            row["status"] = status
            row["updatedAt"] = utc_now_iso()
            row["moderatedAt"] = utc_now_iso()
            row["moderatedBy"] = session.get("admin_email") or ADMIN_EMAIL if has_request_context() else ADMIN_EMAIL
            updated = True
            break
    if updated:
        save_cms_collection_rows(collection, rows)
        admin_revision_log(f"comment_{status}", "comment", target, details={"collection": collection})
    return updated


def site_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    target = clean_plain_text(email, 180).lower()
    if not target:
        return None
    for row in cms_collection_rows("siteUsers"):
        if str(row.get("email") or "").strip().lower() == target:
            return row
    return None


def registration_country_from_request() -> Dict[str, str]:
    code = geo_country_from_headers()
    if not code:
        code = geo_country_from_ip(get_client_ip()) or ""
    code = clean_plain_text(code, 8).upper()
    country = COUNTRY_BY_CODE.get(code.lower()) if code else None
    name = country_display_name_cached_for_lang(country, DEFAULT_LANG) if country else ""
    return {"code": code, "name": name or code or "Unknown"}


def current_site_user() -> Optional[Dict[str, Any]]:
    email = str(session.get("user_email") or "").strip().lower()
    user_id = str(session.get("user_id") or "").strip()
    if not email and not user_id:
        return None
    for row in cms_collection_rows("siteUsers"):
        if (email and str(row.get("email") or "").strip().lower() == email) or (user_id and str(row.get("id") or "") == user_id):
            return row
    return None


def iso_to_epoch(value: Any) -> int:
    try:
        text = str(value or "").strip()
        if not text:
            return 0
        return int(time.mktime(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return 0


def update_site_user(user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = cms_collection_rows("siteUsers")
    updated: Optional[Dict[str, Any]] = None
    now = utc_now_iso()
    for item in rows:
        if str(item.get("id") or "") == str(user_id):
            item.update(updates)
            item["updatedAt"] = now
            updated = item
            break
    if updated:
        save_cms_collection_rows("siteUsers", rows)
    return updated


def site_user_is_verified(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    if "emailVerified" in user:
        return bool(user.get("emailVerified"))
    # Legacy users created before verification existed stay usable.
    return str(user.get("status") or "active") == "active"


def public_site_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not user:
        return {}
    return {
        "id": user.get("id") or "",
        "email": user.get("email") or "",
        "name": user.get("name") or "",
        "country": user.get("country") or user.get("registrationCountry") or "",
        "registrationCountry": user.get("registrationCountry") or "",
        "preferredLanguage": user.get("preferredLanguage") or DEFAULT_LANG,
        "preferredVoiceGender": user.get("preferredVoiceGender") or "female",
        "emailVerified": site_user_is_verified(user),
        "status": user.get("status") or ("active" if site_user_is_verified(user) else "pending_verification"),
        "registeredAt": user.get("registeredAt") or user.get("createdAt") or "",
        "lastLoginAt": user.get("lastLoginAt") or "",
    }


def account_feature_allowed(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    status = str(user.get("status") or "active").lower()
    return status not in {"disabled", "banned", "deleted"}


def auth_rate_limited(action: str, email: str = "", *, limit: int = 10, window_seconds: int = 300) -> bool:
    key = f"{action}:{clean_plain_text(email, 180).lower()}:{get_client_ip() if has_request_context() else ''}"
    now = int(time.time())
    with AUTH_RATE_LIMIT_LOCK:
        bucket = [ts for ts in AUTH_RATE_LIMITS.get(key, []) if now - ts < window_seconds]
        limited = len(bucket) >= limit
        bucket.append(now)
        AUTH_RATE_LIMITS[key] = bucket[-limit * 2:]
    return limited


def secure_token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def store_single_use_token(collection: str, user: Dict[str, Any], *, ttl_seconds: int, purpose: str) -> str:
    raw = secrets.token_urlsafe(32)
    now = int(time.time())
    rows = cms_collection_rows(collection)
    rows.insert(0, {
        "id": secrets.token_hex(8),
        "userId": user.get("id"),
        "email": user.get("email"),
        "tokenHash": secure_token_hash(raw),
        "purpose": purpose,
        "expiresAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + ttl_seconds)),
        "usedAt": "",
        "createdAt": utc_now_iso(),
    })
    save_cms_collection_rows(collection, rows[:2000])
    return raw


def consume_single_use_token(collection: str, token: str) -> Tuple[Optional[Dict[str, Any]], str]:
    token_h = secure_token_hash(token)
    rows = cms_collection_rows(collection)
    now = int(time.time())
    matched: Optional[Dict[str, Any]] = None
    status = "invalid"
    for item in rows:
        if str(item.get("tokenHash") or "") != token_h:
            continue
        matched = item
        if item.get("usedAt"):
            status = "used"
        elif iso_to_epoch(item.get("expiresAt")) < now:
            status = "expired"
        else:
            item["usedAt"] = utc_now_iso()
            status = "ok"
        break
    if matched:
        save_cms_collection_rows(collection, rows)
    return matched, status


def send_user_email(to_email: str, subject: str, text_body: str, html_body: str = "") -> bool:
    """Email service boundary. Without SMTP, only local/dev returns a logged delivery."""
    to_email = clean_plain_text(to_email, 180).lower()
    if not is_valid_email(to_email):
        return False
    message = EmailMessage()
    message["Subject"] = clean_plain_text(subject, 160)
    message["From"] = SMTP_FROM or CONTACT_EMAIL
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    sent, _status = send_email_message(message, subject=subject, log_body=text_body, to_email=to_email)
    if not sent:
        if REQUIRE_SMTP_FOR_EMAIL:
            return False
    return sent or not REQUIRE_SMTP_FOR_EMAIL


def account_email_base_url() -> str:
    explicit = str(os.getenv("APP_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if has_request_context():
        return host_base_url()
    return SITE_URL


def send_verification_email(user: Dict[str, Any], *, force: bool = False) -> Tuple[bool, str]:
    last_sent = iso_to_epoch(user.get("verificationLastSentAt"))
    if not force and last_sent and int(time.time()) - last_sent < 60:
        return False, "Please wait before requesting another email."
    token = store_single_use_token("emailVerificationTokens", user, ttl_seconds=60 * 60 * 24, purpose="verify_email")
    link = f"{account_email_base_url()}/auth/verify-email?token={urllib.parse.quote(token)}"
    body = "\n".join([
        f"Confirm your email for {BRAND_NAME}",
        "",
        f"Open this link to confirm your email: {link}",
        "",
        "This link expires in 24 hours.",
    ])
    html_body = (
        f"<p>Confirm your email for {html.escape(BRAND_NAME)}.</p>"
        f"<p><a href=\"{html.escape(link)}\">Confirm email</a></p>"
        f"<p>This link expires in 24 hours.</p>"
    )
    ok = send_user_email(str(user.get("email") or ""), f"Confirm your email for {BRAND_NAME}", body, html_body)
    update_site_user(str(user.get("id") or ""), {"verificationLastSentAt": utc_now_iso()})
    return ok, "Verification email sent."


def send_password_reset_email(user: Dict[str, Any]) -> bool:
    token = store_single_use_token("passwordResetTokens", user, ttl_seconds=60 * 60, purpose="password_reset")
    link = f"{account_email_base_url()}/auth/reset-password?token={urllib.parse.quote(token)}"
    body = "\n".join([
        f"Reset your {BRAND_NAME} password",
        "",
        f"Open this link to set a new password: {link}",
        "",
        "This link expires in 1 hour.",
    ])
    html_body = (
        f"<p>Reset your {html.escape(BRAND_NAME)} password.</p>"
        f"<p><a href=\"{html.escape(link)}\">Reset password</a></p>"
        f"<p>This link expires in 1 hour.</p>"
    )
    return send_user_email(str(user.get("email") or ""), f"Reset your {BRAND_NAME} password", body, html_body)


def create_site_user(email: str, password: str, *, country: str = "", name: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    email = clean_plain_text(email, 180).lower()
    if not is_valid_email(email):
        return None, "Enter a valid email."
    if len(str(password or "")) < 8:
        return None, "Password must be at least 8 characters."
    if site_user_by_email(email):
        return None, "This email is already registered. Use Log In."
    detected_country = registration_country_from_request()
    country_name = clean_plain_text(country or detected_country["name"], 120)
    now = utc_now_iso()
    row = {
        "id": secrets.token_hex(10),
        "email": email,
        "passwordHash": generate_password_hash(password),
        "name": clean_plain_text(name, 120),
        "country": country_name,
        "registrationCountry": country_name,
        "registrationCountryCode": detected_country["code"],
        "preferredLanguage": DEFAULT_LANG,
        "preferredVoiceGender": "female",
        "emailVerified": False,
        "registeredAt": now,
        "createdAt": now,
        "lastLoginAt": "",
        "status": "pending_verification",
        "role": "User",
        "ip": clean_plain_text(get_client_ip(), 80),
        "userAgent": clean_plain_text(request.headers.get("User-Agent") or "", 300),
    }
    cms_insert("siteUsers", row)
    admin_revision_log("site_user_registered", "siteUser", email, details={"country": country})
    return row, ""


def login_site_user(email: str, password: str) -> Tuple[Optional[Dict[str, Any]], str]:
    row = site_user_by_email(email)
    if not row:
        return None, "User not found. Use Sign Up to create an account."
    if str(row.get("status") or "").lower() in {"disabled", "banned", "deleted"}:
        return None, "This account is not active."
    try:
        ok = check_password_hash(str(row.get("passwordHash") or ""), str(password or ""))
    except Exception:
        ok = False
    if not ok:
        return None, "Wrong email or password."
    rows = cms_collection_rows("siteUsers")
    now = utc_now_iso()
    for item in rows:
        if str(item.get("id") or "") == str(row.get("id") or ""):
            item["lastLoginAt"] = now
            item["loginCount"] = int(item.get("loginCount") or 0) + 1
            item["lastLoginIp"] = clean_plain_text(get_client_ip(), 80)
            item["lastLoginUserAgent"] = clean_plain_text(request.headers.get("User-Agent") or "", 300)
            if "emailVerified" not in item and str(item.get("status") or "active") == "active":
                item["emailVerified"] = True
            row = item
            break
    save_cms_collection_rows("siteUsers", rows)
    session["user_email"] = row.get("email")
    session["user_id"] = row.get("id")
    session["user_login_at"] = int(time.time())
    return row, ""


def admin_revision_log(action: str, entity_type: str, entity_name: str, *, status: str = "ok", details: Optional[Dict[str, Any]] = None) -> None:
    try:
        ADMIN_DATA_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": int(time.time()),
            "iso": utc_now_iso(),
            "user": session.get("admin_email") or ADMIN_EMAIL,
            "action": clean_plain_text(action, 120),
            "entityType": clean_plain_text(entity_type, 80),
            "entityName": clean_plain_text(entity_name, 240),
            "status": clean_plain_text(status, 40),
            "details": details or {},
            "ip": get_client_ip() if request else "",
        }
        with ADMIN_REVISIONS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def load_admin_revisions(limit: int = 80) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        if not ADMIN_REVISIONS_PATH.exists():
            return rows
        for line in reversed(ADMIN_REVISIONS_PATH.read_text(encoding="utf-8").splitlines()[-limit * 2:]):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except Exception:
                continue
            if len(rows) >= limit:
                break
    except Exception:
        return []
    return rows


def default_robots_text() -> str:
    if GLOBAL_NOINDEX:
        return "\n".join(
            [
                "User-agent: *",
                "Disallow: /",
            ]
        ) + "\n"
    return "\n".join(
        [
            "User-agent: *",
            "Disallow: /admin/",
            "Disallow: /api/",
            "Disallow: /login/",
            "Disallow: /dashboard/",
            "Disallow: /account/",
            "Disallow: /preview/",
            "Disallow: /draft/",
            "Disallow: /internal/",
            "Disallow: /generate-audio/",
            "Disallow: /tts/",
            "Disallow: /cache/",
            "Allow: /",
            f"Sitemap: {absolute_url('/sitemap.xml') if has_request_context() else '/sitemap.xml'}",
        ]
    ) + "\n"


def load_robots_text() -> str:
    if GLOBAL_NOINDEX:
        return default_robots_text()
    try:
        if ADMIN_ROBOTS_PATH.exists():
            text = ADMIN_ROBOTS_PATH.read_text(encoding="utf-8").strip()
            if text:
                return text + "\n"
    except Exception:
        pass
    return default_robots_text()


def save_robots_text(text: str) -> None:
    ADMIN_ROBOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_ROBOTS_PATH.write_text(clean_plain_text(text, 20000).strip() + "\n", encoding="utf-8")
    admin_revision_log("robots_saved", "robots.txt", "/robots.txt")


def load_admin_redirects() -> List[Dict[str, Any]]:
    data = load_admin_json(ADMIN_REDIRECTS_PATH, {"redirects": []})
    rows = data.get("redirects") if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def save_admin_redirects(rows: List[Dict[str, Any]]) -> None:
    save_admin_json(ADMIN_REDIRECTS_PATH, {"redirects": rows[:5000], "updatedAt": utc_now_iso()})


def load_admin_settings() -> Dict[str, Any]:
    defaults = {
        "siteName": BRAND_NAME,
        "siteUrl": SITE_URL,
        "defaultLanguage": DEFAULT_LANG,
        "defaultVoiceGender": "female",
        "audioStoragePath": str(AUDIO_STORAGE_PATH),
        "audioVersion": AUDIO_BUILD_AUDIO_VERSION,
        "mapProvider": "Leaflet / OpenStreetMap",
        "routingProvider": os.getenv("ROUTE_PROVIDER") or "not configured",
        "sitemapEnabled": True,
        "robotsManaged": True,
    }
    data = load_admin_json(ADMIN_SETTINGS_PATH, {})
    if isinstance(data, dict):
        defaults.update(data)
    return defaults


def save_admin_settings(form: Any) -> Dict[str, Any]:
    settings = load_admin_settings()
    for key in [
        "siteName",
        "siteUrl",
        "defaultLanguage",
        "defaultVoiceGender",
        "audioStoragePath",
        "mapProvider",
        "routingProvider",
    ]:
        settings[key] = clean_plain_text(form.get(key) or settings.get(key) or "", 300)
    settings["sitemapEnabled"] = bool(form.get("sitemapEnabled"))
    settings["robotsManaged"] = bool(form.get("robotsManaged"))
    settings["updatedAt"] = utc_now_iso()
    save_admin_json(ADMIN_SETTINGS_PATH, settings)
    admin_revision_log("settings_saved", "settings", "Site settings")
    return settings


def load_blog_data() -> Dict[str, Any]:
    data = load_json(BLOG_POSTS_PATH)
    if not isinstance(data, dict):
        return {"posts": []}
    posts = data.get("posts")
    if not isinstance(posts, list):
        data["posts"] = []
    return data


def load_blog_posts(include_drafts: bool = False, lang: Optional[str] = None) -> List[Dict[str, Any]]:
    data = load_blog_data()
    out: List[Dict[str, Any]] = []
    wanted_lang = normalize_lang(lang) if lang else ""
    for raw in data.get("posts") or []:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "draft").strip().lower()
        if not include_drafts and status != "published":
            continue
        post_lang = normalize_lang(str(raw.get("lang") or DEFAULT_LANG))
        if wanted_lang and post_lang != wanted_lang:
            continue
        post = dict(raw)
        post["lang"] = post_lang
        post["status"] = status if status in {"draft", "published", "scheduled", "archived"} else "draft"
        post["tags"] = [str(x).strip() for x in (post.get("tags") or []) if str(x).strip()]
        if post.get("bodyHtmlRaw"):
            post["bodyHtml"] = render_safe_html(post.get("bodyHtmlRaw") or "")
        else:
            post["bodyHtml"] = render_safe_markdown(post.get("bodyMarkdown") or "")
        post["excerptHtml"] = render_safe_markdown(post.get("excerpt") or "")
        out.append(post)
    out.sort(key=lambda row: str(row.get("publishedAt") or row.get("updatedAt") or ""), reverse=True)
    return out


def save_blog_posts(posts: List[Dict[str, Any]]) -> None:
    atomic_write_json(BLOG_POSTS_PATH, {"posts": posts})


def find_blog_post(slug: str, lang: Optional[str] = None, include_drafts: bool = False) -> Optional[Dict[str, Any]]:
    slug = str(slug or "").strip().lower()
    for post in load_blog_posts(include_drafts=include_drafts, lang=lang):
        if str(post.get("slug") or "").strip().lower() == slug:
            return post
    return None


def blog_post_url(post: Dict[str, Any]) -> str:
    lang = normalize_lang(str(post.get("lang") or DEFAULT_LANG))
    slug = str(post.get("slug") or "")
    return f"/blog/{slug}" if lang == "en" else f"/{public_lang_code(lang)}/blog/{slug}"


def blog_index_url(lang: str) -> str:
    lang = normalize_lang(lang)
    return "/blog" if lang == "en" else f"/{public_lang_code(lang)}/blog"


def contact_url(lang: str) -> str:
    lang = normalize_lang(lang)
    return "/contacts/" if lang == "en" else f"/{public_lang_code(lang)}/contacts/"


def parse_tags(value: Any) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in re.split(r"[,#]", str(value or "")):
        tag = clean_plain_text(item, 40)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out[:12]


def blog_categories(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counter: Counter = Counter()
    for post in posts:
        category = clean_plain_text(post.get("category") or "Travel", 80)
        counter[category] += 1
    return [{"name": name, "count": count, "slug": slugify(name)} for name, count in counter.most_common()]


WIKI_USER_AGENT = "SonicCity/1.0 (https://soniccity.app)"
PLACE_IMAGE_CACHE_DIR = ROOT / "cache" / "place_images"
PLACE_GEO_CACHE_DIR = ROOT / "cache" / "place_geo"
ROUTE_CACHE_DIR = ROOT / "cache" / "routes"
ROUTE_PROVIDER = str(os.getenv("ROUTE_PROVIDER") or "osrm").strip().lower()
ROUTE_OSRM_FOOT_URL = str(os.getenv("ROUTE_OSRM_FOOT_URL") or "https://routing.openstreetmap.de/routed-foot/route/v1/foot").strip()
ROUTE_OSRM_DRIVING_URL = str(os.getenv("ROUTE_OSRM_DRIVING_URL") or "https://router.project-osrm.org/route/v1/driving").strip()
PLACE_IMAGE_PLACEHOLDER_PATH = ROOT / "static" / "img" / "place-placeholder.svg"
CITY_IMAGE_CACHE_DIR = ROOT / "cache" / "city_images"
COUNTRY_IMAGE_CACHE_DIR = ROOT / "cache" / "country_images"
CANONICAL_IMAGE_LANG = "en"

PLACE_METADATA_OVERRIDES: Dict[Tuple[str, str, str], Dict[str, Any]] = {
    ("spain", "valencia", "city-of-arts-and-sciences"): {
        "category": "landmark",
        "lat": 39.454167,
        "lon": -0.35,
    },
    ("spain", "valencia", "central-market"): {
        "category": "landmark",
        "lat": 39.4747,
        "lon": -0.3784,
    },
    ("spain", "valencia", "valencia-cathedral"): {
        "category": "church",
        "lat": 39.475833,
        "lon": -0.375,
    },
    ("spain", "valencia", "turia-gardens"): {
        "category": "park",
        "lat": 39.4713,
        "lon": -0.3757,
    },
    ("spain", "valencia", "la-lonja-de-la-seda"): {
        "category": "landmark",
        "lat": 39.474417,
        "lon": -0.378444,
    },
    ("spain", "valencia", "malvarrosa-beach"): {
        "category": "landmark",
        "lat": 39.4799,
        "lon": -0.323,
    },
    ("spain", "valencia", "bioparc-valencia"): {
        "category": "park",
        "lat": 39.478,
        "lon": -0.407,
    },
    ("spain", "valencia", "barrio-del-carmen"): {
        "category": "landmark",
        "lat": 39.4782,
        "lon": -0.3776,
    },
    ("spain", "valencia", "oceanografic"): {
        "category": "museum",
        "lat": 39.45279,
        "lon": -0.34812,
    },
    ("spain", "valencia", "albufera-day-trip"): {
        "category": "park",
        "lat": 39.3469,
        "lon": -0.333,
    },
    ("italy", "rome", "st-peters-basilica"): {
        "category": "church",
        "lat": 41.9021569,
        "lon": 12.4537105,
    },
}


def http_get_json(url: str, timeout_s: int = 10) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = r.read()
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def http_get_bytes(url: str, timeout_s: int = 20) -> Optional[bytes]:
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
                    "2",
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
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except Exception:
            pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return r.read()
    except Exception:
        return None


def image_ext_from_url(url: str) -> str:
    try:
        path = urllib.parse.urlparse(url).path
        ext = Path(path).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        if ext in {".jpg", ".png", ".webp", ".gif"}:
            return ext
    except Exception:
        pass
    return ".jpg"


def image_ext_from_bytes(data: bytes) -> Optional[str]:
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


def wiki_thumbnail_url(wiki_lang: str, title: str, size_px: int = 900) -> Optional[str]:
    title = str(title or "").strip()
    if not title:
        return None

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": str(int(size_px)),
        "titles": title,
    }
    url = f"https://{wiki_lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=10)
    if not isinstance(data, dict):
        return None

    pages = (((data.get("query") or {}).get("pages") or []))
    if not isinstance(pages, list):
        return None

    for page in pages:
        if not isinstance(page, dict):
            continue
        thumb = page.get("thumbnail")
        if isinstance(thumb, dict) and thumb.get("source"):
            return str(thumb["source"])
    return None


def wiki_thumbnail_url_search(wiki_lang: str, query: str, size_px: int = 900) -> Optional[str]:
    """
    Fallback thumbnail lookup using Wikipedia search.
    Useful when an item title isn't an exact page title (e.g. landmarks, colloquial names).
    """
    query = str(query or "").strip()
    if not query:
        return None

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": "5",
        "gsrnamespace": "0",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": str(int(size_px)),
    }
    url = f"https://{wiki_lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return None
    pages = (((data.get("query") or {}).get("pages") or []))
    if not isinstance(pages, list):
        return None

    for page in pages:
        if not isinstance(page, dict):
            continue
        thumb = page.get("thumbnail")
        if isinstance(thumb, dict) and thumb.get("source"):
            return str(thumb["source"])
    return None


def commons_thumbnail_url_search(query: str, size_px: int = 1200) -> Optional[str]:
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
        "iiurlwidth": str(int(size_px)),
    }
    url = f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return None
    pages = (((data.get("query") or {}).get("pages") or []))
    if not isinstance(pages, list):
        return None
    for page in pages:
        if not isinstance(page, dict):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        if not isinstance(info, dict):
            continue
        if not str(info.get("mime") or "").lower().startswith("image/"):
            continue
        image_url = str(info.get("thumburl") or info.get("url") or "").strip()
        if image_url.startswith(("http://", "https://")):
            return image_url
    return None


def wiki_summary(wiki_lang: str, title: str) -> Optional[Dict[str, Any]]:
    title = str(title or "").strip()
    if not title:
        return None
    slug = title.replace(" ", "_")
    url = f"https://{wiki_lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(slug)}"
    data = http_get_json(url, timeout_s=12)
    return data if isinstance(data, dict) else None


def summary_coordinates(summary: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if not isinstance(summary, dict):
        return None
    c = summary.get("coordinates")
    if isinstance(c, dict):
        try:
            lat = float(c.get("lat"))
            lon = float(c.get("lon"))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return (lat, lon)
        except Exception:
            pass
    return None


def wiki_search_titles(wiki_lang: str, query: str, limit: int = 8) -> List[str]:
    q = str(query or "").strip()
    if not q:
        return []
    params = {
        "action": "query",
        "list": "search",
        "srsearch": q,
        "srlimit": str(max(1, min(int(limit or 8), 20))),
        "format": "json",
        "origin": "*",
    }
    url = f"https://{wiki_lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return []
    results = ((data.get("query") or {}).get("search") or [])
    if not isinstance(results, list):
        return []
    out: List[str] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        t = str(r.get("title") or "").strip()
        if t:
            out.append(t)
    return out


def resolve_place_coordinates(
    wiki_lang: str,
    place_name: str,
    city_name: str,
    country_name: str,
) -> Optional[Tuple[float, float, str]]:
    """
    Best-effort coordinate resolver for a place name.
    Returns (lat, lon, resolved_title).
    """
    place_name = str(place_name or "").strip()
    city_name = str(city_name or "").strip()
    country_name = str(country_name or "").strip()
    if not place_name:
        return None

    direct = wiki_summary(wiki_lang, place_name)
    if direct and str(direct.get("type") or "").lower() != "disambiguation":
        coords = summary_coordinates(direct)
        if coords:
            return (coords[0], coords[1], str(direct.get("title") or place_name))

    queries = [
        city_name and country_name and f"\"{place_name}\" {city_name} {country_name}",
        city_name and f"\"{place_name}\" {city_name}",
        country_name and f"\"{place_name}\" {country_name}",
        city_name and country_name and f"{place_name} {city_name} {country_name}",
        city_name and f"{place_name} {city_name}",
        country_name and f"{place_name} {country_name}",
        place_name,
    ]

    for q in [x for x in queries if x]:
        titles = wiki_search_titles(wiki_lang, q, limit=10)
        for t in titles:
            s = wiki_summary(wiki_lang, t)
            if not s:
                continue
            if str(s.get("type") or "").lower() == "disambiguation":
                continue
            coords = summary_coordinates(s)
            if coords:
                return (coords[0], coords[1], str(s.get("title") or t))

    return None


def resolve_place_coordinates_osm(
    place_name: str,
    city_name: str,
    country_name: str,
) -> Optional[Tuple[float, float, str]]:
    place_name = str(place_name or "").strip()
    city_name = str(city_name or "").strip()
    country_name = str(country_name or "").strip()
    if not place_name:
        return None
    queries = [
        ", ".join(x for x in (place_name, city_name, country_name) if x),
        ", ".join(x for x in (place_name, country_name) if x),
        " ".join(x for x in (place_name, city_name, country_name) if x),
    ]
    seen: set[str] = set()
    for q in queries:
        q = q.strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": q,
            "format": "jsonv2",
            "limit": "5",
            "addressdetails": "1",
        })
        rows = http_get_json(url, timeout_s=10)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            coords = valid_lat_lon(row.get("lat"), row.get("lon"))
            title = str(row.get("name") or row.get("display_name") or place_name).strip()
            if coords and resolved_title_matches_place(title, place_name, city_name):
                return coords[0], coords[1], title
    return None


def resolved_title_matches_place(title: str, place_name: str, city_name: str) -> bool:
    title_key = normalize_place_name_key(title)
    place_key = normalize_place_name_key(place_name)
    city_key = normalize_place_name_key(city_name)
    if not title_key or not place_key:
        return False
    if city_key and title_key == city_key and place_key != city_key:
        return False
    place_tokens = {t for t in place_key.split() if len(t) > 2}
    title_tokens = {t for t in title_key.split() if len(t) > 2}
    if not place_tokens:
        return False
    overlap = len(place_tokens & title_tokens)
    return overlap >= max(1, min(2, len(place_tokens)))


def valid_lat_lon(lat: Any, lon: Any) -> Optional[Tuple[float, float]]:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        if -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0:
            return lat_f, lon_f
    except Exception:
        return None
    return None


def flag_url_from_code(code: str) -> str:
    code = (code or "").strip().lower()
    if not code:
        return ""
    # Prefer full flag (root). Fallback to square flags if needed.
    if (ROOT / "static" / "img" / "flags" / f"{code}.svg").exists():
        return f"/img/flags/{code}.svg"
    if (ROOT / "static" / "img" / "flags" / "1x1" / f"{code}.svg").exists():
        return f"/img/flags/1x1/{code}.svg"
    return ""


def flag_emoji_from_code(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return "🌍"
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def load_countries() -> List[Dict[str, Any]]:
    data = load_json(COUNTRIES_PATH)
    if data is None:
        print(f"[WARN] Missing/empty: {COUNTRIES_PATH}")
        return []

    out: List[Dict[str, Any]] = []
    if isinstance(data, list):
        for c in data:
            name = str(c.get("name") or "").strip()
            code = str(c.get("code") or "").strip().lower()
            if not name or not code:
                continue
            if code in EXCLUDED_COUNTRY_CODES:
                continue
            out.append(
                {
                    "name": name,
                    "code": code,
                    "continent": str(c.get("continent") or "").strip(),
                    "capital": str(c.get("capital") or "").strip(),
                    "slug": slugify(name),
                    "flagUrl": flag_url_from_code(code),
                    "flagEmoji": flag_emoji_from_code(code),
                }
            )
    print(f"[OK] Loaded countries: {len(out)}")
    return out


def load_cities() -> List[Dict[str, Any]]:
    data = load_json(CITIES_PATH)
    if data is None:
        print(f"[WARN] Missing/empty: {CITIES_PATH}")
        return []

    out: List[Dict[str, Any]] = []
    if isinstance(data, list):
        for c in data:
            try:
                cc = str(c.get("country", "")).strip().lower()
                if cc in EXCLUDED_COUNTRY_CODES:
                    continue
                out.append(
                    {
                        "id": str(c.get("id", "")),
                        "name": str(c.get("name", "")).strip(),
                        "country": str(c.get("country", "")).strip(),  # ISO2 code
                        "lat": float(c.get("lat")),
                        "lon": float(c.get("lon")),
                        "population": int(c.get("population") or 0),
                        "wikiTitle": str(c.get("wikiTitle") or c.get("name") or "").strip(),
                    }
                )
            except Exception:
                continue
    print(f"[OK] Loaded cities: {len(out)}")
    return out


TOP_COUNTRY_SLUG_ALIASES = {
    # country_flags.json uses “Czechia”, dataset uses “Czech Republic”
    "czech-republic": "czechia",
}

CITY_PLACE_CITY_SLUG_ALIASES = {
    ("belgium", "antwerp"): "antwerpen",
    ("belgium", "bruges"): "brugge",
    ("germany", "cologne"): "koln",
    ("germany", "frankfurt"): "frankfurt-am-main",
    ("greece", "heraklion"): "irakleion",
    ("luxembourg", "luxembourg-city"): "luxembourg",
    ("spain", "seville"): "sevilla",
    ("switzerland", "geneva"): "geneve",
    ("switzerland", "lucerne"): "luzern",
}


def parse_coordinates_raw(raw: str) -> Optional[Tuple[float, float]]:
    s = str(raw or "").strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split(";")]
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except Exception:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def load_top_places() -> Dict[str, List[Dict[str, Any]]]:
    data = load_json(TOP_PLACES_PATH)
    if data is None:
        print(f"[WARN] Missing/empty: {TOP_PLACES_PATH}")
        return {}
    if not isinstance(data, dict):
        print(f"[WARN] Bad format: {TOP_PLACES_PATH}")
        return {}

    out: Dict[str, List[Dict[str, Any]]] = {}
    total = 0

    for ctry in (data.get("countries") or []):
        name = str(ctry.get("name") or "").strip()
        if not name:
            continue

        raw_slug = slugify(name)
        country_slug = TOP_COUNTRY_SLUG_ALIASES.get(raw_slug, raw_slug)
        country = COUNTRY_BY_SLUG.get(country_slug)
        if not country:
            continue
        if (country.get("code") or "") in EXCLUDED_COUNTRY_CODES:
            continue

        places: List[Dict[str, Any]] = []
        for city in (ctry.get("cities") or []):
            place_name = str(city.get("name") or "").strip()
            if not place_name:
                continue

            place_slug = slugify(place_name)

            coords = parse_coordinates_raw((city.get("infobox") or {}).get("_coordinates_raw") or "")
            if not coords:
                continue
            lat, lon = coords

            try:
                population = int(city.get("population") or 0)
            except Exception:
                population = 0

            main_city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, place_slug))
            if main_city:
                lat = float(main_city.get("lat") or lat)
                lon = float(main_city.get("lon") or lon)
                population = int(main_city.get("population") or population)

            places.append(
                {
                    "id": str((main_city or {}).get("id") or city.get("qid") or f"tp_{country_slug}_{place_slug}"),
                    "qid": str(city.get("qid") or ""),
                    "name": place_name,
                    "country": str(country.get("code") or "").upper(),
                    "countryName": str(country.get("name") or ""),
                    "countrySlug": country_slug,
                    "citySlug": place_slug,
                    "lat": lat,
                    "lon": lon,
                    "population": population,
                    "wikiTitle": str((main_city or {}).get("wikiTitle") or place_name),
                    "inMainDataset": bool(main_city),
                    "isTopPlace": True,
                }
            )

        if places:
            places.sort(key=lambda x: (-(int(x.get("population") or 0)), x.get("name", "")))
            out[country_slug] = places
            total += len(places)

    print(f"[OK] Loaded top places: {total}")
    return out


def build_top_places_indexes() -> None:
    global TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG
    TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG = {}
    for country_slug, places in TOP_PLACES_BY_COUNTRYSLUG.items():
        for p in places:
            slug = str(p.get("citySlug") or "")
            if not slug:
                continue
            TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG[(country_slug, slug)] = p


def build_city_places_indexes() -> None:
    global CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG, PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG
    global INDEXED_CITIES_BY_COUNTRYSLUG

    CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG = {}
    PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG = {}
    INDEXED_CITIES_BY_COUNTRYSLUG = {}

    data = load_json(PLACES_INDEX_PATH)
    if data is None:
        print(f"[WARN] Missing/empty: {PLACES_INDEX_PATH}")
        return
    if not isinstance(data, dict):
        print(f"[WARN] Bad format: {PLACES_INDEX_PATH}")
        return

    cb = data.get("countries_by_slug")
    if not isinstance(cb, dict):
        print(f"[WARN] Bad format (countries_by_slug): {PLACES_INDEX_PATH}")
        return

    cities_loaded = 0
    places_loaded = 0
    seen_city_keys = set()
    for country_key, payload in cb.items():
        raw_slug = slugify(country_key)
        country_slug = TOP_COUNTRY_SLUG_ALIASES.get(raw_slug, raw_slug)
        country = COUNTRY_BY_SLUG.get(country_slug)
        if not country:
            continue
        if (country.get("code") or "") in EXCLUDED_COUNTRY_CODES:
            continue

        cities = payload.get("cities") if isinstance(payload, dict) else None
        if not isinstance(cities, list):
            continue

        for city_entry in cities:
            if not isinstance(city_entry, dict):
                continue
            city_name = str(city_entry.get("name") or "").strip()
            if not city_name:
                continue

            city_slug = slugify(city_name)
            city_slug = CITY_PLACE_CITY_SLUG_ALIASES.get((country_slug, city_slug), city_slug)
            main_city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
            if not main_city:
                continue

            places = city_entry.get("places")
            if not isinstance(places, list) or not places:
                continue

            uniq: List[Dict[str, Any]] = []
            by_slug: Dict[str, Dict[str, Any]] = {}
            for p in places:
                place_meta: Dict[str, Any] = {}
                if isinstance(p, dict):
                    place_meta = dict(p)
                    place_name = str(
                        place_meta.get("name")
                        or place_meta.get("title")
                        or place_meta.get("label")
                        or ""
                    ).strip()
                else:
                    place_name = str(p or "").strip()
                if not place_name:
                    continue
                place_slug = str(place_meta.get("slug") or slugify(place_name)).strip()
                if not place_slug:
                    continue

                override = PLACE_METADATA_OVERRIDES.get((country_slug, city_slug, place_slug), {})
                item: Dict[str, Any] = {
                    "name": place_name,
                    "slug": place_slug,
                    "countrySlug": country_slug,
                    "citySlug": city_slug,
                    "countryName": country.get("name") or "",
                    "countryCode": country.get("code") or "",
                    "cityName": main_city.get("name") or city_name,
                    "category": "Landmark",
                }
                for key in (
                    "category",
                    "wikidataId",
                    "wikidata_id",
                    "osmId",
                    "osm_id",
                    "wikipediaUrl",
                    "wikiUrl",
                    "image",
                    "imageUrl",
                    "lat",
                    "lon",
                ):
                    if place_meta.get(key) not in (None, ""):
                        item[key] = place_meta.get(key)
                item.update(override)
                current = by_slug.get(place_slug)
                if current is None:
                    by_slug[place_slug] = item
                    uniq.append(item)
                elif place_quality_score(item) > place_quality_score(current):
                    merged = {**current, **item}
                    by_slug[place_slug] = merged
                    for idx, existing in enumerate(uniq):
                        if str(existing.get("slug") or "") == place_slug:
                            uniq[idx] = merged
                            break

            if uniq:
                uniq = dedupe_places(uniq)
                CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG[(country_slug, city_slug)] = uniq
                for item in uniq:
                    PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG[(country_slug, city_slug, str(item.get("slug") or ""))] = item
                cities_loaded += 1
                places_loaded += len(uniq)

                k = (country_slug, city_slug)
                if k not in seen_city_keys:
                    seen_city_keys.add(k)
                    INDEXED_CITIES_BY_COUNTRYSLUG.setdefault(country_slug, []).append(main_city)

    print(f"[OK] Loaded city places: {cities_loaded} cities / {places_loaded} places")
    for slug, arr in INDEXED_CITIES_BY_COUNTRYSLUG.items():
        arr.sort(key=lambda x: int(x.get("population") or 0), reverse=True)


def global_top_places_for_lang(lang: str, limit: int = 12) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for (country_slug, city_slug), places in CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.items():
        country = COUNTRY_BY_SLUG.get(country_slug)
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
        if not country or not city:
            continue
        city_population = int(city.get("population") or 0)
        country_name = country_display_name_cached_for_lang(country, lang)
        city_name = city_display_name_cached_for_lang(city, lang)
        for place in (places or [])[:4]:
            place_slug = str(place.get("slug") or "").strip()
            if not place_slug:
                continue
            key = f"{country_slug}:{city_slug}:{place_slug}".lower()
            if key in seen:
                continue
            seen.add(key)
            row = dict(place)
            row["countrySlug"] = country_slug
            row["citySlug"] = city_slug
            row["countryName"] = country_name
            row["cityName"] = city_name
            row["category"] = row.get("category") or "Landmark"
            row["displayName"] = place_display_name_cached_for_lang(row, lang)
            row["name"] = row["displayName"]
            row["_rankPopulation"] = city_population
            rows.append(row)
    rows.sort(key=lambda x: (-(int(x.get("_rankPopulation") or 0)), str(x.get("name") or "")))
    return rows[:limit]


def global_top_place_groups_for_lang(
    lang: str,
    limit_groups: int = 8,
    places_per_city: int = 8,
    country_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    requested_country = str(country_filter or "").strip()
    requested_target_city_slugs = target_country_city_slugs(requested_country) if requested_country else set()
    for (country_slug, city_slug), places in CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.items():
        if requested_country and country_slug != requested_country:
            continue
        if requested_target_city_slugs and city_slug not in requested_target_city_slugs:
            continue
        country = COUNTRY_BY_SLUG.get(country_slug)
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
        if not country or not city or not places:
            continue
        country_name = country_display_name_cached_for_lang(country, lang)
        city_name = city_display_name_cached_for_lang(city, lang)
        place_rows: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for place in dedupe_places(places):
            place_slug = str(place.get("slug") or "").strip()
            if not place_slug or place_slug in seen:
                continue
            seen.add(place_slug)
            row = dict(place)
            row["countrySlug"] = country_slug
            row["citySlug"] = city_slug
            row["countryName"] = country_name
            row["cityName"] = city_name
            row["category"] = row.get("category") or "Landmark"
            row["displayName"] = place_display_name_cached_for_lang(row, lang)
            row["name"] = row["displayName"]
            place_rows.append(row)
            if len(place_rows) >= places_per_city:
                break
        if not place_rows:
            continue
        groups.append(
            {
                "countrySlug": country_slug,
                "citySlug": city_slug,
                "countryName": country_name,
                "cityName": city_name,
                "population": int(city.get("population") or 0),
                "places": place_rows,
            }
        )
    groups.sort(key=lambda x: (-(int(x.get("population") or 0)), str(x.get("cityName") or "")))
    if limit_groups and limit_groups > 0:
        return groups[:limit_groups]
    return groups


def resolve_country(country_value: str) -> Optional[Dict[str, Any]]:
    raw = str(country_value or "").strip()
    if not raw:
        return None

    code = raw.lower()
    if code in COUNTRY_BY_CODE:
        return COUNTRY_BY_CODE[code]

    name_lc = raw.lower()
    if name_lc in COUNTRY_BY_NAME_LC:
        return COUNTRY_BY_NAME_LC[name_lc]

    return None


def build_indexes() -> None:
    global COUNTRY_BY_CODE, COUNTRY_BY_NAME_LC, COUNTRY_BY_SLUG
    global CITY_BY_COUNTRYSLUG_CITYSLUG, CITIES_BY_COUNTRYSLUG

    COUNTRY_BY_CODE = {c["code"]: c for c in COUNTRIES}
    COUNTRY_BY_NAME_LC = {c["name"].lower(): c for c in COUNTRIES}
    COUNTRY_BY_SLUG = {c["slug"]: c for c in COUNTRIES}

    CITY_BY_COUNTRYSLUG_CITYSLUG = {}
    CITIES_BY_COUNTRYSLUG = {}

    for city in CITIES:
        co = resolve_country(city.get("country") or "")
        if not co:
            # Keep city usable for /api/nearby, but it won't have country pages/URLs.
            continue

        city_slug = slugify(city["name"])
        country_slug = co["slug"]

        city["countryObj"] = co
        city["citySlug"] = city_slug
        city["countrySlug"] = country_slug

        CITY_BY_COUNTRYSLUG_CITYSLUG[(country_slug, city_slug)] = city
        CITIES_BY_COUNTRYSLUG.setdefault(country_slug, []).append(city)

    for slug, arr in CITIES_BY_COUNTRYSLUG.items():
        arr.sort(key=lambda x: int(x.get("population") or 0), reverse=True)


def top_countries(n: int = 25) -> List[Dict[str, Any]]:
    items = []
    for slug, c in COUNTRY_BY_SLUG.items():
        cnt = len(CITIES_BY_COUNTRYSLUG.get(slug, []))
        items.append((cnt, c))
    items.sort(key=lambda x: (x[0], x[1]["name"]), reverse=True)
    return [x[1] for x in items[:n]]


def top_cities(n: int = 50) -> List[Dict[str, Any]]:
    usable = [c for c in CITIES if c.get("countryObj")]
    usable.sort(key=lambda x: int(x.get("population") or 0), reverse=True)
    return usable[:n]


def target_country_cities(country_slug: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Production catalog scope: up to 10 population-ranked cities per supported country."""
    cap = TARGET_CITIES_PER_COUNTRY if limit is None else int(limit or 0)
    rows = CITIES_BY_COUNTRYSLUG.get(str(country_slug or "").strip().lower(), []) or []
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for city in rows:
        city_slug = str(city.get("citySlug") or slugify(city.get("name") or "")).strip().lower()
        if not city_slug or city_slug in seen:
            continue
        seen.add(city_slug)
        out.append(city)
        if cap > 0 and len(out) >= cap:
            break
    return out


def target_country_city_slugs(country_slug: str, limit: Optional[int] = None) -> Set[str]:
    return {
        str(city.get("citySlug") or "").strip().lower()
        for city in target_country_cities(country_slug, limit)
        if str(city.get("citySlug") or "").strip()
    }


def target_countries(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Production index scope: up to 50 supported countries, excluding blocked markets."""
    cap = TARGET_COUNTRIES_LIMIT if limit is None else int(limit or 0)
    rows: List[Dict[str, Any]] = []
    for country in COUNTRIES:
        code = str(country.get("code") or "").strip().lower()
        slug = str(country.get("slug") or "").strip().lower()
        if not slug or code in EXCLUDED_COUNTRY_CODES:
            continue
        rows.append(country)
        if cap > 0 and len(rows) >= cap:
            break
    return rows


def target_country_slugs(limit: Optional[int] = None) -> Set[str]:
    return {str(country.get("slug") or "").strip().lower() for country in target_countries(limit)}


def country_in_index_scope(country_slug: str) -> bool:
    return str(country_slug or "").strip().lower() in target_country_slugs()


def city_in_index_scope(country_slug: str, city_slug: str) -> bool:
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    return country_in_index_scope(country_slug) and city_slug in target_country_city_slugs(country_slug)


def target_places_for_city(country_slug: str, city_slug: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    cap = TARGET_PLACES_PER_CITY if limit is None else int(limit or 0)
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    places = dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug), []))
    return places[:cap] if cap > 0 else places


def target_place_slugs_for_city(country_slug: str, city_slug: str, limit: Optional[int] = None) -> Set[str]:
    return {
        str(place.get("slug") or place.get("placeSlug") or "").strip().lower()
        for place in target_places_for_city(country_slug, city_slug, limit)
        if str(place.get("slug") or place.get("placeSlug") or "").strip()
    }


def place_in_index_scope(country_slug: str, city_slug: str, place_slug: str) -> bool:
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    place_slug = str(place_slug or "").strip().lower()
    return city_in_index_scope(country_slug, city_slug) and place_slug in target_place_slugs_for_city(country_slug, city_slug)


def landing_featured_places(limit: int = 24) -> List[Dict[str, Any]]:
    """
    Picks a small, diverse set of places for the landing gallery.
    We prefer 1 place per country (when available) to keep it varied.
    """

    out: List[Dict[str, Any]] = []
    if limit <= 0:
        return out

    countries = list(COUNTRY_BY_SLUG.items())
    countries.sort(key=lambda x: x[1].get("name") or "")

    for country_slug, country in countries:
        if (country.get("code") or "") in EXCLUDED_COUNTRY_CODES:
            continue
        cities = INDEXED_CITIES_BY_COUNTRYSLUG.get(country_slug) or []
        if not cities:
            continue

        city = cities[0]
        city_slug = str(city.get("citySlug") or "")
        if not city_slug:
            continue

        places = CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or []
        if not places:
            continue

        first = places[0]
        place_slug = str(first.get("slug") or "")
        if not place_slug:
            continue

        full = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
        if not full:
            full = {
                **first,
                "countrySlug": country_slug,
                "citySlug": city_slug,
                "countryName": str(country.get("name") or ""),
                "countryCode": str(country.get("code") or ""),
                "cityName": str(city.get("name") or ""),
            }

        out.append(full)
        if len(out) >= limit:
            break

    return out


def localized_featured_places(rows: List[Dict[str, Any]], lang: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        row = dict(item)
        country_slug = str(row.get("countrySlug") or "").strip().lower()
        city_slug = str(row.get("citySlug") or "").strip().lower()
        place_slug = str(row.get("slug") or row.get("placeSlug") or "").strip().lower()
        if place_slug and not place_translation_exists(country_slug, city_slug, place_slug, lang):
            continue
        co = COUNTRY_BY_SLUG.get(str(row.get("countrySlug") or ""))
        if co:
            row["countryName"] = country_display_name_cached_for_lang(co, lang)
        row["cityName"] = city_display_name_cached_for_lang(row, lang)
        row["displayName"] = place_display_name_cached_for_lang(row, lang)
        row["name"] = row["displayName"]
        out.append(row)
    return out


def localized_category_label(category: str, lang: str) -> str:
    key = slugify(category).replace("-", "_")
    translations = t(lang)
    return translations.get(f"category_{key}") or clean_plain_text(category, 80)


def landing_popular_city_cards(lang: str) -> List[Dict[str, Any]]:
    specs = [
        ("spain", "valencia", "home_city_valencia_desc", "12", "34"),
        ("spain", "barcelona", "home_city_barcelona_desc", "14", "42"),
        ("italy", "rome", "home_city_rome_desc", "15", "48"),
        ("france", "paris", "home_city_paris_desc", "16", "52"),
        ("austria", "vienna", "home_city_vienna_desc", "11", "31"),
        ("czechia", "prague", "home_city_prague_desc", "13", "36"),
    ]
    translations = t(lang)
    rows: List[Dict[str, Any]] = []
    for country_slug, city_slug, desc_key, audio_count, places_count in specs:
        if not city_translation_exists(country_slug, city_slug, lang):
            continue
        country = COUNTRY_BY_SLUG.get(country_slug) or {"name": country_slug.replace("-", " ").title(), "slug": country_slug}
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {"name": city_slug.replace("-", " ").title(), "countrySlug": country_slug, "citySlug": city_slug}
        rows.append(
            {
                "name": city_display_name_cached_for_lang({**city, "countrySlug": country_slug, "citySlug": city_slug}, lang),
                "country": country_display_name_cached_for_lang(country, lang),
                "countrySlug": country_slug,
                "citySlug": city_slug,
                "desc": translations.get(desc_key) or "",
                "audioCount": audio_count,
                "placesCount": places_count,
            }
        )
    return rows


def landing_iconic_place_cards(lang: str) -> List[Dict[str, Any]]:
    specs = [
        ("spain", "valencia", "valencia-cathedral", "Cathedral", "home_place_valencia_cathedral_desc"),
        ("spain", "barcelona", "sagrada-familia", "Landmark", "home_place_sagrada_familia_desc"),
        ("italy", "rome", "colosseum", "Monument", "home_place_colosseum_desc"),
        ("france", "paris", "eiffel-tower", "Landmark", "home_place_eiffel_tower_desc"),
        ("austria", "vienna", "schonbrunn-palace", "Palace", "home_place_schonbrunn_desc"),
        ("czechia", "prague", "charles-bridge", "Bridge", "home_place_charles_bridge_desc"),
    ]
    translations = t(lang)
    rows: List[Dict[str, Any]] = []
    for country_slug, city_slug, place_slug, category, desc_key in specs:
        if not place_translation_exists(country_slug, city_slug, place_slug, lang):
            continue
        country = COUNTRY_BY_SLUG.get(country_slug) or {"name": country_slug.replace("-", " ").title(), "slug": country_slug}
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {"name": city_slug.replace("-", " ").title(), "countrySlug": country_slug, "citySlug": city_slug}
        place = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug)) or {"name": place_slug.replace("-", " ").title(), "slug": place_slug}
        place_row = {**place, "countrySlug": country_slug, "citySlug": city_slug, "slug": place_slug}
        rows.append(
            {
                "name": place_display_name_cached_for_lang(place_row, lang),
                "category": localized_category_label(category, lang),
                "country": country_display_name_cached_for_lang(country, lang),
                "countrySlug": country_slug,
                "city": city_display_name_cached_for_lang({**city, "countrySlug": country_slug, "citySlug": city_slug}, lang),
                "citySlug": city_slug,
                "slug": place_slug,
                "desc": translations.get(desc_key) or "",
            }
        )
    return rows


def footer_popular_city_links(lang: str) -> List[Dict[str, str]]:
    specs = [("spain", "valencia"), ("italy", "rome"), ("france", "paris"), ("spain", "barcelona")]
    rows: List[Dict[str, str]] = []
    for country_slug, city_slug in specs:
        if not city_translation_exists(country_slug, city_slug, lang):
            continue
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {"name": city_slug.replace("-", " ").title(), "countrySlug": country_slug, "citySlug": city_slug}
        rows.append(
            {
                "name": city_display_name_cached_for_lang({**city, "countrySlug": country_slug, "citySlug": city_slug}, lang),
                "url": city_url(lang, country_slug, city_slug),
            }
        )
    return rows


def landing_primary_image(lang: str, featured_places: List[Dict[str, Any]]) -> str:
    if featured_places:
        p = featured_places[0]
        cslug = str(p.get("countrySlug") or "")
        cty = str(p.get("citySlug") or "")
        pslug = str(p.get("slug") or "")
        if cslug and cty and pslug:
            return f"/media/place/{CANONICAL_IMAGE_LANG}/{cslug}/{cty}/{pslug}"
    return "/static/img/place-placeholder.svg"


def country_center(country_slug: str) -> Tuple[float, float]:
    cities = CITIES_BY_COUNTRYSLUG.get(country_slug, [])
    if not cities:
        return (39.4699, -0.3763)
    sample = cities[:20]
    lat = sum(float(c["lat"]) for c in sample) / len(sample)
    lon = sum(float(c["lon"]) for c in sample) / len(sample)
    return (lat, lon)

def normalize_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if lang == "uk":
        lang = "ua"
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def is_admin_authorized() -> bool:
    if session.get("admin_email") == ADMIN_EMAIL:
        return True
    if not ADMIN_BASIC_AUTH_ENABLED:
        return False
    auth = request.authorization
    if not auth:
        return False
    email_ok = secrets.compare_digest(str(auth.username or "").strip().lower(), ADMIN_EMAIL)
    password = str(auth.password or "")
    pass_ok = False
    if ADMIN_PASSWORD_HASH:
        try:
            pass_ok = check_password_hash(ADMIN_PASSWORD_HASH, password)
        except Exception:
            pass_ok = False
    if not pass_ok and ADMIN_INITIAL_PASSWORD:
        pass_ok = secrets.compare_digest(password, ADMIN_INITIAL_PASSWORD)
    return bool(email_ok and pass_ok)


def require_admin_auth() -> Optional[Response]:
    if is_admin_authorized():
        return None
    if request.method == "GET":
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("admin_login", next=next_url), code=302)
    return Response("Admin authorization required.", 403)


def admin_password_is_valid(password: str) -> bool:
    if ADMIN_PASSWORD_HASH:
        try:
            if check_password_hash(ADMIN_PASSWORD_HASH, password):
                return True
        except Exception:
            pass
    if ADMIN_INITIAL_PASSWORD and secrets.compare_digest(password, ADMIN_INITIAL_PASSWORD):
        return True
    return False


def lang_param_or_none(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip().lower()
    if v == "uk":
        v = "ua"
    return v if v in SUPPORTED_LANGS else None


def lang_from_path(path: str) -> Optional[str]:
    m = re.match(r"^/([a-z]{2})(?:/|$)", path or "")
    if not m:
        return None
    return lang_param_or_none(m.group(1))


def parse_accept_language(header: str) -> Optional[str]:
    values: List[Tuple[float, str]] = []
    for chunk in str(header or "").split(","):
        part = chunk.strip()
        if not part:
            continue
        token, *attrs = part.split(";")
        tag = token.strip().lower()
        if not tag:
            continue
        q = 1.0
        for attr in attrs:
            a = attr.strip().lower()
            if not a.startswith("q="):
                continue
            try:
                q = float(a[2:])
            except Exception:
                pass
        values.append((q, tag))

    values.sort(key=lambda x: x[0], reverse=True)
    for _, tag in values:
        code = tag.split("-")[0]
        if code == "uk":
            code = "ua"
        if code in SUPPORTED_LANGS:
            return code
    return None


def get_client_ip() -> str:
    candidates = [
        request.headers.get("CF-Connecting-IP"),
        request.headers.get("True-Client-IP"),
        request.headers.get("X-Real-IP"),
        request.headers.get("X-Forwarded-For"),
        request.remote_addr,
    ]
    for raw in candidates:
        if not raw:
            continue
        ip = str(raw).split(",")[0].strip()
        if ip.count(":") == 1 and "." in ip:
            host, maybe_port = ip.rsplit(":", 1)
            if maybe_port.isdigit():
                ip = host
        if ip:
            return ip
    return ""


def is_public_ip(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
    except Exception:
        return False
    return not (
        obj.is_private
        or obj.is_loopback
        or obj.is_reserved
        or obj.is_link_local
        or obj.is_multicast
        or obj.is_unspecified
    )


def geo_country_from_headers() -> Optional[str]:
    for key in ("CF-IPCountry", "CloudFront-Viewer-Country", "X-Country-Code", "X-Appengine-Country"):
        raw = (request.headers.get(key) or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", raw):
            return raw
    return None


def geo_country_from_ip(ip: str) -> Optional[str]:
    if not ip or not is_public_ip(ip):
        return None

    now = time.time()
    cached = GEO_IP_CACHE.get(ip)
    if cached and (now - cached[0]) < GEO_IP_CACHE_TTL_S:
        return cached[1] or None

    country_code = ""
    try:
        url = f"https://ipapi.co/{urllib.parse.quote(ip)}/country/"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": WIKI_USER_AGENT,
                "Accept": "text/plain",
            },
        )
        with urllib.request.urlopen(req, timeout=1.8) as r:
            txt = r.read().decode("utf-8", errors="ignore").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", txt):
            country_code = txt
    except Exception:
        country_code = ""

    GEO_IP_CACHE[ip] = (now, country_code)
    return country_code or None


def lang_from_geo_country(country_code: Optional[str]) -> Optional[str]:
    cc = str(country_code or "").strip().upper()
    if not cc:
        return None
    if cc in {"FR", "BE", "LU", "MC"}:
        return "fr"
    if cc in {"ES", "AR", "MX", "CO", "CL", "PE", "UY", "VE", "EC", "BO", "PY", "CR", "PA", "GT", "HN", "SV", "NI", "DO", "PR"}:
        return "es"
    if cc in {"IT", "SM", "VA"}:
        return "it"
    if cc in {"DE", "AT", "CH", "LI"}:
        return "de"
    if cc in {"UA"}:
        return "ua"
    return None


def detect_preferred_lang() -> str:
    param_lang = lang_param_or_none(request.args.get("lang"))
    if param_lang:
        return param_lang

    cookie_lang = lang_param_or_none(request.cookies.get("lang"))
    if cookie_lang:
        return cookie_lang

    browser_lang = parse_accept_language(request.headers.get("Accept-Language") or "")
    if browser_lang:
        return browser_lang

    country_code = geo_country_from_headers()
    if not country_code:
        country_code = geo_country_from_ip(get_client_ip())
    geo_lang = lang_from_geo_country(country_code)
    if geo_lang:
        return geo_lang

    return DEFAULT_LANG


def is_bot_request() -> bool:
    ua = (request.headers.get("User-Agent") or "").lower()
    return any(x in ua for x in BOT_UA_HINTS)


def truncate_log_value(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    return text[:limit]


def access_log_should_skip(path: str) -> bool:
    clean = path or "/"
    if clean in {"/favicon.ico", "/robots.txt", "/sitemap.xml", "/llms.txt"}:
        return True
    return clean.startswith(("/static/", "/media/"))


def ua_family(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "unknown"
    if "headlesschrome" in ua:
        return "Headless Chrome"
    if "edg/" in ua or "edge/" in ua:
        return "Edge"
    if "chrome/" in ua and "chromium" not in ua:
        return "Chrome"
    if "chromium" in ua:
        return "Chromium"
    if "safari/" in ua and "chrome/" not in ua:
        return "Safari"
    if "firefox/" in ua:
        return "Firefox"
    if "bot" in ua or "crawler" in ua or "spider" in ua:
        return "Bot"
    return "Other"


def access_noise_flags(path: str, user_agent: str, referrer: str, status_code: int) -> List[str]:
    ua = (user_agent or "").lower()
    flags: List[str] = []
    if not referrer:
        flags.append("direct")
    if "headlesschrome" in ua or "phantomjs" in ua or "selenium" in ua or "playwright" in ua:
        flags.append("headless")
    if any(x in ua for x in BOT_UA_HINTS):
        flags.append("bot-ua")
    if status_code >= 400:
        flags.append("error")
    if (path or "").startswith("/api/"):
        flags.append("api")
    if ua_family(user_agent) in {"Chrome", "Headless Chrome"} and not referrer:
        flags.append("direct-chrome")
    return flags


@app.before_request
def mark_request_started() -> None:
    g.request_started_at = time.time()


@app.after_request
def write_access_event(response: Response) -> Response:
    if robots_meta_for_path(request.path or "/", current_lang()).startswith("noindex"):
        response.headers["X-Robots-Tag"] = GLOBAL_X_ROBOTS_TAG
    if not ACCESS_LOG_ENABLED:
        return response
    try:
        path = request.path or "/"
        if access_log_should_skip(path):
            return response

        ip = get_client_ip()
        country = geo_country_from_headers()
        if not country and ACCESS_LOG_GEO_LOOKUP:
            country = geo_country_from_ip(ip)

        referrer = request.referrer or request.headers.get("Referer") or ""
        user_agent = request.headers.get("User-Agent") or ""
        started_at = float(getattr(g, "request_started_at", time.time()) or time.time())
        duration_ms = max(0, int((time.time() - started_at) * 1000))
        event = {
            "ts": int(time.time()),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": request.method,
            "path": truncate_log_value(path, 300),
            "query": truncate_log_value((request.query_string or b"").decode("utf-8", errors="ignore"), 500),
            "status": int(response.status_code),
            "durationMs": duration_ms,
            "ip": truncate_log_value(ip, 80),
            "country": truncate_log_value(country or "", 8),
            "host": truncate_log_value(request.host, 120),
            "referrer": truncate_log_value(referrer, 500),
            "ua": truncate_log_value(user_agent, 500),
            "uaFamily": ua_family(user_agent),
            "flags": access_noise_flags(path, user_agent, referrer, int(response.status_code)),
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with ACCESS_LOG_LOCK:
            with ACCESS_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass
    return response


def should_auto_redirect_from_root(detected_lang: str) -> bool:
    if detected_lang == "en":
        return False
    if is_bot_request():
        return False
    if (request.args.get("no_redirect") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    host = (request.host or "").lower()
    if host.startswith("127.0.0.1") or host.startswith("localhost"):
        return False
    return True


@app.before_request
def redirect_en_prefixed_paths() -> Optional[Response]:
    path = (request.path or "/").split("?", 1)[0]
    if path == "/en" or path.startswith("/en/"):
        target = path[3:] or "/"
        if not target.startswith("/"):
            target = f"/{target}"
        qs = (request.query_string or b"").decode("utf-8", errors="ignore")
        if qs:
            target = f"{target}?{qs}"
        return redirect(target, code=301)
    return None


@app.before_request
def apply_managed_redirects() -> Optional[Response]:
    if request.method not in {"GET", "HEAD"}:
        return None
    path = (request.path or "/").rstrip("/") or "/"
    if path.startswith(("/admin", "/api", "/static", "/media")) or path in {"/robots.txt", "/sitemap.xml", "/llms.txt", "/favicon.ico"}:
        return None
    for row in load_admin_redirects():
        if not isinstance(row, dict) or not row.get("active", True):
            continue
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        if not source or not target:
            continue
        source_path = source.rstrip("/") or "/"
        if source_path != path:
            continue
        if target.rstrip("/") == path:
            continue
        code = int(row.get("code") or 301)
        if code not in {301, 302, 307, 308}:
            code = 301
        return redirect(target, code=code)
    return None


def split_path_lang(path: str) -> Tuple[str, List[str]]:
    clean = (path or "/").split("?", 1)[0]
    if clean != "/" and clean.endswith("/"):
        clean = clean[:-1]
    parts = [p for p in clean.split("/") if p]
    if not parts:
        return "en", []
    first = str(parts[0]).strip().lower()
    if first in SUPPORTED_LANGS or first == "uk":
        return normalize_lang(first), parts[1:]
    return "en", parts


def localized_path_for(path: str, lang: str) -> str:
    lang = normalize_lang(lang)
    public_lang = public_lang_code(lang)
    _, tail = split_path_lang(path)
    if not tail:
        return "/" if lang == "en" else f"/{public_lang}"
    if tail[0] == "admin":
        return "/" + "/".join(tail)
    if lang == "en":
        return "/" + "/".join(tail)
    return "/" + "/".join([public_lang, *tail])


def host_base_url() -> str:
    if SITE_URL:
        return SITE_URL
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
    if host:
        return f"{proto}://{host}"
    return (request.url_root or "").rstrip("/")


def absolute_url(path: str) -> str:
    p = path if str(path).startswith("/") else f"/{path}"
    return f"{host_base_url().rstrip('/')}{p}"


def canonical_path_for_request() -> str:
    path = (request.path or "/").split("?", 1)[0]
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    if path == "/en":
        return "/"
    if path.startswith("/en/"):
        stripped = path[3:]
        return stripped if stripped.startswith("/") else f"/{stripped}"
    return path or "/"


def entity_route_from_path(path: str) -> Optional[Dict[str, str]]:
    _, tail = split_path_lang(path)
    if not tail:
        return None
    reserved = {"api", "media", "static", "img", "admin", "main", "c", "robots.txt", "sitemap.xml", "llms.txt", "favicon.ico"}
    if tail[0] in reserved:
        return None
    country_slug = tail[0]
    if country_slug not in COUNTRY_BY_SLUG:
        return None
    if len(tail) == 1:
        return {"kind": "country", "country_slug": country_slug, "city_slug": "", "place_slug": ""}
    city_slug = tail[1]
    if len(tail) == 2:
        if CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)):
            return {"kind": "city", "country_slug": country_slug, "city_slug": city_slug, "place_slug": ""}
        return None
    place_slug = tail[2]
    if len(tail) == 3 and PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug)):
        return {"kind": "place", "country_slug": country_slug, "city_slug": city_slug, "place_slug": place_slug}
    return None


def entity_in_index_scope(kind: str, country_slug: str, city_slug: str = "", place_slug: str = "") -> bool:
    kind = str(kind or "").strip().lower()
    if kind == "country":
        return country_in_index_scope(country_slug)
    if kind == "city":
        return city_in_index_scope(country_slug, city_slug)
    if kind == "place":
        return place_in_index_scope(country_slug, city_slug, place_slug)
    return False


def entity_is_indexable_for_lang(kind: str, lang: str, country_slug: str, city_slug: str = "", place_slug: str = "") -> bool:
    if not entity_in_index_scope(kind, country_slug, city_slug, place_slug):
        return False
    return entity_page_is_published_for_lang(kind, lang, country_slug, city_slug, place_slug)


def private_or_technical_path(path: str) -> bool:
    clean = (path or "/").split("?", 1)[0].rstrip("/") or "/"
    if clean.startswith((
        "/admin",
        "/api",
        "/account",
        "/login",
        "/verify-email",
        "/reset-password",
        "/preview",
        "/draft",
        "/internal",
        "/generate-audio",
        "/tts",
        "/cache",
    )):
        return True
    return clean in {"/robots.txt", "/llms.txt", "/favicon.ico"} or clean.endswith(".json") or clean.endswith(".xml")


def robots_meta_for_path(path: str, lang: Optional[str] = None) -> str:
    if private_or_technical_path(path):
        return "noindex,nofollow"
    resolved_lang = normalize_lang(lang or split_path_lang(path)[0])
    entity = entity_route_from_path(path)
    if entity:
        if entity_is_indexable_for_lang(
            entity["kind"],
            resolved_lang,
            entity["country_slug"],
            entity.get("city_slug") or "",
            entity.get("place_slug") or "",
        ):
            return "index,follow"
        return "noindex,nofollow"
    return "index,follow"


def available_langs_for_path(path: str) -> List[str]:
    entity = entity_route_from_path(path)
    if not entity:
        return list(LANG_ORDER)
    return published_langs_for_entity(
        entity["kind"],
        entity["country_slug"],
        entity.get("city_slug") or "",
        entity.get("place_slug") or "",
    )


def hreflang_links_for_request() -> List[Dict[str, str]]:
    path = canonical_path_for_request()
    parts = [p for p in path.split("/") if p]
    reserved = {"api", "media", "static", "img", "admin", "main", "c", "robots.txt", "sitemap.xml", "llms.txt", "favicon.ico"}
    if parts and parts[0] in reserved:
        return []

    links: List[Dict[str, str]] = []
    available_langs = available_langs_for_path(path)
    for lang in available_langs:
        rel = localized_path_for(path, lang)
        links.append(
            {
                "lang": HREFLANG_CODE_BY_LANG.get(lang, lang),
                "url": absolute_url(rel),
            }
        )
    if DEFAULT_LANG in available_langs:
        links.append({"lang": "x-default", "url": absolute_url(localized_path_for(path, DEFAULT_LANG))})
    return links


def current_lang() -> str:
    # Per product requirement: "/" is always English
    if request.path == "/":
        return "en"
    path = (request.path or "/").split("?", 1)[0]
    lang_on_path = lang_from_path(path)
    if lang_on_path:
        return normalize_lang(lang_on_path)

    parts = [p for p in path.split("/") if p]
    reserved = {"api", "media", "static", "img", "admin", "main", "c", "robots.txt", "sitemap.xml", "llms.txt", "favicon.ico"}
    if parts and parts[0] not in reserved:
        return "en"
    return normalize_lang(request.args.get("lang") or request.cookies.get("lang") or DEFAULT_LANG)


class TranslationDict(dict):
    def __missing__(self, key: str) -> str:
        text_key = str(key)
        fallback = str(self.get(f"__fallback__{text_key}") or "")
        if fallback:
            self[text_key] = fallback
            return fallback
        fallback = text_key.replace("_", " ").replace(".", " ").strip()
        self[text_key] = fallback
        return fallback


def t(lang: str) -> Dict[str, str]:
    lang = normalize_lang(lang)
    out = dict(I18N[DEFAULT_LANG])
    out.update(ADDITIONAL_UI_TRANSLATIONS.get(DEFAULT_LANG) or {})
    try:
        out.update(ui_translation_map(DEFAULT_LANG))
    except Exception:
        pass
    out.update(I18N.get(lang) or {})
    out.update(ADDITIONAL_UI_TRANSLATIONS.get(lang) or {})
    try:
        out.update(ui_translation_map(lang))
    except Exception:
        pass
    return TranslationDict(out)


def i18n_fmt(template: str, **kwargs: Any) -> str:
    out = str(template or "")
    for key, value in kwargs.items():
        out = out.replace("{" + str(key) + "}", str(value))
    return out


def country_url(lang: str, country_slug: str) -> str:
    slug = normalize_lang(lang)
    return f"/{country_slug}" if slug == "en" else f"/{public_lang_code(slug)}/{country_slug}"


def city_url(lang: str, country_slug: str, city_slug: str) -> str:
    slug = normalize_lang(lang)
    return f"/{country_slug}/{city_slug}" if slug == "en" else f"/{public_lang_code(slug)}/{country_slug}/{city_slug}"


def place_url(lang: str, country_slug: str, city_slug: str, place_slug: str) -> str:
    slug = normalize_lang(lang)
    if slug == "en":
        return f"/{country_slug}/{city_slug}/{place_slug}"
    return f"/{public_lang_code(slug)}/{country_slug}/{city_slug}/{place_slug}"


def landing_url(lang: str) -> str:
    slug = normalize_lang(lang)
    return "/" if slug == "en" else f"/{public_lang_code(slug)}"


def audio_manifest_path(
    *,
    version: str,
    lang: str,
    gender: str,
    country_slug: str,
    city_slug: str,
    place_slug: Optional[str] = None,
) -> Path:
    return AUDIO_STORAGE_PROVIDER.manifest_path(
        version=version,
        lang=lang,
        gender=gender,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )


def is_siri_audio_manifest(manifest_path: Path) -> bool:
    try:
        if not manifest_path.exists() or manifest_path.stat().st_size <= 0:
            return False
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        backend = str(data.get("ttsBackend") or "").strip().lower()
        profile = str(data.get("voiceProfile") or "").strip().lower()
        sections = data.get("sections") or []
        if backend != "edge":
            return False
        if profile != "siri":
            return False
        if not isinstance(sections, list) or not sections:
            return False
        return True
    except Exception:
        return False


def siri_manifest_title(
    *,
    lang: str,
    country_slug: str,
    city_slug: str,
    place_slug: Optional[str] = None,
) -> str:
    for gender in ("female", "male"):
        manifest_path = audio_manifest_path(
            version=AUDIO_BUILD_AUDIO_VERSION,
            lang=lang,
            gender=gender,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
        )
        if not is_siri_audio_manifest(manifest_path):
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = str(data.get("title") or "").strip()
            if title:
                return title
        except Exception:
            continue
    return ""


def read_audio_manifest_summary(manifest_path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not manifest_path.exists() or manifest_path.stat().st_size <= 0:
            return None
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        backend = str(data.get("ttsBackend") or "").strip().lower()
        profile = str(data.get("voiceProfile") or "").strip().lower()
        sections = data.get("sections") or []
        if backend != "edge" or profile != "siri" or not isinstance(sections, list) or not sections:
            return None
        ready = 0
        failed = 0
        outdated = 0
        for sec in sections:
            status = str((sec or {}).get("status") or "ready").strip().lower()
            if status == "failed":
                failed += 1
            elif status == "outdated":
                outdated += 1
            else:
                ready += 1
        return {
            "sections": len(sections),
            "ready": ready,
            "failed": failed,
            "outdated": outdated,
            "voice": str(data.get("voiceName") or data.get("voice") or "").strip(),
            "updated": int(manifest_path.stat().st_mtime),
        }
    except Exception:
        return None


def audio_target_summary(
    *,
    country_slug: str,
    city_slug: str,
    place_slug: Optional[str] = None,
) -> Dict[str, Any]:
    ready_langs: List[str] = []
    sections = 0
    ready = 0
    failed = 0
    outdated = 0
    newest = 0
    voices: List[str] = []
    for lang in LANG_ORDER:
        lang_best: Optional[Dict[str, Any]] = None
        for gender in ("female", "male"):
            manifest_path = audio_manifest_path(
                version=AUDIO_BUILD_AUDIO_VERSION,
                lang=lang,
                gender=gender,
                country_slug=country_slug,
                city_slug=city_slug,
                place_slug=place_slug,
            )
            summary = read_audio_manifest_summary(manifest_path)
            if summary:
                lang_best = summary
                voice = str(summary.get("voice") or "")
                if voice and voice not in voices:
                    voices.append(voice)
                break
        if not lang_best:
            continue
        ready_langs.append(lang)
        sections = max(sections, int(lang_best.get("sections") or 0))
        ready += int(lang_best.get("ready") or 0)
        failed += int(lang_best.get("failed") or 0)
        outdated += int(lang_best.get("outdated") or 0)
        newest = max(newest, int(lang_best.get("updated") or 0))
    total_langs = len(LANG_ORDER)
    return {
        "readyLangs": ready_langs,
        "readyLangCount": len(ready_langs),
        "totalLangs": total_langs,
        "sections": sections,
        "ready": ready,
        "failed": failed,
        "outdated": outdated,
        "voice": ", ".join(voices[:2]),
        "updated": newest,
        "status": "ready" if len(ready_langs) == total_langs and failed == 0 and outdated == 0 else ("partial" if ready_langs else "missing"),
    }


def title_i18n_cache_path(
    *,
    kind: str,
    lang: str,
    country_slug: str = "",
    city_slug: str = "",
    place_slug: str = "",
) -> Path:
    lang = normalize_lang(lang)
    base = TITLE_I18N_CACHE_DIR / lang / kind
    if kind == "country":
        return base / f"{country_slug}.json"
    if kind == "city":
        return base / country_slug / f"{city_slug}.json"
    return base / country_slug / city_slug / f"{place_slug}.json"


def read_title_i18n_cache(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        title = str(data.get("title") or "").strip()
        return title
    except Exception:
        return ""


def write_title_i18n_cache(path: Path, title: str) -> None:
    title = str(title or "").strip()
    if not title:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"title": title}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def wiki_langlink_title(from_wiki_lang: str, title: str, target_wiki_lang: str) -> str:
    from_wiki_lang = str(from_wiki_lang or "").strip().lower()
    target_wiki_lang = str(target_wiki_lang or "").strip().lower()
    title = str(title or "").strip()
    if not from_wiki_lang or not target_wiki_lang or not title:
        return ""
    if from_wiki_lang == target_wiki_lang:
        return title

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "prop": "langlinks",
        "lllimit": "500",
        "titles": title,
    }
    url = f"https://{from_wiki_lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    data = http_get_json(url, timeout_s=12)
    if not isinstance(data, dict):
        return ""
    pages = (((data.get("query") or {}).get("pages") or []))
    if not isinstance(pages, list) or not pages:
        return ""
    page = pages[0] or {}
    links = page.get("langlinks") or []
    if not isinstance(links, list):
        return ""
    for item in links:
        if not isinstance(item, dict):
            continue
        if str(item.get("lang") or "").strip().lower() != target_wiki_lang:
            continue
        translated = str(item.get("title") or item.get("*") or "").strip()
        if translated:
            return translated
    return ""


def wiki_summary_title_if_exists(wiki_lang: str, title: str) -> str:
    summary = wiki_summary(wiki_lang, title)
    if not isinstance(summary, dict):
        return ""
    if str(summary.get("type") or "").lower() == "disambiguation":
        return ""
    return str(summary.get("title") or title or "").strip()


def resolve_localized_title(
    *,
    kind: str,
    lang: str,
    country_slug: str = "",
    city_slug: str = "",
    place_slug: str = "",
    source_title: str,
    city_name: str = "",
    country_name: str = "",
) -> str:
    lang = normalize_lang(lang)
    source_title = str(source_title or "").strip()
    city_name = str(city_name or "").strip()
    country_name = str(country_name or "").strip()
    if not source_title:
        return ""
    if lang == "en":
        return source_title

    wiki_lang = SUPPORTED_LANGS.get(lang, SUPPORTED_LANGS[DEFAULT_LANG])["wiki"]
    mem_key = f"{lang}:{kind}:{country_slug}:{city_slug}:{place_slug}:{source_title}"
    with TITLE_I18N_LOCK:
        cached_mem = TITLE_I18N_MEM.get(mem_key)
    if cached_mem:
        return cached_mem

    cache_path = title_i18n_cache_path(
        kind=kind,
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )
    if cache_path.exists():
        cached = read_title_i18n_cache(cache_path)
        if cached:
            with TITLE_I18N_LOCK:
                TITLE_I18N_MEM[mem_key] = cached
            return cached

    translated = wiki_langlink_title("en", source_title, wiki_lang)
    if not translated:
        translated = wiki_summary_title_if_exists(wiki_lang, source_title)

    if not translated:
        queries: List[str] = []
        if kind == "place":
            queries.extend(
                [
                    city_name and country_name and f"\"{source_title}\" {city_name} {country_name}",
                    city_name and f"\"{source_title}\" {city_name}",
                    country_name and f"\"{source_title}\" {country_name}",
                    source_title,
                ]
            )
        elif kind == "city":
            queries.extend(
                [
                    country_name and f"{source_title} {country_name}",
                    source_title,
                ]
            )
        else:
            queries.append(source_title)

        for query in [x for x in queries if x]:
            titles = wiki_search_titles(wiki_lang, query, limit=6)
            for title in titles:
                resolved = wiki_summary_title_if_exists(wiki_lang, title)
                if resolved:
                    translated = resolved
                    break
            if translated:
                break

    if translated:
        with TITLE_I18N_LOCK:
            TITLE_I18N_MEM[mem_key] = translated
        write_title_i18n_cache(cache_path, translated)
    return translated


def cached_localized_title(
    *,
    kind: str,
    lang: str,
    country_slug: str = "",
    city_slug: str = "",
    place_slug: str = "",
    source_title: str,
) -> str:
    lang = normalize_lang(lang)
    source_title = str(source_title or "").strip()
    if not source_title:
        return ""
    if lang == "en":
        return source_title
    mem_key = f"{lang}:{kind}:{country_slug}:{city_slug}:{place_slug}:{source_title}"
    with TITLE_I18N_LOCK:
        cached_mem = TITLE_I18N_MEM.get(mem_key)
    if cached_mem:
        return cached_mem
    cache_path = title_i18n_cache_path(
        kind=kind,
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )
    if not cache_path.exists():
        return ""
    cached = read_title_i18n_cache(cache_path)
    if cached:
        with TITLE_I18N_LOCK:
            TITLE_I18N_MEM[mem_key] = cached
    return cached


COUNTRY_NAME_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ua": {
        "albania": "Албанія", "andorra": "Андорра", "austria": "Австрія", "belgium": "Бельгія",
        "bosnia-and-herzegovina": "Боснія і Герцеговина", "bulgaria": "Болгарія", "croatia": "Хорватія",
        "cyprus": "Кіпр", "czechia": "Чехія", "denmark": "Данія", "estonia": "Естонія",
        "finland": "Фінляндія", "france": "Франція", "germany": "Німеччина", "greece": "Греція",
        "hungary": "Угорщина", "iceland": "Ісландія", "ireland": "Ірландія", "italy": "Італія",
        "kosovo": "Косово", "latvia": "Латвія", "liechtenstein": "Ліхтенштейн", "lithuania": "Литва",
        "luxembourg": "Люксембург", "malta": "Мальта", "moldova": "Молдова", "monaco": "Монако",
        "montenegro": "Чорногорія", "netherlands": "Нідерланди", "north-macedonia": "Північна Македонія",
        "norway": "Норвегія", "poland": "Польща", "portugal": "Португалія", "romania": "Румунія",
        "san-marino": "Сан-Марино", "serbia": "Сербія", "slovakia": "Словаччина", "slovenia": "Словенія",
        "spain": "Іспанія", "sweden": "Швеція", "switzerland": "Швейцарія", "turkey": "Туреччина",
        "ukraine": "Україна", "united-kingdom": "Велика Британія", "vatican-city": "Ватикан",
    },
    "fr": {
        "albania": "Albanie", "andorra": "Andorre", "austria": "Autriche", "belgium": "Belgique",
        "bosnia-and-herzegovina": "Bosnie-Herzégovine", "bulgaria": "Bulgarie", "croatia": "Croatie",
        "cyprus": "Chypre", "czechia": "Tchéquie", "denmark": "Danemark", "estonia": "Estonie",
        "finland": "Finlande", "france": "France", "germany": "Allemagne", "greece": "Grèce",
        "hungary": "Hongrie", "iceland": "Islande", "ireland": "Irlande", "italy": "Italie",
        "kosovo": "Kosovo", "latvia": "Lettonie", "liechtenstein": "Liechtenstein", "lithuania": "Lituanie",
        "luxembourg": "Luxembourg", "malta": "Malte", "moldova": "Moldavie", "monaco": "Monaco",
        "montenegro": "Monténégro", "netherlands": "Pays-Bas", "north-macedonia": "Macédoine du Nord",
        "norway": "Norvège", "poland": "Pologne", "portugal": "Portugal", "romania": "Roumanie",
        "san-marino": "Saint-Marin", "serbia": "Serbie", "slovakia": "Slovaquie", "slovenia": "Slovénie",
        "spain": "Espagne", "sweden": "Suède", "switzerland": "Suisse", "turkey": "Turquie",
        "ukraine": "Ukraine", "united-kingdom": "Royaume-Uni", "vatican-city": "Vatican",
    },
    "es": {
        "albania": "Albania", "andorra": "Andorra", "austria": "Austria", "belgium": "Bélgica",
        "bosnia-and-herzegovina": "Bosnia y Herzegovina", "bulgaria": "Bulgaria", "croatia": "Croacia",
        "cyprus": "Chipre", "czechia": "Chequia", "denmark": "Dinamarca", "estonia": "Estonia",
        "finland": "Finlandia", "france": "Francia", "germany": "Alemania", "greece": "Grecia",
        "hungary": "Hungría", "iceland": "Islandia", "ireland": "Irlanda", "italy": "Italia",
        "kosovo": "Kosovo", "latvia": "Letonia", "liechtenstein": "Liechtenstein", "lithuania": "Lituania",
        "luxembourg": "Luxemburgo", "malta": "Malta", "moldova": "Moldavia", "monaco": "Mónaco",
        "montenegro": "Montenegro", "netherlands": "Países Bajos", "north-macedonia": "Macedonia del Norte",
        "norway": "Noruega", "poland": "Polonia", "portugal": "Portugal", "romania": "Rumanía",
        "san-marino": "San Marino", "serbia": "Serbia", "slovakia": "Eslovaquia", "slovenia": "Eslovenia",
        "spain": "España", "sweden": "Suecia", "switzerland": "Suiza", "turkey": "Turquía",
        "ukraine": "Ucrania", "united-kingdom": "Reino Unido", "vatican-city": "Ciudad del Vaticano",
    },
    "it": {
        "albania": "Albania", "andorra": "Andorra", "austria": "Austria", "belgium": "Belgio",
        "bosnia-and-herzegovina": "Bosnia ed Erzegovina", "bulgaria": "Bulgaria", "croatia": "Croazia",
        "cyprus": "Cipro", "czechia": "Cechia", "denmark": "Danimarca", "estonia": "Estonia",
        "finland": "Finlandia", "france": "Francia", "germany": "Germania", "greece": "Grecia",
        "hungary": "Ungheria", "iceland": "Islanda", "ireland": "Irlanda", "italy": "Italia",
        "kosovo": "Kosovo", "latvia": "Lettonia", "liechtenstein": "Liechtenstein", "lithuania": "Lituania",
        "luxembourg": "Lussemburgo", "malta": "Malta", "moldova": "Moldavia", "monaco": "Monaco",
        "montenegro": "Montenegro", "netherlands": "Paesi Bassi", "north-macedonia": "Macedonia del Nord",
        "norway": "Norvegia", "poland": "Polonia", "portugal": "Portogallo", "romania": "Romania",
        "san-marino": "San Marino", "serbia": "Serbia", "slovakia": "Slovacchia", "slovenia": "Slovenia",
        "spain": "Spagna", "sweden": "Svezia", "switzerland": "Svizzera", "turkey": "Turchia",
        "ukraine": "Ucraina", "united-kingdom": "Regno Unito", "vatican-city": "Città del Vaticano",
    },
    "de": {
        "albania": "Albanien", "andorra": "Andorra", "austria": "Österreich", "belgium": "Belgien",
        "bosnia-and-herzegovina": "Bosnien und Herzegowina", "bulgaria": "Bulgarien", "croatia": "Kroatien",
        "cyprus": "Zypern", "czechia": "Tschechien", "denmark": "Dänemark", "estonia": "Estland",
        "finland": "Finnland", "france": "Frankreich", "germany": "Deutschland", "greece": "Griechenland",
        "hungary": "Ungarn", "iceland": "Island", "ireland": "Irland", "italy": "Italien",
        "kosovo": "Kosovo", "latvia": "Lettland", "liechtenstein": "Liechtenstein", "lithuania": "Litauen",
        "luxembourg": "Luxemburg", "malta": "Malta", "moldova": "Moldau", "monaco": "Monaco",
        "montenegro": "Montenegro", "netherlands": "Niederlande", "north-macedonia": "Nordmazedonien",
        "norway": "Norwegen", "poland": "Polen", "portugal": "Portugal", "romania": "Rumänien",
        "san-marino": "San Marino", "serbia": "Serbien", "slovakia": "Slowakei", "slovenia": "Slowenien",
        "spain": "Spanien", "sweden": "Schweden", "switzerland": "Schweiz", "turkey": "Türkei",
        "ukraine": "Ukraine", "united-kingdom": "Vereinigtes Königreich", "vatican-city": "Vatikanstadt",
    },
}


ENTITY_NAME_TRANSLATIONS: Dict[str, Dict[str, Dict[str, str]]] = {
    "city": {
        "valencia": {"ua": "Валенсія", "fr": "Valence", "es": "Valencia", "it": "Valencia", "de": "Valencia"},
        "barcelona": {"ua": "Барселона", "fr": "Barcelone", "es": "Barcelona", "it": "Barcellona", "de": "Barcelona"},
        "rome": {"ua": "Рим", "fr": "Rome", "es": "Roma", "it": "Roma", "de": "Rom"},
        "paris": {"ua": "Париж", "fr": "Paris", "es": "París", "it": "Parigi", "de": "Paris"},
        "vienna": {"ua": "Відень", "fr": "Vienne", "es": "Viena", "it": "Vienna", "de": "Wien"},
        "prague": {"ua": "Прага", "fr": "Prague", "es": "Praga", "it": "Praga", "de": "Prag"},
        "madrid": {"ua": "Мадрид", "fr": "Madrid", "es": "Madrid", "it": "Madrid", "de": "Madrid"},
        "florence": {"ua": "Флоренція", "fr": "Florence", "es": "Florencia", "it": "Firenze", "de": "Florenz"},
        "venice": {"ua": "Венеція", "fr": "Venise", "es": "Venecia", "it": "Venezia", "de": "Venedig"},
        "nice": {"ua": "Ніцца", "fr": "Nice", "es": "Niza", "it": "Nizza", "de": "Nizza"},
        "lyon": {"ua": "Ліон", "fr": "Lyon", "es": "Lyon", "it": "Lione", "de": "Lyon"},
    },
    "place": {
        "valencia-cathedral": {"ua": "Валенсійський собор", "fr": "Cathédrale de Valence", "es": "Catedral de Valencia", "it": "Cattedrale di Valencia", "de": "Kathedrale von Valencia"},
        "sagrada-familia": {"ua": "Саграда Фамілія", "fr": "Sagrada Família", "es": "Sagrada Familia", "it": "Sagrada Família", "de": "Sagrada Família"},
        "colosseum": {"ua": "Колізей", "fr": "Colisée", "es": "Coliseo", "it": "Colosseo", "de": "Kolosseum"},
        "eiffel-tower": {"ua": "Ейфелева вежа", "fr": "Tour Eiffel", "es": "Torre Eiffel", "it": "Torre Eiffel", "de": "Eiffelturm"},
        "schonbrunn-palace": {"ua": "Палац Шенбрунн", "fr": "Château de Schönbrunn", "es": "Palacio de Schönbrunn", "it": "Palazzo di Schönbrunn", "de": "Schloss Schönbrunn"},
        "charles-bridge": {"ua": "Карлів міст", "fr": "Pont Charles", "es": "Puente de Carlos", "it": "Ponte Carlo", "de": "Karlsbrücke"},
    },
}

ENGLISH_ENTITY_NAME_OVERRIDES: Dict[str, Dict[str, str]] = {
    "city": {
        "arhus": "Aarhus",
        "antwerpen": "Antwerp",
        "geneve": "Geneva",
        "gent": "Ghent",
        "gdansk": "Gdansk",
        "goteborg": "Gothenburg",
        "koln": "Cologne",
        "krakow": "Krakow",
        "luzern": "Lucerne",
        "malmo": "Malmo",
        "nurnberg": "Nuremberg",
        "odz": "Lodz",
        "poznan": "Poznan",
        "rome": "Rome",
        "vienna": "Vienna",
        "prague": "Prague",
        "wrocaw": "Wroclaw",
        "zurich": "Zurich",
    },
}


def manual_country_name(country_slug: str, lang: str) -> str:
    lang = normalize_lang(lang)
    return (COUNTRY_NAME_TRANSLATIONS.get(lang) or {}).get(str(country_slug or "").strip().lower(), "")


def manual_entity_name(kind: str, slug: str, lang: str) -> str:
    lang = normalize_lang(lang)
    clean_slug = str(slug or "").strip().lower()
    if lang == DEFAULT_LANG:
        english = (ENGLISH_ENTITY_NAME_OVERRIDES.get(kind) or {}).get(clean_slug, "")
        if english:
            return english
    return ((ENTITY_NAME_TRANSLATIONS.get(kind) or {}).get(clean_slug) or {}).get(lang, "")


def country_display_name_for_lang(country: Dict[str, Any], lang: str) -> str:
    country_slug = str(country.get("slug") or slugify(country.get("name") or "")).strip().lower()
    source_title = str(country.get("name") or "").strip()
    return (
        manual_country_name(country_slug, lang)
        or
        resolve_localized_title(
            kind="country",
            lang=lang,
            country_slug=country_slug,
            source_title=source_title,
            country_name=source_title,
        )
        or source_title
    )


def country_display_name_cached_for_lang(country: Dict[str, Any], lang: str) -> str:
    country_slug = str(country.get("slug") or slugify(country.get("name") or "")).strip().lower()
    source_title = str(country.get("name") or "").strip()
    return (
        manual_country_name(country_slug, lang)
        or
        cached_localized_title(
            kind="country",
            lang=lang,
            country_slug=country_slug,
            source_title=source_title,
        )
        or source_title
    )


def city_display_name_for_lang(city: Dict[str, Any], lang: str) -> str:
    lang = normalize_lang(lang)
    country_slug = str(city.get("countrySlug") or "").strip().lower()
    city_slug = str(city.get("citySlug") or slugify(city.get("name") or "")).strip().lower()
    manual = manual_entity_name("city", city_slug, lang)
    if manual:
        return manual
    country = COUNTRY_BY_SLUG.get(country_slug) or resolve_country(city.get("country") or "")
    source_title = str(city.get("wikiTitle") or city.get("name") or "").strip()
    title = (
        resolve_localized_title(
            kind="city",
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            source_title=source_title,
            country_name=str((country or {}).get("name") or ""),
        )
        or str(city.get("name") or "")
    )
    if lang == DEFAULT_LANG:
        return title
    if title and title != str(city.get("name") or ""):
        return title
    return siri_manifest_title(lang=lang, country_slug=country_slug, city_slug=city_slug) or title


def city_display_name_cached_for_lang(city: Dict[str, Any], lang: str) -> str:
    lang = normalize_lang(lang)
    country_slug = str(city.get("countrySlug") or "").strip().lower()
    city_slug = str(city.get("citySlug") or slugify(city.get("name") or "")).strip().lower()
    manual = manual_entity_name("city", city_slug, lang)
    if manual:
        return manual
    cached = (
        cached_localized_title(
            kind="city",
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            source_title=str(city.get("wikiTitle") or city.get("name") or "").strip(),
        )
        or str(city.get("name") or "")
    )
    if lang == DEFAULT_LANG:
        return cached
    if cached and cached != str(city.get("name") or ""):
        return cached
    return siri_manifest_title(lang=lang, country_slug=country_slug, city_slug=city_slug) or cached


def place_display_name_for_lang(place: Dict[str, Any], lang: str) -> str:
    lang = normalize_lang(lang)
    country_slug = str(place.get("countrySlug") or "").strip().lower()
    city_slug = str(place.get("citySlug") or "").strip().lower()
    place_slug = str(place.get("slug") or "").strip().lower()
    manual = manual_entity_name("place", place_slug, lang)
    if manual:
        return manual
    country = COUNTRY_BY_SLUG.get(country_slug)
    city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {}
    title = (
        resolve_localized_title(
            kind="place",
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
            source_title=str(place.get("name") or ""),
            city_name=str(place.get("cityName") or city.get("name") or ""),
            country_name=str((country or {}).get("name") or place.get("countryName") or ""),
        )
        or str(place.get("name") or "")
    )
    if lang == DEFAULT_LANG:
        return title
    if title and title != str(place.get("name") or ""):
        return title
    return siri_manifest_title(lang=lang, country_slug=country_slug, city_slug=city_slug, place_slug=place_slug) or title


def place_display_name_cached_for_lang(place: Dict[str, Any], lang: str) -> str:
    lang = normalize_lang(lang)
    country_slug = str(place.get("countrySlug") or "").strip().lower()
    city_slug = str(place.get("citySlug") or "").strip().lower()
    place_slug = str(place.get("slug") or "").strip().lower()
    manual = manual_entity_name("place", place_slug, lang)
    if manual:
        return manual
    cached = (
        cached_localized_title(
            kind="place",
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
            source_title=str(place.get("name") or ""),
        )
        or str(place.get("name") or "")
    )
    if lang == DEFAULT_LANG:
        return cached
    if cached and cached != str(place.get("name") or ""):
        return cached
    return siri_manifest_title(lang=lang, country_slug=country_slug, city_slug=city_slug, place_slug=place_slug) or cached


def cached_entity_translation_exists(
    *,
    kind: str,
    lang: str,
    country_slug: str = "",
    city_slug: str = "",
    place_slug: str = "",
    source_title: str = "",
) -> bool:
    lang = normalize_lang(lang)
    if lang == DEFAULT_LANG:
        return True
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    place_slug = str(place_slug or "").strip().lower()
    if kind == "country" and manual_country_name(country_slug, lang):
        return True
    if kind == "city" and manual_entity_name("city", city_slug, lang):
        return True
    if kind == "place" and manual_entity_name("place", place_slug, lang):
        return True
    source_title = str(source_title or "").strip()
    if not source_title:
        return False
    return bool(
        cached_localized_title(
            kind=kind,
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
            source_title=source_title,
        )
    )


def country_translation_exists(country_slug: str, lang: str) -> bool:
    country_slug = str(country_slug or "").strip().lower()
    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        return False
    return cached_entity_translation_exists(
        kind="country",
        lang=lang,
        country_slug=country_slug,
        source_title=str(country.get("name") or ""),
    )


def city_translation_exists(country_slug: str, city_slug: str, lang: str) -> bool:
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
    if not city:
        for row in CITIES_BY_COUNTRYSLUG.get(country_slug, []):
            if str(row.get("citySlug") or "").strip().lower() == city_slug:
                city = row
                break
    if not city:
        return False
    return country_translation_exists(country_slug, lang) and cached_entity_translation_exists(
        kind="city",
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        source_title=str(city.get("wikiTitle") or city.get("name") or ""),
    )


def place_translation_exists(country_slug: str, city_slug: str, place_slug: str, lang: str) -> bool:
    country_slug = str(country_slug or "").strip().lower()
    city_slug = str(city_slug or "").strip().lower()
    place_slug = str(place_slug or "").strip().lower()
    place = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
    if not place:
        return False
    return city_translation_exists(country_slug, city_slug, lang) and cached_entity_translation_exists(
        kind="place",
        lang=lang,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
        source_title=str(place.get("name") or ""),
    )


def public_place_card_for_lang(
    place: Dict[str, Any],
    *,
    lang: str,
    country_slug: str,
    city_slug: str,
    country_name: str = "",
    city_name: str = "",
) -> Optional[Dict[str, Any]]:
    place_slug = str(place.get("slug") or place.get("placeSlug") or "").strip()
    if not place_slug:
        return None
    has_translation = place_translation_exists(country_slug, city_slug, place_slug, lang)
    url_lang = lang if has_translation else DEFAULT_LANG
    row = dict(place)
    row["slug"] = place_slug
    row["placeSlug"] = place_slug
    row["countrySlug"] = country_slug
    row["citySlug"] = city_slug
    row["countryName"] = country_name
    row["cityName"] = city_name
    row["category"] = row.get("category") or "Landmark"
    row["categoryLabel"] = localized_category_label(str(row.get("category") or "Landmark"), lang)
    row["displayName"] = place_display_name_cached_for_lang(row, lang)
    row["name"] = row["displayName"]
    row["hasTranslation"] = has_translation
    row["url"] = place_url(url_lang, country_slug, city_slug, place_slug)
    return row


def entity_page_is_published_for_lang(
    kind: str,
    lang: str,
    country_slug: str,
    city_slug: str = "",
    place_slug: str = "",
) -> bool:
    kind = str(kind or "").strip().lower()
    if kind == "country":
        return country_translation_exists(country_slug, lang)
    if kind == "city":
        return city_translation_exists(country_slug, city_slug, lang)
    if kind == "place":
        return place_translation_exists(country_slug, city_slug, place_slug, lang)
    return False


def published_langs_for_entity(
    kind: str,
    country_slug: str,
    city_slug: str = "",
    place_slug: str = "",
) -> List[str]:
    return [
        lang
        for lang in LANG_ORDER
        if entity_page_is_published_for_lang(kind, lang, country_slug, city_slug, place_slug)
    ]


def audio_build_job_key(
    country_slug: str,
    city_slug: str,
    lang: str,
    gender: str,
    place_slug: Optional[str] = None,
) -> str:
    target = f"{country_slug}/{city_slug}"
    if place_slug:
        target = f"{target}/{place_slug}"
    return f"{target}:{lang}:{gender}"


def update_audio_build_status(job_key: str, **patch: Any) -> Dict[str, Any]:
    with AUDIO_BUILD_LOCK:
        st = AUDIO_BUILD_STATUS.get(job_key) or {}
        st.update(patch)
        st["updatedAt"] = int(time.time())
        AUDIO_BUILD_STATUS[job_key] = st
        return dict(st)


def parse_audio_build_progress(line: str, fallback: float = 8.0) -> Tuple[float, str]:
    raw = str(line or "").strip()
    if not raw:
        return fallback, ""

    low = raw.lower()
    progress = max(0.0, min(99.0, float(fallback)))
    label = raw

    edge_match = re.search(r"\[edge\]\s+(\d+)\s*/\s*(\d+)\s+audio files generated", low)
    if edge_match:
        done = int(edge_match.group(1) or 0)
        total = max(1, int(edge_match.group(2) or 1))
        progress = 55.0 + (min(done, total) / total) * 42.0
        label = f"Audio files {done}/{total}"
        return min(progress, 97.0), label

    if "source mode:" in low:
        return 10.0, "Preparing source"
    if "rewrite mode:" in low:
        return 14.0, "Preparing text"
    if "tts backend:" in low or "edge profile:" in low:
        return 22.0, "Preparing voice"
    if "rewritten" in low and "sections" in low:
        match = re.search(r"rewritten\s+(\d+)\s+sections", low)
        cnt = int(match.group(1) or 0) if match else 0
        return 48.0, f"Sections ready ({cnt})" if cnt else "Sections ready"
    if "audio + manifests ready" in low:
        return 100.0, "Audio ready"
    if "[fallback linked-local]" in low:
        return 18.0, "Retrying local language voice"

    return progress, label


def run_audio_build_subprocess(job_key: str, cmd: List[str], *, progress_floor: float = 8.0) -> Tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("AUDIO_STORAGE_PATH", str(AUDIO_STORAGE_PATH))
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )
    lines: List[str] = []
    current_progress = progress_floor

    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                text = str(line or "").rstrip()
                lines.append(text)
                progress, label = parse_audio_build_progress(text, fallback=current_progress)
                current_progress = max(current_progress, progress)
                update_audio_build_status(
                    job_key,
                    status="running",
                    progress=round(min(current_progress, 99.0), 1),
                    label=label or text or "Generating audio",
                    lastLine=text,
                )
    finally:
        returncode = proc.wait()

    return returncode, "\n".join(lines).strip()


def _run_audio_build_job(
    job_key: str,
    country_slug: str,
    city_slug: str,
    lang: str,
    gender: str,
    place_slug: Optional[str] = None,
) -> None:
    manifest = audio_manifest_path(
        version=AUDIO_BUILD_AUDIO_VERSION,
        lang=lang,
        gender=gender,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )

    with AUDIO_BUILD_LOCK:
        st = AUDIO_BUILD_STATUS.get(job_key) or {}
        st.update(
            {
                "status": "running",
                "progress": 4.0,
                "label": "Queued",
                "updatedAt": int(time.time()),
                "country": country_slug,
                "city": city_slug,
                "place": place_slug or "",
                "lang": lang,
                "gender": gender,
                "kind": "country" if city_slug == "__country__" else ("place" if place_slug else "city"),
                "version": AUDIO_BUILD_AUDIO_VERSION,
            }
        )
        AUDIO_BUILD_STATUS[job_key] = st

    primary_cmd = [
        sys.executable,
        "-u",
        str(ROOT / "generate_audio_guides.py"),
        "--country-slug",
        country_slug,
        "--city-slug",
        city_slug,
        "--target-kind",
        "country" if city_slug == "__country__" else ("place" if place_slug else "city"),
        "--audio-version",
        AUDIO_BUILD_AUDIO_VERSION,
        "--langs",
        lang,
        "--genders",
        gender,
        "--tts-backend",
        "edge",
        "--edge-profile",
        "siri",
        f"--edge-rate={AUDIO_BUILD_EDGE_RATE}",
        f"--edge-pitch={AUDIO_BUILD_EDGE_PITCH}",
        f"--edge-volume={AUDIO_BUILD_EDGE_VOLUME}",
        f"--edge-concurrency={AUDIO_BUILD_EDGE_CONCURRENCY}",
        "--source-mode",
        AUDIO_BUILD_SOURCE_MODE,
        "--chunk-chars",
        str(AUDIO_BUILD_CHUNK_CHARS),
        "--force",
        "--sleep",
        "0",
    ]
    if place_slug:
        primary_cmd.extend(["--place-slug", place_slug])

    fallback_cmd = [
        sys.executable,
        "-u",
        str(ROOT / "generate_audio_guides.py"),
        "--country-slug",
        country_slug,
        "--city-slug",
        city_slug,
        "--target-kind",
        "country" if city_slug == "__country__" else ("place" if place_slug else "city"),
        "--audio-version",
        AUDIO_BUILD_AUDIO_VERSION,
        "--langs",
        lang,
        "--genders",
        gender,
        "--tts-backend",
        "edge",
        "--edge-profile",
        "siri",
        f"--edge-rate={AUDIO_BUILD_EDGE_RATE}",
        f"--edge-pitch={AUDIO_BUILD_EDGE_PITCH}",
        f"--edge-volume={AUDIO_BUILD_EDGE_VOLUME}",
        f"--edge-concurrency={AUDIO_BUILD_EDGE_CONCURRENCY}",
        "--source-mode",
        "linked-local",
        "--chunk-chars",
        str(AUDIO_BUILD_CHUNK_CHARS),
        "--no-rewrite",
        "--force",
        "--sleep",
        "0",
    ]
    if place_slug:
        fallback_cmd.extend(["--place-slug", place_slug])

    with AUDIO_BUILD_SEMAPHORE:
        try:
            combined_output = ""
            ok = False

            if AUDIO_BUILD_USE_REWRITE:
                run_code, combined_output = run_audio_build_subprocess(job_key, primary_cmd, progress_floor=8.0)
                ok = run_code == 0 and is_siri_audio_manifest(manifest)

            if not ok:
                update_audio_build_status(job_key, progress=18.0, label="Loading audio")
                fallback_code, fb_out = run_audio_build_subprocess(job_key, fallback_cmd, progress_floor=18.0)
                ok = fallback_code == 0 and is_siri_audio_manifest(manifest)
                combined_output = "\n\n".join([x for x in [combined_output, "[fallback linked-local]", fb_out] if x]).strip()
            with AUDIO_BUILD_LOCK:
                st = AUDIO_BUILD_STATUS.get(job_key) or {}
                st["status"] = "done" if ok else "failed"
                st["ready"] = bool(ok)
                st["progress"] = 100.0 if ok else max(float(st.get("progress") or 0.0), 18.0)
                st["label"] = "Audio ready" if ok else (st.get("label") or "Audio failed")
                st["updatedAt"] = int(time.time())
                if not ok:
                    st["error"] = combined_output[-1200:]
                AUDIO_BUILD_STATUS[job_key] = st
        except Exception as e:
            with AUDIO_BUILD_LOCK:
                st = AUDIO_BUILD_STATUS.get(job_key) or {}
                st["status"] = "failed"
                st["updatedAt"] = int(time.time())
                st["error"] = str(e)
                AUDIO_BUILD_STATUS[job_key] = st


def enqueue_audio_build(
    country_slug: str,
    city_slug: str,
    lang: str,
    gender: str,
    place_slug: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = audio_manifest_path(
        version=AUDIO_BUILD_AUDIO_VERSION,
        lang=lang,
        gender=gender,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug,
    )
    if is_siri_audio_manifest(manifest):
        return {"status": "ready", "ready": True, "progress": 100.0, "label": "Audio ready", "version": AUDIO_BUILD_AUDIO_VERSION}

    job_key = audio_build_job_key(country_slug, city_slug, lang, gender, place_slug=place_slug)
    with AUDIO_BUILD_LOCK:
        st = AUDIO_BUILD_STATUS.get(job_key)
        if st and st.get("status") in {"queued", "running"}:
            out = dict(st)
            out["ready"] = False
            return out

        AUDIO_BUILD_STATUS[job_key] = {
            "status": "queued",
            "createdAt": int(time.time()),
            "updatedAt": int(time.time()),
            "country": country_slug,
            "city": city_slug,
            "place": place_slug or "",
            "lang": lang,
            "gender": gender,
            "kind": "country" if city_slug == "__country__" else ("place" if place_slug else "city"),
            "version": AUDIO_BUILD_AUDIO_VERSION,
            "progress": 2.0,
            "label": "Queued",
        }

    thr = threading.Thread(
        target=_run_audio_build_job,
        args=(job_key, country_slug, city_slug, lang, gender, place_slug),
        daemon=True,
    )
    thr.start()
    return {"status": "queued", "ready": False, "progress": 2.0, "label": "Queued", "version": AUDIO_BUILD_AUDIO_VERSION}


def enqueue_city_audio_build(country_slug: str, city_slug: str, lang: str, gender: str) -> Dict[str, Any]:
    return enqueue_audio_build(country_slug, city_slug, lang, gender, place_slug=None)


def europe_countries() -> List[Dict[str, Any]]:
    arr = [c for c in COUNTRIES if (c.get("continent") or "").strip().lower() == "europe"]
    arr.sort(key=lambda x: x.get("name", ""))
    return arr


# -------- static alias for /img/... --------
@app.get("/img/<path:filename>")
def img_static(filename: str):
    img_dir = ROOT / "static" / "img"
    return send_from_directory(img_dir, filename)


def svg_text_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def generated_media_svg_markup(title: str, subtitle: str, label: str = "Audio Guide") -> str:
    safe_title = svg_text_escape(title)
    safe_subtitle = svg_text_escape(subtitle)
    safe_label = svg_text_escape(label)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0a1333"/>
      <stop offset=".52" stop-color="#111935"/>
      <stop offset="1" stop-color="#1d2b62"/>
    </linearGradient>
    <radialGradient id="glow" cx=".25" cy=".18" r=".85">
      <stop offset="0" stop-color="#29d6ff" stop-opacity=".38"/>
      <stop offset=".42" stop-color="#8d5bff" stop-opacity=".18"/>
      <stop offset="1" stop-color="#8d5bff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="800" fill="url(#bg)"/>
  <rect width="1200" height="800" fill="url(#glow)"/>
  <path d="M120 560 C 290 420, 430 650, 610 500 S 920 330, 1080 210" fill="none" stroke="#29d6ff" stroke-opacity=".28" stroke-width="10" stroke-linecap="round"/>
  <circle cx="260" cy="470" r="18" fill="#29d6ff"/>
  <circle cx="610" cy="500" r="18" fill="#8d5bff"/>
  <circle cx="930" cy="300" r="18" fill="#29d6ff"/>
  <rect x="86" y="86" width="1028" height="628" rx="46" fill="#ffffff" fill-opacity=".06" stroke="#ffffff" stroke-opacity=".22"/>
  <text x="120" y="180" fill="#9ca7c7" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="800">{safe_label}</text>
  <text x="120" y="330" fill="#ebf1ff" font-family="Inter, Arial, sans-serif" font-size="82" font-weight="900">{safe_title}</text>
  <text x="120" y="405" fill="#cbd6f2" font-family="Inter, Arial, sans-serif" font-size="38" font-weight="700">{safe_subtitle}</text>
  <text x="120" y="650" fill="#ebf1ff" font-family="Inter, Arial, sans-serif" font-size="30" font-weight="800">Listen free with map and audio stories</text>
</svg>"""


def generated_media_svg_response(title: str, subtitle: str, label: str = "Audio Guide") -> Response:
    svg = generated_media_svg_markup(title, subtitle, label)
    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    resp.headers["X-SonicCity-Generated-Image"] = "1"
    return resp


def generated_media_svg_file_response(cache_dir: Path, slug: str, title: str, subtitle: str, label: str = "Audio Guide") -> Response:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / f"{slug}.svg"
        if not dest.exists() or dest.stat().st_size == 0:
            dest.write_text(generated_media_svg_markup(title, subtitle, label), encoding="utf-8")
        resp = make_response(send_file(dest, mimetype="image/svg+xml"))
        resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
        resp.headers["X-SonicCity-Generated-Image"] = "1"
        return resp
    except Exception:
        return generated_media_svg_response(title, subtitle, label)


@app.get("/media/place/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>/<city_slug>/<place_slug>")
def media_place_image(lang: str, country_slug: str, city_slug: str, place_slug: str):
    """
    Cached Wikipedia thumbnail proxy for a place.

    - Returns a local cached file when available.
    - If not cached, fetches a thumbnail from Wikipedia and stores it under ./cache/place_images/...
    - If Wikipedia has no image, returns an SVG placeholder and writes a .missing marker to avoid refetching.
    """
    lang = normalize_lang(lang)

    place = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
    if not place:
        abort(404)

    force = str(request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}

    # Visual media must be language-stable. Translated Wikipedia pages can point
    # to different thumbnails, so city/place photos use one canonical cache.
    wiki_lang = CANONICAL_IMAGE_LANG
    cache_dir_req = PLACE_IMAGE_CACHE_DIR / CANONICAL_IMAGE_LANG / country_slug / city_slug
    cache_dir_en = cache_dir_req
    cache_dir_req.mkdir(parents=True, exist_ok=True)

    candidate_dirs = [cache_dir_req]

    title = str(place.get("name") or "").strip()
    city_name = str(place.get("cityName") or "").strip()
    country_name = str(place.get("countryName") or "").strip()
    generated_title = title or place_slug.replace("-", " ").title()
    generated_subtitle = f"{city_name}, {country_name}".strip(", ")
    direct_image_url = str(place.get("imageUrl") or place.get("image") or "").strip()
    has_direct_image = direct_image_url.startswith(("http://", "https://"))

    # Serve from the canonical cache first.
    for cache_dir in candidate_dirs:
        cached_exts = (".jpg", ".png", ".webp", ".gif") if has_direct_image else (".jpg", ".png", ".webp", ".gif", ".svg")
        for ext in cached_exts:
            fp = cache_dir / f"{place_slug}{ext}"
            if fp.exists() and fp.stat().st_size > 0:
                if ext != ".svg":
                    try:
                        if not image_ext_from_bytes(fp.read_bytes()[:32]):
                            fp.unlink(missing_ok=True)
                            continue
                    except OSError:
                        continue
                resp = make_response(send_file(fp))
                resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
                return resp

    if has_direct_image:
        for cache_dir in candidate_dirs:
            for ext in (".missing", ".svg"):
                stale = cache_dir / f"{place_slug}{ext}"
                try:
                    if stale.exists():
                        stale.unlink()
                except OSError:
                    pass

    # If we've previously concluded "no image", skip refetching (unless forced).
    if not force and PLACE_IMAGE_PLACEHOLDER_PATH.exists() and not has_direct_image:
        if (cache_dir_req / f"{place_slug}.missing").exists():
            return generated_media_svg_file_response(cache_dir_req, place_slug, generated_title, generated_subtitle, "Place Audio Guide")

    title_candidates: List[str] = [title]
    if city_name:
        title_candidates.append(f"{title}, {city_name}")
        title_candidates.append(f"{title} ({city_name})")

    search_candidates: List[str] = []
    if city_name:
        search_candidates.append(f"{title} {city_name}")
    if country_name:
        search_candidates.append(f"{title} {country_name}")

    def add_title(x: str) -> None:
        s = str(x or "").strip()
        if s and s not in title_candidates:
            title_candidates.append(s)

    def add_search(x: str) -> None:
        s = str(x or "").strip()
        if s and s not in search_candidates:
            search_candidates.append(s)

    # Heuristics: remove generic travel suffixes that are unlikely to be Wikipedia titles.
    cleaned = re.sub(
        r"\b(day\s*trip|nearby|sites|cruise|riverwalk|boat\s*tour|walking\s*tour|tour)\b",
        "",
        title,
        flags=re.I,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-–—")
    if cleaned and cleaned.lower() != title.lower():
        add_title(cleaned)
        if city_name:
            add_title(f"{cleaned}, {city_name}")
            add_title(f"{cleaned} ({city_name})")
            add_search(f"{cleaned} {city_name}")
        if country_name:
            add_search(f"{cleaned} {country_name}")

        # Declension-ish fallback: drop trailing 'a' from long words (e.g., Bastejkalna → Bastejkaln).
        words = cleaned.split()
        for i, w in enumerate(words):
            if len(w) >= 7 and w.endswith("a"):
                w2 = w[:-1]
                v = " ".join(words[:i] + [w2] + words[i + 1 :]).strip()
                if v and v.lower() != cleaned.lower():
                    add_title(v)
                    if city_name:
                        add_search(f"{v} {city_name}")
                    if country_name:
                        add_search(f"{v} {country_name}")

    thumb_url = None
    if has_direct_image:
        thumb_url = direct_image_url
    for cand in title_candidates:
        if thumb_url:
            break
        thumb_url = wiki_thumbnail_url(wiki_lang, cand)
        if thumb_url:
            break
    if not thumb_url:
        for q in search_candidates:
            thumb_url = commons_thumbnail_url_search(q, size_px=1200)
            if thumb_url:
                break
            thumb_url = wiki_thumbnail_url_search(wiki_lang, q)
            if thumb_url:
                break

    used_cache_dir = cache_dir_req

    # Last resort: fall back to the city's hero image (better than a placeholder).
    if not thumb_url:
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
        city_title = str((city or {}).get("wikiTitle") or (city or {}).get("name") or city_name).strip()
        if city_title:
            thumb_url = wiki_thumbnail_url(wiki_lang, city_title, size_px=1200)
            used_cache_dir = cache_dir_req
            if not thumb_url:
                thumb_url = wiki_thumbnail_url_search(wiki_lang, f"{city_title} {country_name}".strip(), size_px=1200)

    if not thumb_url:
        try:
            (cache_dir_req / f"{place_slug}.missing").touch(exist_ok=True)
        except Exception:
            pass
        return generated_media_svg_file_response(cache_dir_req, place_slug, generated_title, generated_subtitle, "Place Audio Guide")

    data = http_get_bytes(thumb_url, timeout_s=20)
    detected_ext = image_ext_from_bytes(data or b"")
    if not data or not detected_ext:
        try:
            (cache_dir_req / f"{place_slug}.missing").touch(exist_ok=True)
        except Exception:
            pass
        return generated_media_svg_file_response(cache_dir_req, place_slug, generated_title, generated_subtitle, "Place Audio Guide")

    ext = detected_ext or image_ext_from_url(thumb_url)
    used_cache_dir.mkdir(parents=True, exist_ok=True)
    dest = used_cache_dir / f"{place_slug}{ext}"

    tmp = used_cache_dir / f"{place_slug}.tmp"
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return generated_media_svg_file_response(cache_dir_req, place_slug, generated_title, generated_subtitle, "Place Audio Guide")

    resp = make_response(send_file(dest))
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    # Remove missing markers if we successfully fetched an image.
    try:
        for d in {cache_dir_req, cache_dir_en}:
            p = d / f"{place_slug}.missing"
            if p.exists():
                p.unlink()
    except Exception:
        pass
    return resp


@app.get("/media/city/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>/<city_slug>")
def media_city_image(lang: str, country_slug: str, city_slug: str):
    lang = normalize_lang(lang)

    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        abort(404)
    if not country_translation_exists(country_slug, lang):
        abort(404)
    country_view = dict(country)
    country_view["displayName"] = country_display_name_cached_for_lang(country_view, lang)
    country_view["name"] = country_view["displayName"]

    city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
    if not city:
        for c in CITIES_BY_COUNTRYSLUG.get(country_slug, []):
            if str(c.get("citySlug") or "") == city_slug:
                city = c
                break
    if not city:
        abort(404)

    force = str(request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}
    # City hero/card images must not change when the UI language changes.
    wiki_lang = CANONICAL_IMAGE_LANG
    cache_dir_req = CITY_IMAGE_CACHE_DIR / CANONICAL_IMAGE_LANG / country_slug
    cache_dir_en = cache_dir_req
    cache_dir_req.mkdir(parents=True, exist_ok=True)

    candidate_dirs = [cache_dir_req]

    if not force:
        for d in candidate_dirs:
            for ext in (".jpg", ".png", ".webp", ".gif", ".svg"):
                fp = d / f"{city_slug}{ext}"
                if fp.exists() and fp.stat().st_size > 0:
                    resp = make_response(send_file(fp))
                    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
                    return resp

    title = str(city.get("wikiTitle") or city.get("name") or "").strip()
    country_name = str(country.get("name") or country_view.get("displayName") or country_view.get("name") or "").strip()
    thumb_url = wiki_thumbnail_url(wiki_lang, title, size_px=1200)
    if not thumb_url:
        thumb_url = wiki_thumbnail_url_search(wiki_lang, f"{title} {country_name}".strip(), size_px=1200)
    used_dir = cache_dir_req

    if not thumb_url:
        return generated_media_svg_file_response(cache_dir_req, city_slug, title or city_slug.replace("-", " ").title(), country_name, "City Audio Guide")

    used_dir.mkdir(parents=True, exist_ok=True)
    ext = image_ext_from_url(thumb_url)
    dest = used_dir / f"{city_slug}{ext}"

    data = http_get_bytes(thumb_url, timeout_s=20)
    if not data:
        return generated_media_svg_file_response(cache_dir_req, city_slug, title or city_slug.replace("-", " ").title(), country_name, "City Audio Guide")

    tmp = used_dir / f"{city_slug}.tmp"
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return generated_media_svg_response(title or city_slug.replace("-", " ").title(), country_name, "City Audio Guide")

    resp = make_response(send_file(dest))
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return resp


@app.get("/media/country/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>")
def media_country_image(lang: str, country_slug: str):
    lang = normalize_lang(lang)

    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        abort(404)

    wiki_lang = SUPPORTED_LANGS[lang]["wiki"]
    cache_dir_req = COUNTRY_IMAGE_CACHE_DIR / wiki_lang
    cache_dir_en = COUNTRY_IMAGE_CACHE_DIR / "en"
    cache_dir_req.mkdir(parents=True, exist_ok=True)

    candidate_dirs = [cache_dir_req]
    if wiki_lang != "en":
        candidate_dirs.append(cache_dir_en)

    for d in candidate_dirs:
        for ext in (".jpg", ".png", ".webp", ".gif"):
            fp = d / f"{country_slug}{ext}"
            if fp.exists() and fp.stat().st_size > 0:
                resp = make_response(send_file(fp))
                resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
                return resp

    title = str(country.get("name") or "").strip()
    thumb_url = wiki_thumbnail_url(wiki_lang, title, size_px=1200)
    used_dir = cache_dir_req
    if not thumb_url and wiki_lang != "en":
        thumb_url = wiki_thumbnail_url("en", title, size_px=1200)
        if thumb_url:
            used_dir = cache_dir_en

    if not thumb_url:
        if PLACE_IMAGE_PLACEHOLDER_PATH.exists():
            return send_file(PLACE_IMAGE_PLACEHOLDER_PATH, mimetype="image/svg+xml", max_age=60 * 60 * 24 * 30)
        abort(404)

    used_dir.mkdir(parents=True, exist_ok=True)
    ext = image_ext_from_url(thumb_url)
    dest = used_dir / f"{country_slug}{ext}"

    data = http_get_bytes(thumb_url, timeout_s=20)
    if not data:
        if PLACE_IMAGE_PLACEHOLDER_PATH.exists():
            return send_file(PLACE_IMAGE_PLACEHOLDER_PATH, mimetype="image/svg+xml", max_age=60 * 60 * 24 * 30)
        abort(404)

    tmp = used_dir / f"{country_slug}.tmp"
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        if PLACE_IMAGE_PLACEHOLDER_PATH.exists():
            return send_file(PLACE_IMAGE_PLACEHOLDER_PATH, mimetype="image/svg+xml", max_age=60 * 60 * 24 * 30)
        abort(404)

    resp = make_response(send_file(dest))
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return resp


# -------- main --------
@app.get("/")
def index():
    lang = "en"
    detected_lang = detect_preferred_lang()
    if should_auto_redirect_from_root(detected_lang):
        resp = make_response(redirect(landing_url(detected_lang), code=302))
        resp.set_cookie("lang", detected_lang, max_age=60 * 60 * 24 * 365)
        return resp

    featured_places = localized_featured_places(landing_featured_places(24), lang)
    auto_faq = auto_faq_for_page(
        "home",
        lang=lang,
    )
    auto_faq_schema = faq_schema_for_items(auto_faq.get("items", []))
    featured_schema_items = [
        {
            "name": place_display_name_cached_for_lang(place, lang),
            "url": place_url(
                lang,
                str(place.get("countrySlug") or ""),
                str(place.get("citySlug") or ""),
                str(place.get("slug") or place.get("placeSlug") or ""),
            ),
        }
        for place in featured_places[:12]
        if place.get("countrySlug") and place.get("citySlug") and (place.get("slug") or place.get("placeSlug"))
    ]
    trn = t(lang)
    seo_title = trn.get("home_meta_title") or f"Free GPS Audio Guide for Cities and Landmarks | {BRAND_NAME}"
    seo_desc = trn.get("home_meta_desc") or "Listen free with a GPS Audio Guide for cities, landmarks and road trips. Open the map, find nearby places and keep audio stories playing while you travel."
    seo_image = landing_primary_image(lang, featured_places)
    admin_content = admin_content_for_public("home", lang)
    comments_context = public_comments_context("landing_page", "home", "SonicCity", landing_url(lang), lang, admin_content)
    resp = make_response(
        render_template(
            "landing.html",
            lang=lang,
            featured_places=featured_places,
            popular_cities=landing_popular_city_cards(lang),
            iconic_places=landing_iconic_place_cards(lang),
            seo_title=seo_title,
            seo_desc=seo_desc,
            seo_keywords="audio guide, city audio guide, travel audio, GPS city guide, map audio tour, self guided tour",
            seo_image=seo_image,
            seo_type="website",
            seo_schema=schema_graph(
                page_type="WebPage",
                lang=lang,
                page_url=landing_url(lang),
                title=seo_title,
                description=seo_desc,
                image_url=seo_image,
                faq_schema=auto_faq_schema,
                item_lists=[
                    schema_item_list_node(trn.get("home_featured_schema") or "Featured SonicCity audio guides", landing_url(lang), "featured-guides", featured_schema_items)
                ],
            ),
            admin_content=admin_content,
            comments_context=comments_context,
            auto_faq=auto_faq,
            auto_faq_schema=auto_faq_schema,
            schema_in_graph=True,
            detected_lang=detected_lang,
            T=t(lang),
            body_class="PageLanding",
            use_leaflet=True,
        )
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


@app.get("/<re('en|fr|es|it|ua|uk|de'):lang>")
def landing_lang(lang: str):
    lang = normalize_lang(lang)
    if lang == "en":
        return redirect("/", code=301)
    featured_places = localized_featured_places(landing_featured_places(24), lang)
    auto_faq = auto_faq_for_page(
        "home",
        lang=lang,
    )
    auto_faq_schema = faq_schema_for_items(auto_faq.get("items", []))
    featured_schema_items = [
        {
            "name": place_display_name_cached_for_lang(place, lang),
            "url": place_url(
                lang,
                str(place.get("countrySlug") or ""),
                str(place.get("citySlug") or ""),
                str(place.get("slug") or place.get("placeSlug") or ""),
            ),
        }
        for place in featured_places[:12]
        if place.get("countrySlug") and place.get("citySlug") and (place.get("slug") or place.get("placeSlug"))
    ]
    trn = t(lang)
    seo_title = trn.get("home_meta_title") or f"Free GPS Audio Guide for Cities and Landmarks | {BRAND_NAME}"
    seo_desc = trn.get("home_meta_desc") or "Listen free with a GPS Audio Guide for cities, landmarks and road trips. Open the map, find nearby places and keep audio stories playing while you travel."
    seo_image = landing_primary_image(lang, featured_places)
    admin_content = admin_content_for_public("home", lang)
    comments_context = public_comments_context("landing_page", "home", "SonicCity", landing_url(lang), lang, admin_content)
    resp = make_response(
        render_template(
            "landing.html",
            lang=lang,
            featured_places=featured_places,
            popular_cities=landing_popular_city_cards(lang),
            iconic_places=landing_iconic_place_cards(lang),
            seo_title=seo_title,
            seo_desc=seo_desc,
            seo_keywords="audio guide, city audio guide, travel audio, GPS city guide, map audio tour, self guided tour",
            seo_image=seo_image,
            seo_type="website",
            seo_schema=schema_graph(
                page_type="WebPage",
                lang=lang,
                page_url=landing_url(lang),
                title=seo_title,
                description=seo_desc,
                image_url=seo_image,
                faq_schema=auto_faq_schema,
                item_lists=[
                    schema_item_list_node(trn.get("home_featured_schema") or "Featured SonicCity audio guides", landing_url(lang), "featured-guides", featured_schema_items)
                ],
            ),
            admin_content=admin_content,
            comments_context=comments_context,
            auto_faq=auto_faq,
            auto_faq_schema=auto_faq_schema,
            schema_in_graph=True,
            detected_lang="",
            T=t(lang),
            body_class="PageLanding",
            use_leaflet=True,
        )
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


@app.post("/api/subscribe")
def api_subscribe():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    name = clean_plain_text(payload.get("name") or "", 120)
    email = clean_plain_text(payload.get("email") or "", 180).lower()
    source_page = clean_plain_text(payload.get("sourcePage") or request.referrer or request.path, 500)
    if not is_valid_email(email):
        return jsonify({"ok": False, "error": "Please enter a valid email."}), 400
    row = save_subscription_message(name=name, email=email, source_page=source_page)
    body = "\n".join(
        [
            "New SonicCity subscription",
            "",
            f"Submission ID: {row.get('id') or '-'}",
            f"Name: {row.get('name') or '-'}",
            f"Email: {row.get('email')}",
            f"Source page: {row.get('source') or '-'}",
            f"Language: {row.get('language') or '-'}",
            f"Time: {row.get('subscribedAt') or utc_now_iso()}",
            f"IP: {row.get('ip') or '-'}",
            f"User-Agent: {row.get('userAgent') or '-'}",
        ]
    )
    sent, delivery_status = send_site_notification_result("New SonicCity subscription", body, reply_to=email)
    row = update_subscription_notification_status(row.get("id") or "", sent=sent, status=delivery_status) or row
    if not sent:
        return jsonify({
            "ok": False,
            "saved": True,
            "sent": False,
            "error": "Subscription saved, but email delivery is not configured.",
            "deliveryStatus": delivery_status,
        }), 503
    return jsonify({"ok": True, "saved": True, "sent": bool(sent), "deliveryStatus": delivery_status})


@app.post("/api/auth/register")
def api_auth_register():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    email = clean_plain_text(payload.get("email") or "", 180).lower()
    if auth_rate_limited("register", email, limit=5, window_seconds=60 * 10):
        return jsonify({"ok": False, "error": "Please wait before creating another account."}), 429
    password = str(payload.get("password") or "")
    repeat = str(payload.get("repeatPassword") or payload.get("password2") or "")
    if repeat and repeat != password:
        return jsonify({"ok": False, "error": "Passwords do not match."}), 400
    user, error = create_site_user(
        email,
        password,
        country=payload.get("country") or "",
        name=payload.get("name") or "",
    )
    if not user:
        return jsonify({"ok": False, "error": error or "Could not create account."}), 400
    send_verification_email(user, force=True)
    session["user_email"] = user.get("email")
    session["user_id"] = user.get("id")
    session["user_login_at"] = int(time.time())
    return jsonify({
        "ok": True,
        "requiresVerification": True,
        "message": "Check your email to confirm your account.",
        "user": {
            "email": user.get("email"),
            "registrationCountry": user.get("registrationCountry") or "",
            "emailVerified": site_user_is_verified(user),
            "status": user.get("status") or "pending_verification",
        },
    })


@app.post("/api/auth/login")
def api_auth_login():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    email = clean_plain_text(payload.get("email") or "", 180).lower()
    if auth_rate_limited("login", email, limit=10, window_seconds=60 * 10):
        return jsonify({"ok": False, "error": "Too many login attempts. Please wait and try again."}), 429
    user, error = login_site_user(email, payload.get("password") or "")
    if not user:
        return jsonify({"ok": False, "error": error or "Wrong email or password."}), 400
    return jsonify({
        "ok": True,
        "requiresVerification": not site_user_is_verified(user),
        "message": "Please confirm your email address to use your account." if not site_user_is_verified(user) else "",
        "user": {
            "email": user.get("email"),
            "registrationCountry": user.get("registrationCountry") or "",
            "emailVerified": site_user_is_verified(user),
            "status": user.get("status") or "active",
        },
    })


@app.post("/api/auth/logout")
def api_auth_logout():
    session.pop("user_email", None)
    session.pop("user_id", None)
    session.pop("user_login_at", None)
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def api_auth_me():
    return jsonify({"ok": True, "user": public_site_user(current_site_user())})


@app.post("/api/auth/resend-verification")
def api_auth_resend_verification():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    user = current_site_user() or site_user_by_email(payload.get("email") or "")
    if not user:
        return jsonify({"ok": False, "error": "Enter the email you used to register."}), 404
    if site_user_is_verified(user):
        return jsonify({"ok": True, "message": "Email is already confirmed."})
    ok, message = send_verification_email(user)
    if not ok:
        return jsonify({"ok": False, "error": message}), 429
    return jsonify({"ok": True, "message": message})


@app.post("/api/auth/request-password-reset")
def api_auth_request_password_reset():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    email = clean_plain_text(payload.get("email") or "", 180).lower()
    if auth_rate_limited("password_reset", email, limit=5, window_seconds=60 * 60):
        return jsonify({"ok": False, "error": "Please wait before requesting another reset email."}), 429
    user = site_user_by_email(email)
    if user:
        send_password_reset_email(user)
    return jsonify({"ok": True, "message": "If this email exists, we sent password reset instructions."})


@app.get("/auth/verify-email")
def auth_verify_email():
    token = str(request.args.get("token") or "")
    item, status = consume_single_use_token("emailVerificationTokens", token)
    title = "Invalid verification link."
    body = "Request a new verification email from the login form."
    if status == "expired":
        title = "Verification link expired."
        body = "Please request a new verification email."
    elif status == "used":
        title = "Email already confirmed."
        body = "You can log in with your email and password."
    elif status == "ok" and item:
        user = None
        for row in cms_collection_rows("siteUsers"):
            if str(row.get("id") or "") == str(item.get("userId") or ""):
                user = row
                break
        if user:
            update_site_user(str(user.get("id") or ""), {"emailVerified": True, "status": "active", "emailVerifiedAt": utc_now_iso()})
            title = "Email confirmed."
            body = "You can now log in and save your listening progress."
    return render_template(
        "auth_message.html",
        title=title,
        body=body,
        action_label="Log In",
        action_url=landing_url(current_lang()),
        seo_title=f"{title} | {BRAND_NAME}",
        seo_desc=body,
        body_class="PageAuthMessage",
        T=t(current_lang()),
    )


@app.get("/auth/reset-password")
def auth_reset_password_form():
    token = clean_plain_text(request.args.get("token") or "", 240)
    return render_template(
        "reset_password.html",
        token=token,
        error="",
        status="",
        seo_title=f"Reset password | {BRAND_NAME}",
        seo_desc=f"Reset your {BRAND_NAME} account password.",
        body_class="PageAuthMessage",
        T=t(current_lang()),
    )


@app.post("/auth/reset-password")
def auth_reset_password_submit():
    token = clean_plain_text(request.form.get("token") or "", 240)
    password = str(request.form.get("password") or "")
    repeat = str(request.form.get("repeatPassword") or "")
    error = ""
    status_msg = ""
    if len(password) < 8:
        error = "Password must be at least 8 characters."
    elif repeat and repeat != password:
        error = "Passwords do not match."
    else:
        item, token_status = consume_single_use_token("passwordResetTokens", token)
        if token_status == "expired":
            error = "Reset link expired."
        elif token_status != "ok" or not item:
            error = "Invalid reset link."
        else:
            user_id = str(item.get("userId") or "")
            update_site_user(user_id, {"passwordHash": generate_password_hash(password), "passwordChangedAt": utc_now_iso()})
            status_msg = "Password updated. You can now log in."
    return render_template(
        "reset_password.html",
        token="" if status_msg else token,
        error=error,
        status=status_msg,
        seo_title=f"Reset password | {BRAND_NAME}",
        seo_desc=f"Reset your {BRAND_NAME} account password.",
        body_class="PageAuthMessage",
        T=t(current_lang()),
    )


def listening_history_for_user(user_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    rows = [row for row in cms_collection_rows("listeningHistory") if str(row.get("userId") or "") == str(user_id)]
    rows.sort(key=lambda row: row.get("lastListenedAt") or row.get("updatedAt") or row.get("createdAt") or "", reverse=True)
    return rows[:limit]


def favorites_for_user(user_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    rows = [row for row in cms_collection_rows("favorites") if str(row.get("userId") or "") == str(user_id)]
    rows.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
    return rows[:limit]


def normalize_saved_guide_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urllib.parse.urlparse(text)
        text = urllib.parse.urlunparse(("", "", parsed.path or "/", "", parsed.query, parsed.fragment))
    return text.rstrip("/")


def current_user_has_favorite(entity_type: str = "", entity_id: str = "", page_url: str = "") -> bool:
    user = current_site_user()
    if not user:
        return False
    target_type = str(entity_type or "").strip()
    target_id = str(entity_id or "").strip()
    target_url = normalize_saved_guide_url(page_url)
    for item in cms_collection_rows("favorites"):
        if str(item.get("userId") or "") != str(user.get("id") or ""):
            continue
        same_entity = (
            target_type
            and target_id
            and str(item.get("entityType") or "") == target_type
            and str(item.get("entityId") or "") == target_id
        )
        same_url = target_url and normalize_saved_guide_url(item.get("pageUrl")) == target_url
        if same_entity or same_url:
            return True
    return False


def account_required_user():
    user = current_site_user()
    if not user:
        return None
    return user


@app.route("/account", methods=["GET", "POST"])
@app.route("/account/profile", methods=["GET", "POST"])
@app.get("/account/listening")
@app.get("/account/saved")
@app.post("/account/listening/clear")
@app.post("/account/saved/clear")
@app.post("/account/delete")
def account_page():
    user = account_required_user()
    if not user:
        return redirect(f"{landing_url(current_lang())}?login=1")
    active_tab = "overview"
    if request.path.endswith("/profile"):
        active_tab = "profile"
    elif request.path.endswith("/listening"):
        active_tab = "listening"
    elif request.path.endswith("/saved"):
        active_tab = "saved"

    msg = ""
    if request.method == "POST" and request.path.endswith("/profile"):
        update_site_user(str(user.get("id") or ""), {
            "name": clean_plain_text(request.form.get("name") or "", 120),
            "country": clean_plain_text(request.form.get("country") or "", 120),
            "preferredLanguage": normalize_lang(request.form.get("preferredLanguage") or DEFAULT_LANG),
            "preferredVoiceGender": "male" if str(request.form.get("preferredVoiceGender") or "") == "male" else "female",
        })
        user = current_site_user() or user
        msg = "Profile updated."
    elif request.method == "POST" and request.path.endswith("/listening/clear"):
        rows = [row for row in cms_collection_rows("listeningHistory") if str(row.get("userId") or "") != str(user.get("id") or "")]
        save_cms_collection_rows("listeningHistory", rows)
        return redirect("/account/listening")
    elif request.method == "POST" and request.path.endswith("/saved/clear"):
        rows = [row for row in cms_collection_rows("favorites") if str(row.get("userId") or "") != str(user.get("id") or "")]
        save_cms_collection_rows("favorites", rows)
        return redirect("/account/saved")
    elif request.method == "POST" and request.path.endswith("/delete"):
        user_id = str(user.get("id") or "")
        rows = [row for row in cms_collection_rows("listeningHistory") if str(row.get("userId") or "") != user_id]
        save_cms_collection_rows("listeningHistory", rows)
        fav_rows = [row for row in cms_collection_rows("favorites") if str(row.get("userId") or "") != user_id]
        save_cms_collection_rows("favorites", fav_rows)
        update_site_user(user_id, {
            "email": f"deleted-{user_id}@deleted.local",
            "name": "",
            "status": "deleted",
            "emailVerified": False,
            "deletedAt": utc_now_iso(),
        })
        session.pop("user_email", None)
        session.pop("user_id", None)
        session.pop("user_login_at", None)
        return redirect(landing_url(current_lang()))

    history = listening_history_for_user(str(user.get("id") or ""), limit=80)
    favorites = favorites_for_user(str(user.get("id") or ""), limit=80)
    continue_item = history[0] if history else {}
    return render_template(
        "account.html",
        user=public_site_user(user),
        email_verified=site_user_is_verified(user),
        active_tab=active_tab,
        history=history,
        favorites=favorites,
        continue_item=continue_item,
        msg=msg,
        langs=LANG_ORDER,
        seo_title=f"My account | {BRAND_NAME}",
        seo_desc="Manage your account, listening history and saved audio guides.",
        body_class="PageAccount",
        T=t(current_lang()),
    )


@app.post("/api/account/listening")
def api_account_save_listening():
    user = current_site_user()
    if not account_feature_allowed(user):
        return jsonify({"ok": False, "requiresVerification": bool(user)}), 403
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    entity_type = clean_plain_text(payload.get("entityType") or "city", 20)
    entity_id = clean_plain_text(payload.get("entityId") or payload.get("entityTitle") or "", 180)
    section_id = clean_plain_text(payload.get("sectionId") or "", 120)
    if not entity_id and not section_id:
        return jsonify({"ok": False, "error": "Missing listening item."}), 400
    now = utc_now_iso()
    duration = max(0.0, float(payload.get("duration") or 0) if str(payload.get("duration") or "").replace(".", "", 1).isdigit() else 0.0)
    current_time = max(0.0, float(payload.get("currentTime") or 0) if str(payload.get("currentTime") or "").replace(".", "", 1).isdigit() else 0.0)
    progress = max(0.0, min(100.0, float(payload.get("progressPercent") or ((current_time / duration) * 100 if duration else 0))))
    rows = cms_collection_rows("listeningHistory")
    match_key = (
        str(user.get("id") or ""),
        entity_type,
        entity_id,
        section_id,
        clean_plain_text(payload.get("language") or DEFAULT_LANG, 12),
        clean_plain_text(payload.get("voiceGender") or "female", 12),
    )
    saved = None
    for item in rows:
        key = (
            str(item.get("userId") or ""),
            str(item.get("entityType") or ""),
            str(item.get("entityId") or ""),
            str(item.get("sectionId") or ""),
            str(item.get("language") or ""),
            str(item.get("voiceGender") or ""),
        )
        if key == match_key:
            saved = item
            break
    if not saved:
        saved = {"id": secrets.token_hex(8), "createdAt": now}
        rows.insert(0, saved)
    saved.update({
        "userId": user.get("id"),
        "entityType": entity_type,
        "entityId": entity_id,
        "entityTitle": clean_plain_text(payload.get("entityTitle") or "", 240),
        "country": clean_plain_text(payload.get("country") or "", 120),
        "city": clean_plain_text(payload.get("city") or "", 120),
        "pageUrl": clean_plain_text(payload.get("pageUrl") or request.referrer or "", 500),
        "language": match_key[4],
        "voiceGender": match_key[5],
        "sectionId": section_id,
        "sectionTitle": clean_plain_text(payload.get("sectionTitle") or "", 240),
        "audioUrl": clean_plain_text(payload.get("audioUrl") or "", 500),
        "duration": round(duration, 2),
        "currentTime": round(current_time, 2),
        "progressPercent": round(progress, 1),
        "completed": bool(payload.get("completed")) or progress >= 99,
        "lastListenedAt": now,
        "updatedAt": now,
    })
    save_cms_collection_rows("listeningHistory", rows[:5000])
    return jsonify({"ok": True, "item": saved})


@app.get("/api/account/listening/<history_id>")
def api_account_listening_item(history_id: str):
    user = current_site_user()
    if not account_feature_allowed(user):
        return jsonify({"ok": False}), 403
    for item in cms_collection_rows("listeningHistory"):
        if str(item.get("id") or "") == str(history_id) and str(item.get("userId") or "") == str(user.get("id") or ""):
            return jsonify({"ok": True, "item": item})
    return jsonify({"ok": False, "error": "Not found."}), 404


@app.post("/api/account/favorites/toggle")
def api_account_favorite_toggle():
    user = current_site_user()
    if not account_feature_allowed(user):
        return jsonify({"ok": False, "requiresVerification": bool(user)}), 403
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if hasattr(payload, "get") else {}
    entity_type = clean_plain_text(payload.get("entityType") or "city", 20)
    entity_id = clean_plain_text(payload.get("entityId") or payload.get("title") or "", 180)
    if not entity_id:
        return jsonify({"ok": False, "error": "Missing favorite item."}), 400
    rows = cms_collection_rows("favorites")
    for idx, item in enumerate(rows):
        if str(item.get("userId") or "") == str(user.get("id") or "") and str(item.get("entityType") or "") == entity_type and str(item.get("entityId") or "") == entity_id:
            rows.pop(idx)
            save_cms_collection_rows("favorites", rows)
            return jsonify({"ok": True, "saved": False})
    row = {
        "id": secrets.token_hex(8),
        "userId": user.get("id"),
        "entityType": entity_type,
        "entityId": entity_id,
        "title": clean_plain_text(payload.get("title") or entity_id, 240),
        "audioTitle": clean_plain_text(payload.get("audioTitle") or "", 240),
        "city": clean_plain_text(payload.get("city") or "", 120),
        "country": clean_plain_text(payload.get("country") or "", 120),
        "pageUrl": clean_plain_text(payload.get("pageUrl") or request.referrer or "", 500),
        "image": clean_plain_text(payload.get("image") or "", 500),
        "language": clean_plain_text(payload.get("language") or DEFAULT_LANG, 12),
        "createdAt": utc_now_iso(),
    }
    rows.insert(0, row)
    save_cms_collection_rows("favorites", rows[:5000])
    return jsonify({"ok": True, "saved": True, "item": row})


def contact_copy(lang: str) -> Dict[str, str]:
    lang = normalize_lang(lang)
    copies = {
        "ua": {
            "title": "Контакти",
            "intro": "Маєте запитання або відгук? Напишіть нам, і ми відповімо електронною поштою.",
            "name": "Ім'я",
            "email": "Email",
            "message": "Повідомлення",
            "button": "Надіслати повідомлення",
            "success": "Дякуємо. Повідомлення надіслано.",
            "error": "Заповніть ім'я, email і повідомлення.",
        },
        "en": {
            "title": "Contacts",
            "intro": "Have a question or feedback? Write to us and we will reply by email.",
            "name": "Name",
            "email": "Email",
            "message": "Message",
            "button": "Send message",
            "success": "Thank you. Your message has been sent.",
            "error": "Please fill in your name, email and message.",
        },
    }
    return copies.get(lang) or copies["en"]


def render_contact_page(lang: str):
    lang = normalize_lang(lang)
    copy = contact_copy(lang)
    status = ""
    error = ""
    form_values = {"name": "", "email": "", "message": ""}
    if request.method == "POST":
        form_values = {
            "name": clean_plain_text(request.form.get("name") or "", 140),
            "email": clean_plain_text(request.form.get("email") or "", 180).lower(),
            "message": clean_plain_text(request.form.get("message") or "", 5000),
        }
        if not form_values["name"] or not is_valid_email(form_values["email"]) or not form_values["message"]:
            error = copy["error"]
        else:
            row = save_contact_message(
                name=form_values["name"],
                email=form_values["email"],
                message_text=form_values["message"],
                source_page=request_source_page(contact_url(lang)),
            )
            body = "\n".join(
                [
                    "New SonicCity contact message",
                    "",
                    f"Name: {row.get('name')}",
                    f"Email: {row.get('email')}",
                    f"Source page: {row.get('source') or '-'}",
                    f"Language: {row.get('language') or '-'}",
                    f"Message:",
                    str(row.get("message") or ""),
                ]
            )
            send_site_notification("New SonicCity contact message", body, reply_to=form_values["email"])
            status = copy["success"]
            form_values = {"name": "", "email": "", "message": ""}
    admin_content = admin_content_for_public(admin_page_key("static", blog_slug="contacts"), lang)
    comments_context = public_comments_context(
        "static_page",
        "static:contacts",
        copy["title"],
        contact_url(lang),
        lang,
        admin_content,
        default_enabled=False,
    )
    return render_template(
        "contact.html",
        lang=lang,
        copy=copy,
        contact_email=CONTACT_EMAIL,
        form_values=form_values,
        status=status,
        error=error,
        admin_content=admin_content,
        comments_context=comments_context,
        seo_title=f"{copy['title']} | {BRAND_NAME}",
        seo_desc=f"Contact {BRAND_NAME} at {CONTACT_EMAIL} or send a message through the contact form.",
        seo_type="website",
        seo_schema=schema_graph(
            page_type="ContactPage",
            lang=lang,
            page_url=contact_url(lang),
            title=f"{copy['title']} | {BRAND_NAME}",
            description=f"Contact {BRAND_NAME} at {CONTACT_EMAIL} or send a message through the contact form.",
            main_entity={
                "@type": "Organization",
                "@id": absolute_url("/#organization"),
                "name": BRAND_NAME,
                "email": CONTACT_EMAIL,
                "contactPoint": {
                    "@type": "ContactPoint",
                    "email": CONTACT_EMAIL,
                    "contactType": "customer support",
                    "availableLanguage": ["en", "fr", "es", "it", "uk", "de"],
                },
            },
        ),
        body_class="PageContact",
        use_leaflet=False,
        T=t(lang),
    )


@app.route("/contacts/", methods=["GET", "POST"])
def contact_page_en():
    return render_contact_page(DEFAULT_LANG)


@app.get("/contacts")
def contact_page_en_redirect():
    return redirect("/contacts/", code=301)


@app.route("/<re('fr|es|it|ua|uk|de'):lang>/contacts/", methods=["GET", "POST"])
def contact_page_localized(lang: str):
    return render_contact_page(lang)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/contacts")
def contact_page_localized_redirect(lang: str):
    return redirect(contact_url(lang), code=301)


# Back-compat: old map route
@app.get("/main/<lang>/")
def main_page(lang: str):
    return redirect(landing_url(lang), code=301)


@app.get("/robots.txt")
def robots_txt():
    return Response(load_robots_text(), mimetype="text/plain")


@app.get("/llms.txt")
def llms_txt():
    fp = ROOT / "llms.txt"
    if not fp.exists():
        return Response("llms.txt has not been generated yet.\n", status=404, mimetype="text/plain; charset=utf-8")
    return send_file(fp, mimetype="text/plain", conditional=True, max_age=3600)


@app.get("/google2fc9b2aed216f535.html")
def google_site_verification():
    fp = ROOT / "google2fc9b2aed216f535.html"
    if not fp.exists():
        abort(404)
    return send_file(fp, mimetype="text/html; charset=utf-8", conditional=True, max_age=3600)


@app.get("/favicon.ico")
def favicon_ico():
    return send_from_directory(ROOT / "static" / "img", "soniccity-favicon.png", mimetype="image/png")


SITEMAP_MAX_URLS = 10000
SITEMAP_CATEGORY_ORDER = ["countries", "city", "places", "blog", "categories", "pages", "lps"]


def sitemap_iso_from_timestamp(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


def sitemap_paths_lastmod(*paths: Path, fallback: str = "") -> str:
    mtimes: List[float] = []
    for path in paths:
        try:
            if path and path.exists():
                mtimes.append(path.stat().st_mtime)
        except Exception:
            continue
    if mtimes:
        return sitemap_iso_from_timestamp(max(mtimes))
    return fallback


def sitemap_lastmod() -> str:
    return sitemap_paths_lastmod(
        COUNTRIES_PATH,
        CITIES_PATH,
        PLACES_INDEX_PATH,
        BLOG_POSTS_PATH,
        ADMIN_PAGES_PATH,
        ADMIN_CMS_STORE_PATH,
        fallback="2026-05-19T00:00:00+00:00",
    )


def sitemap_normalize_lastmod(value: Optional[str] = None) -> str:
    raw = clean_plain_text(value or "", 80)
    if not raw:
        return sitemap_lastmod()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T00:00:00+00:00"
    if raw.endswith("Z"):
        return f"{raw[:-1]}+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", raw):
        return f"{raw}+00:00"
    return raw


def sitemap_lang_alt(lang_slug: str, path: str) -> Dict[str, str]:
    return {"lang": HREFLANG_CODE_BY_LANG.get(lang_slug, lang_slug), "url": absolute_url(path)}


def sitemap_alternates(path_builder, langs: Optional[List[str]] = None) -> List[Dict[str, str]]:
    available = list(langs or LANG_ORDER)
    alts = [sitemap_lang_alt(lang_slug, path_builder(lang_slug)) for lang_slug in available]
    if DEFAULT_LANG in available:
        alts.append({"lang": "x-default", "url": absolute_url(path_builder(DEFAULT_LANG))})
    return alts


def sitemap_url_entry(
    path: str,
    alternates: Optional[List[Dict[str, str]]] = None,
    lastmod: Optional[str] = None,
    *,
    priority: str = "0.7",
    changefreq: str = "weekly",
) -> Dict[str, Any]:
    return {
        "loc": absolute_url(path),
        "lastmod": sitemap_normalize_lastmod(lastmod),
        "priority": priority,
        "changefreq": changefreq,
        "alternates": alternates or [],
    }


def sitemap_index_entry(path: str, lastmod: Optional[str] = None) -> Dict[str, str]:
    return {"loc": absolute_url(path), "lastmod": sitemap_normalize_lastmod(lastmod)}


def sitemap_page_lastmod(page_key: str, lang: str, *fallback_paths: Path) -> str:
    content = load_admin_page_content(page_key, lang)
    return sitemap_normalize_lastmod(content.get("updatedAt") or sitemap_paths_lastmod(*fallback_paths, fallback=sitemap_lastmod()))


def sitemap_category_lastmod(lang: str, category: str) -> str:
    category = "city" if category == "cities" else str(category or "").strip().lower()
    if category == "countries":
        return sitemap_paths_lastmod(COUNTRIES_PATH, ADMIN_PAGES_PATH, fallback=sitemap_lastmod())
    if category == "city":
        return sitemap_paths_lastmod(CITIES_PATH, PLACES_INDEX_PATH, ADMIN_PAGES_PATH, fallback=sitemap_lastmod())
    if category == "places":
        return sitemap_paths_lastmod(PLACES_INDEX_PATH, ADMIN_PAGES_PATH, fallback=sitemap_lastmod())
    if category in {"blog", "categories"}:
        return sitemap_paths_lastmod(BLOG_POSTS_PATH, ADMIN_CMS_STORE_PATH, fallback=sitemap_lastmod())
    if category in {"pages", "lps"}:
        return sitemap_paths_lastmod(ADMIN_PAGES_PATH, ADMIN_CMS_STORE_PATH, fallback=sitemap_lastmod())
    return sitemap_lastmod()


def sitemap_category_path(lang: str, category: str) -> str:
    lang = normalize_lang(lang)
    category = "city" if category == "cities" else str(category or "").strip().lower()
    filename = f"{category}.xml"
    return f"/{filename}" if lang == DEFAULT_LANG else f"/{lang}/{filename}"


def sitemap_language_index_path(lang: str) -> str:
    lang = normalize_lang(lang)
    return "/sitemap_default.xml" if lang == DEFAULT_LANG else f"/{lang}/sitemap.xml"


def sitemap_admin_page_is_indexable(page_key: str, lang: str) -> bool:
    content = load_admin_page_content(page_key, lang)
    if str(content.get("status") or "published").lower() != "published":
        return False
    if not bool(content.get("robotsIndex", True)):
        return False
    if not bool(content.get("sitemapIncluded", True)):
        return False
    if bool(content.get("redirectEnabled", False)):
        return False
    return True


def sitemap_managed_page_rows(lang: str, page_type: str) -> List[Dict[str, Any]]:
    lang = normalize_lang(lang)
    out: List[Dict[str, Any]] = []
    pages = (load_admin_pages_data().get("pages") or {})
    for page_key in sorted(pages.keys()):
        parts = split_admin_page_key(page_key)
        if parts.get("type") != page_type:
            continue
        slug = slugify(parts.get("place") or parts.get("blog") or parts.get("city") or parts.get("country") or "")
        if not slug or not sitemap_admin_page_is_indexable(page_key, lang):
            continue
        content = load_admin_page_content(page_key, lang)
        has_visible_content = bool(html_to_plain_text(content.get("seoTextHtml") or "", 4000)) or bool(content.get("visibleFaq"))
        if not has_visible_content:
            continue
        prefix = "landing" if page_type == "landing" else "pages"

        def build_path(lang_slug: str, *, _prefix: str = prefix, _slug: str = slug) -> str:
            return f"/{_prefix}/{_slug}" if normalize_lang(lang_slug) == DEFAULT_LANG else f"/{normalize_lang(lang_slug)}/{_prefix}/{_slug}"

        out.append(
            sitemap_url_entry(
                build_path(lang),
                sitemap_alternates(build_path),
                content.get("updatedAt") or sitemap_paths_lastmod(ADMIN_PAGES_PATH, fallback=sitemap_lastmod()),
                priority="0.8" if page_type == "landing" else "0.5",
                changefreq="weekly" if page_type == "landing" else "monthly",
            )
        )
    return out


def sitemap_rows_for_category(lang: str, category: str) -> List[Dict[str, Any]]:
    lang = normalize_lang(lang)
    category = "city" if category == "cities" else str(category or "").strip().lower()
    rows: List[Dict[str, Any]] = []

    if category == "lps":
        rows.append(
            sitemap_url_entry(
                landing_url(lang),
                sitemap_alternates(landing_url),
                sitemap_page_lastmod("home", lang, ADMIN_PAGES_PATH, ADMIN_CMS_STORE_PATH),
                priority="1.0",
                changefreq="weekly",
            )
        )
        rows.extend(sitemap_managed_page_rows(lang, "landing"))
        return rows[:SITEMAP_MAX_URLS]

    if category == "pages":
        rows.append(
            sitemap_url_entry(
                contact_url(lang),
                sitemap_alternates(contact_url),
                sitemap_page_lastmod(admin_page_key("static", blog_slug="contacts"), lang, ADMIN_PAGES_PATH, ADMIN_CMS_STORE_PATH),
                priority="0.5",
                changefreq="monthly",
            )
        )
        rows.extend(sitemap_managed_page_rows(lang, "static"))
        return rows[:SITEMAP_MAX_URLS]

    if category == "countries":
        for c in target_countries():
            cslug = str(c.get("slug") or "")
            if not cslug:
                continue
            entity_langs = [
                item_lang
                for item_lang in LANG_ORDER
                if entity_is_indexable_for_lang("country", item_lang, cslug)
            ]
            if lang not in entity_langs:
                continue

            def build_path(lang_slug: str, *, _cslug: str = cslug) -> str:
                return country_url(lang_slug, _cslug)

            rows.append(
                sitemap_url_entry(
                    country_url(lang, cslug),
                    sitemap_alternates(build_path, entity_langs),
                    sitemap_page_lastmod(admin_page_key("country", country_slug=cslug), lang, COUNTRIES_PATH, PLACES_INDEX_PATH),
                    priority="0.8",
                    changefreq="weekly",
                )
            )
        return rows[:SITEMAP_MAX_URLS]

    if category == "city":
        for country in target_countries():
            country_slug = str(country.get("slug") or "").strip().lower()
            if not country_slug:
                continue
            for city in target_country_cities(country_slug):
                city_slug = str(city.get("citySlug") or "")
                if not city_slug:
                    continue
                entity_langs = [
                    item_lang
                    for item_lang in LANG_ORDER
                    if entity_is_indexable_for_lang("city", item_lang, country_slug, city_slug)
                ]
                if lang not in entity_langs:
                    continue

                def build_path(lang_slug: str, *, _country_slug: str = country_slug, _city_slug: str = city_slug) -> str:
                    return city_url(lang_slug, _country_slug, _city_slug)

                rows.append(
                    sitemap_url_entry(
                        city_url(lang, country_slug, city_slug),
                        sitemap_alternates(build_path, entity_langs),
                        sitemap_page_lastmod(admin_page_key("city", country_slug=country_slug, city_slug=city_slug), lang, CITIES_PATH, PLACES_INDEX_PATH),
                        priority="0.8",
                        changefreq="weekly",
                    )
                )
        return rows[:SITEMAP_MAX_URLS]

    if category == "places":
        for country in target_countries():
            country_slug = str(country.get("slug") or "").strip().lower()
            if not country_slug:
                continue
            for city in target_country_cities(country_slug):
                city_slug = str(city.get("citySlug") or "").strip().lower()
                if not city_slug:
                    continue
                places = target_places_for_city(country_slug, city_slug)
                for place in places:
                    pslug = str(place.get("slug") or "")
                    if not pslug:
                        continue
                    entity_langs = [
                        item_lang
                        for item_lang in LANG_ORDER
                        if entity_is_indexable_for_lang("place", item_lang, country_slug, city_slug, pslug)
                    ]
                    if lang not in entity_langs:
                        continue

                    def build_path(lang_slug: str, *, _country_slug: str = country_slug, _city_slug: str = city_slug, _pslug: str = pslug) -> str:
                        return place_url(lang_slug, _country_slug, _city_slug, _pslug)

                    rows.append(
                        sitemap_url_entry(
                            place_url(lang, country_slug, city_slug, pslug),
                            sitemap_alternates(build_path, entity_langs),
                            sitemap_page_lastmod(admin_page_key("place", country_slug=country_slug, city_slug=city_slug, place_slug=pslug), lang, PLACES_INDEX_PATH),
                            priority="0.7",
                            changefreq="weekly",
                        )
                    )
        return rows[:SITEMAP_MAX_URLS]

    if category == "blog":
        rows.append(
            sitemap_url_entry(
                blog_index_url(lang),
                sitemap_alternates(blog_index_url),
                sitemap_paths_lastmod(BLOG_POSTS_PATH, ADMIN_CMS_STORE_PATH, fallback=sitemap_lastmod()),
                priority="0.6",
                changefreq="weekly",
            )
        )
        for post in load_blog_posts(lang=lang):
            if not bool(post.get("robotsIndex", True)) or not bool(post.get("sitemapIncluded", True)):
                continue
            rows.append(
                sitemap_url_entry(
                    blog_post_url(post),
                    [sitemap_lang_alt(lang, blog_post_url(post))],
                    post.get("updatedAt") or post.get("publishedAt") or None,
                    priority="0.6",
                    changefreq="monthly",
                )
            )
        return rows[:SITEMAP_MAX_URLS]

    if category == "categories":
        category_rows = [
            row for row in cms_collection_rows("blogCategories")
            if normalize_lang(str(row.get("language") or DEFAULT_LANG)) == lang
            and str(row.get("status") or "published").lower() == "published"
            and str(row.get("slug") or "").strip()
        ]
        if not category_rows:
            category_rows = blog_categories(load_blog_posts(lang=lang))
        for row in category_rows:
            slug = slugify(row.get("slug") or row.get("name") or "")
            if not slug:
                continue
            path = f"{blog_index_url(lang)}?category={urllib.parse.quote(slug)}"
            rows.append(
                sitemap_url_entry(
                    path,
                    [sitemap_lang_alt(lang, path)],
                    row.get("updatedAt") or sitemap_paths_lastmod(BLOG_POSTS_PATH, ADMIN_CMS_STORE_PATH, fallback=sitemap_lastmod()),
                    priority="0.4",
                    changefreq="monthly",
                )
            )
        return rows[:SITEMAP_MAX_URLS]

    return rows


def sitemap_xml_response(rows: List[Dict[str, Any]]) -> Response:
    xml = render_template("sitemap.xml", urls=sorted(rows, key=lambda row: row["loc"]))
    resp = Response(xml, content_type="text/xml; charset=UTF-8")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def sitemap_index_response(rows: List[Dict[str, str]]) -> Response:
    xml = render_template("sitemap_index.xml", sitemaps=sorted(rows, key=lambda row: row["loc"]))
    resp = Response(xml, content_type="text/xml; charset=UTF-8")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.errorhandler(404)
def not_found(error):
    lang = current_lang()
    return (
        render_template(
            "error.html",
            lang=lang,
            status_code=404,
            title="Guide not found",
            message="This audio guide is not available yet. Try the live map or browse nearby countries.",
            seo_title=f"Not found | {BRAND_NAME}",
            seo_desc="The requested SonicCity page was not found.",
            seo_type="website",
            seo_image="/static/img/place-placeholder.svg",
            seo_schema={
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": f"Not found | {BRAND_NAME}",
                "url": absolute_url(canonical_path_for_request()),
            },
            T=t(lang),
            body_class="PageError",
            use_leaflet=False,
        ),
        404,
    )


@app.errorhandler(500)
def server_error(error):
    lang = current_lang()
    return (
        render_template(
            "error.html",
            lang=lang,
            status_code=500,
            title="Something went wrong",
            message="The guide could not be loaded right now. Please retry from the map.",
            seo_title=f"Server error | {BRAND_NAME}",
            seo_desc="SonicCity server error.",
            seo_type="website",
            seo_image="/static/img/place-placeholder.svg",
            seo_schema={
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": f"Server error | {BRAND_NAME}",
                "url": absolute_url(canonical_path_for_request()),
            },
            T=t(lang),
            body_class="PageError",
            use_leaflet=False,
        ),
        500,
    )


@app.get("/sitemap.xml")
def sitemap_xml():
    rows = [sitemap_index_entry(sitemap_language_index_path(DEFAULT_LANG), sitemap_lastmod())]
    rows.extend(sitemap_index_entry(sitemap_language_index_path(lang_slug), sitemap_lastmod()) for lang_slug in LANG_ORDER if lang_slug != DEFAULT_LANG)
    return sitemap_index_response(rows)


@app.get("/sitemap.xsl")
def sitemap_xsl():
    resp = make_response(render_template("sitemap.xsl"))
    resp.headers["Content-Type"] = "text/xsl; charset=UTF-8"
    resp.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/sitemap_default.xml")
def sitemap_default_xml():
    rows = [sitemap_index_entry(sitemap_category_path(DEFAULT_LANG, category), sitemap_category_lastmod(DEFAULT_LANG, category)) for category in SITEMAP_CATEGORY_ORDER]
    return sitemap_index_response(rows)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/sitemap.xml")
def sitemap_language_xml(lang: str):
    lang = normalize_lang(lang)
    rows = [sitemap_index_entry(sitemap_category_path(lang, category), sitemap_category_lastmod(lang, category)) for category in SITEMAP_CATEGORY_ORDER]
    return sitemap_index_response(rows)


@app.get("/<re('countries|city|cities|places|blog|categories|pages|lps'):category>.xml")
def sitemap_default_category_xml(category: str):
    return sitemap_xml_response(sitemap_rows_for_category(DEFAULT_LANG, category))


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/<re('countries|city|cities|places|blog|categories|pages|lps'):category>.xml")
def sitemap_language_category_xml(lang: str, category: str):
    return sitemap_xml_response(sitemap_rows_for_category(lang, category))


@app.get("/cities.json")
def cities_json():
    if not CITIES_PATH.exists():
        abort(404)
    resp = make_response(send_file(CITIES_PATH, mimetype="application/json", conditional=True, max_age=3600))
    resp.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    return resp


# -------- api nearby --------
@app.get("/api/nearby")
def api_nearby():
    try:
        lat = float(request.args.get("lat", "nan"))
        lon = float(request.args.get("lon", "nan"))
        r = float(request.args.get("r", "10"))
        limit = int(request.args.get("limit", "40"))
    except Exception:
        return jsonify({"error": "Bad params"}), 400

    if not (math.isfinite(lat) and math.isfinite(lon)):
        return jsonify({"error": "lat/lon required"}), 400

    r = max(0.5, min(r, 100.0))
    limit = max(1, min(limit, 200))

    lang = normalize_lang(request.args.get("lang") or DEFAULT_LANG)
    found = detect_nearby_cities(
        cities=CITIES,
        lat=lat,
        lon=lon,
        radius_km=r,
        limit=limit,
        lang=lang,
        resolve_country=resolve_country,
        slugify=slugify,
        city_url=city_url,
        country_display_name_for_lang=country_display_name_for_lang,
        city_display_name_for_lang=city_display_name_for_lang,
        min_population=MIN_CITY_POPULATION,
    )
    return jsonify(found)


# -------- api search (menu search + homepage search) --------
@app.get("/api/search")
def api_search():
    lang = normalize_lang(request.args.get("lang") or DEFAULT_LANG)
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"items": []})
    cache_key = (lang, q)
    now = time.time()
    with SEARCH_RESPONSE_CACHE_LOCK:
        cached = SEARCH_RESPONSE_CACHE.get(cache_key)
        if cached and now - cached[0] < SEARCH_RESPONSE_CACHE_TTL_SECONDS:
            resp = jsonify(cached[1])
            resp.headers["Cache-Control"] = "private, max-age=60"
            return resp

    items: List[Dict[str, Any]] = []
    for c in COUNTRIES:
        if not country_translation_exists(c["slug"], lang):
            continue
        n = c["name"].lower()
        if n.startswith(q) or q in n:
            items.append(
                {
                    "type": "country",
                    "name": country_display_name_cached_for_lang(c, lang),
                    "slug": c["slug"],
                    "code": c["code"],
                    "flag": c["flagUrl"],
                    "flagEmoji": c.get("flagEmoji") or "🌍",
                    "label": t(lang)["type_country"],
                    "url": country_url(lang, c["slug"]),
                }
            )

    places: List[Dict[str, Any]] = []
    for p in TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG.values():
        if p.get("inMainDataset"):
            continue
        n = str(p.get("name") or "").lower()
        if not (n.startswith(q) or q in n):
            continue
        co = COUNTRY_BY_SLUG.get(str(p.get("countrySlug") or ""))
        if not co:
            continue
        city_slug = str(p.get("citySlug") or "")
        if not city_translation_exists(co["slug"], city_slug, lang):
            continue
        places.append(
            {
                "type": "place",
                "displayName": city_display_name_cached_for_lang({**p, "countrySlug": co["slug"], "citySlug": str(p.get("citySlug") or "")}, lang),
                "name": city_display_name_cached_for_lang({**p, "countrySlug": co["slug"], "citySlug": str(p.get("citySlug") or "")}, lang),
                "slug": city_slug,
                "countryName": country_display_name_cached_for_lang(co, lang),
                "countrySlug": co["slug"],
                "flag": co["flagUrl"],
                "flagEmoji": co.get("flagEmoji") or "🌍",
                "label": t(lang)["type_place"],
                "population": int(p.get("population") or 0),
                "url": city_url(lang, co["slug"], city_slug),
            }
        )
    places.sort(key=lambda x: (-(int(x.get("population") or 0)), x.get("name", "")))

    city_places: List[Dict[str, Any]] = []
    for (cslug, ctyslug, pslug), p in PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.items():
        n = str(p.get("name") or "").lower()
        if not (n.startswith(q) or q in n):
            continue
        co = COUNTRY_BY_SLUG.get(cslug)
        if not co:
            continue
        if not place_translation_exists(cslug, ctyslug, pslug, lang):
            continue
        city_places.append(
            {
                "type": "place",
                "displayName": place_display_name_cached_for_lang({**p, "countrySlug": co["slug"], "citySlug": ctyslug, "slug": pslug}, lang),
                "name": place_display_name_cached_for_lang({**p, "countrySlug": co["slug"], "citySlug": ctyslug, "slug": pslug}, lang),
                "slug": pslug,
                "cityName": city_display_name_cached_for_lang({**p, "name": p.get("cityName") or "", "countrySlug": co["slug"], "citySlug": ctyslug}, lang),
                "cityDisplayName": city_display_name_cached_for_lang({**p, "name": p.get("cityName") or "", "countrySlug": co["slug"], "citySlug": ctyslug}, lang),
                "citySlug": ctyslug,
                "countryName": country_display_name_cached_for_lang(co, lang),
                "countrySlug": co["slug"],
                "flag": co["flagUrl"],
                "flagEmoji": co.get("flagEmoji") or "🌍",
                "label": t(lang)["type_place"],
                "url": place_url(lang, co["slug"], ctyslug, pslug),
            }
        )
    city_places.sort(key=lambda x: (x.get("name", ""), x.get("cityName", ""), x.get("countryName", "")))

    cities: List[Dict[str, Any]] = []
    for city in CITIES:
        co = resolve_country(city.get("country") or "")
        if not co:
            continue
        city_slug = slugify(city["name"])
        if not city_translation_exists(co["slug"], city_slug, lang):
            continue
        n = city["name"].lower()
        if n.startswith(q) or q in n:
            country_display = country_display_name_cached_for_lang(co, lang)
            cities.append(
                {
                    "type": "city",
                    "displayName": city_display_name_cached_for_lang({**city, "countrySlug": co["slug"], "citySlug": city_slug}, lang),
                    "name": city_display_name_cached_for_lang({**city, "countrySlug": co["slug"], "citySlug": city_slug}, lang),
                    "slug": city_slug,
                    "countryName": country_display,
                    "countrySlug": co["slug"],
                    "flag": co["flagUrl"],
                    "flagEmoji": co.get("flagEmoji") or "🌍",
                    "label": t(lang)["type_city"],
                    "url": city_url(lang, co["slug"], city_slug),
                }
            )
    cities.sort(key=lambda x: x["name"])

    # Interleave: countries first, then places, then cities
    items.extend(places[:6])
    items.extend(city_places[:6])
    items.extend(cities)
    items = items[:14]

    payload = {"items": items}
    with SEARCH_RESPONSE_CACHE_LOCK:
        if len(SEARCH_RESPONSE_CACHE) > 600:
            SEARCH_RESPONSE_CACHE.clear()
        SEARCH_RESPONSE_CACHE[cache_key] = (now, payload)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "private, max-age=60"
    return resp


@app.get("/api/place_geo")
def api_place_geo():
    """
    Resolve coordinates for a place (for map markers/tooltips).
    Cached on disk under ./cache/place_geo/<wiki_lang>/<country>/<city>/<place>.json.
    """
    lang = normalize_lang(request.args.get("lang") or DEFAULT_LANG)
    country_slug = str(request.args.get("country") or "").strip()
    city_slug = str(request.args.get("city") or "").strip()
    place_slug = str(request.args.get("place") or "").strip()

    if not (country_slug and city_slug and place_slug):
        return jsonify({"error": "Bad params"}), 400

    place = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
    if not place:
        return jsonify({"error": "Not found"}), 404

    override = PLACE_METADATA_OVERRIDES.get((country_slug, city_slug, place_slug), {})
    override_coords = valid_lat_lon(override.get("lat"), override.get("lon"))
    if override_coords:
        return jsonify({
            "lat": override_coords[0],
            "lon": override_coords[1],
            "title": place.get("name") or place_slug,
            "source": "curated",
        })

    data_coords = valid_lat_lon(
        place.get("lat") or place.get("latitude"),
        place.get("lon") or place.get("lng") or place.get("longitude"),
    )
    if data_coords:
        return jsonify({
            "lat": data_coords[0],
            "lon": data_coords[1],
            "title": place.get("name") or place_slug,
            "source": "data",
        })

    wiki_lang = SUPPORTED_LANGS[lang]["wiki"]
    cache_dir = PLACE_GEO_CACHE_DIR / wiki_lang / country_slug / city_slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{place_slug}.json"
    missing_path = cache_dir / f"{place_slug}.missing"
    en_cache_dir = PLACE_GEO_CACHE_DIR / "en" / country_slug / city_slug
    en_cache_path = en_cache_dir / f"{place_slug}.json"
    en_missing_path = en_cache_dir / f"{place_slug}.missing"

    def read_place_geo_cache(path: Path, source: str) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            coords = valid_lat_lon(cached.get("lat"), cached.get("lon"))
            resolved_title = str(cached.get("title") or "").strip()
            if coords and resolved_title_matches_place(
                resolved_title,
                str(place.get("name") or ""),
                str(place.get("cityName") or ""),
            ):
                return {"lat": coords[0], "lon": coords[1], "title": resolved_title, "source": source}
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    cached_geo = read_place_geo_cache(cache_path, "cache")
    if cached_geo:
        return jsonify(cached_geo)

    if wiki_lang != "en":
        cached_geo = read_place_geo_cache(en_cache_path, "cache")
        if cached_geo:
            try:
                cache_path.write_text(
                    json.dumps({
                        "lat": cached_geo["lat"],
                        "lon": cached_geo["lon"],
                        "title": cached_geo["title"],
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )
                missing_path.unlink(missing_ok=True)
            except Exception:
                pass
            return jsonify(cached_geo)

    current_missing = missing_path.exists()
    skip_wiki_lookup = current_missing and (wiki_lang == "en" or en_missing_path.exists())

    place_name = str(place.get("name") or "").strip()
    city_name = str(place.get("cityName") or "").strip()
    country_name = str(place.get("countryName") or "").strip()

    resolved = None
    used_lang = wiki_lang
    if not current_missing:
        resolved = resolve_place_coordinates(wiki_lang, place_name, city_name, country_name)

    attempted_en = False
    if not resolved and wiki_lang != "en" and not skip_wiki_lookup:
        used_lang = "en"
        attempted_en = True
        if not en_missing_path.exists():
            resolved = resolve_place_coordinates("en", place_name, city_name, country_name)

    if not resolved:
        used_lang = wiki_lang
        resolved = resolve_place_coordinates_osm(place_name, city_name, country_name)

    if not resolved:
        try:
            missing_path.touch(exist_ok=True)
            if attempted_en:
                en_cache_dir.mkdir(parents=True, exist_ok=True)
                en_missing_path.touch(exist_ok=True)
        except Exception:
            pass
        return jsonify({"error": "No coordinates"}), 404

    lat, lon, title = resolved
    if not resolved_title_matches_place(title, place_name, city_name):
        try:
            missing_path.touch(exist_ok=True)
        except Exception:
            pass
        return jsonify({"error": "No matching coordinates"}), 404
    try:
        cache_dir2 = PLACE_GEO_CACHE_DIR / used_lang / country_slug / city_slug
        cache_dir2.mkdir(parents=True, exist_ok=True)
        (cache_dir2 / f"{place_slug}.json").write_text(
            json.dumps({"lat": lat, "lon": lon, "title": title}, ensure_ascii=False),
            encoding="utf-8",
        )
        missing_path.unlink(missing_ok=True)
    except Exception:
        pass

    return jsonify({"lat": lat, "lon": lon, "title": title, "source": used_lang})


def route_cache_path(from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str) -> Path:
    raw = f"{ROUTE_PROVIDER}:{mode}:{from_lat:.6f},{from_lon:.6f}:{to_lat:.6f},{to_lon:.6f}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return ROUTE_CACHE_DIR / mode / f"{digest}.json"


def route_base_url(mode: str) -> str:
    if mode == "driving":
        return ROUTE_OSRM_DRIVING_URL
    return ROUTE_OSRM_FOOT_URL


def fetch_ground_route(
    *,
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    mode: str,
) -> Tuple[Dict[str, Any], int]:
    if ROUTE_PROVIDER in {"", "none", "disabled"}:
        return {"status": "unavailable", "error": "Route provider is not configured."}, 503
    if ROUTE_PROVIDER != "osrm":
        return {"status": "unavailable", "error": "Route provider is not configured."}, 503

    base = route_base_url(mode)
    if not base:
        return {"status": "unavailable", "error": "Route provider is not configured."}, 503

    cache_path = route_cache_path(from_lat, from_lon, to_lat, to_lon, mode)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("status") == "ready":
                return cached, 200
        except Exception:
            try:
                cache_path.unlink(missing_ok=True)
            except Exception:
                pass

    coords = f"{from_lon:.7f},{from_lat:.7f};{to_lon:.7f},{to_lat:.7f}"
    params = urllib.parse.urlencode({
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "alternatives": "false",
    })
    url = f"{base.rstrip('/')}/{coords}?{params}"
    data = http_get_json(url, timeout_s=14)
    if not isinstance(data, dict) or data.get("code") != "Ok":
        return {"status": "failed", "error": "Route provider failed."}, 502

    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        return {"status": "failed", "error": "No ground route found."}, 502

    route = routes[0]
    geometry = route.get("geometry") if isinstance(route, dict) else None
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return {"status": "failed", "error": "Route provider returned no route line."}, 502

    out = {
        "status": "ready",
        "provider": "osrm",
        "mode": mode,
        "distanceMeters": float(route.get("distance") or 0),
        "durationSeconds": float(route.get("duration") or 0),
        "geometry": geometry,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out, 200


@app.post("/api/route")
def api_route():
    payload = request.get_json(silent=True) or {}
    mode = str(payload.get("mode") or "walking").strip().lower()
    if mode not in {"walking", "driving"}:
        mode = "walking"
    from_payload = payload.get("from") if isinstance(payload.get("from"), dict) else {}
    to_payload = payload.get("to") if isinstance(payload.get("to"), dict) else {}
    from_coords = valid_lat_lon(from_payload.get("lat"), from_payload.get("lng") or from_payload.get("lon"))
    to_coords = valid_lat_lon(to_payload.get("lat"), to_payload.get("lng") or to_payload.get("lon"))
    if not from_coords or not to_coords:
        return jsonify({"status": "unavailable", "error": "Enable location to build a route from your position."}), 400
    out, status_code = fetch_ground_route(
        from_lat=from_coords[0],
        from_lon=from_coords[1],
        to_lat=to_coords[0],
        to_lon=to_coords[1],
        mode=mode,
    )
    return jsonify(out), status_code


@app.post("/api/audio_build")
def api_audio_build():
    """
    Queue pre-generated audio build (city/place, natural edge voices) for a single lang+gender.
    Used when a manifest is missing, so the frontend can show "audio loading" and retry.
    """
    payload = request.get_json(silent=True) or {}
    lang = normalize_lang(str(payload.get("lang") or DEFAULT_LANG))
    gender = str(payload.get("gender") or "female").strip().lower()
    kind = str(payload.get("kind") or "").strip().lower()
    country_slug = str(payload.get("country") or "").strip().lower()
    city_slug = str(payload.get("city") or "").strip().lower()
    place_slug = str(payload.get("place") or "").strip().lower()
    if kind == "country":
        city_slug = "__country__"
        place_slug = ""

    if gender not in {"female", "male"}:
        return jsonify({"error": "Bad gender"}), 400
    if not country_slug or not city_slug:
        return jsonify({"error": "Bad params"}), 400

    if kind == "country":
        if country_slug not in COUNTRY_BY_SLUG:
            return jsonify({"error": "Country not found"}), 404
    elif (country_slug, city_slug) not in CITY_BY_COUNTRYSLUG_CITYSLUG:
        return jsonify({"error": "City not found"}), 404

    if kind != "country" and place_slug:
        if (country_slug, city_slug, place_slug) not in PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG:
            return jsonify({"error": "Place not found"}), 404

    out = enqueue_audio_build(country_slug, city_slug, lang, gender, place_slug=place_slug or None)
    return jsonify(out)


@app.get("/api/audio_build_status")
def api_audio_build_status():
    lang = normalize_lang(request.args.get("lang") or DEFAULT_LANG)
    gender = str(request.args.get("gender") or "female").strip().lower()
    kind = str(request.args.get("kind") or "").strip().lower()
    country_slug = str(request.args.get("country") or "").strip().lower()
    city_slug = str(request.args.get("city") or "").strip().lower()
    place_slug = str(request.args.get("place") or "").strip().lower()
    if kind == "country":
        city_slug = "__country__"
        place_slug = ""

    if gender not in {"female", "male"}:
        return jsonify({"error": "Bad gender"}), 400
    if not country_slug or not city_slug:
        return jsonify({"error": "Bad params"}), 400

    manifest = audio_manifest_path(
        version=AUDIO_BUILD_AUDIO_VERSION,
        lang=lang,
        gender=gender,
        country_slug=country_slug,
        city_slug=city_slug,
        place_slug=place_slug or None,
    )
    manifest_summary = read_audio_manifest_summary(manifest)
    if manifest_summary:
        return jsonify(
            {
                "status": "ready",
                "ready": True,
                "progress": 100.0,
                "label": "Audio ready",
                "version": AUDIO_BUILD_AUDIO_VERSION,
                "sections": manifest_summary.get("sections") or 0,
                "readySections": manifest_summary.get("ready") or 0,
                "failedSections": manifest_summary.get("failed") or 0,
                "outdatedSections": manifest_summary.get("outdated") or 0,
                "voice": manifest_summary.get("voice") or "",
            }
        )

    job_key = audio_build_job_key(country_slug, city_slug, lang, gender, place_slug=place_slug or None)
    with AUDIO_BUILD_LOCK:
        st = dict(AUDIO_BUILD_STATUS.get(job_key) or {})
    if not st:
        return jsonify({"status": "missing", "ready": False, "progress": 0.0, "version": AUDIO_BUILD_AUDIO_VERSION})
    st["ready"] = False
    st.setdefault("progress", 0.0)
    st.setdefault("version", AUDIO_BUILD_AUDIO_VERSION)
    return jsonify(st)


def country_label_from_code(country_code: str) -> str:
    code = (country_code or "").strip().lower()
    if not code:
        return "Unknown"
    country = COUNTRY_BY_CODE.get(code)
    if country:
        return f"{country_display_name_cached_for_lang(country, 'en')} ({code.upper()})"
    return code.upper()


def load_access_events(max_rows: int = 50000, days: int = 7) -> List[Dict[str, Any]]:
    if not ACCESS_LOG_PATH.exists():
        return []
    try:
        lines = ACCESS_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    now = time.time()
    cutoff = now - max(1, days) * 86400
    events: List[Dict[str, Any]] = []
    for line in lines[-max(1000, max_rows):]:
        try:
            event = json.loads(line)
        except Exception:
            continue
        try:
            ts = int(event.get("ts") or 0)
        except Exception:
            ts = 0
        if ts and ts < cutoff:
            continue
        events.append(event)
    return events


def top_counter_rows(counter: Counter, limit: int = 12) -> List[Dict[str, Any]]:
    return [{"label": str(label), "count": int(count)} for label, count in counter.most_common(limit)]


def traffic_noise_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    country_counter: Counter = Counter()
    ua_counter: Counter = Counter()
    path_counter: Counter = Counter()
    referrer_counter: Counter = Counter()
    flag_counter: Counter = Counter()
    ip_counter: Counter = Counter()
    ip_country: Dict[str, Counter] = defaultdict(Counter)
    ip_ua: Dict[str, Counter] = defaultdict(Counter)
    ip_paths: Dict[str, Counter] = defaultdict(Counter)
    status_counter: Counter = Counter()

    for event in events:
        ip = str(event.get("ip") or "unknown")
        country = country_label_from_code(str(event.get("country") or ""))
        ua = str(event.get("uaFamily") or ua_family(str(event.get("ua") or "")) or "unknown")
        path = str(event.get("path") or "/")
        referrer = str(event.get("referrer") or "")
        ref_host = "Direct / empty"
        if referrer:
            try:
                ref_host = urllib.parse.urlparse(referrer).netloc or referrer[:80]
            except Exception:
                ref_host = referrer[:80]

        try:
            status = int(event.get("status") or 0)
        except Exception:
            status = 0

        country_counter[country] += 1
        ua_counter[ua] += 1
        path_counter[path] += 1
        referrer_counter[ref_host] += 1
        status_counter[str(status or "unknown")] += 1
        ip_counter[ip] += 1
        ip_country[ip][country] += 1
        ip_ua[ip][ua] += 1
        ip_paths[ip][path] += 1
        for flag in event.get("flags") or []:
            flag_counter[str(flag)] += 1

    top_ips: List[Dict[str, Any]] = []
    for ip, count in ip_counter.most_common(20):
        top_ips.append(
            {
                "ip": ip,
                "count": int(count),
                "country": ip_country[ip].most_common(1)[0][0] if ip_country[ip] else "Unknown",
                "ua": ip_ua[ip].most_common(1)[0][0] if ip_ua[ip] else "unknown",
                "path": ip_paths[ip].most_common(1)[0][0] if ip_paths[ip] else "/",
            }
        )

    return {
        "total": len(events),
        "direct": int(flag_counter.get("direct", 0)),
        "directChrome": int(flag_counter.get("direct-chrome", 0)),
        "botUa": int(flag_counter.get("bot-ua", 0)),
        "headless": int(flag_counter.get("headless", 0)),
        "errors": int(flag_counter.get("error", 0)),
        "countries": top_counter_rows(country_counter),
        "browsers": top_counter_rows(ua_counter),
        "paths": top_counter_rows(path_counter),
        "referrers": top_counter_rows(referrer_counter),
        "flags": top_counter_rows(flag_counter),
        "statuses": top_counter_rows(status_counter),
        "ips": top_ips,
    }


ADMIN_CMS_GROUPS = [
    {
        "key": "blog",
        "label": "Blog",
        "items": [
            ("blog/articles", "Blog articles"),
            ("blog/authors", "Blog authors"),
            ("blog/categories", "Blog categories"),
            ("blog/comments", "Blog comments"),
            ("blog/ratings", "Blog ratings"),
            ("blog/likes", "Blog likes"),
        ],
    },
    {
        "key": "comments",
        "label": "Comments",
        "items": [
            ("comments", "All comments"),
        ],
    },
    {
        "key": "translations",
        "label": "Translations",
        "items": [
            ("translations/ui", "UI Translations"),
            ("translations/pages", "Page Translations"),
            ("translations/missing", "Missing Translations"),
            ("translations/import-export", "Import / Export"),
            ("translations/qa", "Translation QA"),
        ],
    },
    {
        "key": "pages",
        "label": "Pages / SEO",
        "items": [
            ("landing-pages", "Landing Pages"),
            ("pages/home", "Home Pages"),
            ("pages/cities", "City Pages"),
            ("pages/countries", "Country Pages"),
            ("pages/places", "Place Pages"),
            ("pages/technical", "Technical Pages"),
            ("redirects", "Redirects"),
            ("seo/audit", "SEO Audit Dashboard"),
        ],
    },
    {
        "key": "audio",
        "label": "Audio",
        "items": [
            ("audio/files", "Audio files"),
            ("audio/queue", "Audio generation queue"),
            ("audio/failed", "Audio failed"),
            ("audio/outdated", "Audio outdated"),
            ("audio/voices", "Voice settings"),
        ],
    },
    {
        "key": "media",
        "label": "Media",
        "items": [
            ("media/images", "Images"),
            ("media/galleries", "Galleries"),
            ("media/files", "Files"),
        ],
    },
    {
        "key": "subscriptions",
        "label": "Subscription",
        "items": [
            ("subscriptions/forms", "Subscription forms"),
            ("subscriptions/subscribers", "Subscribers"),
            ("subscriptions/export", "Export subscribers"),
        ],
    },
    {
        "key": "contacts",
        "label": "Contacts",
        "items": [
            ("contacts/messages", "Contact messages"),
        ],
    },
    {
        "key": "admins",
        "label": "Users",
        "items": [
            ("admins/users", "Users"),
            ("admins/roles", "Roles / permissions"),
            ("admins/login-history", "Login history"),
        ],
    },
    {
        "key": "settings",
        "label": "Site settings",
        "items": [
            ("settings/general", "General settings"),
            ("settings/languages", "Languages"),
            ("robots", "Robots.txt"),
            ("sitemap", "Sitemap"),
            ("schema", "Schema settings"),
            ("settings/analytics", "Analytics settings"),
        ],
    },
    {
        "key": "logs",
        "label": "Logs",
        "items": [
            ("logs/actions", "Admin actions"),
            ("logs/audio", "Audio generation logs"),
            ("logs/seo", "SEO changes"),
            ("logs/errors", "Errors"),
        ],
    },
]
ADMIN_CMS_NAV = [("dashboard", "Dashboard", "/admin")]
for _group in ADMIN_CMS_GROUPS:
    for _path, _label in _group["items"]:
        ADMIN_CMS_NAV.append((_path, _label, f"/admin/{_path}"))


def admin_nav_items(active: str) -> List[Dict[str, Any]]:
    return [{"key": key, "label": label, "url": url, "active": key == active} for key, label, url in ADMIN_CMS_NAV]


def admin_group_nav(active: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    active_root = str(active or "dashboard").split("/", 1)[0]
    for group in ADMIN_CMS_GROUPS:
        items = []
        for path, label in group.get("items") or []:
            items.append({"key": path, "label": label, "url": f"/admin/{path}", "active": path == active})
        out.append({
            "key": group["key"],
            "label": group["label"],
            "active": group["key"] == active_root,
            "items": items,
        })
    return out


def admin_audio_manifest_records(limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    root = AUDIO_STORAGE_PATH / AUDIO_BUILD_AUDIO_VERSION
    if not root.exists():
        return rows
    manifests: List[Path] = []
    for idx, manifest in enumerate(root.glob("**/manifest.json")):
        manifests.append(manifest)
        if idx >= max(limit * 4, 250):
            break
    for manifest in sorted(manifests, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        parts = manifest.relative_to(root).parts
        if len(parts) < 5:
            continue
        lang, gender, country_slug, city_slug = parts[0], parts[1], parts[2], parts[3]
        place_slug = parts[4] if len(parts) > 5 else ""
        summary = read_audio_manifest_summary(manifest)
        audio_files = list(manifest.parent.glob("*.mp3")) + list(manifest.parent.glob("*.wav")) + list(manifest.parent.glob("*.m4a"))
        size = sum((p.stat().st_size for p in audio_files if p.exists()), 0)
        rows.append(
            {
                "entity": "place" if place_slug else "city",
                "name": place_slug or city_slug,
                "country": country_slug,
                "city": city_slug,
                "place": place_slug,
                "language": lang.upper(),
                "voice": gender,
                "status": "Ready" if summary else "Invalid",
                "sections": str((summary or {}).get("sections") or 0),
                "failed": str((summary or {}).get("failed") or 0),
                "size": human_file_size(size),
                "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(manifest.stat().st_mtime)),
                "path": str(manifest.relative_to(ROOT)),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def human_file_size(num: int) -> str:
    value = float(num or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{int(num)} B"


def admin_audio_totals() -> Dict[str, Any]:
    cached = getattr(g, "_admin_audio_totals", None) if has_request_context() else None
    if isinstance(cached, dict):
        return cached
    root = AUDIO_STORAGE_PATH / AUDIO_BUILD_AUDIO_VERSION
    manifest_paths: List[Path] = []
    total_size = 0
    file_count = 0
    if root.exists():
        for idx, manifest in enumerate(root.glob("**/manifest.json")):
            manifest_paths.append(manifest)
            if idx >= 2000:
                break
        for ext in ("*.mp3", "*.wav", "*.m4a"):
            for path in root.glob(f"**/{ext}"):
                try:
                    total_size += path.stat().st_size
                    file_count += 1
                    if file_count >= 5000:
                        break
                except Exception:
                    continue
            if file_count >= 5000:
                break
    failed = 0
    for manifest in manifest_paths[:300]:
        summary = read_audio_manifest_summary(manifest)
        if summary:
            failed += int(summary.get("failed") or 0)
    cached = {
        "manifests": len(manifest_paths),
        "files": f"{file_count}+" if file_count >= 5000 else file_count,
        "storage": human_file_size(total_size) + ("+" if file_count >= 5000 else ""),
        "ready": len(manifest_paths),
        "failed": failed,
    }
    if has_request_context():
        g._admin_audio_totals = cached
    return cached


def admin_site_totals() -> Dict[str, Any]:
    cached = getattr(g, "_admin_site_totals", None) if has_request_context() else None
    if isinstance(cached, dict):
        return cached
    countries = target_countries()
    city_count = sum(len(target_country_cities(str(c.get("slug") or ""))) for c in countries)
    place_count = sum(
        len(target_places_for_city(str(c.get("slug") or ""), str(city.get("citySlug") or "")))
        for c in countries
        for city in target_country_cities(str(c.get("slug") or ""))
    )
    blog_posts = load_blog_posts(include_drafts=True)
    audio = admin_audio_totals()
    sitemap_count = 1 + len(countries) * len(LANG_ORDER) + city_count * len(LANG_ORDER) + place_count * len(LANG_ORDER) + sum(1 for p in blog_posts if p.get("status") == "published")
    cached = {
        "pages": 1 + len(countries) * len(LANG_ORDER) + city_count * len(LANG_ORDER) + place_count * len(LANG_ORDER) + len(blog_posts),
        "published": 1 + len(countries) * len(LANG_ORDER) + city_count * len(LANG_ORDER) + place_count * len(LANG_ORDER) + sum(1 for p in blog_posts if p.get("status") == "published"),
        "drafts": sum(1 for p in blog_posts if p.get("status") != "published"),
        "countries": len(countries),
        "cities": city_count,
        "places": place_count,
        "blogPosts": len(blog_posts),
        "audioFiles": audio["files"],
        "audioReady": audio["ready"],
        "audioFailed": audio["failed"],
        "audioStorage": audio["storage"],
        "sitemapUrls": sitemap_count,
        "seoIssues": admin_seo_issue_count(),
        "redirects": len(load_admin_redirects()),
        "langs": len(LANG_ORDER),
    }
    if has_request_context():
        g._admin_site_totals = cached
    return cached


def admin_page_public_url(row: Dict[str, Any]) -> str:
    kind = row.get("type")
    lang = normalize_lang(str(row.get("language") or DEFAULT_LANG).lower())
    if kind == "country":
        return country_url(lang, str(row.get("country") or ""))
    if kind == "city":
        return city_url(lang, str(row.get("country") or ""), str(row.get("city") or ""))
    if kind == "place":
        return place_url(lang, str(row.get("country") or ""), str(row.get("city") or ""), str(row.get("place") or ""))
    if kind == "blog":
        slug = str(row.get("slug") or "")
        return f"/blog/{slug}" if lang == "en" else f"/{lang}/blog/{slug}"
    if kind == "static":
        slug = str(row.get("slug") or row.get("place") or "")
        return f"/pages/{slug}" if lang == "en" else f"/{lang}/pages/{slug}"
    if kind == "landing":
        slug = str(row.get("slug") or row.get("place") or "")
        return f"/landing/{slug}" if lang == "en" else f"/{lang}/landing/{slug}"
    return landing_url(lang)


def admin_page_public_url_from_key(page_key: str, lang: str, *, fallback_slug: str = "") -> str:
    parts = split_admin_page_key(page_key)
    kind = parts.get("type") or "home"
    if kind == "country":
        return country_url(lang, parts.get("country") or fallback_slug)
    if kind == "city":
        return city_url(lang, parts.get("country") or "", parts.get("city") or fallback_slug)
    if kind == "place":
        return place_url(lang, parts.get("country") or "", parts.get("city") or "", parts.get("place") or fallback_slug)
    if kind == "blog":
        slug = parts.get("blog") or fallback_slug
        return f"/blog/{slug}" if normalize_lang(lang) == "en" else f"/{normalize_lang(lang)}/blog/{slug}"
    if kind in {"landing", "static", "custom"}:
        slug = parts.get("blog") or parts.get("place") or fallback_slug
        prefix = "landing" if kind == "landing" else "pages"
        return f"/{prefix}/{slug}" if normalize_lang(lang) == "en" else f"/{normalize_lang(lang)}/{prefix}/{slug}"
    return landing_url(lang)


def admin_page_key_for_record(row: Dict[str, Any]) -> str:
    return admin_page_key(
        str(row.get("type") or "home"),
        country_slug=str(row.get("country") or ""),
        city_slug=str(row.get("city") or ""),
        place_slug=str(row.get("place") or ""),
        blog_slug=str(row.get("slug") or ""),
    )


def admin_page_content_status_for_record(row: Dict[str, Any]) -> Dict[str, str]:
    content = load_admin_page_content(admin_page_key_for_record(row), normalize_lang(str(row.get("language") or DEFAULT_LANG)))
    seo_plain = html_to_plain_text(content.get("seoTextHtml") or "", 1000)
    faq_items = content.get("visibleFaq") or []
    return {
        "seoText": "Ready" if content.get("seoTextEnabled") and seo_plain else "Missing",
        "faqStatus": f"{len(faq_items)} items" if content.get("faqEnabled") and faq_items else "Missing",
    }


def admin_page_records(
    limit: int = 240,
    *,
    page_type: str = "",
    lang: str = "",
    q: str = "",
    include_audio: bool = True,
    include_content_status: bool = True,
) -> List[Dict[str, Any]]:
    q_lc = q.strip().lower()
    lang_filter = normalize_lang(lang) if lang else ""
    type_filter = str(page_type or "").strip().lower()
    rows: List[Dict[str, Any]] = []

    def add(row: Dict[str, Any]) -> None:
        if len(rows) >= limit:
            return
        if type_filter and row.get("type") != type_filter:
            return
        if lang_filter and row.get("language") != lang_filter:
            return
        hay = " ".join(str(row.get(k) or "") for k in ("title", "url", "type", "language", "country", "city", "place", "slug")).lower()
        if q_lc and q_lc not in hay:
            return
        row["url"] = admin_page_public_url(row)
        row["indexing"] = "Index"
        row["seo"] = "OK" if row.get("title") and row.get("description") else "Issue"
        if include_content_status:
            row.update(admin_page_content_status_for_record(row))
        rows.append(row)

    langs = [lang_filter] if lang_filter else LANG_ORDER
    if not type_filter or type_filter == "home":
        for lang_slug in langs:
            add({"title": "Home", "type": "home", "language": lang_slug, "status": "Published", "description": "Landing page"})
    for country in target_countries():
        cslug = str(country.get("slug") or "")
        if not cslug:
            continue
        if not type_filter or type_filter == "country":
            for lang_slug in langs:
                add({
                    "title": country_display_name_cached_for_lang(country, lang_slug),
                    "type": "country",
                    "language": lang_slug,
                    "country": cslug,
                    "status": "Published",
                    "description": "Country audio guide",
                })
                if len(rows) >= limit:
                    return rows
        if type_filter and type_filter not in {"city", "place"}:
            continue
        for city in target_country_cities(cslug):
            city_slug = str(city.get("citySlug") or "")
            if not city_slug:
                continue
            if not type_filter or type_filter == "city":
                for lang_slug in langs:
                    add({
                        "title": city_display_name_cached_for_lang(city, lang_slug),
                        "type": "city",
                        "language": lang_slug,
                        "country": cslug,
                        "city": city_slug,
                        "status": "Published",
                        "description": "City audio guide",
                        "audio": audio_target_summary(country_slug=cslug, city_slug=city_slug).get("status", "missing") if include_audio else "",
                    })
                    if len(rows) >= limit:
                        return rows
            if type_filter and type_filter != "place":
                continue
            for place in target_places_for_city(cslug, city_slug):
                if len(rows) >= limit:
                    return rows
                place_slug = str(place.get("slug") or "")
                if not place_slug:
                    continue
                for lang_slug in langs:
                    add({
                        "title": clean_plain_text(place.get("name") or place.get("title") or place_slug, 180),
                        "type": "place",
                        "language": lang_slug,
                        "country": cslug,
                        "city": city_slug,
                        "place": place_slug,
                        "status": "Published",
                        "description": "Place audio guide",
                        "audio": audio_target_summary(country_slug=cslug, city_slug=city_slug, place_slug=place_slug).get("status", "missing") if include_audio else "",
                    })
                    if len(rows) >= limit:
                        return rows
    if not type_filter or type_filter == "blog":
        for post in load_blog_posts(include_drafts=True):
            add({
                "title": str(post.get("title") or ""),
                "type": "blog",
                "language": normalize_lang(str(post.get("lang") or DEFAULT_LANG)),
                "slug": str(post.get("slug") or ""),
                "status": str(post.get("status") or "draft").title(),
                "description": str(post.get("metaDescription") or post.get("excerpt") or ""),
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_page_records_total(*, page_type: str = "", lang: str = "", q: str = "") -> int:
    q_lc = str(q or "").strip().lower()
    lang_filter = normalize_lang(lang) if lang else ""
    type_filter = str(page_type or "").strip().lower()
    langs = [lang_filter] if lang_filter else LANG_ORDER
    countries = target_countries()
    if not q_lc:
        total = 0
        if not type_filter or type_filter == "home":
            total += len(langs)
        if not type_filter or type_filter == "country":
            total += len(countries) * len(langs)
        if not type_filter or type_filter == "city":
            total += sum(len(target_country_cities(str(c.get("slug") or ""))) for c in countries) * len(langs)
        if not type_filter or type_filter == "place":
            total += sum(
                len(target_places_for_city(str(c.get("slug") or ""), str(city.get("citySlug") or "")))
                for c in countries
                for city in target_country_cities(str(c.get("slug") or ""))
            ) * len(langs)
        if not type_filter or type_filter == "blog":
            total += sum(
                1
                for post in load_blog_posts(include_drafts=True)
                if (not lang_filter or normalize_lang(str(post.get("lang") or DEFAULT_LANG)) == lang_filter)
            )
        return total
    return len(admin_page_records(limit=1000000, page_type=type_filter, lang=lang_filter, q=q_lc, include_audio=False, include_content_status=False))


def admin_landing_page_records(limit: int = 240) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def add(row: Dict[str, Any]) -> None:
        if len(rows) >= limit:
            return
        row["url"] = admin_page_public_url(row)
        row["indexing"] = "Index"
        row["seo"] = "OK" if row.get("title") and row.get("description") else "Issue"
        row.update(admin_page_content_status_for_record(row))
        rows.append(row)

    for lang_slug in LANG_ORDER:
        add({"title": "Home", "type": "home", "language": lang_slug, "status": "Published", "description": "Landing page"})
        if len(rows) >= limit:
            return rows
    for country in COUNTRIES:
        if (country.get("code") or "").lower() in EXCLUDED_COUNTRY_CODES:
            continue
        cslug = str(country.get("slug") or "")
        if not cslug:
            continue
        for lang_slug in LANG_ORDER:
            add({
                "title": country_display_name_cached_for_lang(country, lang_slug),
                "type": "country",
                "language": lang_slug,
                "country": cslug,
                "status": "Published",
                "description": f"{country_display_name_cached_for_lang(country, lang_slug)} audio guide landing page",
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_landing_page_records_total() -> int:
    countries = [c for c in COUNTRIES if (c.get("code") or "").lower() not in EXCLUDED_COUNTRY_CODES]
    return (1 + len(countries)) * len(LANG_ORDER)


def admin_country_records() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for country in COUNTRIES:
        if (country.get("code") or "").lower() in EXCLUDED_COUNTRY_CODES:
            continue
        slug = str(country.get("slug") or "")
        cities = target_country_cities(slug)
        place_count = sum(len(dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((slug, str(c.get("citySlug") or "")), []))) for c in cities)
        rows.append({
            "name": country_display_name_cached_for_lang(country, "en"),
            "slug": slug,
            "iso": str(country.get("code") or "").upper(),
            "languages": ", ".join(LANG_ORDER).upper(),
            "cities": str(len(cities)),
            "places": str(place_count),
            "seo": "OK",
            "sitemap": "Included",
            "url": country_url("en", slug),
        })
    return sorted(rows, key=lambda r: r["name"])


def admin_city_records(limit: int = 500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for country in COUNTRIES:
        if (country.get("code") or "").lower() in EXCLUDED_COUNTRY_CODES:
            continue
        cslug = str(country.get("slug") or "")
        for city in target_country_cities(cslug):
            city_slug = str(city.get("citySlug") or "")
            if not city_slug:
                continue
            audio = audio_target_summary(country_slug=cslug, city_slug=city_slug)
            rows.append({
                "name": city_display_name_cached_for_lang(city, "en"),
                "country": country_display_name_cached_for_lang(country, "en"),
                "slug": city_slug,
                "population": f"{int(city.get('population') or 0):,}",
                "coordinates": f"{float(city.get('lat') or 0):.4f}, {float(city.get('lon') or 0):.4f}",
                "places": str(len(dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((cslug, city_slug), [])))),
                "audio": str(audio.get("status") or "missing"),
                "seo": "OK",
                "sitemap": "Included",
                "url": city_url("en", cslug, city_slug),
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_place_records(limit: int = 800) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for (country_slug, city_slug), places in CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.items():
        country = COUNTRY_BY_SLUG.get(country_slug)
        city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {"name": city_slug}
        for place in dedupe_places(places)[:TARGET_PLACES_PER_CITY]:
            place_slug = str(place.get("slug") or "")
            if not place_slug:
                continue
            audio = audio_target_summary(country_slug=country_slug, city_slug=city_slug, place_slug=place_slug)
            rows.append({
                "name": place_display_name_cached_for_lang(place, "en"),
                "city": city_display_name_cached_for_lang(city, "en"),
                "country": country_display_name_cached_for_lang(country, "en") if country else country_slug,
                "category": str(place.get("category") or "Landmark"),
                "coordinates": f"{float(place.get('lat') or 0):.4f}, {float(place.get('lon') or 0):.4f}" if place.get("lat") and place.get("lon") else "No coordinates",
                "image": "Yes" if place.get("image") or place.get("imageUrl") else "Fallback",
                "audio": str(audio.get("status") or "missing"),
                "seo": "OK",
                "url": place_url("en", country_slug, city_slug, place_slug),
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_sitemap_records(limit: int = 500) -> Dict[str, Any]:
    rows = admin_page_records(limit=limit)
    return {"rows": rows, "total": admin_site_totals()["sitemapUrls"], "lastGenerated": utc_now_iso()}


def admin_seo_issue_count() -> int:
    issues = 0
    for post in load_blog_posts(include_drafts=True):
        if not post.get("metaTitle") or not post.get("metaDescription"):
            issues += 1
    return issues


def admin_media_records(limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    roots = [ROOT / "static" / "img", BLOG_UPLOAD_DIR, MEDIA_UPLOAD_DIR]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("**/*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
            if not path.is_file() or path.name.startswith("."):
                continue
            ext = path.suffix.lower().lstrip(".")
            if ext not in {"png", "jpg", "jpeg", "webp", "svg", "gif", "mp3", "wav", "m4a"}:
                continue
            rows.append({
                "filename": path.name,
                "type": "audio" if ext in {"mp3", "wav", "m4a"} else "image",
                "size": human_file_size(path.stat().st_size),
                "path": str(path.relative_to(ROOT)),
                "alt": "Needs alt" if ext in {"png", "jpg", "jpeg", "webp"} else "—",
                "used": "Check pages",
                "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_media_records_total() -> int:
    total = 0
    roots = [ROOT / "static" / "img", BLOG_UPLOAD_DIR, MEDIA_UPLOAD_DIR]
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/*"):
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower().lstrip(".") in {"png", "jpg", "jpeg", "webp", "svg", "gif", "mp3", "wav", "m4a"}:
                total += 1
    return total


def admin_schema_rows() -> List[Dict[str, Any]]:
    return [
        {"pageType": "Home", "schema": "WebSite", "status": "Active", "required": "name, url, inLanguage"},
        {"pageType": "Country", "schema": "Country / WebPage", "status": "Active", "required": "name, url, inLanguage"},
        {"pageType": "City", "schema": "City", "status": "Active", "required": "name, url, inLanguage"},
        {"pageType": "Place", "schema": "TouristAttraction", "status": "Active", "required": "name, url, inLanguage"},
        {"pageType": "Blog", "schema": "BlogPosting", "status": "Active", "required": "headline, image, datePublished"},
        {"pageType": "FAQ", "schema": "FAQPage", "status": "Conditional", "required": "questions, acceptedAnswer"},
    ]


def admin_internal_link_rows(limit: int = 300) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for country in COUNTRIES:
        cslug = str(country.get("slug") or "")
        if not cslug or (country.get("code") or "").lower() in EXCLUDED_COUNTRY_CODES:
            continue
        for city in target_country_cities(cslug)[:3]:
            city_slug = str(city.get("citySlug") or "")
            if not city_slug:
                continue
            rows.append({"source": country_url("en", cslug), "target": city_url("en", cslug, city_slug), "anchor": city_display_name_cached_for_lang(city, "en"), "type": "country_to_city", "status": "OK"})
            for place in dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((cslug, city_slug), []))[:3]:
                pslug = str(place.get("slug") or "")
                if pslug:
                    rows.append({"source": city_url("en", cslug, city_slug), "target": place_url("en", cslug, city_slug, pslug), "anchor": place_display_name_cached_for_lang(place, "en"), "type": "city_to_place", "status": "OK"})
            if len(rows) >= limit:
                return rows
    return rows


def admin_internal_link_rows_total() -> int:
    return len(admin_internal_link_rows(limit=1000000))


def admin_language_rows() -> List[Dict[str, Any]]:
    manifests = admin_audio_manifest_records(limit=10000)
    by_lang = Counter(str(row.get("language") or "").lower() for row in manifests)
    return [
        {
            "language": SUPPORTED_LANGS[lang]["label"],
            "code": lang,
            "hreflang": HREFLANG_CODE_BY_LANG.get(lang, lang),
            "enabled": "Yes",
            "fallback": "English" if lang != DEFAULT_LANG else "Default",
            "audio": str(by_lang.get(lang, 0)),
            "missingTranslations": "Review",
        }
        for lang in LANG_ORDER
    ]


def admin_problem_rows() -> List[Dict[str, Any]]:
    totals = admin_site_totals()
    return [
        {"problem": "Missing or draft meta fields", "count": str(totals["seoIssues"]), "manager": "/admin/seo"},
        {"problem": "Failed audio sections", "count": str(totals["audioFailed"]), "manager": "/admin/audio"},
        {"problem": "Redirect rules configured", "count": str(totals["redirects"]), "manager": "/admin/redirects"},
        {"problem": "Robots.txt managed file", "count": "1" if ADMIN_ROBOTS_PATH.exists() else "Default", "manager": "/admin/robots"},
    ]


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if is_admin_authorized() and request.method == "GET":
        return redirect(request.args.get("next") or url_for("admin_dashboard"), code=302)

    error = ""
    if request.method == "POST":
        email = str(request.form.get("email") or "").strip().lower()
        password = str(request.form.get("password") or "")
        if secrets.compare_digest(email, ADMIN_EMAIL) and admin_password_is_valid(password):
            session.clear()
            session["admin_email"] = ADMIN_EMAIL
            session["admin_login_at"] = int(time.time())
            rows = cms_collection_rows("loginHistory")
            rows.insert(0, {"id": secrets.token_hex(8), "email": ADMIN_EMAIL, "status": "success", "ip": get_client_ip(), "createdAt": utc_now_iso()})
            save_cms_collection_rows("loginHistory", rows[:1000])
            target = request.form.get("next") or url_for("admin_dashboard")
            if not str(target).startswith("/") or str(target).startswith("//"):
                target = url_for("admin_dashboard")
            return redirect(target, code=302)
        rows = cms_collection_rows("loginHistory")
        rows.insert(0, {"id": secrets.token_hex(8), "email": email, "status": "failed", "ip": get_client_ip(), "createdAt": utc_now_iso()})
        save_cms_collection_rows("loginHistory", rows[:1000])
        error = "Email or password is incorrect."

    return render_template(
        "admin_login.html",
        error=error,
        next_url=request.args.get("next") or request.form.get("next") or url_for("admin_dashboard"),
        seo_title=f"Admin login | {BRAND_NAME}",
        seo_desc="Secure admin login for SonicCity.",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        seo_schema={
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": f"Admin login | {BRAND_NAME}",
            "url": absolute_url("/admin/login"),
        },
        T=t(DEFAULT_LANG),
        body_class="PageAdmin PageAdminLogin",
        use_leaflet=False,
    )


@app.post("/admin/logout")
def admin_logout():
    session.pop("admin_email", None)
    session.pop("admin_login_at", None)
    return redirect(url_for("admin_login"), code=302)


def redirect_localized_admin(admin_tail: str = "") -> Response:
    path = "/admin"
    if admin_tail:
        path = f"{path}/{admin_tail.strip('/')}"
    if request.query_string:
        path = f"{path}?{request.query_string.decode('utf-8', 'ignore')}"
    return redirect(path, code=307 if request.method != "GET" else 302)


@app.route("/<re('en|fr|es|it|ua|uk|de'):lang>/admin", methods=["GET", "POST"])
def localized_admin_root(lang: str):
    return redirect_localized_admin()


@app.route("/<re('en|fr|es|it|ua|uk|de'):lang>/admin/<path:admin_tail>", methods=["GET", "POST"])
def localized_admin_path(lang: str, admin_tail: str):
    return redirect_localized_admin(admin_tail)


def admin_quick_page_options(lang: str, limit: int = 80) -> List[Dict[str, str]]:
    lang = normalize_lang(lang)
    options = [{"key": "home", "label": "Home page", "type": "home"}]
    for country in COUNTRIES:
        code = str(country.get("code") or "").lower()
        if code in EXCLUDED_COUNTRY_CODES:
            continue
        cslug = str(country.get("slug") or "")
        if not cslug:
            continue
        options.append({
            "key": admin_page_key("country", country_slug=cslug),
            "label": f"Country: {country_display_name_cached_for_lang(country, lang)}",
            "type": "country",
        })
        if len(options) >= limit:
            return options
    for country_slug, cities in INDEXED_CITIES_BY_COUNTRYSLUG.items():
        country = COUNTRY_BY_SLUG.get(country_slug)
        for city in cities[:TARGET_CITIES_PER_COUNTRY]:
            cslug = str(city.get("citySlug") or "")
            if not cslug:
                continue
            options.append({
                "key": admin_page_key("city", country_slug=country_slug, city_slug=cslug),
                "label": f"City: {city_display_name_cached_for_lang(city, lang)} · {country_display_name_cached_for_lang(country, lang) if country else country_slug}",
                "type": "city",
            })
            if len(options) >= limit:
                return options
    return options


@app.route("/admin/pages", methods=["GET", "POST"])
def admin_pages():
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp

    if request.method == "POST":
        lang = normalize_lang(request.form.get("lang") or DEFAULT_LANG)
        page_type = str(request.form.get("page_type") or "home").strip().lower()
        page_key = admin_page_key(
            page_type,
            country_slug=str(request.form.get("country_slug") or "").strip().lower(),
            city_slug=str(request.form.get("city_slug") or "").strip().lower(),
            place_slug=str(request.form.get("place_slug") or "").strip().lower(),
            blog_slug=str(request.form.get("blog_slug") or "").strip().lower(),
        )
        faq = normalize_faq_rows(
            request.form.getlist("faq_question"),
            request.form.getlist("faq_answer"),
            request.form.getlist("faq_visible") if "faq_visible" in request.form else None,
            request.form.getlist("faq_order"),
        )
        h1_value = request.form.get("page_h1") or ""
        slug_value = request.form.get("content_slug") or ""
        seo_mode = str(request.form.get("seo_editor_mode") or "markdown").strip().lower()
        seo_markdown = request.form.get("seo_text_markdown") or ""
        seo_html = request.form.get("seo_text_html_raw") or ""
        seo_html_for_validation = render_safe_html(seo_html) if seo_mode == "html" else render_safe_markdown(seo_markdown)
        seo_enabled = checkbox_enabled(request.form.get("seo_text_enabled")) if "seo_text_enabled" in request.form else bool(html_to_plain_text(seo_html_for_validation))
        faq_enabled = checkbox_enabled(request.form.get("faq_enabled")) if "faq_enabled" in request.form else bool(faq)
        seo_title = request.form.get("seo_text_title") or (h1_value or "Audio guide notes" if seo_enabled else "")
        validation_errors = admin_validate_page_content(
            page_key,
            lang,
            h1=h1_value,
            slug=slug_value,
            seo_enabled=seo_enabled,
            seo_title=seo_title,
            seo_html=seo_html_for_validation,
            faq_enabled=faq_enabled,
            faq_rows=faq,
        )
        if validation_errors:
            q = urllib.parse.urlencode({"lang": lang, "pageKey": page_key, "msg": " ".join(validation_errors), "kind": "error"})
            return redirect(f"/admin/pages?{q}", code=302)
        save_admin_page_content(
            page_key,
            lang,
            seo_markdown,
            faq,
            seo_editor_mode=seo_mode,
            seo_text_html_raw=seo_html,
            h1=h1_value,
            slug=slug_value,
            seo_enabled=seo_enabled,
            seo_title=seo_title,
            seo_intro=request.form.get("seo_text_intro") or "",
            seo_display_mode=request.form.get("seo_display_mode") or "full",
            faq_enabled=faq_enabled,
            faq_title=request.form.get("faq_title") or "Questions before you listen",
            slug_manually_edited=checkbox_enabled(request.form.get("slug_manually_edited")),
            status=request.form.get("status") or "published",
            meta_title=request.form.get("meta_title") or "",
            meta_description=request.form.get("meta_description") or "",
            canonical_mode=request.form.get("canonical_mode") or "self",
            canonical_url=request.form.get("canonical_url") or "",
            robots_index=checkbox_enabled(request.form.get("robots_index")) if "robots_index" in request.form else True,
            robots_follow=checkbox_enabled(request.form.get("robots_follow")) if "robots_follow" in request.form else True,
            og_title=request.form.get("og_title") or "",
            og_description=request.form.get("og_description") or "",
            og_image=request.form.get("og_image") or "",
            twitter_title=request.form.get("twitter_title") or "",
            twitter_description=request.form.get("twitter_description") or "",
            twitter_image=request.form.get("twitter_image") or "",
            schema_json=request.form.get("schema_json") or "",
            redirect_enabled=checkbox_enabled(request.form.get("redirect_enabled")),
            redirect_type=request.form.get("redirect_type") or "301",
            redirect_target=request.form.get("redirect_target") or "",
            redirect_notes=request.form.get("redirect_notes") or "",
            sitemap_included=checkbox_enabled(request.form.get("sitemap_included")) if "sitemap_included" in request.form else True,
            comments_enabled=checkbox_enabled(request.form.get("comments_enabled")) if "comments_enabled" in request.form else True,
        )
        admin_revision_log("page_content_saved", "page", page_key, details={"lang": lang, "faq": len(faq), "seoEnabled": seo_enabled})
        q = urllib.parse.urlencode({"lang": lang, "pageKey": page_key, "msg": "SEO text and FAQ saved.", "kind": "success"})
        return redirect(f"/admin/pages?{q}", code=302)

    if request.args.get("pageKey") or request.args.get("edit"):
        params = request.args.to_dict(flat=True)
        params.setdefault("lang", normalize_lang(params.get("lang") or DEFAULT_LANG))
        return redirect(f"/admin/pages/edit?{urllib.parse.urlencode(params)}", code=302)
    return admin_cms_section_response("pages/all")


def blog_sidebar_context(lang: str, posts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    posts = posts if posts is not None else load_blog_posts(lang=lang)
    tag_counter: Counter = Counter()
    for post in posts:
        for tag in post.get("tags") or []:
            tag_counter[tag] += 1
    return {
        "popular_posts": posts[:5],
        "categories": blog_categories(posts),
        "tags": [{"name": name, "count": count, "slug": slugify(name)} for name, count in tag_counter.most_common(18)],
    }


@app.get("/blog")
def blog_index_en():
    return blog_index(DEFAULT_LANG)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/blog")
def blog_index(lang: str):
    lang = normalize_lang(lang)
    q = clean_plain_text(request.args.get("q") or "", 120)
    category = clean_plain_text(request.args.get("category") or "", 80).lower()
    tag = clean_plain_text(request.args.get("tag") or "", 80).lower()
    posts = load_blog_posts(lang=lang)
    filtered = []
    for post in posts:
        hay = " ".join(
            [
                str(post.get("title") or ""),
                str(post.get("excerpt") or ""),
                str(post.get("category") or ""),
                " ".join(post.get("tags") or []),
            ]
        ).lower()
        if q and q.lower() not in hay:
            continue
        if category and slugify(post.get("category") or "") != category:
            continue
        if tag and tag not in {slugify(x) for x in post.get("tags") or []}:
            continue
        filtered.append(post)
    sidebar = blog_sidebar_context(lang, posts)
    seo_title = f"Free Travel Audio Guide Blog | {BRAND_NAME}"
    seo_desc = "Read travel audio guide tips, city stories and landmark ideas for planning free self-guided trips across Europe."
    page_url = blog_index_url(lang)
    admin_content = admin_content_for_public(admin_page_key("blog", blog_slug="index"), lang)
    post_schema_items = [
        {"name": post.get("title") or "", "url": blog_post_url(post)}
        for post in filtered[:24]
        if post.get("slug")
    ]
    blog_schema = schema_graph(
        page_type="CollectionPage",
        lang=lang,
        page_url=page_url,
        title=seo_title,
        description=seo_desc,
        image_url="/static/img/place-placeholder.svg",
        breadcrumbs=[("Home", landing_url(lang)), ("Blog", page_url)],
        faq_schema=admin_content.get("faqSchema"),
        main_entity={
            "@type": "Blog",
            "@id": f"{schema_abs_url(page_url)}#main-entity",
            "name": f"{BRAND_NAME} Blog",
            "url": schema_abs_url(page_url),
        },
        item_lists=[schema_item_list_node("SonicCity blog posts", page_url, "posts", post_schema_items)],
    )
    return render_template(
        "blog_index.html",
        lang=lang,
        posts=filtered,
        all_posts=posts,
        sidebar=sidebar,
        query=q,
        active_category=category,
        active_tag=tag,
        admin_content=admin_content,
        schema_in_graph=True,
        seo_title=seo_title,
        seo_desc=seo_desc,
        seo_keywords="audio guide blog, travel audio guide, city guide tips, free audio guide",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        seo_schema=blog_schema,
        T=t(lang),
        body_class="PageBlog",
        use_leaflet=False,
    )


@app.get("/blog/<slug>")
def blog_detail_en(slug: str):
    return blog_detail(DEFAULT_LANG, slug)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/blog/<slug>")
def blog_detail(lang: str, slug: str):
    lang = normalize_lang(lang)
    post = find_blog_post(slug, lang=lang)
    if not post:
        abort(404)
    posts = load_blog_posts(lang=lang)
    idx = next((i for i, row in enumerate(posts) if row.get("id") == post.get("id")), -1)
    prev_post = posts[idx + 1] if idx >= 0 and idx + 1 < len(posts) else None
    next_post = posts[idx - 1] if idx > 0 else None
    sidebar = blog_sidebar_context(lang, posts)
    blog_stats = admin_blog_engagement_stats(str(post.get("id") or ""))
    page_key = admin_page_key("blog", blog_slug=str(post.get("slug") or ""))
    admin_content = admin_content_for_public(page_key, lang)
    page_url = blog_post_url(post)
    comments_context = public_comments_context(
        "blog_article",
        str(post.get("id") or ""),
        str(post.get("title") or slug),
        page_url,
        lang,
        admin_content,
        default_enabled=True,
    )
    approved_comments = comments_context.get("approved") or []
    blog_entity: Dict[str, Any] = {
        "@type": post.get("schemaType") or "BlogPosting",
        "@id": f"{schema_abs_url(page_url)}#main-entity",
        "headline": post.get("title") or "",
        "name": post.get("title") or "",
        "description": post.get("metaDescription") or post.get("excerpt") or "",
        "url": schema_abs_url(page_url),
        "inLanguage": schema_lang(lang),
        "datePublished": post.get("publishedAt") or post.get("updatedAt") or "",
        "dateModified": post.get("updatedAt") or post.get("publishedAt") or "",
        "author": {"@type": "Organization", "name": BRAND_NAME},
        "publisher": {"@id": absolute_url("/#organization")},
        "mainEntityOfPage": {"@id": f"{schema_abs_url(page_url)}#webpage"},
    }
    if post.get("heroImage"):
        blog_entity["image"] = schema_abs_url(str(post["heroImage"]))
    if approved_comments:
        blog_entity["commentCount"] = len(approved_comments)
    comment_nodes = [
        {
            "@type": "Comment",
            "@id": f"{schema_abs_url(page_url)}#comment-{idx}",
            "text": clean_plain_text(row.get("commentText") or "", 500),
            "author": {"@type": "Person", "name": clean_plain_text(row.get("authorName") or "Reader", 100)},
            "dateCreated": row.get("createdAt") or "",
        }
        for idx, row in enumerate(approved_comments[:10], 1)
    ]
    schema = schema_graph(
        page_type="WebPage",
        lang=lang,
        page_url=page_url,
        title=post.get("title") or "",
        description=post.get("metaDescription") or post.get("excerpt") or "",
        image_url=post.get("heroImage") or "/static/img/place-placeholder.svg",
        breadcrumbs=[("Home", landing_url(lang)), ("Blog", blog_index_url(lang)), (post.get("title") or "", page_url)],
        faq_schema=admin_content.get("faqSchema"),
        main_entity=blog_entity,
        rating_stats=blog_stats,
        extra_nodes=comment_nodes,
    )
    return render_template(
        "blog_detail.html",
        lang=lang,
        post=post,
        prev_post=prev_post,
        next_post=next_post,
        sidebar=sidebar,
        blog_stats=blog_stats,
        comments_context=comments_context,
        admin_content=admin_content,
        schema_in_graph=True,
        seo_title=post.get("metaTitle") or f"{post.get('title')} | {BRAND_NAME}",
        seo_desc=post.get("metaDescription") or clean_plain_text(post.get("excerpt") or "", 180),
        seo_keywords=", ".join(post.get("tags") or []),
        seo_type="article",
        seo_image=post.get("heroImage") or "/static/img/place-placeholder.svg",
        seo_schema=schema,
        T=t(lang),
        body_class="PageBlog PageBlogDetail",
        use_leaflet=False,
    )


def handle_blog_comment(lang: str, slug: str) -> Response:
    post = find_blog_post(slug, lang=lang)
    if not post:
        abort(404)
    if clean_plain_text(request.form.get("website") or "", 200):
        return safe_comment_redirect(blog_post_url(post), "pending")
    name = clean_plain_text(request.form.get("name") or "", 120)
    email = clean_plain_text(request.form.get("email") or "", 180)
    comment = comment_plain_text(request.form.get("comment") or "", 1000)
    if not name or len(name) > 100 or not is_valid_email(email) or not comment or len(comment) > 1000:
        return safe_comment_redirect(blog_post_url(post), "error")
    if comment_submission_rate_limited(email):
        return safe_comment_redirect(blog_post_url(post), "rate")
    save_public_comment(
        page_type="blog_article",
        page_id=str(post.get("id") or ""),
        page_url=blog_post_url(post),
        page_title=str(post.get("title") or slug),
        language=lang,
        author_name=name,
        author_email=email,
        comment_text=comment,
    )
    return safe_comment_redirect(blog_post_url(post), "pending")


@app.post("/blog/<slug>/comments")
def blog_comment_en(slug: str):
    return handle_blog_comment(DEFAULT_LANG, slug)


@app.post("/<re('fr|es|it|ua|uk|de'):lang>/blog/<slug>/comments")
def blog_comment_localized(lang: str, slug: str):
    return handle_blog_comment(normalize_lang(lang), slug)


@app.post("/comments/submit")
def submit_public_comment():
    page_type = normalize_comment_page_type(request.form.get("pageType"))
    page_id = clean_plain_text(request.form.get("pageId") or "", 240)
    page_url = clean_plain_text(request.form.get("pageUrl") or request.referrer or "", 500)
    page_title = clean_plain_text(request.form.get("pageTitle") or "Public page", 220)
    language = normalize_lang(request.form.get("language") or current_lang())
    if clean_plain_text(request.form.get("website") or "", 200):
        return safe_comment_redirect(page_url, "pending")
    name = clean_plain_text(request.form.get("name") or "", 100)
    email = clean_plain_text(request.form.get("email") or "", 180).lower()
    comment = comment_plain_text(request.form.get("comment") or "", 1000)
    if not page_type or not page_id or not page_url or not page_title:
        return safe_comment_redirect(page_url, "error")
    if not name or len(name) > 100 or not is_valid_email(email) or not comment or len(comment) > 1000:
        return safe_comment_redirect(page_url, "error")
    if comment_submission_rate_limited(email):
        return safe_comment_redirect(page_url, "rate")
    save_public_comment(
        page_type=page_type,
        page_id=page_id,
        page_url=page_url,
        page_title=page_title,
        language=language,
        author_name=name,
        author_email=email,
        comment_text=comment,
    )
    return safe_comment_redirect(page_url, "pending")


def handle_blog_like(lang: str, slug: str) -> Response:
    post = find_blog_post(slug, lang=lang)
    if not post:
        abort(404)
    cookie_key = f"blog_like_{post.get('id')}"
    if not request.cookies.get(cookie_key):
        rows = cms_collection_rows("blogLikes")
        rows.insert(0, {
            "id": secrets.token_hex(8),
            "postId": post.get("id") or "",
            "postSlug": post.get("slug") or slug,
            "ip": get_client_ip(),
            "createdAt": utc_now_iso(),
        })
        save_cms_collection_rows("blogLikes", rows[:10000])
    resp = redirect(f"{blog_post_url(post)}#blog-engagement", code=302)
    resp.set_cookie(cookie_key, "1", max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.post("/blog/<slug>/like")
def blog_like_en(slug: str):
    return handle_blog_like(DEFAULT_LANG, slug)


@app.post("/<re('fr|es|it|ua|uk|de'):lang>/blog/<slug>/like")
def blog_like_localized(lang: str, slug: str):
    return handle_blog_like(normalize_lang(lang), slug)


def handle_blog_rating(lang: str, slug: str) -> Response:
    post = find_blog_post(slug, lang=lang)
    if not post:
        abort(404)
    try:
        rating = int(request.form.get("rating") or 0)
    except Exception:
        rating = 0
    if 1 <= rating <= 5:
        cookie_key = f"blog_rating_{post.get('id')}"
        if not request.cookies.get(cookie_key):
            rows = cms_collection_rows("blogRatings")
            rows.insert(0, {"id": secrets.token_hex(8), "postId": post.get("id") or "", "postSlug": slug, "rating": rating, "status": "approved", "ip": get_client_ip(), "createdAt": utc_now_iso()})
            save_cms_collection_rows("blogRatings", rows[:10000])
        resp = redirect(f"{blog_post_url(post)}#blog-engagement", code=302)
        resp.set_cookie(cookie_key, "1", max_age=60 * 60 * 24 * 365, samesite="Lax")
        return resp
    return redirect(f"{blog_post_url(post)}?rating=bad#blog-engagement", code=302)


@app.post("/blog/<slug>/rating")
def blog_rating_en(slug: str):
    return handle_blog_rating(DEFAULT_LANG, slug)


@app.post("/<re('fr|es|it|ua|uk|de'):lang>/blog/<slug>/rating")
def blog_rating_localized(lang: str, slug: str):
    return handle_blog_rating(normalize_lang(lang), slug)


@app.post("/audio-rating")
def audio_rating_submit():
    entity_type = clean_plain_text(request.form.get("entityType") or "", 30).lower()
    if entity_type not in {"country", "city", "place"}:
        abort(400)
    country_slug = slugify(request.form.get("countrySlug") or "")
    city_slug = slugify(request.form.get("citySlug") or "")
    place_slug = slugify(request.form.get("placeSlug") or "")
    lang = normalize_lang(request.form.get("language") or current_lang())
    try:
        rating = int(request.form.get("rating") or 0)
    except Exception:
        rating = 0
    return_to = clean_plain_text(request.form.get("returnTo") or request.referrer or "/", 500)
    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/"
    if "#audio-rating" not in return_to:
        return_to = return_to.split("#", 1)[0] + "#audio-rating"
    if not 1 <= rating <= 5:
        return redirect(f"{return_to.split('#', 1)[0]}?rating=bad#audio-rating", code=302)
    key = audio_rating_key(entity_type, country_slug, city_slug, place_slug)
    cookie_key = "audio_rating_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:18]
    resp = redirect(return_to, code=302)
    if request.cookies.get(cookie_key):
        return resp
    rows = cms_collection_rows("audioRatings")
    rows.insert(
        0,
        {
            "id": secrets.token_hex(8),
            "entityType": entity_type,
            "entityKey": key,
            "countrySlug": country_slug,
            "citySlug": city_slug,
            "placeSlug": place_slug,
            "language": lang,
            "rating": rating,
            "status": "approved",
            "pageUrl": return_to.split("#", 1)[0],
            "ip": get_client_ip(),
            "userAgent": clean_plain_text(request.headers.get("User-Agent") or "", 500),
            "createdAt": utc_now_iso(),
        },
    )
    save_cms_collection_rows("audioRatings", rows[:20000])
    resp.set_cookie(cookie_key, "1", max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.get("/admin/blog")
def admin_blog():
    return admin_cms_section_response("blog/articles")


def empty_blog_post(lang: str = DEFAULT_LANG) -> Dict[str, Any]:
    return {
        "id": "",
        "title": "",
        "slug": "",
        "lang": normalize_lang(lang),
        "status": "draft",
        "category": "Travel Audio Guides",
        "tags": [],
        "heroImage": "",
        "excerpt": "",
        "bodyMarkdown": "",
        "bodyHtmlRaw": "",
        "bodyEditorMode": "html",
        "slugManuallyEdited": False,
        "metaTitle": "",
        "metaDescription": "",
        "publishedAt": "",
        "updatedAt": "",
    }


@app.route("/admin/blog/new", methods=["GET", "POST"])
def admin_blog_new():
    return admin_blog_edit("")


@app.route("/admin/blog/articles/new", methods=["GET", "POST"])
def admin_blog_article_new():
    return admin_blog_edit("")


@app.route("/admin/blog/articles/<post_id>/change", methods=["GET", "POST"])
def admin_blog_article_change(post_id: str):
    return admin_blog_edit(post_id)


@app.route("/admin/blog/<post_id>", methods=["GET", "POST"])
def admin_blog_edit(post_id: str):
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp
    if post_id in {"articles", "authors", "categories", "comments", "ratings", "likes"} and request.method == "GET":
        return admin_cms_section_response(f"blog/{post_id}")
    all_posts = load_blog_posts(include_drafts=True)
    existing = next((p for p in all_posts if str(p.get("id") or "") == str(post_id or "")), None)
    if request.method == "POST":
        title = clean_plain_text(request.form.get("title") or "", 180)
        lang = normalize_lang(request.form.get("lang") or DEFAULT_LANG)
        slug = slugify(request.form.get("slug") or title)
        if not title or not slug:
            return render_template(
                "admin_blog_editor.html",
                post={**(existing or empty_blog_post()), "title": title, "slug": slug},
                authors=cms_collection_rows("blogAuthors"),
                categories=cms_collection_rows("blogCategories"),
                error="Title and slug are required.",
                admin_groups=admin_group_nav("blog/articles"),
                active_path="blog/articles",
                admin_nav=admin_nav_items("blog/articles"),
                seo_title=f"Edit blog post | {BRAND_NAME}",
                T=t(DEFAULT_LANG),
                body_class="PageAdmin",
                use_leaflet=False,
            )
        current_id = str(existing.get("id") if existing else post_id or secrets.token_hex(8))
        if any(
            str(p.get("slug") or "").lower() == slug
            and normalize_lang(str(p.get("lang") or DEFAULT_LANG)) == lang
            and str(p.get("id") or "") != current_id
            for p in all_posts
        ):
            return render_template(
                "admin_blog_editor.html",
                post={**(existing or empty_blog_post()), "title": title, "slug": slug},
                authors=cms_collection_rows("blogAuthors"),
                categories=cms_collection_rows("blogCategories"),
                error="This slug already exists for this language.",
                admin_groups=admin_group_nav("blog/articles"),
                active_path="blog/articles",
                admin_nav=admin_nav_items("blog/articles"),
                seo_title=f"Edit blog post | {BRAND_NAME}",
                T=t(DEFAULT_LANG),
                body_class="PageAdmin",
                use_leaflet=False,
            )
        status = str(request.form.get("status") or "draft").strip().lower()
        if status not in {"draft", "published", "scheduled", "archived"}:
            status = "draft"
        hero_image = clean_plain_text(request.form.get("hero_image") or "", 500)
        upload = request.files.get("hero_upload")
        if upload and upload.filename:
            ok, error, filename, ext, _size = validate_upload_file(
                upload,
                allowed_extensions=ALLOWED_IMAGE_UPLOAD_EXTENSIONS,
                allowed_mime_prefixes=("image/",),
                max_bytes=MAX_MEDIA_UPLOAD_BYTES,
            )
            if ok:
                BLOG_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                dest_name = f"{slug}-{secrets.token_hex(4)}{ext}"
                upload.save(BLOG_UPLOAD_DIR / dest_name)
                hero_image = f"/static/uploads/blog/{dest_name}"
            else:
                return render_template(
                    "admin_blog_editor.html",
                    post={**(existing or empty_blog_post()), "title": title, "slug": slug},
                    authors=cms_collection_rows("blogAuthors"),
                    categories=cms_collection_rows("blogCategories"),
                    error=error,
                    admin_groups=admin_group_nav("blog/articles"),
                    active_path="blog/articles",
                    admin_nav=admin_nav_items("blog/articles"),
                    seo_title=f"Edit blog post | {BRAND_NAME}",
                    T=t(DEFAULT_LANG),
                    body_class="PageAdmin",
                    use_leaflet=False,
                )
        now = utc_now_iso()
        body_editor_mode = str(request.form.get("body_editor_mode") or "html").strip().lower()
        if body_editor_mode not in {"html", "markdown"}:
            body_editor_mode = "html"
        body_html_raw = render_safe_html(request.form.get("body_html_raw") or "") if body_editor_mode == "html" else ""
        body_markdown = clean_plain_text(request.form.get("body_markdown") or "", 80000)
        post = {
            "id": current_id,
            "title": title,
            "h1": clean_plain_text(request.form.get("h1") or title, 180),
            "slug": slug,
            "lang": lang,
            "slugManuallyEdited": checkbox_enabled(request.form.get("slug_manually_edited")),
            "status": status,
            "category": clean_plain_text(request.form.get("category") or "Travel Audio Guides", 80),
            "author": clean_plain_text(request.form.get("author") or f"{BRAND_NAME} Team", 120),
            "tags": parse_tags(request.form.get("tags") or ""),
            "heroImage": hero_image,
            "excerpt": clean_plain_text(request.form.get("excerpt") or "", 600),
            "bodyEditorMode": body_editor_mode,
            "bodyMarkdown": body_markdown,
            "bodyHtmlRaw": body_html_raw,
            "metaTitle": clean_plain_text(request.form.get("meta_title") or "", 180),
            "metaDescription": clean_plain_text(request.form.get("meta_description") or "", 220),
            "canonical": clean_plain_text(request.form.get("canonical") or "", 500),
            "robotsIndex": checkbox_enabled(request.form.get("robots_index")) if "robots_index" in request.form else True,
            "robotsFollow": checkbox_enabled(request.form.get("robots_follow")) if "robots_follow" in request.form else True,
            "ogTitle": clean_plain_text(request.form.get("og_title") or "", 180),
            "ogDescription": clean_plain_text(request.form.get("og_description") or "", 240),
            "ogImage": clean_plain_text(request.form.get("og_image") or "", 500),
            "twitterTitle": clean_plain_text(request.form.get("twitter_title") or "", 180),
            "twitterDescription": clean_plain_text(request.form.get("twitter_description") or "", 240),
            "twitterImage": clean_plain_text(request.form.get("twitter_image") or "", 500),
            "schemaType": clean_plain_text(request.form.get("schema_type") or "BlogPosting", 80),
            "sitemapIncluded": checkbox_enabled(request.form.get("sitemap_included")) if "sitemap_included" in request.form else True,
            "publishedAt": clean_plain_text(request.form.get("published_at") or "", 40) or (now if status == "published" else ""),
            "updatedAt": now,
            "updatedBy": session.get("admin_email") or ADMIN_EMAIL,
        }
        if existing:
            all_posts = [post if str(p.get("id") or "") == current_id else p for p in all_posts]
        else:
            all_posts.append(post)
        save_blog_posts(all_posts)
        admin_revision_log("blog_article_saved", "blog", title, details={"lang": lang, "status": status, "slug": slug})
        q = urllib.parse.urlencode({"lang": lang, "msg": "Blog post saved.", "kind": "success"})
        return redirect(f"/admin/blog/articles?{q}", code=302)

    post = existing or empty_blog_post(normalize_lang(request.args.get("lang") or DEFAULT_LANG))
    post_comments = admin_comment_rows_for_page(str(post.get("id") or ""), normalize_lang(str(post.get("lang") or DEFAULT_LANG)), limit=50) if post.get("id") else []
    return render_template(
        "admin_blog_editor.html",
        post=post,
        post_comments=post_comments,
        authors=cms_collection_rows("blogAuthors"),
        categories=cms_collection_rows("blogCategories"),
        error="",
        admin_groups=admin_group_nav("blog/articles"),
        active_path="blog/articles",
        admin_nav=admin_nav_items("blog/articles"),
        seo_title=f"{'New' if not existing else 'Edit'} blog post | {BRAND_NAME}",
        seo_desc="Create or edit a SonicCity blog post.",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        T=t(post.get("lang") or DEFAULT_LANG),
        body_class="PageAdmin",
        use_leaflet=False,
    )


@app.post("/admin/blog/<post_id>/delete")
def admin_blog_delete(post_id: str):
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp
    posts = [p for p in load_blog_posts(include_drafts=True) if str(p.get("id") or "") != str(post_id or "")]
    save_blog_posts(posts)
    return redirect("/admin/blog/articles?msg=Blog+post+deleted.&kind=success", code=302)


@app.get("/admin/traffic")
def admin_traffic():
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp

    try:
        days = int(request.args.get("days") or 7)
    except Exception:
        days = 7
    days = min(90, max(1, days))
    events = load_access_events(days=days)
    summary = traffic_noise_summary(events)

    return render_template(
        "admin_traffic.html",
        days=days,
        summary=summary,
        access_log_path=str(ACCESS_LOG_PATH),
        access_log_enabled=ACCESS_LOG_ENABLED,
        access_log_geo_lookup=ACCESS_LOG_GEO_LOOKUP,
        seo_title=f"{BRAND_NAME} Traffic",
        seo_desc="Traffic noise diagnostics for SonicCity.",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        seo_schema={
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": f"{BRAND_NAME} Traffic",
            "url": absolute_url("/admin/traffic"),
        },
        T=t(DEFAULT_LANG),
        body_class="PageAdmin",
        use_leaflet=False,
    )


def admin_cms_render(
    section: str,
    title: str,
    subtitle: str,
    *,
    metrics: Optional[List[Dict[str, Any]]] = None,
    table: Optional[Dict[str, Any]] = None,
    panels: Optional[List[Dict[str, Any]]] = None,
    forms: Optional[List[Dict[str, Any]]] = None,
    problems: Optional[List[Dict[str, Any]]] = None,
    message: str = "",
    message_kind: str = "info",
) -> str:
    return render_template(
        "admin_cms.html",
        section=section,
        active_path=section,
        admin_groups=admin_group_nav(section),
        admin_nav=admin_nav_items(section),
        title=title,
        subtitle=subtitle,
        metrics=metrics or [],
        table=table or {},
        panels=panels or [],
        forms=forms or [],
        problems=problems or [],
        recent_actions=load_admin_revisions(8),
        admin_msg=message,
        admin_msg_kind=message_kind if message_kind in {"info", "success", "warning", "error"} else "info",
        totals=admin_site_totals() if section == "dashboard" else {},
        settings=load_admin_settings(),
        seo_title=f"{title} | {BRAND_NAME} Admin",
        seo_desc=f"Admin CMS section: {title}.",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        T=t(DEFAULT_LANG),
        body_class="PageAdmin PageAdminCms",
        use_leaflet=False,
    )


ADMIN_TABLE_PAGE_SIZE = 50
ADMIN_TABLE_PAGE_SIZE_OPTIONS = [25, 50, 100]


def admin_current_table_page() -> int:
    try:
        page = int(request.args.get("page") or request.args.get("p") or 1)
    except Exception:
        page = 1
    return max(1, page)


def admin_current_page_size() -> int:
    try:
        page_size = int(request.args.get("pageSize") or ADMIN_TABLE_PAGE_SIZE)
    except Exception:
        page_size = ADMIN_TABLE_PAGE_SIZE
    return page_size if page_size in ADMIN_TABLE_PAGE_SIZE_OPTIONS else ADMIN_TABLE_PAGE_SIZE


def admin_table_source_limit(page_size: Optional[int] = None) -> int:
    effective_size = page_size or admin_current_page_size()
    return admin_current_table_page() * effective_size


def admin_page_url_for(page: int, page_size: Optional[int] = None) -> str:
    params = request.args.to_dict(flat=True)
    params.pop("p", None)
    params["page"] = str(max(1, int(page or 1)))
    params["pageSize"] = str(page_size or admin_current_page_size())
    query = urllib.parse.urlencode(params)
    return request.path + (f"?{query}" if query else "")


def admin_table(
    columns: List[Tuple[str, str]],
    rows: List[Dict[str, Any]],
    *,
    title: str = "",
    empty: str = "No records found.",
    total: Optional[int] = None,
    page_size: Optional[int] = None,
) -> Dict[str, Any]:
    effective_size = page_size or admin_current_page_size()
    page = admin_current_table_page()
    source_rows = rows or []
    total_count = int(total if total is not None else len(source_rows))
    total_pages = max(1, math.ceil(total_count / effective_size)) if total_count else 1
    page = min(page, total_pages)
    start = (page - 1) * effective_size
    end = start + effective_size
    page_rows = source_rows[start:end]
    last_shown = start + len(page_rows)
    return {
        "title": title,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": page_rows,
        "empty": empty,
        "pagination": {
            "page": page,
            "pageSize": effective_size,
            "pageSizeOptions": ADMIN_TABLE_PAGE_SIZE_OPTIONS,
            "total": total_count,
            "totalPages": total_pages,
            "from": start + 1 if page_rows else 0,
            "to": last_shown,
            "hasPrev": page > 1,
            "hasNext": last_shown < total_count,
            "firstUrl": admin_page_url_for(1, effective_size),
            "prevUrl": admin_page_url_for(page - 1),
            "nextUrl": admin_page_url_for(page + 1),
            "lastUrl": admin_page_url_for(total_pages, effective_size),
            "pageSizeUrl25": admin_page_url_for(1, 25),
            "pageSizeUrl50": admin_page_url_for(1, 50),
            "pageSizeUrl100": admin_page_url_for(1, 100),
        },
    }


def admin_dashboard_metrics() -> List[Dict[str, Any]]:
    totals = admin_site_totals()
    return [
        {"label": "Total pages", "value": totals["pages"], "note": f"{totals['published']} published"},
        {"label": "Countries", "value": totals["countries"], "note": f"{totals['cities']} cities"},
        {"label": "Places", "value": totals["places"], "note": "target places in CMS"},
        {"label": "Blog posts", "value": totals["blogPosts"], "note": f"{totals['drafts']} drafts"},
        {"label": "Audio files", "value": totals["audioFiles"], "note": totals["audioStorage"]},
        {"label": "SEO issues", "value": totals["seoIssues"], "note": "meta/content review"},
        {"label": "Sitemap URLs", "value": totals["sitemapUrls"], "note": "generated sitemap"},
        {"label": "Redirects", "value": totals["redirects"], "note": "managed rules"},
    ]


def admin_content_topic_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    root = AUDIO_STORAGE_PATH / AUDIO_BUILD_AUDIO_VERSION
    if not root.exists():
        return rows
    for manifest in sorted(root.glob("**/manifest.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        parts = manifest.relative_to(root).parts
        if len(parts) < 5:
            continue
        lang, gender, country_slug, city_slug = parts[0], parts[1], parts[2], parts[3]
        place_slug = parts[4] if len(parts) > 5 else ""
        for sec in data.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            text = str(sec.get("text") or sec.get("cleanText") or "")
            rows.append({
                "entity": place_slug or city_slug,
                "type": "Place" if place_slug else "City",
                "language": lang.upper(),
                "voice": gender,
                "topic": str(sec.get("title") or sec.get("heading") or sec.get("id") or "Untitled"),
                "status": str(sec.get("status") or "ready").title(),
                "words": str(len(re.findall(r"\\w+", text))),
                "hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:10] if text else str(sec.get("textHash") or ""),
                "source": "Wikipedia / Admin",
            })
            if len(rows) >= limit:
                return rows
    return rows


def admin_content_topic_rows_total() -> int:
    total = 0
    root = AUDIO_STORAGE_PATH / AUDIO_BUILD_AUDIO_VERSION
    if not root.exists():
        return total
    for manifest in root.glob("**/manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        total += sum(1 for sec in (data.get("sections") or []) if isinstance(sec, dict))
    return total


def admin_handle_audio_post() -> Tuple[str, str]:
    action = str(request.form.get("action") or "").strip()
    if action == "upload":
        f = request.files.get("audio_file")
        if not f or not f.filename:
            return "Choose an audio file first.", "error"
        ok, error, _filename, ext, _size = validate_upload_file(
            f,
            allowed_extensions=ALLOWED_AUDIO_UPLOAD_EXTENSIONS,
            allowed_mime_prefixes=("audio/", "application/octet-stream"),
            max_bytes=MAX_AUDIO_UPLOAD_BYTES,
        )
        if not ok:
            return error, "error"
        entity_type = str(request.form.get("entity_type") or "city").strip().lower()
        country = secure_filename(request.form.get("country_slug") or "unknown")
        city = secure_filename(request.form.get("city_slug") or "unknown")
        place = secure_filename(request.form.get("place_slug") or "")
        lang = normalize_lang(request.form.get("lang") or DEFAULT_LANG)
        gender = str(request.form.get("voice_gender") or "female").strip().lower()
        if gender not in {"female", "male"}:
            gender = "female"
        section_id = secure_filename(request.form.get("section_id") or "manual")
        base = AUDIO_STORAGE_PATH / "manual" / ("places" if entity_type == "place" else "cities") / country / city
        if entity_type == "place" and place:
            base = base / place
        base = base / lang / gender
        base.mkdir(parents=True, exist_ok=True)
        filename = f"{section_id}-{int(time.time())}{ext}"
        dest = base / filename
        f.save(dest)
        uploads = load_admin_json(ADMIN_AUDIO_UPLOADS_PATH, {"uploads": []})
        rows = uploads.get("uploads") if isinstance(uploads, dict) else []
        if not isinstance(rows, list):
            rows = []
        rows.insert(0, {
            "entityType": entity_type,
            "country": country,
            "city": city,
            "place": place,
            "lang": lang,
            "voiceGender": gender,
            "sectionId": section_id,
            "path": str(dest.relative_to(ROOT)),
            "size": dest.stat().st_size,
            "uploadedAt": utc_now_iso(),
            "uploadedBy": session.get("admin_email") or ADMIN_EMAIL,
        })
        save_admin_json(ADMIN_AUDIO_UPLOADS_PATH, {"uploads": rows[:1000], "updatedAt": utc_now_iso()})
        admin_revision_log("audio_uploaded", entity_type, filename, details={"path": str(dest.relative_to(ROOT))})
        return "Audio file uploaded. TODO: wire manual upload into generated manifest selection if it should replace frontend playback automatically.", "success"
    if action == "delete":
        raw_path = str(request.form.get("path") or "").strip()
        if not raw_path:
            return "Missing audio path.", "error"
        candidate = (ROOT / raw_path).resolve()
        if not str(candidate).startswith(str(AUDIO_STORAGE_PATH.resolve())) or not candidate.exists() or not candidate.is_file():
            return "Audio path is outside managed storage.", "error"
        candidate.unlink()
        admin_revision_log("audio_deleted", "audio", raw_path)
        return "Audio file deleted.", "success"
    return "", "info"


def admin_handle_media_post() -> Tuple[str, str]:
    action = str(request.form.get("action") or "").strip()
    if action != "upload":
        return "", "info"
    f = request.files.get("media_file")
    if not f or not f.filename:
        return "Choose a media file first.", "error"
    ok, error, safe_original, ext, _size = validate_upload_file(
        f,
        allowed_extensions=ALLOWED_MEDIA_UPLOAD_EXTENSIONS,
        allowed_mime_prefixes=("image/", "audio/", "application/octet-stream"),
        max_bytes=MAX_AUDIO_UPLOAD_BYTES if Path(f.filename).suffix.lower() in ALLOWED_AUDIO_UPLOAD_EXTENSIONS else MAX_MEDIA_UPLOAD_BYTES,
    )
    if not ok:
        return error, "error"
    MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}-{safe_original}"
    dest = MEDIA_UPLOAD_DIR / filename
    f.save(dest)
    data = load_admin_json(ADMIN_MEDIA_INDEX_PATH, {"media": []})
    rows = data.get("media") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    rows.insert(0, {
        "filename": filename,
        "path": str(dest.relative_to(ROOT)),
        "type": "audio" if ext in {".mp3", ".wav", ".m4a"} else "image",
        "size": dest.stat().st_size,
        "alt": clean_plain_text(request.form.get("alt") or "", 300),
        "uploadedAt": utc_now_iso(),
        "uploadedBy": session.get("admin_email") or ADMIN_EMAIL,
    })
    save_admin_json(ADMIN_MEDIA_INDEX_PATH, {"media": rows[:2000], "updatedAt": utc_now_iso()})
    admin_revision_log("media_uploaded", "media", filename)
    return "Media uploaded.", "success"


def admin_add_redirect_from_form() -> Tuple[str, str]:
    if str(request.form.get("action") or "").strip() == "delete":
        source = clean_plain_text(request.form.get("source") or "", 300)
        if not source:
            return "Redirect source is required.", "error"
        rows = [r for r in load_admin_redirects() if str(r.get("source") or "") != source]
        save_admin_redirects(rows)
        admin_revision_log("redirect_deleted", "redirect", source)
        return "Redirect deleted.", "success"
    source = clean_plain_text(request.form.get("source") or "", 300)
    target = clean_plain_text(request.form.get("target") or "", 500)
    if not source.startswith("/") or not target:
        return "Redirect source must start with / and target is required.", "error"
    try:
        code = int(request.form.get("code") or 301)
    except Exception:
        code = 301
    if code not in {301, 302, 307, 308}:
        code = 301
    rows = load_admin_redirects()
    rows = [r for r in rows if str(r.get("source") or "") != source]
    rows.insert(0, {
        "source": source,
        "target": target,
        "code": code,
        "language": normalize_lang(request.form.get("lang") or DEFAULT_LANG),
        "notes": clean_plain_text(request.form.get("notes") or "", 500),
        "active": True,
        "createdBy": session.get("admin_email") or ADMIN_EMAIL,
        "createdAt": utc_now_iso(),
    })
    save_admin_redirects(rows)
    admin_revision_log("redirect_saved", "redirect", source, details={"target": target, "code": code})
    return "Redirect saved.", "success"


def admin_sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    q = clean_plain_text(request.args.get("q") or "", 120).lower()
    status = clean_plain_text(request.args.get("status") or "", 80).lower()
    lang = clean_plain_text(request.args.get("lang") or request.args.get("language") or "", 20).lower()
    sort_key = clean_plain_text(request.args.get("sort") or "", 80)
    if q:
        rows = [
            row for row in rows
            if q in " ".join(str(v) for v in row.values()).lower()
        ]
    if status:
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == status]
    if lang:
        rows = [row for row in rows if str(row.get("language") or row.get("lang") or "").strip().lower() == lang]
    if sort_key:
        reverse = sort_key.startswith("-")
        key = sort_key[1:] if reverse else sort_key
        rows = sorted(rows, key=lambda row: str(row.get(key) or "").lower(), reverse=reverse)
    return rows


def admin_action_link(label: str, href: str) -> str:
    safe_href = html.escape(href, quote=True)
    safe_label = html.escape(label)
    return f'<a class="ux-adminActionLink" href="{safe_href}">{safe_label}</a>'


def admin_star_rating_html(value: Any, count: Optional[int] = None) -> str:
    try:
        rating = max(0.0, min(5.0, float(value or 0)))
    except Exception:
        rating = 0.0
    if not rating:
        return '<span class="cms-starsText">No ratings</span>'
    percent = int(round((rating / 5.0) * 100))
    label = f"{rating:.1f} / 5"
    if count is not None:
        label = f"{label} · {int(count)} ratings"
    safe_label = html.escape(label)
    return (
        f'<span class="cms-starMeter" aria-label="{safe_label}">'
        '<span class="cms-starBase">★★★★★</span>'
        f'<span class="cms-starFill" style="width:{percent}%">★★★★★</span>'
        '</span>'
        f'<span class="cms-starsText">{safe_label}</span>'
    )


def admin_blog_article_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for post in load_blog_posts(include_drafts=True):
        stats = admin_blog_engagement_stats(str(post.get("id") or ""))
        rows.append({
            "title": post.get("title") or "Untitled",
            "h1": post.get("h1") or post.get("title") or "",
            "slug": post.get("slug") or "",
            "language": normalize_lang(str(post.get("lang") or DEFAULT_LANG)).upper(),
            "category": post.get("category") or "Travel Audio Guides",
            "author": post.get("author") or f"{BRAND_NAME} Team",
            "status": str(post.get("status") or "draft").title(),
            "comments": str(stats["comments"]),
            "likes": str(stats["likes"]),
            "rating": admin_star_rating_html(stats["ratingAverage"], stats["ratings"]),
            "seo": "OK" if post.get("metaTitle") and post.get("metaDescription") else "Issue",
            "updatedAt": post.get("updatedAt") or "",
            "actions": " ".join([
                admin_action_link("Edit", f"/admin/blog/articles/{post.get('id')}/change"),
                admin_action_link("Preview", blog_post_url(post)),
            ]),
        })
        if len(rows) >= limit:
            break
    return admin_sort_rows(rows)


def admin_blog_engagement_stats(post_id: str) -> Dict[str, Any]:
    legacy_comments = [r for r in cms_collection_rows("blogComments") if str(r.get("postId") or "") == post_id]
    universal_comments = [
        r for r in cms_collection_rows("comments")
        if str(r.get("pageType") or "") == "blog_article" and str(r.get("pageId") or "") == post_id
    ]
    comments = legacy_comments + universal_comments
    likes = [r for r in cms_collection_rows("blogLikes") if str(r.get("postId") or "") == post_id]
    ratings = [r for r in cms_collection_rows("blogRatings") if str(r.get("postId") or "") == post_id and str(r.get("status") or "approved") != "spam"]
    rating_values = []
    for row in ratings:
        try:
            rating_values.append(float(row.get("rating") or 0))
        except Exception:
            continue
    avg = sum(rating_values) / len(rating_values) if rating_values else 0
    return {
        "comments": len(comments),
        "approvedComments": sum(1 for r in comments if normalize_comment_status(r.get("status")) == "approved"),
        "likes": len(likes),
        "ratings": len(rating_values),
        "ratingAverage": avg,
        "ratingPercent": max(0, min(100, int(round((avg / 5) * 100)))) if avg else 0,
        "ratingLabel": f"{avg:.1f} / 5 ({len(rating_values)})" if rating_values else "No ratings",
    }


def admin_cms_store_table_rows(collection: str, columns: List[str], limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in cms_collection_rows(collection)[:limit]:
        if not isinstance(raw, dict):
            continue
        row = {key: raw.get(key) or "" for key in columns}
        row.setdefault("status", raw.get("status") or "")
        row.setdefault("updatedAt", raw.get("updatedAt") or raw.get("createdAt") or "")
        rows.append(row)
    return admin_sort_rows(rows)


def admin_blog_comment_rows(limit: int = 250) -> List[Dict[str, Any]]:
    post_by_id = {str(p.get("id") or ""): p for p in load_blog_posts(include_drafts=True)}
    rows: List[Dict[str, Any]] = []
    for item in cms_collection_rows("blogComments")[:limit]:
        post = post_by_id.get(str(item.get("postId") or "")) or {}
        rows.append({
            "article": post.get("title") or item.get("postSlug") or "Unknown article",
            "name": item.get("name") or "",
            "email": item.get("email") or "",
            "excerpt": clean_plain_text(item.get("comment") or "", 120),
            "rating": admin_star_rating_html(item.get("rating") or 0),
            "status": item.get("status") or "pending",
            "createdAt": item.get("createdAt") or "",
            "ip": item.get("ip") or "",
            "actions": " ".join([
                admin_action_link("Approve", f"/admin/blog/comments/{item.get('id')}/approve"),
                admin_action_link("Reject", f"/admin/blog/comments/{item.get('id')}/reject"),
            ]),
        })
    return admin_sort_rows(rows)


def admin_comment_rows(limit: int = 250, *, page_type_filter: str = "") -> List[Dict[str, Any]]:
    page_type_filter = normalize_comment_page_type(page_type_filter)
    rows: List[Dict[str, Any]] = []
    for item in all_comment_rows()[:limit]:
        if page_type_filter and str(item.get("pageType") or "") != page_type_filter:
            continue
        status = normalize_comment_status(item.get("status"))
        comment_ref = str(item.get("id") or "")
        encoded_ref = urllib.parse.quote(comment_ref, safe="")
        actions = [
            admin_action_link("View", f"/admin/comments/{encoded_ref}"),
            admin_action_link("Approve", f"/admin/comments/{encoded_ref}/approve"),
            admin_action_link("Reject", f"/admin/comments/{encoded_ref}/reject"),
            admin_action_link("Spam", f"/admin/comments/{encoded_ref}/spam"),
            admin_action_link("Delete", f"/admin/comments/{encoded_ref}/delete"),
        ]
        if item.get("pageUrl"):
            actions.append(admin_action_link("Open", str(item.get("pageUrl"))))
        rows.append({
            "createdAt": item.get("createdAt") or "",
            "page": item.get("pageTitle") or item.get("pageId") or "",
            "pageType": str(item.get("pageType") or "").replace("_", " ").title(),
            "language": normalize_lang(str(item.get("language") or DEFAULT_LANG)).upper(),
            "name": item.get("authorName") or "",
            "email": item.get("authorEmail") or "",
            "excerpt": clean_plain_text(item.get("commentText") or "", 140),
            "status": status,
            "actions": " ".join(actions),
        })
    return admin_sort_rows(rows)


def admin_comment_rows_total(*, page_type_filter: str = "") -> int:
    page_type_filter = normalize_comment_page_type(page_type_filter)
    rows = all_comment_rows()
    if page_type_filter:
        rows = [row for row in rows if str(row.get("pageType") or "") == page_type_filter]
    q = clean_plain_text(request.args.get("q") or "", 120).lower()
    status = clean_plain_text(request.args.get("status") or "", 80).lower()
    lang = clean_plain_text(request.args.get("lang") or request.args.get("language") or "", 20).lower()
    if q:
        rows = [row for row in rows if q in " ".join(str(v) for v in row.values()).lower()]
    if status:
        rows = [row for row in rows if normalize_comment_status(row.get("status")) == status]
    if lang:
        rows = [row for row in rows if normalize_lang(str(row.get("language") or "")) == lang]
    return len(rows)


def admin_comment_rows_for_page(page_id: str, lang: str, limit: int = 50) -> List[Dict[str, Any]]:
    page_id = clean_plain_text(page_id, 240)
    lang = normalize_lang(lang)
    rows = [
        row for row in all_comment_rows()
        if str(row.get("pageId") or "") == page_id
        and normalize_lang(str(row.get("language") or lang)) == lang
    ]
    rows.sort(key=lambda row: row.get("createdAt") or "", reverse=True)
    return rows[:limit]


def admin_comment_detail_panel(comment_ref: str) -> Optional[List[Dict[str, str]]]:
    item = find_comment_record(comment_ref)
    if not item:
        return None
    body = "\n".join([
        f"Page: {clean_plain_text(item.get('pageTitle') or '', 220)}",
        f"URL: {clean_plain_text(item.get('pageUrl') or '', 500)}",
        f"Type: {clean_plain_text(item.get('pageType') or '', 80)}",
        f"Language: {normalize_lang(str(item.get('language') or DEFAULT_LANG)).upper()}",
        f"Name: {clean_plain_text(item.get('authorName') or '', 100)}",
        f"Email: {clean_plain_text(item.get('authorEmail') or '', 180)}",
        f"Status: {normalize_comment_status(item.get('status'))}",
        f"Created: {clean_plain_text(item.get('createdAt') or '', 80)}",
        f"IP: {clean_plain_text(item.get('ipAddress') or '', 80)}",
        f"User agent: {clean_plain_text(item.get('userAgent') or '', 500)}",
        "",
        comment_plain_text(item.get("commentText") or "", 1000),
    ])
    encoded_ref = urllib.parse.quote(str(item.get("id") or comment_ref), safe="")
    actions = " · ".join([
        f"Approve: /admin/comments/{encoded_ref}/approve",
        f"Reject: /admin/comments/{encoded_ref}/reject",
        f"Spam: /admin/comments/{encoded_ref}/spam",
        f"Delete: /admin/comments/{encoded_ref}/delete",
    ])
    return [
        {"title": "Comment detail", "body": body},
        {"title": "Moderation actions", "body": actions},
    ]


def admin_blog_rating_rows(limit: int = 250) -> List[Dict[str, Any]]:
    post_by_id = {str(p.get("id") or ""): p for p in load_blog_posts(include_drafts=True)}
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in cms_collection_rows("blogRatings"):
        post_id = str(item.get("postId") or item.get("postSlug") or "")
        if not post_id:
            continue
        bucket = grouped.setdefault(post_id, {"ratings": [], "last": "", "post": post_by_id.get(post_id) or {}})
        try:
            rating = float(item.get("rating") or 0)
        except Exception:
            rating = 0
        if 1 <= rating <= 5:
            bucket["ratings"].append(rating)
        created = str(item.get("createdAt") or "")
        if created > str(bucket.get("last") or ""):
            bucket["last"] = created
    rows = []
    for post_id, data in grouped.items():
        values = data.get("ratings") or []
        avg = sum(values) / len(values) if values else 0
        post = data.get("post") or {}
        rows.append({
            "article": post.get("title") or post_id or "Unknown article",
            "rating": admin_star_rating_html(avg, len(values)),
            "ratingNumber": f"{avg:.1f}",
            "ratingsCount": len(values),
            "lastRating": data.get("last") or "",
            "actions": admin_action_link("Open post", blog_post_url(post)) if post else "",
        })
        if len(rows) >= limit:
            break
    return admin_sort_rows(rows)


def admin_blog_like_rows(limit: int = 250) -> List[Dict[str, Any]]:
    counter: Dict[str, int] = {}
    for item in cms_collection_rows("blogLikes"):
        key = str(item.get("postId") or item.get("postSlug") or "")
        if key:
            counter[key] = counter.get(key, 0) + 1
    post_by_id = {str(p.get("id") or ""): p for p in load_blog_posts(include_drafts=True)}
    rows = [
        {"article": (post_by_id.get(post_id) or {}).get("title") or post_id, "likes": count, "status": "real", "updatedAt": utc_now_iso()}
        for post_id, count in sorted(counter.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return admin_sort_rows(rows[:limit])


def admin_subscription_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows = []
    for item in cms_collection_rows("subscribers")[:limit]:
        submitted_at = item.get("submittedAt") or item.get("subscribedAt") or item.get("createdAt") or ""
        rows.append({
            "submittedAt": submitted_at,
            "email": item.get("email") or "",
            "name": item.get("name") or "",
            "language": item.get("language") or "",
            "sourcePage": item.get("sourcePage") or item.get("source") or "",
            "notification": "Sent" if item.get("emailNotificationSent") else (item.get("emailNotificationStatus") or "Not sent"),
            "status": item.get("status") or "pending",
            "ip": item.get("ip") or "",
            "userAgent": clean_plain_text(item.get("userAgent") or "", 180),
            "id": item.get("id") or "",
        })
    return admin_sort_rows(rows)


def admin_user_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    history_counts = Counter(str(row.get("userId") or "") for row in cms_collection_rows("listeningHistory"))
    favorite_counts = Counter(str(row.get("userId") or "") for row in cms_collection_rows("favorites"))
    subscriber_emails = {str(row.get("email") or "").strip().lower() for row in cms_collection_rows("subscribers")}
    for item in cms_collection_rows("siteUsers")[:limit]:
        user_id = str(item.get("id") or "")
        email = str(item.get("email") or "").strip().lower()
        rows.append({
            "email": email,
            "name": item.get("name") or "",
            "type": "Site user",
            "emailVerified": "Yes" if site_user_is_verified(item) else "No",
            "registrationCountry": item.get("registrationCountry") or item.get("registrationCountryCode") or "",
            "registeredAt": item.get("registeredAt") or item.get("createdAt") or "",
            "lastLoginAt": item.get("lastLoginAt") or "",
            "status": item.get("status") or "active",
            "listening": history_counts.get(user_id, 0),
            "favorites": favorite_counts.get(user_id, 0),
            "subscription": "Subscribed" if email in subscriber_emails else "—",
            "ip": item.get("ip") or "",
            "id": item.get("id") or "",
            "actions": f'<a class="cms-btn cms-btn-soft" href="/admin/users/{html.escape(user_id)}">Open</a>',
        })
    for item in cms_collection_rows("adminUsers"):
        rows.append({
            "email": item.get("email") or "",
            "name": item.get("name") or "",
            "type": "Admin",
            "emailVerified": "Yes",
            "registrationCountry": item.get("registrationCountry") or item.get("source") or "env",
            "registeredAt": item.get("createdAt") or "",
            "lastLoginAt": item.get("lastLoginAt") or "",
            "status": "active" if item.get("active", True) else "inactive",
            "listening": 0,
            "favorites": 0,
            "subscription": "—",
            "ip": item.get("ip") or "",
            "id": item.get("id") or "",
            "actions": "",
        })
    return admin_sort_rows(rows)


def admin_contact_message_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows = []
    for item in cms_collection_rows("contactMessages")[:limit]:
        submitted_at = item.get("submittedAt") or item.get("createdAt") or ""
        rows.append({
            "submittedAt": submitted_at,
            "name": item.get("name") or "",
            "email": item.get("email") or "",
            "message": clean_plain_text(item.get("message") or "", 240),
            "language": item.get("language") or "",
            "sourcePage": item.get("sourcePage") or item.get("source") or "",
            "status": item.get("status") or "new",
            "ip": item.get("ip") or "",
            "userAgent": clean_plain_text(item.get("userAgent") or "", 180),
            "id": item.get("id") or "",
        })
    return admin_sort_rows(rows)


def admin_audio_queue_rows(status_filter: str = "", limit: int = 250) -> List[Dict[str, Any]]:
    rows = admin_audio_manifest_records(limit=limit)
    if status_filter:
        rows = [r for r in rows if status_filter.lower() in str(r.get("status") or "").lower() or (status_filter == "failed" and str(r.get("failed") or "0") != "0")]
    return admin_sort_rows(rows)


def admin_seo_audit_rows(limit: int = 250) -> List[Dict[str, Any]]:
    rows = admin_page_records(
        limit=limit,
        page_type=request.args.get("type") or "",
        lang=request.args.get("lang") or "",
        q=request.args.get("q") or "",
        include_audio=False,
    )
    for row in rows:
        issues = []
        if row.get("seo") != "OK":
            issues.append("meta")
        if row.get("seoText") == "Missing":
            issues.append("seo text")
        if row.get("faqStatus") == "Missing":
            issues.append("faq")
        row["audio"] = row.get("audio") or "Managed in Audio"
        row["issues"] = ", ".join(issues) or "OK"
        row["actions"] = admin_action_link("Edit", f"/admin/pages/edit?lang={row.get('language')}&pageKey={admin_page_key_for_record(row)}")
    return rows


def admin_generic_page_rows(page_type: str, limit: int = 250) -> List[Dict[str, Any]]:
    mapped = {
        "home": "home",
        "cities": "city",
        "countries": "country",
        "places": "place",
        "technical": "static",
    }.get(page_type, "")
    rows = admin_page_records(
        limit=limit,
        page_type=mapped,
        lang=request.args.get("lang") or "",
        q=request.args.get("q") or "",
        include_audio=False,
    )
    for row in rows:
        row["audio"] = row.get("audio") or "Managed in Audio"
        row["actions"] = admin_action_link("Edit", f"/admin/pages/edit?lang={row.get('language')}&pageKey={admin_page_key_for_record(row)}")
    return rows


def admin_cms_section_response(section: str) -> Response:
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp

    msg = str(request.args.get("msg") or "").strip()
    kind = str(request.args.get("kind") or "info").strip().lower()
    if request.method == "POST":
        if section == "robots":
            save_robots_text(request.form.get("robots_text") or "")
            return redirect("/admin/robots?msg=Robots.txt+saved.&kind=success", code=302)
        if section == "settings":
            save_admin_settings(request.form)
            return redirect("/admin/settings?msg=Settings+saved.&kind=success", code=302)
        if section == "redirects":
            msg, kind = admin_add_redirect_from_form()
            return redirect(f"/admin/redirects?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)
        if section == "audio":
            msg, kind = admin_handle_audio_post()
            return redirect(f"/admin/audio?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)
        if section == "media":
            msg, kind = admin_handle_media_post()
            return redirect(f"/admin/media?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)

    if section == "dashboard":
        return admin_cms_render(
            "dashboard",
            "Admin Dashboard",
            "Production CMS overview for pages, audio, SEO, sitemap, robots, content and logs.",
            metrics=admin_dashboard_metrics(),
            problems=admin_problem_rows(),
            table=admin_table(
                [("problem", "Problem"), ("count", "Count"), ("manager", "Manager")],
                admin_problem_rows(),
                title="Problems to fix",
            ),
            message=msg,
            message_kind=kind,
        )
    if section == "countries":
        return admin_cms_render("countries", "Countries", "Manage country pages, images, SEO, sitemap and featured guides.", table=admin_table([("name", "Country"), ("slug", "Slug"), ("iso", "ISO"), ("languages", "Languages"), ("cities", "Cities"), ("places", "Places"), ("seo", "SEO"), ("sitemap", "Sitemap"), ("url", "URL")], admin_country_records(), title="Countries", total=admin_site_totals()["countries"]), message=msg, message_kind=kind)
    if section == "cities":
        return admin_cms_render("cities", "Cities", "Manage population-ranked city pages, audio status, map data and SEO.", table=admin_table([("name", "City"), ("country", "Country"), ("slug", "Slug"), ("population", "Population"), ("coordinates", "Coordinates"), ("places", "Places"), ("audio", "Audio"), ("seo", "SEO"), ("sitemap", "Sitemap"), ("url", "URL")], admin_city_records(limit=admin_table_source_limit()), title="Cities", total=admin_site_totals()["cities"]), message=msg, message_kind=kind)
    if section == "places":
        return admin_cms_render("places", "Places", "Manage landmarks, museums, churches, maps, images and place audio pages.", table=admin_table([("name", "Place"), ("city", "City"), ("country", "Country"), ("category", "Category"), ("coordinates", "Coordinates"), ("image", "Image"), ("audio", "Audio"), ("seo", "SEO"), ("url", "URL")], admin_place_records(limit=admin_table_source_limit()), title="Places", total=admin_site_totals()["places"]), message=msg, message_kind=kind)
    if section == "audio":
        return admin_cms_render("audio", "Audio Manager", "Review generated audio, upload replacements and manage missing, failed or outdated files.", metrics=[{"label": "Audio files", "value": admin_audio_totals()["files"], "note": admin_audio_totals()["storage"]}, {"label": "Manifests", "value": admin_audio_totals()["manifests"], "note": f"v{AUDIO_BUILD_AUDIO_VERSION}"}, {"label": "Failed sections", "value": admin_audio_totals()["failed"], "note": "retry required"}], table=admin_table([("entity", "Entity"), ("name", "Name"), ("country", "Country"), ("city", "City"), ("language", "Lang"), ("voice", "Voice"), ("status", "Status"), ("sections", "Sections"), ("failed", "Failed"), ("size", "Size"), ("path", "Path")], admin_audio_manifest_records(limit=admin_table_source_limit()), title="Generated audio manifests", total=admin_audio_totals()["manifests"]), forms=[{"type": "audioUpload"}], message=msg, message_kind=kind)
    if section == "content":
        return admin_cms_render("content", "Content Editor", "Edit audio topics, source text and public page copy without showing raw Wikipedia text publicly.", table=admin_table([("entity", "Entity"), ("type", "Type"), ("language", "Lang"), ("voice", "Voice"), ("topic", "Topic"), ("status", "Audio"), ("words", "Words"), ("hash", "Text hash"), ("source", "Source")], admin_content_topic_rows(limit=admin_table_source_limit()), title="Audio topic content", total=admin_content_topic_rows_total()), panels=[{"title": "TODO: full revisions diff", "body": "The project stores generated source text inside audio manifests. A DB-backed section revision model should be added before drag-and-drop ordering and compare source vs edited can be production safe."}], message=msg, message_kind=kind)
    if section == "landing-pages":
        rows = admin_landing_page_records(limit=admin_table_source_limit())
        return admin_cms_render("landing-pages", "Landing Pages", "Manage landing templates, SEO blocks, CTA sections and FAQ before public rendering.", table=admin_table([("title", "Title"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("status", "Status"), ("seo", "SEO"), ("seoText", "SEO text"), ("faqStatus", "FAQ")], rows, title="Landing pages", total=admin_landing_page_records_total()), panels=[{"title": "Block editor", "body": "Use /admin/pages to edit SEO HTML/Markdown and FAQ blocks. TODO: add drag-and-drop block storage in data/admin/pages.json blocks[]."}], message=msg, message_kind=kind)
    if section == "media":
        return admin_cms_render("media", "Media Library", "Manage images, blog uploads, OG media and manual audio uploads.", table=admin_table([("filename", "Filename"), ("type", "Type"), ("size", "Size"), ("path", "Path"), ("alt", "Alt"), ("used", "Used on"), ("updated", "Updated")], admin_media_records(limit=admin_table_source_limit()), title="Media files", total=admin_media_records_total()), forms=[{"type": "mediaUpload"}], message=msg, message_kind=kind)
    if section == "seo":
        rows = admin_page_records(limit=admin_table_source_limit(), page_type=request.args.get("type") or "", lang=request.args.get("lang") or "", q=request.args.get("q") or "")
        return admin_cms_render("seo", "SEO Manager", "Audit titles, descriptions, canonical, hreflang, schema, sitemap and indexing.", table=admin_table([("title", "Page"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("seo", "SEO"), ("seoText", "SEO text"), ("faqStatus", "FAQ"), ("indexing", "Indexing"), ("audio", "Audio")], rows, title="SEO audit", total=admin_page_records_total(page_type=request.args.get("type") or "", lang=request.args.get("lang") or "", q=request.args.get("q") or "")), panels=[{"title": "Checklist", "body": "Title, description, one H1, canonical, hreflang, OG image, SEO text before footer, FAQ schema, sitemap, robots, content depth, audio availability and internal links are checked from server-rendered data where available."}], message=msg, message_kind=kind)
    if section == "sitemap":
        sitemap = admin_sitemap_records(limit=admin_table_source_limit())
        return admin_cms_render("sitemap", "Sitemap Manager", "Preview generated sitemap URLs and inclusion rules.", metrics=[{"label": "URLs", "value": sitemap["total"], "note": "generated"}, {"label": "Languages", "value": len(LANG_ORDER), "note": "hreflang alternates"}], table=admin_table([("title", "Page"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("indexing", "Indexing")], sitemap["rows"], title="Sitemap preview", total=sitemap["total"]), panels=[{"title": "Rules", "body": "Admin, API, draft, preview and noindex pages are excluded. Public country/city/place/blog pages are generated server-side for Google."}], message=msg, message_kind=kind)
    if section == "robots":
        return admin_cms_render("robots", "Robots.txt Manager", "Edit robots.txt, keep admin/API private and expose sitemap directive.", forms=[{"type": "robots", "value": load_robots_text()}], panels=[{"title": "Validation", "body": "Disallow admin/API/private generation routes. Keep Sitemap directive pointed at /sitemap.xml."}], message=msg, message_kind=kind)
    if section == "redirects":
        return admin_cms_render("redirects", "Redirects Manager", "Create and review 301/302/307/308 redirects. Active redirects are applied before public routing.", table=admin_table([("source", "Source"), ("target", "Target"), ("code", "Code"), ("language", "Lang"), ("active", "Active"), ("createdAt", "Created")], load_admin_redirects(), title="Redirect rules"), forms=[{"type": "redirect"}], message=msg, message_kind=kind)
    if section == "schema":
        return admin_cms_render("schema", "Schema Manager", "Preview and validate JSON-LD by page type without adding fake schema.", table=admin_table([("pageType", "Page type"), ("schema", "Schema"), ("status", "Status"), ("required", "Required fields")], admin_schema_rows(), title="Structured data"), panels=[{"title": "Override TODO", "body": "Schema overrides should be stored per page in data/admin/pages.json after final field model is approved."}], message=msg, message_kind=kind)
    if section == "internal-links":
        return admin_cms_render("internal-links", "Internal Links Manager", "Audit country → city, city → place and related guide links.", table=admin_table([("source", "Source"), ("target", "Target"), ("anchor", "Anchor"), ("type", "Type"), ("status", "Status")], admin_internal_link_rows(limit=admin_table_source_limit()), title="Internal links", total=admin_internal_link_rows_total()), message=msg, message_kind=kind)
    if section == "languages":
        return admin_cms_render("languages", "Localization / Languages", "Manage language availability, hreflang mapping, fallback and audio coverage.", table=admin_table([("language", "Language"), ("code", "Code"), ("hreflang", "Hreflang"), ("enabled", "Enabled"), ("fallback", "Fallback"), ("audio", "Audio manifests"), ("missingTranslations", "Missing translations")], admin_language_rows(), title="Languages"), message=msg, message_kind=kind)
    if section == "users":
        rows = [{"email": ADMIN_EMAIL, "role": "Super Admin", "status": "Active", "source": "ADMIN_EMAIL / ADMIN_PASSWORD_HASH env", "permissions": "Everything"}]
        return admin_cms_render("users", "Users / Admin Roles", "Protected admin users and planned role model.", table=admin_table([("email", "Email"), ("role", "Role"), ("status", "Status"), ("source", "Source"), ("permissions", "Permissions")], rows, title="Users"), panels=[{"title": "TODO: multi-user DB", "body": "Current project has env/session auth only. Add a users table before per-editor permissions, password reset and audit ownership can be fully production-grade."}], message=msg, message_kind=kind)
    if section == "logs":
        revisions = load_admin_revisions(120)
        rows = revisions[: admin_table_source_limit() + 1] or load_access_events(max_rows=admin_table_source_limit() + 1, days=14)
        return admin_cms_render("logs", "Logs", "Review admin revisions, audio/content events and traffic diagnostics.", table=admin_table([("iso", "Date"), ("user", "User"), ("action", "Action"), ("entityType", "Entity type"), ("entityName", "Entity"), ("status", "Status"), ("path", "Path")], rows, title="Recent logs"), message=msg, message_kind=kind)
    if section == "settings":
        return admin_cms_render("settings", "Settings", "General, audio, map, SEO and media configuration.", forms=[{"type": "settings", "value": load_admin_settings()}], message=msg, message_kind=kind)
    abort(404)


@app.route("/admin/countries", methods=["GET", "POST"])
def admin_countries():
    return admin_cms_section_response("countries")


@app.route("/admin/cities", methods=["GET", "POST"])
def admin_cities():
    return admin_cms_section_response("cities")


@app.route("/admin/places", methods=["GET", "POST"])
def admin_places():
    return admin_cms_section_response("places")


@app.route("/admin/audio", methods=["GET", "POST"])
def admin_audio_manager():
    return admin_cms_section_response("audio")


@app.route("/admin/content", methods=["GET", "POST"])
def admin_content_manager():
    return admin_cms_section_response("content")


@app.route("/admin/landing-pages", methods=["GET", "POST"])
def admin_landing_pages():
    return admin_cms_section_response("landing-pages")


@app.route("/admin/media", methods=["GET", "POST"])
def admin_media_library():
    return admin_cms_section_response("media")


@app.route("/admin/seo", methods=["GET", "POST"])
def admin_seo_manager():
    return admin_cms_section_response("seo")


@app.route("/admin/sitemap", methods=["GET", "POST"])
def admin_sitemap_manager():
    return admin_cms_section_response("sitemap")


@app.route("/admin/robots", methods=["GET", "POST"])
def admin_robots_manager():
    return admin_cms_section_response("robots")


@app.route("/admin/redirects", methods=["GET", "POST"])
def admin_redirects_manager():
    return admin_cms_section_response("redirects")


@app.route("/admin/schema", methods=["GET", "POST"])
def admin_schema_manager():
    return admin_cms_section_response("schema")


@app.route("/admin/internal-links", methods=["GET", "POST"])
def admin_internal_links_manager():
    return admin_cms_section_response("internal-links")


@app.route("/admin/languages", methods=["GET", "POST"])
def admin_languages_manager():
    return admin_cms_section_response("languages")


@app.route("/admin/users", methods=["GET", "POST"])
def admin_users_manager():
    return admin_cms_section_response("users")


@app.route("/admin/logs", methods=["GET", "POST"])
def admin_logs_manager():
    return admin_cms_section_response("logs")


@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings_manager():
    return admin_cms_section_response("settings")


@app.get("/admin")
def admin_dashboard():
    return admin_cms_section_response("dashboard")


@app.route("/admin/users/<user_id>", methods=["GET", "POST"])
def admin_user_detail(user_id: str):
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp
    users = cms_collection_rows("siteUsers")
    user = next((row for row in users if str(row.get("id") or "") == str(user_id)), None)
    if not user:
        abort(404)
    if request.method == "POST":
        action = clean_plain_text(request.form.get("action") or "", 60)
        if action == "deactivate":
            user = update_site_user(user_id, {"status": "disabled"}) or user
        elif action == "activate":
            user = update_site_user(user_id, {"status": "active"}) or user
        elif action == "verify":
            user = update_site_user(user_id, {"emailVerified": True, "status": "active", "emailVerifiedAt": utc_now_iso()}) or user
        elif action == "resend":
            send_verification_email(user, force=True)
        admin_revision_log(f"user_{action}", "siteUser", str(user.get("email") or user_id))
        return redirect(f"/admin/users/{user_id}")
    history = listening_history_for_user(user_id, limit=100)
    favorites = favorites_for_user(user_id, limit=100)
    user_email = str(user.get("email") or "").lower()
    comments = [
        row for row in all_comment_rows()
        if str(row.get("userId") or "") == user_id or str(row.get("authorEmail") or "").lower() == user_email
    ]
    ratings = [row for row in cms_collection_rows("blogRatings") if str(row.get("userId") or "") == user_id or str(row.get("email") or "").lower() == str(user.get("email") or "").lower()]
    return render_template(
        "admin_user_detail.html",
        title=f"User: {user.get('email')}",
        subtitle="Profile, listening history, favorites and security actions.",
        admin_groups=admin_group_nav("admins/users"),
        active_path="admins/users",
        user=user,
        public_user=public_site_user(user),
        history=history,
        favorites=favorites,
        comments=comments,
        ratings=ratings,
        seo_title=f"User detail | {BRAND_NAME} CMS",
        seo_desc="Admin user detail.",
        body_class="PageAdminCms",
        use_leaflet=False,
        T=t(DEFAULT_LANG),
    )


def admin_cms_section_response(section: str) -> Response:
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp

    section = (section or "dashboard").strip("/")
    alias = {
        "dashboard": "dashboard",
        "blog": "blog/articles",
        "pages": "pages/all",
        "countries": "pages/countries",
        "cities": "pages/cities",
        "places": "pages/places",
        "audio": "audio/files",
        "media": "media/images",
        "seo": "seo/audit",
        "subscriptions": "subscriptions/subscribers",
        "subscription": "subscriptions/subscribers",
        "contacts": "contacts/messages",
        "comments": "comments",
        "internal-links": "internal-links",
        "languages": "settings/languages",
        "users": "admins/users",
        "settings": "settings/general",
        "logs": "logs/actions",
        "content": "pages/all",
    }
    section = alias.get(section, section)
    msg = str(request.args.get("msg") or "").strip()
    kind = str(request.args.get("kind") or "info").strip().lower()
    if kind not in {"info", "success", "warning", "error"}:
        kind = "info"

    if request.method == "POST":
        if section == "robots":
            save_robots_text(request.form.get("robots_text") or "")
            return redirect("/admin/robots?msg=Robots.txt+saved.&kind=success", code=302)
        if section.startswith("settings"):
            save_admin_settings(request.form)
            return redirect("/admin/settings/general?msg=Settings+saved.&kind=success", code=302)
        if section == "redirects":
            msg, kind = admin_add_redirect_from_form()
            return redirect(f"/admin/redirects?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)
        if section.startswith("audio"):
            msg, kind = admin_handle_audio_post()
            return redirect(f"/admin/audio/files?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)
        if section.startswith("media"):
            msg, kind = admin_handle_media_post()
            return redirect(f"/admin/media/images?{urllib.parse.urlencode({'msg': msg, 'kind': kind})}", code=302)
        if section.startswith("translations"):
            msg, kind = save_ui_translation_from_form(request.form)
            return redirect(f"/admin/translations/ui?{urllib.parse.urlencode({'msg': msg, 'kind': kind, 'key': request.form.get('key') or ''})}", code=302)

    if section.startswith("comments/"):
        parts = section.split("/")
        comment_ref = urllib.parse.unquote(parts[1]) if len(parts) >= 2 else ""
        action = parts[2] if len(parts) >= 3 else ""
        if action in {"approve", "reject", "spam", "delete"}:
            status = {"approve": "approved", "reject": "rejected", "spam": "spam", "delete": "deleted"}[action]
            update_comment_status(comment_ref, status)
            return redirect("/admin/comments?msg=Comment+updated.&kind=success", code=302)
        panels = admin_comment_detail_panel(comment_ref)
        if panels is None:
            abort(404)
        encoded_ref = urllib.parse.quote(comment_ref, safe="")
        table = admin_table(
            [("actions", "Actions")],
            [{
                "actions": " ".join([
                    admin_action_link("Approve", f"/admin/comments/{encoded_ref}/approve"),
                    admin_action_link("Reject", f"/admin/comments/{encoded_ref}/reject"),
                    admin_action_link("Spam", f"/admin/comments/{encoded_ref}/spam"),
                    admin_action_link("Delete", f"/admin/comments/{encoded_ref}/delete"),
                    admin_action_link("Back", "/admin/comments"),
                ])
            }],
            title="Moderation",
            total=1,
        )
        return admin_cms_render("comments", "Comment detail", "Review one public comment and moderate it.", panels=panels, table=table, message=msg, message_kind=kind)

    if section.startswith("blog/comments/"):
        parts = section.split("/")
        if len(parts) >= 4:
            comment_id, action = parts[2], parts[3]
            rows = []
            for row in cms_collection_rows("blogComments"):
                if str(row.get("id") or "") == comment_id:
                    if action == "approve":
                        row["status"] = "approved"
                    elif action == "reject":
                        row["status"] = "rejected"
                    elif action == "spam":
                        row["status"] = "spam"
                    row["updatedAt"] = utc_now_iso()
                    admin_revision_log(f"blog_comment_{action}", "blogComment", comment_id)
                rows.append(row)
            save_cms_collection_rows("blogComments", rows)
        return redirect("/admin/blog/comments?msg=Comment+updated.&kind=success", code=302)

    if section == "dashboard":
        return admin_cms_render(
            "dashboard",
            "Audio Guide CMS",
            "Production CMS for blog, pages, audio, media, SEO, subscriptions, admins, settings and logs.",
            metrics=admin_dashboard_metrics(),
            problems=admin_problem_rows(),
            table=admin_table([("problem", "Problem"), ("count", "Count"), ("manager", "Manager")], admin_problem_rows(), title="Problems to fix"),
            message=msg,
            message_kind=kind,
        )

    table: Optional[Dict[str, Any]] = None
    forms: List[Dict[str, Any]] = []
    panels: List[Dict[str, Any]] = []
    metrics: List[Dict[str, Any]] = []
    title = "CMS"
    subtitle = "Manage content."

    if section == "blog/articles":
        title = "Blog articles"
        subtitle = "Create, edit, publish, draft, archive and optimize blog articles."
        table = admin_table(
            [("title", "Title"), ("language", "Lang"), ("category", "Category"), ("author", "Author"), ("status", "Status"), ("comments", "Comments"), ("likes", "Likes"), ("rating", "Rating"), ("seo", "SEO"), ("updatedAt", "Updated"), ("actions", "Actions")],
            admin_blog_article_rows(limit=admin_table_source_limit()),
            title="Blog articles",
            total=len(load_blog_posts(include_drafts=True)),
        )
    elif section == "blog/authors":
        title = "Blog authors"
        subtitle = "Authors, bios, avatars and author SEO."
        table = admin_table([("name", "Name"), ("slug", "Slug"), ("email", "Email"), ("role", "Role"), ("status", "Status"), ("updatedAt", "Updated")], admin_cms_store_table_rows("blogAuthors", ["name", "slug", "email", "role", "status", "updatedAt"], limit=admin_table_source_limit()), title="Blog authors", total=len(cms_collection_rows("blogAuthors")))
    elif section == "blog/categories":
        title = "Blog categories"
        subtitle = "Category pages with SEO text, FAQ, order and metadata."
        table = admin_table([("name", "Name"), ("h1", "H1"), ("slug", "Slug"), ("language", "Lang"), ("status", "Status"), ("order", "Order"), ("updatedAt", "Updated")], admin_cms_store_table_rows("blogCategories", ["name", "h1", "slug", "language", "status", "order", "updatedAt"], limit=admin_table_source_limit()), title="Blog categories", total=len(cms_collection_rows("blogCategories")))
    elif section == "blog/comments":
        title = "Blog comments"
        subtitle = "Moderate public comments before they appear on blog posts."
        table = admin_table([("createdAt", "Date"), ("page", "Article"), ("pageType", "Type"), ("language", "Lang"), ("name", "Name"), ("email", "Email"), ("excerpt", "Comment"), ("status", "Status"), ("actions", "Actions")], admin_comment_rows(limit=admin_table_source_limit(), page_type_filter="blog_article"), title="Blog comments", total=admin_comment_rows_total(page_type_filter="blog_article"))
    elif section == "blog/ratings":
        title = "Blog ratings"
        subtitle = "Real user ratings only. AggregateRating schema can use approved real data."
        table = admin_table([("article", "Article"), ("rating", "Average rating"), ("ratingNumber", "Number"), ("ratingsCount", "Count"), ("lastRating", "Last rating"), ("actions", "Actions")], admin_blog_rating_rows(limit=admin_table_source_limit()), title="Blog ratings", total=len(cms_collection_rows("blogRatings")))
    elif section == "blog/likes":
        title = "Blog likes"
        subtitle = "Cookie/session/IP limited blog likes."
        table = admin_table([("article", "Article"), ("likes", "Likes"), ("status", "Status"), ("updatedAt", "Updated")], admin_blog_like_rows(limit=admin_table_source_limit()), title="Blog likes", total=len(cms_collection_rows("blogLikes")))
    elif section == "comments":
        title = "Comments"
        subtitle = "Universal moderation for blog, landing, city, country, place and enabled static pages."
        table = admin_table(
            [("createdAt", "Date"), ("page", "Page"), ("pageType", "Type"), ("language", "Lang"), ("name", "Name"), ("email", "Email"), ("excerpt", "Comment"), ("status", "Status"), ("actions", "Actions")],
            admin_comment_rows(limit=admin_table_source_limit()),
            title="All comments",
            total=admin_comment_rows_total(),
        )
    elif section.startswith("translations"):
        title = {
            "translations/ui": "UI Translations",
            "translations/pages": "Page Translations",
            "translations/missing": "Missing Translations",
            "translations/import-export": "Translation Import / Export",
            "translations/qa": "Translation QA",
        }.get(section, "Translations")
        subtitle = "Database-backed translation keys, page translation status, missing strings and import/export workflow."
        if section == "translations/pages":
            rows = admin_page_translation_rows(limit=admin_table_source_limit())
            table = admin_table(
                [("title", "Page"), ("type", "Type"), ("url", "URL"), ("en", "EN"), ("fr", "FR"), ("es", "ES"), ("it", "IT"), ("uk", "UK"), ("de", "DE"), ("updatedAt", "Updated"), ("actions", "Actions")],
                rows,
                title="Page translation status",
                total=len(rows),
            )
        elif section == "translations/missing":
            rows = admin_missing_translation_rows(limit=admin_table_source_limit())
            table = admin_table([("key", "Key"), ("namespace", "Namespace"), ("language", "Lang"), ("description", "English source"), ("actions", "Actions")], rows, title="Missing UI translations", total=len(rows))
        elif section == "translations/qa":
            rows = admin_translation_progress_rows()
            table = admin_table([("language", "Language"), ("translated", "Translated"), ("reviewed", "Reviewed"), ("progress", "Progress")], rows, title="Translation progress", total=len(rows))
            metrics = [{"label": row["language"], "value": row["progress"], "note": row["translated"]} for row in rows]
        elif section == "translations/import-export":
            rows = admin_translation_progress_rows()
            table = admin_table([("language", "Language"), ("translated", "Translated"), ("reviewed", "Reviewed"), ("progress", "Progress")], rows, title="Export summary", total=len(rows))
            panels = [
                {
                    "title": "JSON storage",
                    "body": f"UI translations are stored in {ADMIN_TRANSLATIONS_PATH.relative_to(ROOT)}. Export/import endpoints are prepared as CMS actions; current manual export is this JSON file.",
                }
            ]
        else:
            selected_key = clean_plain_text(request.args.get("key") or "nav_start_guide", 180)
            selected_lang = public_lang_code(internal_lang_code(request.args.get("lang") or DEFAULT_LANG))
            selected_row = {}
            for row in load_translations_store().get("uiTranslations") or []:
                if isinstance(row, dict) and row.get("key") == selected_key and row.get("language") == selected_lang:
                    selected_row = row
                    break
            forms = [{"type": "uiTranslation", "row": selected_row or {"key": selected_key, "language": selected_lang, "status": "missing"}}]
            table = admin_table(
                [("namespace", "Namespace"), ("key", "Key"), ("en", "EN"), ("fr", "FR"), ("es", "ES"), ("it", "IT"), ("uk", "UK"), ("de", "DE"), ("status", "Status"), ("updatedAt", "Updated"), ("actions", "Actions")],
                admin_ui_translation_rows(limit=admin_table_source_limit()),
                title="UI translation keys",
                total=len(admin_ui_translation_rows(limit=100000)),
            )
    elif section == "landing-pages":
        title = "Landing Pages"
        subtitle = "Home, country and custom landing pages with SEO text and FAQ before footer."
        rows = admin_landing_page_records(limit=admin_table_source_limit())
        for row in rows:
            row["actions"] = admin_action_link("Edit", f"/admin/pages/edit?lang={row.get('language')}&pageKey={admin_page_key_for_record(row)}")
        table = admin_table([("title", "Title"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("status", "Status"), ("seo", "SEO"), ("seoText", "SEO text"), ("faqStatus", "FAQ"), ("actions", "Actions")], rows, title="Landing pages", total=admin_landing_page_records_total())
    elif section.startswith("pages/"):
        page_kind = section.split("/", 1)[1]
        labels = {"all": "All pages", "home": "Home Pages", "cities": "City Pages", "countries": "Country Pages", "places": "Place Pages", "technical": "Technical Pages"}
        title = labels.get(page_kind, "Pages")
        subtitle = "Edit H1, slug, metadata, canonical, redirects, SEO text, FAQ and schema by language."
        rows = admin_generic_page_rows(page_kind, limit=admin_table_source_limit())
        total_type = {"home": "home", "cities": "city", "countries": "country", "places": "place", "technical": "static"}.get(page_kind, "")
        table = admin_table([("title", "Page title"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("status", "Status"), ("indexing", "Indexing"), ("seo", "SEO"), ("seoText", "SEO text"), ("faqStatus", "FAQ"), ("audio", "Audio"), ("actions", "Actions")], rows, title=title, total=admin_page_records_total(page_type=total_type, lang=request.args.get("lang") or "", q=request.args.get("q") or ""))
    elif section in {"seo/audit", "seo"}:
        title = "SEO Audit Dashboard"
        subtitle = "Missing H1/meta/canonical/hreflang/schema/SEO text/FAQ and thin content checks."
        table = admin_table([("title", "Page"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("seo", "SEO"), ("seoText", "SEO text"), ("faqStatus", "FAQ"), ("indexing", "Indexing"), ("audio", "Audio"), ("issues", "Issues"), ("actions", "Actions")], admin_seo_audit_rows(limit=admin_table_source_limit()), title="SEO audit", total=admin_page_records_total(page_type=request.args.get("type") or "", lang=request.args.get("lang") or "", q=request.args.get("q") or ""))
    elif section.startswith("audio"):
        title = {
            "audio/files": "Audio files",
            "audio/queue": "Audio generation queue",
            "audio/failed": "Audio failed",
            "audio/outdated": "Audio outdated",
            "audio/voices": "Voice settings",
        }.get(section, "Audio files")
        subtitle = "Review generated audio, upload replacements, delete bad files and track missing/failed/outdated audio."
        status_filter = "failed" if section == "audio/failed" else ""
        metrics = [{"label": "Audio files", "value": admin_audio_totals()["files"], "note": admin_audio_totals()["storage"]}, {"label": "Manifests", "value": admin_audio_totals()["manifests"], "note": AUDIO_BUILD_AUDIO_VERSION}, {"label": "Failed", "value": admin_audio_totals()["failed"], "note": "sections"}]
        table = admin_table([("entity", "Entity"), ("name", "Name"), ("country", "Country"), ("city", "City"), ("language", "Lang"), ("voice", "Voice"), ("status", "Status"), ("sections", "Sections"), ("failed", "Failed"), ("size", "Size"), ("path", "Path")], admin_audio_queue_rows(status_filter=status_filter, limit=admin_table_source_limit()), title=title, total=admin_audio_totals()["manifests"])
        forms = [{"type": "audioUpload"}]
        if section == "audio/voices":
            table = admin_table([("language", "Language"), ("female", "Female voice"), ("male", "Male voice"), ("provider", "Provider"), ("status", "Status")], [{"language": l.upper(), "female": "High-quality voice", "male": "High-quality voice", "provider": "System / configured provider", "status": "Configured in settings"} for l in LANG_ORDER], title="Voice settings")
            forms = [{"type": "settings", "value": load_admin_settings()}]
    elif section.startswith("media"):
        title = {"media/images": "Images", "media/galleries": "Galleries", "media/files": "Files"}.get(section, "Media")
        subtitle = "Upload, index and reuse media without loading full-size files in tables."
        if section == "media/galleries":
            table = admin_table([("name", "Gallery"), ("status", "Status"), ("updatedAt", "Updated")], admin_cms_store_table_rows("galleries", ["name", "status", "updatedAt"], limit=admin_table_source_limit()), title="Galleries", total=len(cms_collection_rows("galleries")))
        else:
            table = admin_table([("filename", "Filename"), ("type", "Type"), ("size", "Size"), ("path", "Path"), ("alt", "Alt"), ("used", "Used on"), ("updated", "Updated")], admin_media_records(limit=admin_table_source_limit()), title=title, total=admin_media_records_total())
            forms = [{"type": "mediaUpload"}]
    elif section.startswith("subscriptions"):
        title = {"subscriptions/forms": "Subscription forms", "subscriptions/subscribers": "Subscribers", "subscriptions/export": "Export subscribers"}.get(section, "Subscriptions")
        subtitle = "Manage subscription form submissions with name, email, source page, date/time and request metadata."
        if section == "subscriptions/forms":
            table = admin_table([("name", "Form"), ("language", "Lang"), ("source", "Source"), ("status", "Status"), ("createdAt", "Created")], admin_cms_store_table_rows("subscriptionForms", ["name", "language", "source", "status", "createdAt"], limit=admin_table_source_limit()), title="Subscription forms", total=len(cms_collection_rows("subscriptionForms")))
        else:
            table = admin_table(
                [("submittedAt", "Date / time"), ("name", "Name"), ("email", "Email"), ("language", "Lang"), ("sourcePage", "Source page"), ("notification", "Email notification"), ("status", "Status"), ("ip", "IP"), ("userAgent", "User agent")],
                admin_subscription_rows(limit=admin_table_source_limit()),
                title="Subscribers",
                total=len(cms_collection_rows("subscribers")),
            )
            if section == "subscriptions/export":
                panels = [{"title": "CSV export", "body": "TODO: add streamed CSV export endpoint after subscriber volume is known. Current data lives in data/admin/cms.json subscribers[]."}]
    elif section.startswith("contacts"):
        title = "Contact messages"
        subtitle = "Messages from the public contact form with name, email, message, source page, date/time and request metadata."
        table = admin_table(
            [("submittedAt", "Date / time"), ("name", "Name"), ("email", "Email"), ("message", "Message"), ("language", "Lang"), ("sourcePage", "Source page"), ("status", "Status"), ("ip", "IP"), ("userAgent", "User agent")],
            admin_contact_message_rows(limit=admin_table_source_limit()),
            title="Contact messages",
            total=len(cms_collection_rows("contactMessages")),
        )
    elif section.startswith("admins"):
        title = {"admins/users": "Users", "admins/roles": "Roles / permissions", "admins/login-history": "Login history"}.get(section, "Admins")
        subtitle = "Registered site users, admin users and role-ready permission model."
        if section == "admins/roles":
            table = admin_table([("name", "Role"), ("permissions", "Permissions")], admin_cms_store_table_rows("roles", ["name", "permissions"], limit=admin_table_source_limit()), title="Roles", total=len(cms_collection_rows("roles")))
        elif section == "admins/login-history":
            table = admin_table([("email", "Email"), ("status", "Status"), ("ip", "IP"), ("createdAt", "Created")], admin_cms_store_table_rows("loginHistory", ["email", "status", "ip", "createdAt"], limit=admin_table_source_limit()), title="Login history", total=len(cms_collection_rows("loginHistory")))
        else:
            table = admin_table(
                [("email", "Email"), ("name", "Name"), ("type", "Type"), ("emailVerified", "Email verified"), ("registrationCountry", "Registration country"), ("registeredAt", "Registered"), ("lastLoginAt", "Last login"), ("status", "Status"), ("listening", "Listening"), ("favorites", "Favorites"), ("subscription", "Subscription"), ("ip", "IP"), ("actions", "Actions")],
                admin_user_rows(limit=admin_table_source_limit()),
                title="Users",
                total=len(cms_collection_rows("siteUsers")) + len(cms_collection_rows("adminUsers")),
            )
    elif section == "internal-links":
        title = "Internal Links Manager"
        subtitle = "Find source pages, target pages, anchors, orphan pages and broken internal links."
        table = admin_table([("source", "Source"), ("target", "Target"), ("anchor", "Anchor"), ("type", "Type"), ("status", "Status")], admin_internal_link_rows(limit=admin_table_source_limit()), title="Internal links", total=admin_internal_link_rows_total())
    elif section in {"robots", "sitemap", "schema", "redirects"} or section.startswith("settings"):
        title = {"robots": "Robots.txt", "sitemap": "Sitemap", "schema": "Schema settings", "redirects": "Redirects", "settings/general": "General settings", "settings/languages": "Languages", "settings/analytics": "Analytics settings"}.get(section, "Settings")
        subtitle = "Technical SEO, indexing and site configuration."
        if section == "robots":
            forms = [{"type": "robots", "value": load_robots_text()}]
        elif section == "sitemap":
            sitemap = admin_sitemap_records(limit=admin_table_source_limit())
            metrics = [{"label": "Sitemap URLs", "value": sitemap["total"], "note": "generated"}, {"label": "Languages", "value": len(LANG_ORDER), "note": "hreflang"}]
            table = admin_table([("title", "Page"), ("url", "URL"), ("type", "Type"), ("language", "Lang"), ("indexing", "Indexing")], sitemap["rows"], title="Sitemap preview", total=sitemap["total"])
        elif section == "schema":
            table = admin_table([("pageType", "Page type"), ("schema", "Schema"), ("status", "Status"), ("required", "Required fields")], admin_schema_rows(), title="Schema preview")
        elif section == "redirects":
            table = admin_table([("source", "Source"), ("target", "Target"), ("code", "Code"), ("language", "Lang"), ("active", "Active"), ("createdAt", "Created")], load_admin_redirects(), title="Redirects", total=len(load_admin_redirects()))
            forms = [{"type": "redirect"}]
        elif section == "settings/languages":
            table = admin_table([("language", "Language"), ("code", "Code"), ("hreflang", "Hreflang"), ("enabled", "Enabled"), ("fallback", "Fallback"), ("audio", "Audio manifests"), ("missingTranslations", "Missing translations")], admin_language_rows(), title="Languages")
        else:
            forms = [{"type": "settings", "value": load_admin_settings()}]
    elif section.startswith("logs"):
        title = {"logs/actions": "Admin actions", "logs/audio": "Audio generation logs", "logs/seo": "SEO changes", "logs/errors": "Errors"}.get(section, "Logs")
        subtitle = "Audit log of admin, content, SEO and audio activity."
        rows = load_admin_revisions(admin_table_source_limit() + 1)
        if section == "logs/audio":
            rows = [r for r in rows if "audio" in str(r.get("action") or "").lower()]
        if section == "logs/seo":
            rows = [r for r in rows if "seo" in str(r.get("action") or "").lower() or "page" in str(r.get("entityType") or "").lower()]
        if section == "logs/errors":
            rows = [r for r in rows if str(r.get("status") or "") == "error"]
        table = admin_table([("iso", "Date"), ("user", "User"), ("action", "Action"), ("entityType", "Entity type"), ("entityName", "Entity"), ("status", "Status"), ("ip", "IP")], rows, title=title)
    else:
        abort(404)

    return admin_cms_render(section, title, subtitle, metrics=metrics, table=table, panels=panels, forms=forms, message=msg, message_kind=kind)


@app.route("/admin/pages/edit", methods=["GET", "POST"])
def admin_page_editor_v2():
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp
    if request.method == "POST":
        return admin_pages()
    lang = normalize_lang(request.args.get("lang") or DEFAULT_LANG)
    page_key = str(request.args.get("pageKey") or "home").strip() or "home"
    current = load_admin_page_content(page_key, lang)
    split = split_admin_page_key(page_key)
    public_url = admin_page_public_url_from_key(page_key, lang, fallback_slug=current.get("slug") or "")
    page_comments = admin_comment_rows_for_page(page_key, lang, limit=50)
    return render_template(
        "admin_page_editor.html",
        lang=lang,
        page_key=page_key,
        split=split,
        current=current,
        public_url=public_url,
        page_comments=page_comments,
        page_options=admin_quick_page_options(lang),
        admin_groups=admin_group_nav("pages/all"),
        active_path="pages/all",
        admin_nav=admin_nav_items("pages/all"),
        admin_msg=str(request.args.get("msg") or ""),
        admin_msg_kind=str(request.args.get("kind") or "info"),
        seo_title=f"Edit page | {BRAND_NAME} CMS",
        seo_desc="Edit H1, slug, SEO, FAQ, redirects, canonical and content blocks.",
        seo_type="website",
        seo_image="/static/img/place-placeholder.svg",
        T=t(lang),
        body_class="PageAdmin PageAdminCms",
        use_leaflet=False,
    )


@app.route("/admin/<path:cms_path>", methods=["GET", "POST"])
def admin_cms_path(cms_path: str):
    return admin_cms_section_response(cms_path)


@app.post("/admin/audio-build")
def admin_audio_build():
    auth_resp = require_admin_auth()
    if auth_resp is not None:
        return auth_resp

    lang = normalize_lang(request.form.get("lang") or DEFAULT_LANG)
    gender = str(request.form.get("gender") or "female").strip().lower()
    country_slug = str(request.form.get("country") or "").strip().lower()
    city_slug = str(request.form.get("city") or "").strip().lower()
    place_slug = str(request.form.get("place") or "").strip().lower()

    if gender not in {"female", "male"}:
        q = urllib.parse.urlencode({"lang": lang, "country": country_slug, "city": city_slug, "msg": "Bad gender", "kind": "error"})
        return redirect(f"/admin?{q}", code=302)

    if (country_slug, city_slug) not in CITY_BY_COUNTRYSLUG_CITYSLUG:
        q = urllib.parse.urlencode({"lang": lang, "country": country_slug, "msg": "City not found", "kind": "error"})
        return redirect(f"/admin?{q}", code=302)

    if place_slug:
        if (country_slug, city_slug, place_slug) not in PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG:
            q = urllib.parse.urlencode(
                {"lang": lang, "country": country_slug, "city": city_slug, "msg": "Place not found", "kind": "error"}
            )
            return redirect(f"/admin?{q}", code=302)

    out = enqueue_audio_build(country_slug, city_slug, lang, gender, place_slug=place_slug or None)
    message = f"{out.get('label') or out.get('status') or 'Queued'} ({country_slug}/{city_slug}{'/' + place_slug if place_slug else ''}, {lang}, {gender})"
    kind = "success" if out.get("ready") else "info"
    q = urllib.parse.urlencode(
        {
            "lang": lang,
            "country": country_slug,
            "city": city_slug,
            "msg": message,
            "kind": kind,
        }
    )
    return redirect(f"/admin?{q}", code=302)


@app.get("/pages/<slug>")
def static_page_en(slug: str):
    return managed_flat_page(DEFAULT_LANG, "static", slug)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/pages/<slug>")
def static_page(lang: str, slug: str):
    return managed_flat_page(lang, "static", slug)


@app.get("/landing/<slug>")
def managed_landing_page_en(slug: str):
    return managed_flat_page(DEFAULT_LANG, "landing", slug)


@app.get("/<re('fr|es|it|ua|uk|de'):lang>/landing/<slug>")
def managed_landing_page(lang: str, slug: str):
    return managed_flat_page(lang, "landing", slug)


def managed_flat_page(lang: str, page_type: str, slug: str):
    lang = normalize_lang(lang)
    page_type = str(page_type or "static").strip().lower()
    slug = slugify(slug)
    page_key = admin_page_key(page_type, place_slug=slug)
    content = admin_content_for_public(page_key, lang)
    if not html_to_plain_text(content.get("seoTextHtml") or "", 2000) and not content.get("faq"):
        abort(404)
    title = clean_plain_text(content.get("h1") or content.get("seoTextTitle") or slug.replace("-", " ").title(), 180)
    prefix = "landing" if page_type == "landing" else "pages"
    alts = [lang_alt(lang_slug, (f"/{prefix}/{slug}" if lang_slug == DEFAULT_LANG else f"/{lang_slug}/{prefix}/{slug}")) for lang_slug in LANG_ORDER]
    alts.append({"lang": "x-default", "url": absolute_url(f"/{prefix}/{slug}")})
    return render_template(
        "static_page.html",
        lang=lang,
        title=title,
        admin_content=content,
        seo_title=f"{title} | {BRAND_NAME}",
        seo_desc=clean_plain_text(content.get("seoTextIntro") or html_to_plain_text(content.get("seoTextHtml") or "", 180), 180),
        SEO_CANONICAL_URL=absolute_url(f"/{prefix}/{slug}" if lang == DEFAULT_LANG else f"/{lang}/{prefix}/{slug}"),
        SEO_HREFLANG_LINKS=alts,
        T=t(lang),
        body_class="PageStatic",
        use_leaflet=False,
    )


# -------- pages (language first) --------
@app.get("/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>")
def country_page(lang: str, country_slug: str):
    lang = normalize_lang(lang)
    if country_slug == "sitemap.xml":
        return sitemap_language_xml(lang)
    if country_slug.endswith(".xml"):
        category = country_slug[:-4]
        if category in {"countries", "city", "cities", "places", "blog", "categories", "pages", "lps"}:
            return sitemap_language_category_xml(lang, category)
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)

    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        abort(404)
    country_view = dict(country)
    country_view["displayName"] = country_display_name_cached_for_lang(country_view, lang)
    country_view["name"] = country_view["displayName"]

    cities_raw = [
        c
        for c in target_country_cities(country_slug)
        if city_translation_exists(country_slug, str(c.get("citySlug") or ""), lang)
    ]
    top_city_slugs = {str(c.get("citySlug") or "").strip().lower() for c in cities_raw}
    top_place_groups = []
    for group in global_top_place_groups_for_lang(lang, TARGET_CITIES_PER_COUNTRY, COUNTRY_TOP_PLACES_PER_CITY, country_slug):
        group_city_slug = str(group.get("citySlug") or "").strip().lower()
        if group_city_slug not in top_city_slugs:
            continue
        group_places = [
            p
            for p in (group.get("places") or [])
            if place_translation_exists(
                country_slug,
                group_city_slug,
                str(p.get("slug") or p.get("placeSlug") or ""),
                lang,
            )
        ]
        if group_places:
            row = dict(group)
            row["places"] = group_places
            top_place_groups.append(row)
    top_place_groups = top_place_groups[:TARGET_CITIES_PER_COUNTRY]
    top_places = [p for group in top_place_groups for p in group.get("places", [])]
    lat, lon = country_center(country_slug)

    city_place_count_by_slug: Dict[str, int] = {
        city_slug_key: min(len(dedupe_places(v)), TARGET_PLACES_PER_CITY)
        for (cslug, city_slug_key), v in CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.items()
        if cslug == country_slug and city_slug_key in top_city_slugs
    }
    country_place_total = len(top_places)
    cities: List[Dict[str, Any]] = []
    for c in cities_raw:
        row = dict(c)
        row["placesCount"] = int(city_place_count_by_slug.get(str(c.get("citySlug") or ""), 0))
        row["displayName"] = city_display_name_cached_for_lang(row, lang)
        row["name"] = row["displayName"]
        cities.append(row)
    top_places_view: List[Dict[str, Any]] = []
    for p in top_places:
        row = dict(p)
        row["categoryLabel"] = localized_category_label(str(row.get("category") or "Landmark"), lang)
        row["displayName"] = place_display_name_cached_for_lang(row, lang)
        row["name"] = row["displayName"]
        top_places_view.append(row)
    trn = t(lang)
    seo_title = i18n_fmt(
        trn["seo_country_title_tpl"],
        country=country_view["displayName"],
    )
    seo_desc = i18n_fmt(
        trn["seo_country_desc_tpl"],
        country=country_view["displayName"],
        cities=str(TARGET_CITIES_PER_COUNTRY),
        places=str(country_place_total),
    )
    seo_keywords = i18n_fmt(
        trn["seo_country_keywords_tpl"],
        country=country_view["displayName"],
    )
    seo_image = f"/media/country/{lang}/{country_slug}"
    auto_faq = auto_faq_for_page(
        "country",
        lang=lang,
        country_name=country_view["displayName"],
        city_names=faq_city_names_for_page(country_slug=country_slug, lang=lang, limit=8),
        place_names=faq_place_names_for_page(country_slug=country_slug, lang=lang, limit=8),
    )
    auto_faq_schema = faq_schema_for_items(auto_faq.get("items", []))
    page_url = country_url(lang, country_slug)
    audio_rating = audio_rating_stats("country", country_slug=country_slug, city_slug="__country__")
    country_entity = {
        "@type": ["Country", "TouristDestination"],
        "@id": f"{schema_abs_url(page_url)}#main-entity",
        "name": country_view["displayName"],
        "url": schema_abs_url(page_url),
    }
    city_schema_items = [
        {"name": c.get("displayName") or c.get("name") or "", "url": city_url(lang, country_slug, str(c.get("citySlug") or ""))}
        for c in cities[:12]
        if c.get("citySlug")
    ]
    place_schema_items = [
        {
            "name": p.get("displayName") or p.get("name") or "",
            "url": place_url(
                lang,
                country_slug,
                str(p.get("citySlug") or ""),
                str(p.get("slug") or p.get("placeSlug") or ""),
            ),
        }
        for p in top_places_view[:24]
        if p.get("citySlug") and (p.get("slug") or p.get("placeSlug"))
    ]
    country_schema = schema_graph(
        page_type="CollectionPage",
        lang=lang,
        page_url=page_url,
        title=seo_title,
        description=seo_desc,
        image_url=seo_image,
        breadcrumbs=[(trn.get("common_home") or "Home", landing_url(lang)), (country_view["displayName"], page_url)],
        faq_schema=auto_faq_schema,
        main_entity=country_entity,
        item_lists=[
            schema_item_list_node((trn.get("country_city_guides_tpl") or "{country} city guides").replace("{country}", country_view["displayName"]), page_url, "cities", city_schema_items),
            schema_item_list_node((trn.get("country_top_places_title_tpl") or "Top places across {country}").replace("{country}", country_view["displayName"]), page_url, "top-places", place_schema_items),
        ],
        audio_objects=schema_audio_objects_for_page(
            page_url=page_url,
            entity_name=country_view["displayName"],
            lang=lang,
            country_slug=country_slug,
            city_slug="__country__",
        ),
        rating_stats=audio_rating,
    )
    admin_content = admin_content_for_public(admin_page_key("country", country_slug=country_slug), lang)
    comments_context = public_comments_context(
        "country_page",
        f"country:{country_slug}",
        country_view["displayName"],
        page_url,
        lang,
        admin_content,
    )

    resp = make_response(
        render_template(
            "country.html",
            country=country_view,
            cities=cities,
            top_places=top_places_view,
            top_place_groups=top_place_groups,
            country_city_total=len(cities),
            country_place_total=country_place_total,
            admin_content=admin_content,
            comments_context=comments_context,
            auto_faq=auto_faq,
            auto_faq_schema=auto_faq_schema,
            schema_in_graph=True,
            center_lat=lat,
            center_lon=lon,
            seo_title=seo_title,
            seo_desc=seo_desc,
            seo_keywords=seo_keywords,
            seo_image=seo_image,
            seo_type="website",
            seo_schema=country_schema,
            audio_rating=audio_rating,
            audio_rating_entity_type="country",
            audio_rating_country_slug=country_slug,
            audio_rating_city_slug="__country__",
            audio_rating_place_slug="",
            lang=lang,
            T=trn,
            body_class="PageCountry",
            use_leaflet=True,
        )
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


@app.get("/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>/<city_slug>")
def city_page(lang: str, country_slug: str, city_slug: str):
    lang = normalize_lang(lang)
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)

    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        abort(404)
    country_view = dict(country)
    country_view["displayName"] = country_display_name_cached_for_lang(country_view, lang)
    country_view["name"] = country_view["displayName"]

    city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
    if not city:
        # fallback: try find by name slug in this country
        for c in CITIES_BY_COUNTRYSLUG.get(country_slug, []):
            if c.get("citySlug") == city_slug:
                city = c
                break
    if not city:
        city = TOP_PLACE_BY_COUNTRYSLUG_PLACESLUG.get((country_slug, city_slug))
    if not city:
        abort(404)

    resolved_city_slug = str(city.get("citySlug") or city_slug)
    if not city_translation_exists(country_slug, resolved_city_slug, lang):
        abort(404)
    city_view = dict(city)
    city_view["citySlug"] = resolved_city_slug
    city_view["displayName"] = city_display_name_cached_for_lang(city_view, lang)
    city_view["name"] = city_view["displayName"]
    places_view = []
    for p in dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, resolved_city_slug), [])):
        row = public_place_card_for_lang(
            p,
            lang=lang,
            country_slug=country_slug,
            city_slug=resolved_city_slug,
            country_name=country_view["displayName"],
            city_name=city_view["displayName"],
        )
        if row:
            places_view.append(row)

    trn = t(lang)
    langs_label = ", ".join(x.upper() for x in LANG_ORDER)
    seo_title = i18n_fmt(
        trn["seo_city_title_tpl"],
        city=city_view["displayName"],
        country=country_view["displayName"],
    )
    seo_desc = i18n_fmt(
        trn["seo_city_desc_tpl"],
        city=city_view["displayName"],
        country=country_view["displayName"],
        langs=langs_label,
    )
    seo_keywords = i18n_fmt(
        trn["seo_city_keywords_tpl"],
        city=city_view["displayName"],
        country=country_view["displayName"],
    )
    seo_image = f"/media/city/{CANONICAL_IMAGE_LANG}/{country_slug}/{resolved_city_slug}"
    auto_faq = auto_faq_for_page(
        "city",
        lang=lang,
        country_name=country_view["displayName"],
        city_name=city_view["displayName"],
        city_names=faq_city_names_for_page(
            country_slug=country_slug,
            lang=lang,
            limit=6,
            exclude_city_slug=resolved_city_slug,
        ),
        place_names=faq_place_names_for_page(
            country_slug=country_slug,
            city_slug=resolved_city_slug,
            lang=lang,
            limit=8,
        ),
    )
    auto_faq_schema = faq_schema_for_items(auto_faq.get("items", []))
    page_url = city_url(lang, country_slug, resolved_city_slug)
    audio_rating = audio_rating_stats("city", country_slug=country_slug, city_slug=resolved_city_slug)
    city_entity: Dict[str, Any] = {
        "@type": ["City", "TouristDestination", "Place"],
        "@id": f"{schema_abs_url(page_url)}#main-entity",
        "name": city_view["displayName"],
        "url": schema_abs_url(page_url),
        "containedInPlace": {"@type": "Country", "name": country_view["displayName"]},
    }
    geo = schema_geo_node(city_view)
    if geo:
        city_entity["geo"] = geo
    place_schema_items = [
        {
            "name": p.get("displayName") or p.get("name") or "",
            "url": str(p.get("url") or place_url(DEFAULT_LANG, country_slug, resolved_city_slug, str(p.get("slug") or p.get("placeSlug") or ""))),
        }
        for p in places_view[:24]
        if p.get("slug") or p.get("placeSlug")
    ]
    city_schema = schema_graph(
        page_type="CollectionPage",
        lang=lang,
        page_url=page_url,
        title=seo_title,
        description=seo_desc,
        image_url=seo_image,
        breadcrumbs=[
            (trn.get("common_home") or "Home", landing_url(lang)),
            (country_view["displayName"], country_url(lang, country_slug)),
            (city_view["displayName"], page_url),
        ],
        faq_schema=auto_faq_schema,
        main_entity=city_entity,
        item_lists=[
            schema_item_list_node((trn.get("places_to_visit_tpl") or "Places to visit in {city}").replace("{city}", city_view["displayName"]), page_url, "places", place_schema_items),
        ],
        audio_objects=schema_audio_objects_for_page(
            page_url=page_url,
            entity_name=city_view["displayName"],
            lang=lang,
            country_slug=country_slug,
            city_slug=resolved_city_slug,
        ),
        rating_stats=audio_rating,
    )
    admin_content = admin_content_for_public(
        admin_page_key("city", country_slug=country_slug, city_slug=resolved_city_slug),
        lang,
    )
    comments_context = public_comments_context(
        "city_page",
        f"city:{country_slug}:{resolved_city_slug}",
        city_view["displayName"],
        page_url,
        lang,
        admin_content,
    )

    resp = make_response(
        render_template(
            "city.html",
            country=country_view,
            city=city_view,
            places=places_view,
            city_places_count=len(places_view),
            admin_content=admin_content,
            comments_context=comments_context,
            auto_faq=auto_faq,
            auto_faq_schema=auto_faq_schema,
            schema_in_graph=True,
            seo_title=seo_title,
            seo_desc=seo_desc,
            seo_keywords=seo_keywords,
            seo_image=seo_image,
            seo_type="article",
            seo_schema=city_schema,
            audio_rating=audio_rating,
            audio_rating_entity_type="city",
            audio_rating_country_slug=country_slug,
            audio_rating_city_slug=resolved_city_slug,
            audio_rating_place_slug="",
            lang=lang,
            T=trn,
            wiki_lang=SUPPORTED_LANGS[lang]["wiki"],
            speech_lang=SUPPORTED_LANGS[lang]["speech"],
            body_class="PageCity",
            use_leaflet=True,
        )
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


@app.get("/<re('en|fr|es|it|ua|uk|de'):lang>/<country_slug>/<city_slug>/<place_slug>")
def place_page(lang: str, country_slug: str, city_slug: str, place_slug: str):
    lang = normalize_lang(lang)
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)

    country = COUNTRY_BY_SLUG.get(country_slug)
    if not country:
        abort(404)
    country_view = dict(country)
    country_view["displayName"] = country_display_name_cached_for_lang(country_view, lang)
    country_view["name"] = country_view["displayName"]

    city = CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug))
    if not city:
        # fallback: try find by name slug in this country
        for c in CITIES_BY_COUNTRYSLUG.get(country_slug, []):
            if c.get("citySlug") == city_slug:
                city = c
                break
    if not city:
        abort(404)

    place = PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
    if not place:
        abort(404)
    if not place_translation_exists(country_slug, city_slug, place_slug, lang):
        abort(404)

    places = dedupe_places(CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug), []))
    city_view = dict(city)
    city_view["citySlug"] = city_slug
    city_view["displayName"] = city_display_name_cached_for_lang(city_view, lang)
    city_view["name"] = city_view["displayName"]
    place_view = dict(place)
    place_view["countrySlug"] = country_slug
    place_view["citySlug"] = city_slug
    place_view["displayName"] = place_display_name_cached_for_lang(place_view, lang)
    place_view["name"] = place_view["displayName"]
    place_view["category"] = place_view.get("category") or "Landmark"
    place_view["categoryLabel"] = localized_category_label(str(place_view.get("category") or "Landmark"), lang)
    place_view["url"] = place_url(lang, country_slug, city_slug, place_slug)
    place_view["hasTranslation"] = True
    places_view = []
    for p in places:
        if str(p.get("slug") or p.get("placeSlug") or "") == place_slug:
            continue
        row = public_place_card_for_lang(
            p,
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            country_name=country_view["displayName"],
            city_name=city_view["displayName"],
        )
        if row:
            places_view.append(row)

    trn = t(lang)
    seo_title = i18n_fmt(
        trn["seo_place_title_tpl"],
        place=place_view["displayName"],
        city=city_view["displayName"],
        country=country_view["displayName"],
    )
    seo_desc = i18n_fmt(
        trn["seo_place_desc_tpl"],
        place=place_view["displayName"],
        city=city_view["displayName"],
        country=country_view["displayName"],
    )
    seo_keywords = i18n_fmt(
        trn["seo_place_keywords_tpl"],
        place=place_view["displayName"],
        city=city_view["displayName"],
        country=country_view["displayName"],
    )
    seo_image = f"/media/place/{CANONICAL_IMAGE_LANG}/{country_slug}/{city_slug}/{place_slug}"
    auto_faq = auto_faq_for_page(
        "place",
        lang=lang,
        country_name=country_view["displayName"],
        city_name=city_view["displayName"],
        place_name=place_view["displayName"],
        place_names=faq_place_names_for_page(
            country_slug=country_slug,
            city_slug=city_slug,
            lang=lang,
            limit=8,
            exclude_place_slug=place_slug,
        ),
        related_place_names=faq_place_names_for_page(
            country_slug=country_slug,
            city_slug=city_slug,
            lang=lang,
            limit=6,
            exclude_place_slug=place_slug,
        ),
    )
    auto_faq_schema = faq_schema_for_items(auto_faq.get("items", []))
    page_url = place_url(lang, country_slug, city_slug, place_slug)
    audio_rating = audio_rating_stats("place", country_slug=country_slug, city_slug=city_slug, place_slug=place_slug)
    same_as: List[str] = []
    for key in ("wikipediaUrl", "wikiUrl", "wikipedia", "url"):
        value = str(place_view.get(key) or "").strip()
        if value.startswith("http") and value not in same_as:
            same_as.append(value)
    wikidata_id = clean_plain_text(place_view.get("wikidataId") or place_view.get("wikidata") or "", 80)
    if wikidata_id:
        same_as.append(f"https://www.wikidata.org/wiki/{wikidata_id}" if not wikidata_id.startswith("http") else wikidata_id)
    place_entity: Dict[str, Any] = {
        "@type": schema_place_types(str(place_view.get("category") or "")),
        "@id": f"{schema_abs_url(page_url)}#main-entity",
        "name": place_view["displayName"],
        "url": schema_abs_url(page_url),
        "containedInPlace": {
            "@type": "City",
            "name": city_view["displayName"],
            "url": schema_abs_url(city_url(lang, country_slug, city_slug)),
        },
    }
    geo = schema_geo_node(place_view)
    if geo:
        place_entity["geo"] = geo
    if seo_image:
        place_entity["image"] = schema_abs_url(seo_image)
    if same_as:
        place_entity["sameAs"] = same_as[:4]
    nearby_schema_items = [
        {
            "name": p.get("displayName") or p.get("name") or "",
            "url": str(p.get("url") or place_url(DEFAULT_LANG, country_slug, city_slug, str(p.get("slug") or p.get("placeSlug") or ""))),
        }
        for p in places_view[:12]
        if p.get("slug") or p.get("placeSlug")
    ]
    place_schema = schema_graph(
        page_type="WebPage",
        lang=lang,
        page_url=page_url,
        title=seo_title,
        description=seo_desc,
        image_url=seo_image,
        breadcrumbs=[
            (trn.get("common_home") or "Home", landing_url(lang)),
            (country_view["displayName"], country_url(lang, country_slug)),
            (city_view["displayName"], city_url(lang, country_slug, city_slug)),
            (place_view["displayName"], page_url),
        ],
        faq_schema=auto_faq_schema,
        main_entity=place_entity,
        item_lists=[
            schema_item_list_node((trn.get("map_places_near_tpl") or "Nearby places in {city}").replace("{city}", city_view["displayName"]), page_url, "nearby-places", nearby_schema_items),
        ],
        audio_objects=schema_audio_objects_for_page(
            page_url=page_url,
            entity_name=place_view["displayName"],
            lang=lang,
            country_slug=country_slug,
            city_slug=city_slug,
            place_slug=place_slug,
        ),
        rating_stats=audio_rating,
    )
    admin_content = admin_content_for_public(
        admin_page_key("place", country_slug=country_slug, city_slug=city_slug, place_slug=place_slug),
        lang,
    )
    comments_context = public_comments_context(
        "place_page",
        f"place:{country_slug}:{city_slug}:{place_slug}",
        place_view["displayName"],
        page_url,
        lang,
        admin_content,
    )

    resp = make_response(
        render_template(
            "place.html",
            country=country_view,
            city=city_view,
            place=place_view,
            places=places_view,
            admin_content=admin_content,
            comments_context=comments_context,
            auto_faq=auto_faq,
            auto_faq_schema=auto_faq_schema,
            schema_in_graph=True,
            seo_title=seo_title,
            seo_desc=seo_desc,
            seo_keywords=seo_keywords,
            seo_image=seo_image,
            seo_type="article",
            seo_schema=place_schema,
            audio_rating=audio_rating,
            audio_rating_entity_type="place",
            audio_rating_country_slug=country_slug,
            audio_rating_city_slug=city_slug,
            audio_rating_place_slug=place_slug,
            lang=lang,
            T=trn,
            wiki_lang=SUPPORTED_LANGS[lang]["wiki"],
            speech_lang=SUPPORTED_LANGS[lang]["speech"],
            body_class="PagePlace",
            use_leaflet=True,
        )
    )
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365)
    return resp


# Back-compat: old pages
@app.get("/main/<lang>/<country_slug>/")
def legacy_main_country(lang: str, country_slug: str):
    return redirect(country_url(lang, country_slug), code=301)


@app.get("/main/<lang>/<country_slug>/<city_slug>/")
def legacy_main_city(lang: str, country_slug: str, city_slug: str):
    return redirect(city_url(lang, country_slug, city_slug), code=301)


# -------- LEGACY --------
# Old 2-letter country-code URLs moved under /c/... (to avoid clashing with language slugs like /es, /fr)
@app.get("/c/<re('[a-z]{2}'):code>")
def legacy_country(code: str):
    c = COUNTRY_BY_CODE.get(code.lower())
    if not c:
        abort(404)
    return redirect(country_url("en", c["slug"]), code=301)


@app.get("/c/<re('[a-z]{2}'):code>/<city_slug>")
def legacy_city(code: str, city_slug: str):
    c = COUNTRY_BY_CODE.get(code.lower())
    if not c:
        abort(404)
    return redirect(city_url("en", c["slug"], city_slug), code=301)


@app.get("/<re('[a-z0-9][a-z0-9-]{2,}'):country_slug>")
def legacy_country_slug(country_slug: str):
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)
    if country_slug not in COUNTRY_BY_SLUG:
        abort(404)
    return country_page("en", country_slug)


@app.get("/<re('[a-z0-9][a-z0-9-]{2,}'):country_slug>/<city_slug>")
def legacy_city_slug(country_slug: str, city_slug: str):
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)
    if country_slug not in COUNTRY_BY_SLUG:
        abort(404)
    return city_page("en", country_slug, city_slug)


@app.get("/<re('[a-z0-9][a-z0-9-]{2,}'):country_slug>/<city_slug>/<place_slug>")
def legacy_place_slug(country_slug: str, city_slug: str, place_slug: str):
    if country_slug in {"api", "img", "static", "main"}:
        abort(404)
    if country_slug not in COUNTRY_BY_SLUG:
        abort(404)
    return place_page("en", country_slug, city_slug, place_slug)


# -------- menu mega data --------
@app.context_processor
def inject_nav_data():
    lang = current_lang()
    user = current_site_user()
    canonical_path = canonical_path_for_request()
    current_path = canonical_path or "/"
    langs = [
        {"slug": public_lang_code(k), "internal": k, "label": SUPPORTED_LANGS[k]["label"], "url": localized_path_for(current_path, k)}
        for k in LANG_ORDER
        if k in SUPPORTED_LANGS
    ]
    home_url = "/" if lang == "en" else landing_url(lang)
    map_url = f"{home_url}#live"
    places_total = sum(len(v) for v in CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.values())
    nav_countries: List[Dict[str, Any]] = []
    for country in europe_countries():
        row = dict(country)
        row["name"] = country_display_name_cached_for_lang(row, lang)
        row["url"] = country_url(lang, row["slug"])
        nav_countries.append(row)

    return dict(
        BRAND_NAME=BRAND_NAME,
        SITE_DOMAIN=SITE_DOMAIN,
        SITE_URL=SITE_URL,
        CONTACT_EMAIL=CONTACT_EMAIL,
        CURRENT_USER=user or {},
        IS_LOGGED_IN=bool(user),
        IS_GUIDE_SAVED=current_user_has_favorite,
        CURRENT_LANG=lang,
        CURRENT_LANG_PUBLIC=public_lang_code(lang),
        NAV_LANGS=langs,
        NAV_HOME_URL=home_url,
        NAV_MAP_URL=map_url,
        NAV_EUROPE_COUNTRIES=nav_countries,
        FOOTER_POPULAR_CITIES=footer_popular_city_links(lang),
        CITIES_COUNT=f"{len(CITIES):,}".replace(",", " "),
        PLACES_COUNT=f"{places_total:,}".replace(",", " "),
        SEO_CANONICAL_URL=absolute_url(canonical_path),
        SEO_ROBOTS=robots_meta_for_path(current_path, lang),
        SEO_HREFLANG_LINKS=hreflang_links_for_request(),
        SEO_OG_LOCALE=OG_LOCALE_BY_LANG.get(lang, "en_US"),
        HTML_LANG=HREFLANG_CODE_BY_LANG.get(lang, "en"),
        URL_LANDING=landing_url,
        URL_COUNTRY=country_url,
        URL_CITY=city_url,
        URL_PLACE=place_url,
        URL_BLOG=blog_index_url,
        URL_BLOG_POST=blog_post_url,
        URL_CONTACT=contact_url,
        PUBLIC_COMMENTS_CONTEXT=public_comments_context,
        CSRF_TOKEN=csrf_token,
        URL_ACCOUNT="/account",
        T=t(lang),
    )


if __name__ == "__main__":
    COUNTRIES = load_countries()
    CITIES = load_cities()
    build_indexes()
    TOP_PLACES_BY_COUNTRYSLUG = load_top_places()
    build_top_places_indexes()
    build_city_places_indexes()
    app.run(
        host=os.getenv("HOST") or "0.0.0.0",
        port=int(os.getenv("PORT") or "8001"),
        debug=env_bool("FLASK_DEBUG", not IS_PRODUCTION),
        use_reloader=False,
        threaded=True,
    )


# Load data when imported (e.g. flask run / gunicorn)
if not COUNTRIES and not CITIES:
    COUNTRIES = load_countries()
    CITIES = load_cities()
    build_indexes()
    TOP_PLACES_BY_COUNTRYSLUG = load_top_places()
    build_top_places_indexes()
    build_city_places_indexes()

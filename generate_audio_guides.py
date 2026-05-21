import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import app as audia_app


ROOT = Path(__file__).resolve().parent
DOTENV_PATH = ROOT / ".env"

WIKI_USER_AGENT = "AudiaGuide/1.0 (audio generator; https://127.0.0.1)"
OPENAI_BASE_URL = "https://api.openai.com/v1"

DEFAULT_AUDIO_VERSION = "v2"
STATIC_AUDIO_ROOT = Path(os.getenv("AUDIO_STORAGE_PATH") or str(ROOT / "static" / "audio")).expanduser()

REWRITE_CACHE_VERSION = "v1"
REWRITE_CACHE_DIR = ROOT / "cache" / "rewrite" / REWRITE_CACHE_VERSION
MIN_AUDIO_SECTION_WORDS = 50


APP_LANG_TO_WIKI = {k: v["wiki"] for k, v in audia_app.SUPPORTED_LANGS.items()}
APP_LANG_TO_GTTS = {
    "en": "en",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "de": "de",
    "ua": "uk",
}

GTTS_TLD_BY_LANG_GENDER: Dict[str, Dict[str, str]] = {
    "en": {"female": "com", "male": "co.uk"},
    "fr": {"female": "fr", "male": "ca"},
    "es": {"female": "es", "male": "com.mx"},
    "it": {"female": "it", "male": "com"},
    "de": {"female": "de", "male": "com"},
    "ua": {"female": "com", "male": "com"},
}


SKIP_H2_BY_WIKI_LANG = {
    "en": {
        "contents",
        "see also",
        "notes",
        "references",
        "further reading",
        "external links",
        "bibliography",
        "citations",
    },
    "fr": {
        "sommaire",
        "voir aussi",
        "notes",
        "références",
        "bibliographie",
        "liens externes",
    },
    "es": {
        "contenido",
        "índice",
        "véase también",
        "notas",
        "referencias",
        "bibliografía",
        "enlaces externos",
    },
    "it": {
        "contenuto",
        "indice",
        "vedi anche",
        "note",
        "riferimenti",
        "bibliografia",
        "collegamenti esterni",
        "link esterni",
    },
    "de": {
        "inhaltsverzeichnis",
        "siehe auch",
        "anmerkungen",
        "einzelnachweise",
        "literatur",
        "web links",
        "weblinks",
        "einzelnachweise und anmerkungen",
    },
    "uk": {
        "зміст",
        "див. також",
        "примітки",
        "посилання",
        "література",
        "джерела",
    },
}

COMMON_SKIP_H2 = {
    "sources",
    "gallery",
    "photo gallery",
    "images",
    "coordinates",
    "navigation",
    "links",
}


GENDER_TO_OPENAI_VOICE_DEFAULT = {
    "female": "nova",
    "male": "onyx",
}

EDGE_VOICE_PRESETS: Dict[str, Dict[str, Dict[str, str]]] = {
    "default": {
        "en": {"female": "en-GB-SoniaNeural", "male": "en-GB-RyanNeural"},
        "fr": {"female": "fr-FR-DeniseNeural", "male": "fr-FR-HenriNeural"},
        "es": {"female": "es-ES-ElviraNeural", "male": "es-ES-AlvaroNeural"},
        "it": {"female": "it-IT-ElsaNeural", "male": "it-IT-DiegoNeural"},
        "de": {"female": "de-DE-KatjaNeural", "male": "de-DE-ConradNeural"},
        "ua": {"female": "uk-UA-PolinaNeural", "male": "uk-UA-OstapNeural"},
    },
    # Siri-like profile: expressive US/locale neural voices with cleaner prosody.
    "siri": {
        "en": {"female": "en-US-AvaNeural", "male": "en-US-BrianNeural"},
        "fr": {"female": "fr-FR-DeniseNeural", "male": "fr-FR-HenriNeural"},
        "es": {"female": "es-ES-ElviraNeural", "male": "es-ES-AlvaroNeural"},
        "it": {"female": "it-IT-IsabellaNeural", "male": "it-IT-DiegoNeural"},
        "de": {"female": "de-DE-SeraphinaMultilingualNeural", "male": "de-DE-FlorianMultilingualNeural"},
        "ua": {"female": "uk-UA-PolinaNeural", "male": "uk-UA-OstapNeural"},
    },
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        return


def sha1_text(text: str) -> str:
    h = hashlib.sha1()
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def clean_plain_text(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", s)
    s = re.sub(r"\[[^\]]*]", "", s)
    for _ in range(14):
        ns = re.sub(r"\([^()]*\)", "", s)
        if ns == s:
            break
        s = ns
    s = re.sub(r"\b([A-Za-zÀ-ÿ'-]+)(\s+\1\b)+", r"\1", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def count_words(text: str) -> int:
    return len(str(text or "").split())


def normalize_heading(text: str) -> str:
    return (
        str(text or "")
        .strip()
        .lower()
        .replace("\u00a0", " ")
    )


def wiki_api_get(wiki_lang: str, params: Dict[str, Any], timeout_s: int = 25) -> Any:
    url = f"https://{wiki_lang}.wikipedia.org/w/api.php"
    r = requests.get(url, params=params, headers={"User-Agent": WIKI_USER_AGENT}, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def wiki_langlinks(from_wiki_lang: str, title: str) -> Dict[str, str]:
    data = wiki_api_get(
        from_wiki_lang,
        {
            "action": "query",
            "prop": "langlinks",
            "format": "json",
            "titles": title,
            "lllimit": 500,
        },
    )
    pages = (data.get("query") or {}).get("pages") or {}
    page = list(pages.values())[0] if pages else {}
    links = page.get("langlinks") or []
    out: Dict[str, str] = {}
    for it in links:
        lang = str(it.get("lang") or "").strip().lower()
        t = str(it.get("*") or it.get("title") or "").strip()
        if lang and t:
            out[lang] = t
    return out


def wiki_parse_html(wiki_lang: str, title: str) -> Tuple[str, str]:
    data = wiki_api_get(
        wiki_lang,
        {
            "action": "parse",
            "format": "json",
            "origin": "*",
            "prop": "text",
            "formatversion": "2",
            "page": title,
        },
        timeout_s=35,
    )
    parsed = data.get("parse") or {}
    html = parsed.get("text") or ""
    resolved_title = str(parsed.get("title") or title).strip()
    if not html:
        raise RuntimeError("No HTML in parse response")
    return (resolved_title, html)


def dedupe_titles(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        t = str(raw or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def wiki_search_titles(wiki_lang: str, query: str, limit: int = 8) -> List[str]:
    q = str(query or "").strip()
    if not q:
        return []
    data = wiki_api_get(
        wiki_lang,
        {
            "action": "query",
            "list": "search",
            "srsearch": q,
            "srlimit": max(1, min(int(limit or 8), 20)),
            "format": "json",
            "origin": "*",
        },
        timeout_s=25,
    )
    results = ((data.get("query") or {}).get("search") or [])
    out: List[str] = []
    for row in results:
        t = str((row or {}).get("title") or "").strip()
        if t:
            out.append(t)
    return dedupe_titles(out)


def resolve_wiki_page(
    wiki_lang: str,
    candidates: Iterable[str],
    *,
    search_limit: int = 6,
) -> Optional[Tuple[str, str, List[Dict[str, str]]]]:
    parsed_seen: set[str] = set()

    def try_title(raw_title: str) -> Optional[Tuple[str, str, List[Dict[str, str]]]]:
        title = str(raw_title or "").strip()
        if not title:
            return None
        key = title.lower()
        if key in parsed_seen:
            return None
        parsed_seen.add(key)
        try:
            resolved_title, html = wiki_parse_html(wiki_lang, title)
            sections = html_to_h2_sections(wiki_lang, html)
            if sections:
                return (resolved_title, html, sections)
        except Exception:
            return None
        return None

    candidate_list = dedupe_titles(candidates)
    for title in candidate_list:
        got = try_title(title)
        if got:
            return got

        try:
            search_titles = wiki_search_titles(wiki_lang, title, limit=search_limit)
        except Exception:
            search_titles = []
        for s_title in search_titles:
            got = try_title(s_title)
            if got:
                return got

    return None


def html_to_h2_sections(wiki_lang: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    for sel in ["table", ".infobox", ".navbox", ".metadata", ".hatnote", "sup", "style", "script", ".mw-editsection"]:
        for el in soup.select(sel):
            el.decompose()

    content = soup.select_one(".mw-parser-output") or soup
    for sel in ["#toc", ".toc", ".reflist", "ol.references", "div.refbegin"]:
        for el in content.select(sel):
            el.decompose()

    nodes = content.select("h2, h3, h4, p, ul, ol")

    skip_set = SKIP_H2_BY_WIKI_LANG.get(wiki_lang, set()) | SKIP_H2_BY_WIKI_LANG.get("en", set()) | COMMON_SKIP_H2

    sections: List[Dict[str, str]] = []
    current_title = "Introduction"
    current_skip = False
    parts: List[str] = []

    def flush() -> None:
        nonlocal parts
        if current_skip:
            parts = []
            return
        joined = "\n".join(parts).strip()
        cleaned = clean_plain_text(joined)
        words = count_words(cleaned)
        if cleaned and words >= MIN_AUDIO_SECTION_WORDS:
            sections.append({"title": current_title, "text": cleaned, "words": words})
        parts = []

    for el in nodes:
        if el.find_parent(id="toc") or el.find_parent(class_="toc"):
            continue

        if el.name == "h2":
            flush()
            raw = el.get_text(" ", strip=True).replace("[edit]", "").strip() or "Section"
            current_title = raw
            current_skip = normalize_heading(raw) in skip_set
            continue

        if current_skip:
            continue

        if el.name in {"h3", "h4"}:
            t = el.get_text(" ", strip=True).replace("[edit]", "").strip()
            if t:
                parts.append(f"\n{t}\n")
            continue

        if el.name == "p":
            t = el.get_text(" ", strip=True).strip()
            if t:
                parts.append(t)
            continue

        if el.name in {"ul", "ol"}:
            items = [li.get_text(" ", strip=True).strip() for li in el.select("li")]
            items = [x for x in items if x]
            if items:
                parts.append("\n".join(f"- {x}" for x in items))
            continue

    flush()
    return [s for s in sections if s.get("title") and s.get("text")]


def split_into_chunks(text: str, max_chars: int) -> List[str]:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return []

    # Try sentence-ish splitting; fallback to hard split.
    sentences = re.split(r"(?<=[.!?…])\s+", s)
    sentences = [x.strip() for x in sentences if x and x.strip()]
    if not sentences:
        sentences = [s]

    out: List[str] = []
    buf: List[str] = []
    n = 0

    for sent in sentences:
        add = (sent if not buf else (" " + sent))
        if n + len(add) > max_chars and buf:
            out.append("".join(buf).strip())
            buf = [sent]
            n = len(sent)
        else:
            buf.append(add if buf else sent)
            n += len(add) if buf else len(sent)

    if buf:
        out.append("".join(buf).strip())

    return [x for x in out if x]


def with_punctuation_pauses(text: str, backend: str) -> str:
    s = clean_plain_text(text)
    b = str(backend or "").lower().strip()
    if b not in {"pyttsx3", "gtts"}:
        return s
    s = re.sub(r"\s*([,;:])\s*", r"\1 \n", s)
    s = re.sub(r"\s*([.!?…])\s*", r"\1 \n\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def extract_response_text(data: Any) -> str:
    if isinstance(data, dict):
        t = data.get("output_text")
        if isinstance(t, str) and t.strip():
            return t.strip()

        out = data.get("output")
        if isinstance(out, list):
            for item in out:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if isinstance(c.get("text"), str) and c["text"].strip():
                        return c["text"].strip()
    raise RuntimeError("No text in OpenAI response")


def openai_post_json(api_key: str, path: str, payload: Dict[str, Any], timeout_s: int = 90) -> Any:
    url = f"{OPENAI_BASE_URL}{path}"
    last_err: Optional[Exception] = None
    for attempt in range(1, 7):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout_s,
            )
        except requests.RequestException as e:
            last_err = e
            if attempt >= 6:
                raise
            time.sleep(min(20.0, 0.9 * (1.8 ** (attempt - 1))))
            continue

        if r.status_code in {429, 500, 502, 503, 504}:
            if attempt >= 6:
                break
            retry_after = r.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after else (0.9 * (1.8 ** (attempt - 1)))
            except Exception:
                wait_s = 0.9 * (1.8 ** (attempt - 1))
            time.sleep(min(30.0, max(0.25, wait_s)))
            continue

        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = {"error": {"message": r.text}}
            msg = (err.get("error") or {}).get("message") or str(err)
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {msg}")

        return r.json()

    if last_err:
        raise RuntimeError(f"OpenAI request failed after retries: {last_err}")
    raise RuntimeError("OpenAI request failed after retries.")


def rewrite_text_via_openai(
    api_key: str,
    model: str,
    app_lang: str,
    chunk: str,
    *,
    source_lang: str = "",
) -> str:
    src = str(source_lang or "").strip().lower()
    tgt = str(app_lang or "").strip().lower()
    target_rule = (
        f"Output must be in {tgt}."
        if tgt
        else "Output must stay in the requested target language."
    )
    source_note = f"Source language: {src}." if src else ""
    system = (
        "You rewrite texts into original, natural audio-guide narration.\n"
        f"Rules: {target_rule} {source_note} Keep meaning; keep similar length; do not add facts; do not cite sources; "
        "do not mention Wikipedia; keep names/dates/numbers; turn lists into flowing narration.\n"
        "Output plain text only."
    )
    user = (
        f"Target language: {app_lang}\n"
        f"{'Source language: ' + source_lang if source_lang else ''}\n\n"
        "Rewrite this into original audio-guide narration. "
        "If the source is in another language, translate it into the target language while preserving meaning and approximate length.\n\n"
        f"{chunk}"
    )
    data = openai_post_json(
        api_key,
        "/responses",
        {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        },
        timeout_s=120,
    )
    return clean_plain_text(extract_response_text(data))


def rewrite_heading_via_openai(
    api_key: str,
    model: str,
    app_lang: str,
    heading: str,
    *,
    source_lang: str = "",
) -> str:
    text = str(heading or "").strip()
    if not text:
        return ""
    src = str(source_lang or "").strip().lower()
    tgt = str(app_lang or "").strip().lower()
    system = (
        "You adapt section headings for a travel audio guide.\n"
        f"Output must be in {tgt or 'the target language'}. "
        "Keep it short. Preserve meaning. Do not add facts. Do not add punctuation unless needed.\n"
        "Return only the heading text."
    )
    user = (
        f"Target language: {app_lang}\n"
        f"{'Source language: ' + source_lang if source_lang else ''}\n\n"
        "Rewrite or translate this heading for the target language:\n\n"
        f"{text}"
    )
    data = openai_post_json(
        api_key,
        "/responses",
        {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        },
        timeout_s=60,
    )
    return clean_plain_text(extract_response_text(data))


def openai_tts_bytes(
    api_key: str,
    model: str,
    voice: str,
    text: str,
) -> bytes:
    url = f"{OPENAI_BASE_URL}/audio/speech"
    last_err: Optional[Exception] = None
    for attempt in range(1, 7):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "voice": voice,
                    "input": text,
                    "response_format": "mp3",
                },
                timeout=120,
            )
        except requests.RequestException as e:
            last_err = e
            if attempt >= 6:
                raise
            time.sleep(min(20.0, 0.9 * (1.8 ** (attempt - 1))))
            continue

        if r.status_code in {429, 500, 502, 503, 504}:
            if attempt >= 6:
                break
            retry_after = r.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after else (0.9 * (1.8 ** (attempt - 1)))
            except Exception:
                wait_s = 0.9 * (1.8 ** (attempt - 1))
            time.sleep(min(30.0, max(0.25, wait_s)))
            continue

        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = {"error": {"message": r.text}}
            msg = (err.get("error") or {}).get("message") or str(err)
            raise RuntimeError(f"OpenAI TTS HTTP {r.status_code}: {msg}")

        return r.content

    if last_err:
        raise RuntimeError(f"OpenAI TTS failed after retries: {last_err}")
    raise RuntimeError("OpenAI TTS failed after retries.")


def best_tts_model(api_key: str, preferred: Optional[str] = None) -> str:
    candidates = []
    if preferred:
        candidates.append(preferred)
    # Prefer highest quality first, then fallback options.
    candidates.extend(["tts-1-hd", "gpt-4o-mini-tts", "tts-1"])

    probe_text = "Hello. This is a short test."
    for m in candidates:
        try:
            _ = openai_tts_bytes(api_key, m, "nova", probe_text)
            return m
        except Exception:
            continue
    raise RuntimeError("No working TTS model found for this API key.")


# ======================= edge-tts (online neural) =======================
def pick_edge_voice(app_lang: str, gender: str, profile: str = "siri") -> str:
    al = str(app_lang or "").lower().strip()
    g = str(gender or "").lower().strip()
    if g not in {"female", "male"}:
        raise RuntimeError(f"Invalid gender: {gender}")

    env_key = f"EDGE_TTS_VOICE_{al.upper()}_{g.upper()}"
    env_voice = (os.environ.get(env_key) or "").strip()
    if env_voice:
        return env_voice

    pf = str(profile or "siri").lower().strip()
    preset = EDGE_VOICE_PRESETS.get(pf) or EDGE_VOICE_PRESETS.get("default") or {}
    v = str((preset.get(al) or {}).get(g) or "").strip()
    if not v and pf != "default":
        v = str((EDGE_VOICE_PRESETS.get("default") or {}).get(al, {}).get(g) or "").strip()
    if v:
        return v
    raise RuntimeError(f"No edge-tts voice mapping for language={app_lang}, gender={gender}")


async def _edge_tts_save(
    voice: str,
    text: str,
    dest_mp3: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> None:
    import edge_tts  # type: ignore

    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_mp3.with_suffix(".tmp.mp3")
    last_err: Optional[Exception] = None
    for attempt in range(1, 4):
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        try:
            communicate = edge_tts.Communicate(
                text=str(text or ""),
                voice=str(voice),
                rate=str(rate),
                pitch=str(pitch),
                volume=str(volume),
            )
            await communicate.save(str(tmp))
            if not tmp.exists() or tmp.stat().st_size <= 256:
                raise RuntimeError("edge-tts returned empty audio")
            tmp.replace(dest_mp3)
            return
        except Exception as e:
            last_err = e
            if attempt >= 3:
                break
            await asyncio.sleep(min(6.0, 0.6 * (2 ** attempt)))
    raise RuntimeError(f"edge-tts failed after retries: {last_err}")


def edge_tts_speak_to_mp3(
    voice: str,
    text: str,
    dest_mp3: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> None:
    asyncio.run(_edge_tts_save(voice=voice, text=text, dest_mp3=dest_mp3, rate=rate, pitch=pitch, volume=volume))


async def edge_tts_generate_jobs(
    jobs: List[Tuple[str, str, Path]],
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
    concurrency: int = 3,
) -> None:
    if not jobs:
        return

    sem = asyncio.Semaphore(max(1, int(concurrency or 1)))
    total = len(jobs)
    done = 0
    lock = asyncio.Lock()

    async def one(job: Tuple[str, str, Path]) -> None:
        nonlocal done
        voice, text, dest = job
        async with sem:
            await _edge_tts_save(voice=voice, text=text, dest_mp3=dest, rate=rate, pitch=pitch, volume=volume)
        async with lock:
            done += 1
            if done % 20 == 0 or done == total:
                print(f"[EDGE] {done}/{total} audio files generated")

    await asyncio.gather(*(one(j) for j in jobs))


# ======================= gTTS (online) =======================
def gtts_speak_to_mp3(text: str, dest_mp3: Path, lang: str, tld: str = "com", slow: bool = False) -> None:
    from gtts import gTTS  # type: ignore

    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_mp3.with_suffix(".tmp.mp3")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass

    last_err: Optional[Exception] = None
    for attempt in range(1, 5):
        try:
            tts = gTTS(text=str(text or ""), lang=str(lang or "en"), tld=str(tld or "com"), slow=bool(slow))
            tts.save(str(tmp))
            if not tmp.exists() or tmp.stat().st_size <= 256:
                raise RuntimeError("gTTS returned empty audio")
            tmp.replace(dest_mp3)
            return
        except Exception as e:
            last_err = e
            if attempt >= 4:
                break
            time.sleep(min(8.0, 0.8 * (2 ** attempt)))

    raise RuntimeError(f"gTTS failed after retries: {last_err}")


# ======================= pyttsx3 (offline) TTS =======================
APP_LANG_TO_TTS_LOCALES = {
    "en": ["en_GB", "en_US"],
    "fr": ["fr_FR", "fr_CA"],
    "es": ["es_ES", "es_MX"],
    "it": ["it_IT"],
    "de": ["de_DE"],
    # app uses "ua" but voices use "uk_UA"
    "ua": ["uk_UA"],
}

DEFAULT_PYTTSX3_VOICE_ID_PREFS: Dict[str, Dict[str, List[str]]] = {
    "en": {
        "female": ["com.apple.voice.compact.en-US.Samantha"],
        "male": ["com.apple.voice.compact.en-GB.Daniel"],
    },
    "fr": {
        "female": ["com.apple.voice.compact.fr-CA.Amelie", "com.apple.eloquence.fr-FR.Grandma"],
        "male": ["com.apple.voice.compact.fr-FR.Thomas", "com.apple.eloquence.fr-FR.Jacques", "com.apple.eloquence.fr-FR.Eddy"],
    },
    "es": {
        "female": ["com.apple.voice.compact.es-ES.Monica", "com.apple.voice.compact.es-MX.Paulina"],
        "male": ["com.apple.eloquence.es-ES.Eddy", "com.apple.eloquence.es-ES.Reed", "com.apple.eloquence.es-ES.Rocko"],
    },
    "it": {
        "female": ["com.apple.voice.compact.it-IT.Alice"],
        "male": ["com.apple.eloquence.it-IT.Eddy", "com.apple.eloquence.it-IT.Reed", "com.apple.eloquence.it-IT.Rocko"],
    },
    "de": {
        "female": ["com.apple.voice.compact.de-DE.Anna"],
        "male": ["com.apple.eloquence.de-DE.Eddy", "com.apple.eloquence.de-DE.Reed", "com.apple.eloquence.de-DE.Rocko"],
    },
    "ua": {
        "female": ["com.apple.voice.compact.uk-UA.Lesya"],
        # Fallback: same voice (some systems ship only a female Ukrainian voice).
        "male": ["com.apple.voice.compact.uk-UA.Lesya"],
    },
}


def _voice_langs(voice: Any) -> List[str]:
    out: List[str] = []
    try:
        langs = getattr(voice, "languages", None) or []
        for l in langs:
            if isinstance(l, (bytes, bytearray)):
                try:
                    l = l.decode("utf-8", errors="ignore")
                except Exception:
                    l = str(l)
            out.append(str(l).replace("-", "_"))
    except Exception:
        return []
    return [x for x in out if x]


def _gender_str(voice: Any) -> str:
    try:
        return str(getattr(voice, "gender", "") or "")
    except Exception:
        return ""


def _matches_locale(voice: Any, locale: str) -> bool:
    loc = str(locale or "").replace("-", "_").lower()
    langs = [x.lower() for x in _voice_langs(voice)]
    if loc in langs:
        return True
    base = loc.split("_")[0]
    return any(l.startswith(base + "_") or l == base for l in langs)


def pick_pyttsx3_voice_id(voices: List[Any], app_lang: str, gender: str) -> Optional[str]:
    al = str(app_lang or "").lower()
    g = str(gender or "").lower()
    if g not in {"female", "male"}:
        return None

    # Env override (exact ID)
    env_key = f"PYTTSX3_VOICE_ID_{al.upper()}_{g.upper()}"
    env_val = (os.environ.get(env_key) or "").strip()
    if env_val and any(str(v.id) == env_val for v in voices):
        return env_val

    # Known-good defaults (macOS)
    for cand in DEFAULT_PYTTSX3_VOICE_ID_PREFS.get(al, {}).get(g, []):
        if any(str(v.id) == cand for v in voices):
            return cand

    # Heuristic fallback
    locales = APP_LANG_TO_TTS_LOCALES.get(al, [al])
    base = str(locales[0]).split("_")[0].lower() if locales else al

    def score(v: Any) -> int:
        vid = str(getattr(v, "id", "") or "")
        vname = str(getattr(v, "name", "") or "")
        langs = [x.lower() for x in _voice_langs(v)]

        lang_score = 0
        for i, loc in enumerate(locales):
            locn = str(loc).replace("-", "_").lower()
            if locn in langs:
                lang_score = max(lang_score, 100 - i * 5)
            elif any(x.startswith(base + "_") or x == base for x in langs):
                lang_score = max(lang_score, 60)

        if not lang_score:
            return 0

        gender_score = 0
        gs = _gender_str(v).lower()
        if g == "female" and "female" in gs:
            gender_score += 25
        elif g == "male" and "male" in gs:
            gender_score += 25
        elif "female" in gs or "male" in gs:
            gender_score -= 10

        # Prefer higher quality voices when possible
        q_score = 0
        if "compact" in vid.lower():
            q_score += 12
        elif "eloquence" in vid.lower():
            q_score += 4

        # Nudge Eloquence personas for gender when no explicit gender is available
        n = vname.lower()
        if g == "male" and ("grandpa" in n or "rocko" in n or "reed" in n or "eddy" in n or "jacques" in n):
            gender_score += 10
        if g == "female" and ("grandma" in n or "shelley" in n or "sandy" in n or "flo" in n):
            gender_score += 10

        return lang_score + gender_score + q_score

    best = None
    best_s = 0
    for v in voices:
        s = score(v)
        if s > best_s:
            best = v
            best_s = s
    return str(getattr(best, "id", "")) if best else None


def _wav_data_chunk_size(path: Path) -> int:
    try:
        with path.open("rb") as f:
            head = f.read(12)
            if len(head) < 12:
                return -1
            if head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
                return -1
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return -1
                ck = hdr[0:4]
                sz = int.from_bytes(hdr[4:8], "little", signed=False)
                if ck == b"data":
                    return int(sz)
                try:
                    f.seek(sz, 1)
                except Exception:
                    return -1
    except Exception:
        return -1


def pyttsx3_speak_to_wav(voice_id: str, text: str, dest_wav: Path, rate: int = 175) -> None:
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp_aif = dest_wav.with_suffix(".tmp.aiff")
    tmp_wav = dest_wav.with_suffix(".tmp.wav")

    if tmp_aif.exists():
        try:
            tmp_aif.unlink()
        except Exception:
            pass
    if tmp_wav.exists():
        try:
            tmp_wav.unlink()
        except Exception:
            pass

    # On macOS, pyttsx3's save_to_file via NSSpeechSynthesizer often only works once per process.
    # Workaround: run pyttsx3 in a fresh subprocess for every chunk.
    code = (
        "import sys\n"
        "import pyttsx3\n"
        "voice_id=sys.argv[1]\n"
        "rate=int(sys.argv[2])\n"
        "out_path=sys.argv[3]\n"
        "txt=sys.stdin.read()\n"
        "engine=pyttsx3.init()\n"
        "engine.setProperty('voice', voice_id)\n"
        "engine.setProperty('rate', rate)\n"
        "engine.save_to_file(txt, out_path)\n"
        "engine.runAndWait()\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code, str(voice_id), str(int(rate)), str(tmp_aif)],
        input=str(text or ""),
        text=True,
        capture_output=True,
    )
    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        raise RuntimeError(f"pyttsx3 subprocess failed ({r.returncode}): {stderr or 'unknown error'}")

    if not tmp_aif.exists() or tmp_aif.stat().st_size <= 32:
        raise RuntimeError("pyttsx3 did not write audio output")

    head = tmp_aif.read_bytes()[:12]
    if head.startswith(b"RIFF") and b"WAVE" in head:
        tmp_aif.replace(tmp_wav)
    elif head.startswith(b"FORM"):
        afc = shutil.which("afconvert")
        if not afc:
            raise RuntimeError("afconvert not found; cannot convert AIFF/AIFC to WAV on this system.")
        # Downmix to mono + 22.05kHz 16-bit LE PCM for size/compatibility.
        cmd = [afc, "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", str(tmp_aif), str(tmp_wav)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            stderr = (r.stderr or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"afconvert failed ({r.returncode}): {stderr or 'unknown error'}")
        try:
            tmp_aif.unlink()
        except Exception:
            pass
    else:
        try:
            tmp_aif.unlink()
        except Exception:
            pass
        raise RuntimeError("Unknown audio format produced by pyttsx3")

    if not tmp_wav.exists() or tmp_wav.stat().st_size <= 44:
        raise RuntimeError("WAV conversion failed (no output)")

    if _wav_data_chunk_size(tmp_wav) <= 0:
        raise RuntimeError("WAV output is empty (no samples)")

    # Atomic replace
    tmp_wav.replace(dest_wav)


@dataclass
class ChunkOut:
    text: str
    words: int
    file: str
    text_hash: str


@dataclass
class SectionOut:
    title: str
    words: int
    text_hash: str
    chunks: List[ChunkOut]


def city_wiki_candidates(city_name: str, country_name: str, wiki_title: str = "") -> List[str]:
    city_name = str(city_name or "").strip()
    country_name = str(country_name or "").strip()
    wiki_title = str(wiki_title or "").strip()
    return dedupe_titles(
        [
            wiki_title,
            city_name,
            f"{city_name}, {country_name}" if city_name and country_name else "",
            f"{city_name} ({country_name})" if city_name and country_name else "",
            f"{city_name} city" if city_name else "",
        ]
    )


def place_wiki_candidates(place_name: str, city_name: str, country_name: str) -> List[str]:
    place_name = str(place_name or "").strip()
    city_name = str(city_name or "").strip()
    country_name = str(country_name or "").strip()
    return dedupe_titles(
        [
            place_name,
            f"{place_name}, {city_name}" if place_name and city_name else "",
            f"{place_name} ({city_name})" if place_name and city_name else "",
            f"{place_name}, {country_name}" if place_name and country_name else "",
            f"{place_name} {city_name}" if place_name and city_name else "",
            f"{place_name} {country_name}" if place_name and country_name else "",
        ]
    )


def main() -> int:
    load_dotenv(DOTENV_PATH)

    parser = argparse.ArgumentParser(
        description="Generate rewritten + pre-generated audio guides into static/audio/<version>/… (male/female).",
    )
    parser.add_argument("--country-slug", default="united-kingdom")
    parser.add_argument("--city-slug", default="london")
    parser.add_argument(
        "--place-slug",
        default="",
        help="Optional place slug. If provided, generates place-level guide under .../<country>/<city>/<place>/.",
    )
    parser.add_argument(
        "--target-kind",
        default="city",
        choices=["city", "place", "country"],
        help="Guide target kind. Country guides are stored under .../<country>/__country__/.",
    )
    parser.add_argument(
        "--audio-version",
        default=DEFAULT_AUDIO_VERSION,
        help=f"Output directory under static/audio/ (default: {DEFAULT_AUDIO_VERSION}).",
    )
    parser.add_argument(
        "--langs",
        default="en,fr,es,it,ua,de",
        help="Comma-separated app languages to generate (default: en,fr,es,it,ua,de).",
    )
    parser.add_argument(
        "--genders",
        default="female,male",
        help="Comma-separated genders to generate (default: female,male).",
    )
    parser.add_argument(
        "--tts-backend",
        default="pyttsx3",
        choices=["pyttsx3", "gtts", "edge", "openai"],
        help="TTS engine to use for audio generation (default: pyttsx3).",
    )
    parser.add_argument("--pyttsx3-rate", type=int, default=175, help="Speech rate for pyttsx3 (default: 175).")
    parser.add_argument("--chunk-chars", type=int, default=1800)
    parser.add_argument("--max-sections", type=int, default=0, help="0 = all sections.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Delay between OpenAI requests (seconds).")
    parser.add_argument("--no-rewrite", action="store_true", help="Skip AI rewrite and use cleaned extracted text directly.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing audio + manifests.")
    parser.add_argument(
        "--source-mode",
        default="en-master",
        choices=["en-master", "linked-local"],
        help="Text source strategy: shared English master content for all languages, or local linked page per language.",
    )
    parser.add_argument("--rewrite-model", default=os.environ.get("OPENAI_REWRITE_MODEL") or os.environ.get("OPENAI_TRANSLATE_MODEL") or "gpt-5-mini")
    # OpenAI-only TTS options (ignored for pyttsx3 backend)
    parser.add_argument("--tts-model", default=os.environ.get("OPENAI_TTS_MODEL") or "")
    parser.add_argument("--voice-female", default=GENDER_TO_OPENAI_VOICE_DEFAULT["female"])
    parser.add_argument("--voice-male", default=GENDER_TO_OPENAI_VOICE_DEFAULT["male"])
    parser.add_argument("--edge-rate", default="+0%", help="edge-tts speech rate (default: +0%%).")
    parser.add_argument("--edge-pitch", default="+2Hz", help="edge-tts pitch (default: +2Hz).")
    parser.add_argument("--edge-volume", default="+0%", help="edge-tts volume (default: +0%%).")
    parser.add_argument("--edge-concurrency", type=int, default=3, help="Concurrent edge-tts jobs (default: 3).")
    parser.add_argument(
        "--edge-profile",
        default="siri",
        choices=["siri", "default"],
        help="Voice preset for edge-tts (default: siri).",
    )
    parser.add_argument("--gtts-slow", action="store_true", help="Use slower pronunciation for gTTS.")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY") or ""

    tts_backend = str(args.tts_backend or "pyttsx3").strip().lower()
    if tts_backend not in {"edge", "pyttsx3", "gtts", "openai"}:
        raise SystemExit("Invalid --tts-backend (use: pyttsx3|gtts|edge|openai).")
    use_rewrite = not bool(args.no_rewrite)
    need_openai = use_rewrite or (tts_backend == "openai")
    if need_openai and not api_key.strip():
        raise SystemExit("Missing OPENAI_API_KEY (set it in .env).")
    source_mode = str(args.source_mode or "en-master").strip().lower()

    audio_version = str(args.audio_version or DEFAULT_AUDIO_VERSION).strip()
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", audio_version, flags=re.I):
        raise SystemExit("Invalid --audio-version (use letters/numbers/dot/dash/underscore).")

    static_audio_dir = STATIC_AUDIO_ROOT / audio_version
    audio_ext = "wav" if tts_backend == "pyttsx3" else "mp3"

    country_slug = str(args.country_slug or "").strip().lower()
    city_slug = str(args.city_slug or "").strip().lower()
    place_slug = str(args.place_slug or "").strip().lower()
    requested_kind = str(args.target_kind or "city").strip().lower()
    if place_slug:
        requested_kind = "place"
    if city_slug == "__country__":
        requested_kind = "country"
    if requested_kind == "country":
        city_slug = "__country__"

    country = audia_app.COUNTRY_BY_SLUG.get(country_slug) or {}
    if not country:
        raise SystemExit(f"Country not found in dataset: {country_slug}")

    country_name = str(country.get("name") or country_slug).strip()
    city: Dict[str, Any] = {}
    city_name = ""
    target_kind = requested_kind
    target_name = country_name
    target_cache_scope = "__country__"
    target_wiki_candidates = dedupe_titles([country_name, f"{country_name} country"])

    if requested_kind != "country":
        city = audia_app.CITY_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug)) or {}
        if not city:
            raise SystemExit(f"City not found in dataset: {country_slug}/{city_slug}")

        country_name = str(country.get("name") or city.get("countryName") or "").strip()
        city_name = str(city.get("name") or city_slug).strip()
        target_kind = "city"
        target_name = city_name
        target_cache_scope = city_slug
        target_wiki_candidates = city_wiki_candidates(
            city_name=city_name,
            country_name=country_name,
            wiki_title=str(city.get("wikiTitle") or ""),
        )

    place: Optional[Dict[str, Any]] = None
    if requested_kind == "place":
        place = audia_app.PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.get((country_slug, city_slug, place_slug))
        if not place:
            raise SystemExit(f"Place not found in dataset: {country_slug}/{city_slug}/{place_slug}")
        target_kind = "place"
        target_name = str(place.get("name") or place_slug).strip()
        target_cache_scope = f"{city_slug}__{place_slug}"
        target_wiki_candidates = place_wiki_candidates(
            place_name=target_name,
            city_name=str(place.get("cityName") or city_name),
            country_name=str(place.get("countryName") or country_name),
        )

    resolved_en_title = ""
    en_sections_raw: List[Dict[str, str]] = []
    en_resolved = resolve_wiki_page("en", target_wiki_candidates, search_limit=10)
    if en_resolved:
        resolved_en_title, _en_html, en_sections_raw = en_resolved
    else:
        fallback = target_wiki_candidates[0] if target_wiki_candidates else target_name
        resolved_en_title = str(fallback or target_name or city_slug)
        print(f"[WARN] Could not resolve EN source page directly, fallback title: {resolved_en_title}")

    try:
        langlinks = wiki_langlinks("en", resolved_en_title) if resolved_en_title else {}
    except Exception:
        langlinks = {}
    place_city_name = str((place or {}).get("cityName") or city_name)
    place_country_name = str((place or {}).get("countryName") or country_name)

    app_langs = [x.strip().lower() for x in str(args.langs or "").split(",") if x.strip()]
    app_langs = [x for x in app_langs if x in audia_app.SUPPORTED_LANGS]
    if not app_langs:
        raise SystemExit("No valid languages requested.")

    genders = [x.strip().lower() for x in str(args.genders or "").split(",") if x.strip()]
    genders = [x for x in genders if x in {"female", "male"}]
    if not genders:
        raise SystemExit("No valid genders requested.")

    rewrite_model = str(args.rewrite_model or "").strip()

    openai_voices = {
        "female": str(args.voice_female or GENDER_TO_OPENAI_VOICE_DEFAULT["female"]).strip(),
        "male": str(args.voice_male or GENDER_TO_OPENAI_VOICE_DEFAULT["male"]).strip(),
    }
    edge_rate = str(args.edge_rate or "+0%").strip()
    edge_pitch = str(args.edge_pitch or "+2Hz").strip()
    edge_volume = str(args.edge_volume or "+0%").strip()
    edge_concurrency = max(1, int(args.edge_concurrency or 1))
    edge_profile = str(args.edge_profile or "siri").strip().lower()
    gtts_slow = bool(args.gtts_slow)

    tts_model = ""
    if tts_backend == "openai":
        tts_model = best_tts_model(api_key, str(args.tts_model or "").strip() or None)

    if target_kind == "country":
        print(f"[OK] Country: {target_name} ({country_slug})")
    elif target_kind == "place":
        print(f"[OK] Place: {target_name} ({country_slug}/{city_slug}/{place_slug})")
    else:
        print(f"[OK] City: {city_name} ({country_slug}/{city_slug})")
    print(f"[OK] Audio version: {audio_version}")
    print(f"[OK] Output: {static_audio_dir}")
    print(f"[OK] Source mode: {source_mode}")
    print(f"[OK] Rewrite mode: {'ai' if use_rewrite else 'off'}")
    if use_rewrite:
        print(f"[OK] Rewrite model: {rewrite_model}")
    print(f"[OK] TTS backend: {tts_backend}")
    if tts_backend == "openai":
        print(f"[OK] TTS model: {tts_model}")
        print(f"[OK] OpenAI voices: female={openai_voices['female']} male={openai_voices['male']}")
    elif tts_backend == "edge":
        print(f"[OK] edge profile: {edge_profile}")
        print(f"[OK] edge prosody: rate={edge_rate}, pitch={edge_pitch}, volume={edge_volume}")
        print(f"[OK] edge concurrency: {edge_concurrency}")
    elif tts_backend == "gtts":
        print(f"[OK] gTTS mode: {'slow' if gtts_slow else 'normal'}")
    else:
        print(f"[OK] pyttsx3 rate: {int(args.pyttsx3_rate)}")

    rewritten_by_lang: Dict[str, Dict[str, Any]] = {}

    for app_lang in app_langs:
        wiki_lang = APP_LANG_TO_WIKI.get(app_lang) or "en"
        resolved_title = ""
        manifest_title = ""
        sections_raw: List[Dict[str, str]] = []

        if source_mode == "en-master" and en_sections_raw:
            resolved_title = resolved_en_title or target_name
            manifest_title = resolved_title
            sections_raw = list(en_sections_raw)
        else:
            lang_candidates: List[str] = []
            linked = str(langlinks.get(wiki_lang) or "").strip()
            if wiki_lang == "en" and resolved_en_title:
                lang_candidates.append(resolved_en_title)
            if linked:
                lang_candidates.append(linked)
            if resolved_en_title:
                lang_candidates.append(resolved_en_title)

            if target_kind == "country":
                lang_candidates.extend([target_name, f"{target_name} country"])
            elif target_kind == "place":
                lang_candidates.extend(
                    place_wiki_candidates(
                        place_name=target_name,
                        city_name=place_city_name,
                        country_name=place_country_name,
                    )
                )
            else:
                lang_candidates.extend(
                    city_wiki_candidates(
                        city_name=city_name,
                        country_name=country_name,
                        wiki_title=str(city.get("wikiTitle") or ""),
                    )
                )
            resolved = resolve_wiki_page(wiki_lang, lang_candidates, search_limit=8)
            if resolved:
                resolved_title, _html, sections_raw = resolved
                manifest_title = resolved_title

        if not sections_raw:
            print(f"[SKIP] {app_lang}: no parseable page for wiki lang '{wiki_lang}'")
            continue

        if not manifest_title:
            manifest_title = resolved_title or target_name

        if args.max_sections and int(args.max_sections) > 0:
            sections_raw = sections_raw[: int(args.max_sections)]

        if not sections_raw:
            print(f"[SKIP] {app_lang}: no sections parsed")
            continue

        if use_rewrite and source_mode == "en-master" and app_lang != "en":
            title_cache_dir = REWRITE_CACHE_DIR / "_titles" / app_lang / country_slug / target_cache_scope
            title_cache_dir.mkdir(parents=True, exist_ok=True)
            title_cache_key = sha1_text(
                f"title\n{rewrite_model}\n{app_lang}\n{source_mode}\n{manifest_title}"
            )
            title_cache_path = title_cache_dir / f"{title_cache_key}.txt"
            if title_cache_path.exists() and not args.force:
                manifest_title = title_cache_path.read_text(encoding="utf-8").strip() or manifest_title
            else:
                manifest_title = rewrite_heading_via_openai(
                    api_key,
                    rewrite_model,
                    app_lang,
                    manifest_title,
                    source_lang="en",
                ) or manifest_title
                title_cache_path.write_text(manifest_title, encoding="utf-8")
                if args.sleep:
                    time.sleep(max(0.0, float(args.sleep)))

        rewritten_sections: List[SectionOut] = []
        for si, sec in enumerate(sections_raw, start=1):
            sec_title_src = str(sec.get("title") or f"Section {si}").strip() or f"Section {si}"
            sec_text = clean_plain_text(sec.get("text") or "")
            if not sec_text or count_words(sec_text) < MIN_AUDIO_SECTION_WORDS:
                continue

            sec_title = sec_title_src
            if use_rewrite and source_mode == "en-master" and app_lang != "en":
                heading_cache_dir = REWRITE_CACHE_DIR / "_headings" / app_lang / country_slug / target_cache_scope
                heading_cache_dir.mkdir(parents=True, exist_ok=True)
                heading_cache_key = sha1_text(
                    f"heading\n{rewrite_model}\n{app_lang}\n{source_mode}\n{sec_title_src}"
                )
                heading_cache_path = heading_cache_dir / f"{heading_cache_key}.txt"
                if heading_cache_path.exists() and not args.force:
                    sec_title = heading_cache_path.read_text(encoding="utf-8").strip() or sec_title_src
                else:
                    sec_title = rewrite_heading_via_openai(
                        api_key,
                        rewrite_model,
                        app_lang,
                        sec_title_src,
                        source_lang="en",
                    ) or sec_title_src
                    heading_cache_path.write_text(sec_title, encoding="utf-8")
                    if args.sleep:
                        time.sleep(max(0.0, float(args.sleep)))

            chunks_in = split_into_chunks(sec_text, int(args.chunk_chars))
            chunks_out: List[ChunkOut] = []

            for ci, chunk in enumerate(chunks_in, start=1):
                if not use_rewrite:
                    rewritten = clean_plain_text(chunk)
                else:
                    cache_dir = REWRITE_CACHE_DIR / app_lang / country_slug / target_cache_scope
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_key = sha1_text(
                        f"{rewrite_model}\n{app_lang}\n{source_mode}\n"
                        f"{'en' if source_mode == 'en-master' else app_lang}\n{chunk}"
                    )
                    cache_path = cache_dir / f"{cache_key}.txt"

                    if cache_path.exists() and not args.force:
                        rewritten = cache_path.read_text(encoding="utf-8").strip()
                    else:
                        rewritten = rewrite_text_via_openai(
                            api_key,
                            rewrite_model,
                            app_lang,
                            chunk,
                            source_lang=("en" if source_mode == "en-master" else app_lang),
                        )
                        cache_path.write_text(rewritten, encoding="utf-8")
                        if args.sleep:
                            time.sleep(max(0.0, float(args.sleep)))

                words = count_words(rewritten)
                chunk_hash = sha1_text(rewritten)
                audio_file = f"s{si:02d}_c{ci:02d}-{chunk_hash[:12]}.{audio_ext}"
                if words <= 0:
                    continue
                chunks_out.append(ChunkOut(text=rewritten, words=words, file=audio_file, text_hash=chunk_hash))

            sec_words = sum(c.words for c in chunks_out)
            if chunks_out and sec_words >= MIN_AUDIO_SECTION_WORDS:
                section_hash = sha1_text("\n".join(c.text for c in chunks_out))
                rewritten_sections.append(SectionOut(title=sec_title, words=sec_words, text_hash=section_hash, chunks=chunks_out))

        if not rewritten_sections:
            print(f"[SKIP] {app_lang}: nothing rewritten")
            continue

        rewritten_by_lang[app_lang] = {
            "resolved_title": resolved_title,
            "sections": rewritten_sections,
        }
        print(f"[OK] {app_lang}: rewritten {len(rewritten_sections)} sections (title: {resolved_title})")

    ok_langs = sorted(rewritten_by_lang.keys())

    if not ok_langs:
        print("[WARN] No languages generated.")
        return 2

    # Setup voice picks (once)
    edge_voice_by_lang_gender: Dict[str, Dict[str, str]] = {}
    if tts_backend == "edge":
        for al in ok_langs:
            edge_voice_by_lang_gender[al] = {}
            for g in genders:
                edge_voice_by_lang_gender[al][g] = pick_edge_voice(al, g, edge_profile)
        print("[OK] edge-tts voices:")
        for al in ok_langs:
            f = edge_voice_by_lang_gender.get(al, {}).get("female") or ""
            m = edge_voice_by_lang_gender.get(al, {}).get("male") or ""
            print(f"  - {al}: female={f or 'N/A'}; male={m or 'N/A'}")

    # Setup pyttsx3 voices (once)
    py_engine = None
    py_voices: List[Any] = []
    py_voice_name_by_id: Dict[str, str] = {}
    py_voice_id_by_lang_gender: Dict[str, Dict[str, str]] = {}
    py_rate = int(args.pyttsx3_rate)

    if tts_backend == "pyttsx3":
        try:
            import pyttsx3  # type: ignore
        except Exception as e:
            raise SystemExit(f"pyttsx3 is not installed or failed to import: {e}")

        py_engine = pyttsx3.init()
        py_voices = list(py_engine.getProperty("voices") or [])
        py_voice_name_by_id = {str(getattr(v, "id", "") or ""): str(getattr(v, "name", "") or "") for v in py_voices}

        for al in ok_langs:
            py_voice_id_by_lang_gender[al] = {}
            for g in genders:
                vid = pick_pyttsx3_voice_id(py_voices, al, g) or ""
                py_voice_id_by_lang_gender[al][g] = vid

            # If one gender is missing, reuse the other voice (keeps audio available).
            f = py_voice_id_by_lang_gender[al].get("female") or ""
            m = py_voice_id_by_lang_gender[al].get("male") or ""
            if not f and m:
                py_voice_id_by_lang_gender[al]["female"] = m
            if not m and f:
                py_voice_id_by_lang_gender[al]["male"] = f

        print("[OK] pyttsx3 voices:")
        for al in ok_langs:
            f = py_voice_id_by_lang_gender.get(al, {}).get("female") or ""
            m = py_voice_id_by_lang_gender.get(al, {}).get("male") or ""
            fn = py_voice_name_by_id.get(f, "")
            mn = py_voice_name_by_id.get(m, "")
            print(f"  - {al}: female={fn or f or 'N/A'}; male={mn or m or 'N/A'}")

    for app_lang in ok_langs:
        payload = rewritten_by_lang[app_lang]
        resolved_title = str(payload.get("resolved_title") or target_name or "").strip() or target_name
        rewritten_sections = payload.get("sections") or []

        for gender in genders:
            out_dir = static_audio_dir / app_lang / gender / country_slug / city_slug
            if place_slug:
                out_dir = out_dir / place_slug
            out_dir.mkdir(parents=True, exist_ok=True)

            edge_jobs: List[Tuple[str, str, Path]] = []
            edge_voice = ""
            if tts_backend == "edge":
                edge_voice = edge_voice_by_lang_gender.get(app_lang, {}).get(gender) or pick_edge_voice(app_lang, gender, edge_profile)

            # Audio files
            for sec in rewritten_sections:
                for ch in sec.chunks:
                    dest = out_dir / ch.file
                    if dest.exists() and dest.stat().st_size > 0 and not args.force:
                        continue

                    tts_text = with_punctuation_pauses(ch.text, tts_backend)

                    if tts_backend == "edge":
                        edge_jobs.append((edge_voice, tts_text, dest))
                        continue

                    if tts_backend == "openai":
                        audio = openai_tts_bytes(api_key, tts_model, openai_voices[gender], tts_text)
                        tmp = out_dir / (ch.file + ".tmp")
                        tmp.write_bytes(audio)
                        tmp.replace(dest)
                    elif tts_backend == "gtts":
                        gtts_lang = APP_LANG_TO_GTTS.get(app_lang) or "en"
                        tld = (GTTS_TLD_BY_LANG_GENDER.get(app_lang, {}) or {}).get(gender, "com")
                        gtts_speak_to_mp3(tts_text, dest, lang=gtts_lang, tld=tld, slow=gtts_slow)
                    else:
                        voice_id = py_voice_id_by_lang_gender.get(app_lang, {}).get(gender) or ""
                        if not voice_id:
                            raise RuntimeError(f"No pyttsx3 voice found for {app_lang}/{gender}")
                        pyttsx3_speak_to_wav(voice_id, tts_text, dest, rate=py_rate)

                    if args.sleep:
                        time.sleep(max(0.0, float(args.sleep)))

            if tts_backend == "edge" and edge_jobs:
                asyncio.run(
                    edge_tts_generate_jobs(
                        jobs=edge_jobs,
                        rate=edge_rate,
                        pitch=edge_pitch,
                        volume=edge_volume,
                        concurrency=edge_concurrency,
                    )
                )

            manifest = {
                "version": 1,
                "kind": target_kind,
                "title": manifest_title or resolved_title or target_name,
                "countrySlug": country_slug,
                "citySlug": city_slug,
                "lang": app_lang,
                "gender": gender,
                "ttsBackend": tts_backend,
                "availableLanguages": ok_langs,
                "sections": [
                    {
                        "title": sec.title,
                        "words": sec.words,
                        "textHash": sec.text_hash,
                        "status": "ready",
                        "chunks": [
                            {
                                "file": ch.file,
                                "words": ch.words,
                                "textHash": ch.text_hash,
                                "status": "ready",
                            }
                            for ch in sec.chunks
                        ],
                    }
                    for sec in rewritten_sections
                ],
            }
            if place_slug:
                manifest["placeSlug"] = place_slug

            if tts_backend == "openai":
                manifest["voice"] = openai_voices[gender]
                manifest["ttsModel"] = tts_model
            elif tts_backend == "edge":
                edge_voice = edge_voice_by_lang_gender.get(app_lang, {}).get(gender) or pick_edge_voice(app_lang, gender, edge_profile)
                manifest["voice"] = edge_voice
                manifest["voiceName"] = edge_voice
                manifest["voiceProfile"] = edge_profile
                manifest["ttsRate"] = edge_rate
                manifest["ttsPitch"] = edge_pitch
                manifest["ttsVolume"] = edge_volume
            elif tts_backend == "gtts":
                gtts_lang = APP_LANG_TO_GTTS.get(app_lang) or "en"
                tld = (GTTS_TLD_BY_LANG_GENDER.get(app_lang, {}) or {}).get(gender, "com")
                manifest["voiceName"] = f"gTTS-{gtts_lang}-{tld}"
                manifest["voiceProfile"] = "gtts"
                manifest["gttsSlow"] = bool(gtts_slow)
            else:
                voice_id = py_voice_id_by_lang_gender.get(app_lang, {}).get(gender) or ""
                manifest["voiceId"] = voice_id
                manifest["voiceName"] = py_voice_name_by_id.get(voice_id, "")
                manifest["voiceRate"] = py_rate

            (out_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        print(f"[OK] {app_lang}: audio + manifests ready ({', '.join(genders)})")

    print(f"[DONE] Generated languages: {', '.join(ok_langs)}")
    print(f"[DONE] Output: {static_audio_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

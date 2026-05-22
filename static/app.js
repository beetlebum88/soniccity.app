// ======================= Helpers =======================
const $ = (id) => document.getElementById(id);

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return (window.AG_CSRF_TOKEN || meta?.getAttribute("content") || "").trim();
}

function csrfHeaders(headers) {
  const out = Object.assign({}, headers || {});
  const token = csrfToken();
  if (token) out["X-CSRF-Token"] = token;
  return out;
}

function setStatus(text) {
  if (els.status) els.status.textContent = text;
}

function audioLoadingText(percent) {
  const n = Number(percent);
  if (Number.isFinite(n)) return `${tr("audio_loading", "Loading audio…")} ${Math.round(clamp(n, 0, 100))}%`;
  return tr("audio_loading", "Loading audio…");
}

function sanitizeAudioLoadingLabel(text, fallbackPercent) {
  const raw = String(text || "").trim();
  if (!raw) return audioLoadingText(fallbackPercent);
  const hiddenVoiceName = String.fromCharCode(115, 105, 114, 105);
  const technicalAudioLabel = new RegExp(`${hiddenVoiceName}|tts|provider|entity|queue|cache|local`, "i");
  if (technicalAudioLabel.test(raw)) return audioLoadingText(fallbackPercent);
  if (/^\d+%$/.test(raw)) return `${tr("audio_loading", "Loading audio…")} ${raw}`;
  if (raw.startsWith(tr("audio_loading", "Loading audio…"))) return raw;
  return audioLoadingText(fallbackPercent);
}

function setPlayerLoading(isLoading, text) {
  const el = $("plLoading");
  if (!el) return;
  const show = !!isLoading;
  el.hidden = !show;
  if (show) el.textContent = sanitizeAudioLoadingLabel(text);
}

function setPlayerStatusLabel(text) {
  const el = $("plStatus");
  if (el) el.textContent = text || tr("player_no_track_label", "Choose an audio story");
}

// Surface unexpected runtime errors in the UI (helps debug on mobile without DevTools).
window.addEventListener("error", (ev) => {
  try {
    const msg = ev?.message || "Unknown error";
    setStatus(`⚠ ${msg}`);
  } catch {}
});
window.addEventListener("unhandledrejection", (ev) => {
  try {
    const msg = ev?.reason?.message || String(ev?.reason || "Unhandled rejection");
    setStatus(`⚠ ${msg}`);
  } catch {}
});

function canSpeak() {
  return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function encodeWikiTitle(title) {
  return encodeURIComponent(String(title || "").replace(/ /g, "_"));
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function flagMarkup(item) {
  const emoji = escapeHtml(item?.flagEmoji || "🌍");
  if (!item?.flag) return `<span class="FlagFallback">${emoji}</span>`;
  return `<span class="FlagFallback" hidden>${emoji}</span><img class="Flag" src="${escapeHtml(item.flag)}" alt="" loading="lazy" onerror="this.hidden=true;this.previousElementSibling.hidden=false"/>`;
}

function cityDisplayName(city) {
  return String(city?.displayName || city?.localizedName || city?.name || "").trim();
}

function countryDisplayName(city) {
  return String(city?.countryDisplayName || city?.localizedCountryName || city?.countryName || city?.country || "").trim();
}

function localizedRoute(lang, parts) {
  const slug = String(lang || "en").toLowerCase();
  const clean = (Array.isArray(parts) ? parts : [])
    .map((part) => String(part || "").trim())
    .filter(Boolean);
  return "/" + (slug === "en" ? clean : [slug, ...clean]).join("/");
}

function normalizeCoordinates(c) {
  const lat = Number(c?.lat);
  const lon = Number(c?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

function stripParenthesesDeep(text) {
  if (!text) return "";
  let out = String(text);
  for (let i = 0; i < 14; i++) {
    const next = out.replace(/\([^()]*\)/g, "");
    if (next === out) break;
    out = next;
  }
  return out;
}

function cleanPlainText(input) {
  if (!input) return "";
  let text = String(input);

  text = text.replace(/[\u2010\u2011\u2012\u2013\u2014\u2212]/g, "-");
  text = text.replace(/\[[^\]]*]/g, "");
  text = stripParenthesesDeep(text);
  text = text.replace(/\b([A-Za-zÀ-ÿ'-]+)(\s+\1\b)+/gi, "$1");
  text = text.replace(/\s{2,}/g, " ").trim();

  return text;
}

function clamp(n, a, b) {
  return Math.max(a, Math.min(b, n));
}

function countWords(text) {
  const t = String(text || "").trim();
  if (!t) return 0;
  return t.split(/\s+/).filter(Boolean).length;
}

function makeWordStarts(text) {
  const s = String(text || "");
  const starts = [];
  const re = /\S+/g;
  let m;
  while ((m = re.exec(s))) starts.push(m.index);
  return starts;
}

function countWordsByCharIndex(wordStarts, charIndex) {
  if (!wordStarts || !wordStarts.length) return 0;
  let lo = 0, hi = wordStarts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (wordStarts[mid] <= charIndex) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function formatTime(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return `${mm}:${ss}`;
}

function sumFiniteNumbers(list) {
  if (!Array.isArray(list) || !list.length) return 0;
  return list.reduce((acc, value) => {
    const n = Number(value);
    return Number.isFinite(n) ? (acc + n) : acc;
  }, 0);
}

function audioPlaybackProgress() {
  const totalChunks = Array.isArray(speakQueue) ? speakQueue.length : 0;
  if (!totalChunks) return { ratio: 0, remainingSec: 0, hasTime: false };

  const chunkIndex = clamp(Number(currentChunkIdx) || 0, 0, Math.max(0, totalChunks - 1));
  const isAnyActive = playerIsActive || (chunkIndex > 0);

  let fracInChunk = 0;
  const d = Number(audioEl?.duration);
  const t = Number(audioEl?.currentTime);
  if (Number.isFinite(d) && d > 0 && Number.isFinite(t) && t >= 0) {
    fracInChunk = clamp(t / d, 0, 1);
  }

  const progressedChunks = isAnyActive
    ? clamp(chunkIndex + fracInChunk, 0, totalChunks)
    : 0;
  const ratio = clamp(progressedChunks / totalChunks, 0, 1);

  const knownDurations = (Array.isArray(audioDurations) ? audioDurations : [])
    .map((x) => Number(x))
    .filter((x) => Number.isFinite(x) && x > 0);
  const knownTotal = sumFiniteNumbers(knownDurations);
  const knownAvg = knownDurations.length ? (knownTotal / knownDurations.length) : 0;
  const fallbackChunkSec = Math.max(knownAvg || 0, 11);

  let consumedSec = 0;
  if (Array.isArray(audioDurations) && audioDurations.length) {
    for (let i = 0; i < chunkIndex; i++) {
      const val = Number(audioDurations[i]);
      consumedSec += (Number.isFinite(val) && val > 0) ? val : fallbackChunkSec;
    }
  } else {
    consumedSec += chunkIndex * fallbackChunkSec;
  }
  consumedSec += (Number.isFinite(t) && t >= 0) ? t : 0;

  const totalEstimate = totalChunks * fallbackChunkSec;
  const remainingSec = Math.max(0, totalEstimate - consumedSec);
  const hasTime = Number.isFinite(totalEstimate) && totalEstimate > 0;

  return { ratio, remainingSec, hasTime };
}

// ======================= Config =======================
const SEARCH_RADIUS_KM = 10;
const MAX_MARKERS = 40;
const MAX_LIST = 12;

// GPS is sampled every 10s, while backend city lookup is gated by movement.
const GPS_REFRESH_MS = 10_000;
const GPS_MIN_FETCH_MS = 8_000;
const GPS_STATIONARY_REFRESH_MS = 60_000;
const GPS_MIN_MOVE_KM = 0.15;
const GPS_WEAK_ACCURACY_M = 180;
const GPS_SLOW_RESPONSE_MS = 18_000;
const AUTO_SWITCH_MIN_MS = 45_000;
const AUTO_SWITCH_MIN_IMPROVEMENT_KM = 1.2;
const AUTO_SWITCH_MOVE_CONFIRM_KM = 0.7;

// fallback speed
const EST_WPM = 160;
const MIN_AUDIO_SECTION_WORDS = 50;

// ======================= i18n / language =======================
const I18N = window.I18N || {};
const tr = (key, fallback) => (I18N && I18N[key]) ? I18N[key] : (fallback ?? key);

const LANG_META = {
  en: { wiki: "en", speech: "en-US" },
  fr: { wiki: "fr", speech: "fr-FR" },
  es: { wiki: "es", speech: "es-ES" },
  it: { wiki: "it", speech: "it-IT" },
  ua: { wiki: "uk", speech: "uk-UA" },
  uk: { wiki: "uk", speech: "uk-UA" },
  de: { wiki: "de", speech: "de-DE" },
};

const APP_TO_WIKI = { en: "en", fr: "fr", es: "es", it: "it", ua: "uk", uk: "uk", de: "de" };
const WIKI_TO_APP = { en: "en", fr: "fr", es: "es", it: "it", uk: "uk", de: "de" };
const audioStorageLang = (lang) => {
  const raw = String(lang || window.APP_LANG_INTERNAL || window.APP_LANG || "en").toLowerCase();
  if (raw === "uk") return "ua";
  return LANG_META[raw] ? raw : "en";
};

let activeAppLang = String(window.APP_LANG || "en").toLowerCase();
if (!LANG_META[activeAppLang]) activeAppLang = "en";

let activeWikiLang = String(window.WIKI_LANG || LANG_META[activeAppLang].wiki);
let activeSpeechLang = String(window.SPEECH_LANG || LANG_META[activeAppLang].speech);
const AG_USER_LOGGED_IN = !!window.AG_IS_LOGGED_IN;
const AG_LOGIN_URL = String(window.AG_LOGIN_URL || "/?login=1");
const AG_SIGNUP_URL = String(window.AG_SIGNUP_URL || "/?login=1&mode=register");

// ======================= Elements =======================
const els = {
  status: $("status"),
  citiesList: $("citiesList"),
  storyPanel: $("storyPanel"),
  storyTitle: $("storyTitle"),
  storySections: $("storySections"),
  storySource: $("storySource"),

  btnLocate: $("btnLocate"),
  btnStop: $("btnStop"),
  autoMode: $("autoMode"),

  btnSpeak: $("btnSpeak"),
  btnStopSpeech: $("btnStopSpeech"),
  btnPause: $("btnPause"),
  btnResume: $("btnResume"),
};

function refreshEls() {
  Object.assign(els, {
    status: $("status"),
    citiesList: $("citiesList"),
    storyPanel: $("storyPanel"),
    storyTitle: $("storyTitle"),
    storySections: $("storySections"),
    storySource: $("storySource"),

    btnLocate: $("btnLocate"),
    btnStop: $("btnStop"),
    autoMode: $("autoMode"),

    btnSpeak: $("btnSpeak"),
    btnStopSpeech: $("btnStopSpeech"),
    btnPause: $("btnPause"),
    btnResume: $("btnResume"),
  });
}

// ======================= State =======================
let map, userMarker, userCircle;
let watchId = null;
let refreshTimerId = null;
let gpsSlowTimerId = null;
let lastGpsStatusTs = 0;

let lastGps = null;
let lastNearbyFetch = null; // {ts, lat, lon}
let lastNearbyCities = [];

let selectedCity = null;
let playbackEntityCity = null;
let playbackGuideSections = [];
let selectedArticle = null;
let pendingPlayRequest = null; // {cityKey, mode:'all'|'section', sectionIdx?, label?}

let markersLayer = null;
let markersByKey = new Map();

let placesLayer = null;
let placeMarkersSession = 0;
let placeMarkersBySlug = new Map();
let activePlaceMarkerSlug = null;

let autoLastSwitchTs = 0;
let lastAutoPickGps = null;
let audioPrefetchKeys = new Set();
let pendingAudioRefreshKeys = new Set();
let audioSelectionToken = 0;
let audioWarmKeys = new Set();
let audioBlobUrlCache = new Map();
let audioBlobPromiseCache = new Map();
let audioLoadState = { active: false, loaded: 0, total: 0, label: "" };

// Speech queue
// chunk: { text, words, blockTitle, sectionIdx, wordStarts }
let speakQueue = [];
let speakIdx = 0;
let isPaused = false;

let chunksDoneWords = 0;
let currentChunkWords = 0;
let currentChunkReadWords = 0;

let playerTotalWords = 0;
let playerReadWords = 0;

let playerIsActive = false;
let playerDockPinned = false;

let boundarySeenCount = 0;
let boundaryLastChar = -1;
let boundaryReliable = false;

let chunkStartTs = 0;
let chunkWps = 0;
let pauseStartedTs = 0;

// Player DOM
let playerEl = null;
let playerSheetOpen = false;
let playerTimer = null;
let playbackSession = 0;
let activeUtterId = 0;

function nextPlaybackSession() {
  playbackSession += 1;
  return playbackSession;
}

 // Playback backend: 'speech' (Web Speech API), 'audio' (pre-generated files), or 'pending' (outline visible, audio building)
 let playbackBackend = "speech";
 let audioEl = null;
 let audioTransitioning = false;
 let audioIntentionalStop = false;
 let audioDurations = []; // seconds per queue item (NaN until known)

 // Voice preference for pre-generated audio ('female'|'male').
 // Start from the same natural female voice profile everywhere unless the user changes it.
 let voiceGender = "female";
 try { localStorage.setItem("ag_voice_gender", voiceGender); } catch {}

 // Smooth progress (avoid jumps)
 let playerReadWordsTarget = 0;
 let playerReadWordsDisplay = 0;

 // rAF render loop
 let renderRafId = null;
 let renderLastUiTs = 0;

 // Current chunk index (for prev/next)
 let currentChunkIdx = -1;

 // Speech settings
 const SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0];
 let speechRate = 1.0;
 const PLAYER_VOLUME_KEY = "ag_player_volume";
 let playerVolume = 1.0;

 // Plan for Play when idle
 let lastPlayPlan = null; // {mode:'all'|'section', sectionIdx?}

// Now playing state
let nowPlaying = {
  mode: null,        // 'all'|'section'
  sectionIdx: null,
  blockTitle: "—",
  cityTitle: "",
};

const globalPlayerState = {
  currentTrackId: null,
  currentEntityType: null,
  currentEntityId: null,
  currentEntityTitle: "",
  currentSectionId: null,
  currentSectionTitle: "",
  currentAudioUrl: "",
  currentLanguage: activeAppLang,
  currentVoiceGender: voiceGender,
  queue: [],
  currentIndex: -1,
  isPlaying: false,
  isLoading: false,
  loadingProgress: 0,
  currentTime: 0,
  duration: 0,
  volume: playerVolume,
  playbackRate: speechRate,
  error: null,
};
window.AG_PLAYER_STATE = globalPlayerState;

function globalPlayerQueueSnapshot() {
  return (Array.isArray(speakQueue) ? speakQueue : []).map((item, idx) => ({
    id: trackIdFromQueueItem(item, idx),
    index: idx,
    title: String(item?.blockTitle || tr("city_outline", "Audio stories")),
    sectionId: Number.isFinite(Number(item?.sectionIdx)) ? Number(item.sectionIdx) : null,
    audioUrl: String(item?.srcUrl || item?.url || "").trim(),
    duration: Number.isFinite(Number(audioDurations?.[idx])) ? Number(audioDurations[idx]) : 0,
  }));
}

function trackIdFromQueueItem(item, idx) {
  const section = Number.isFinite(Number(item?.sectionIdx)) ? Number(item.sectionIdx) : "na";
  const url = String(item?.srcUrl || item?.url || "").trim();
  const entityCity = playbackEntityCity || selectedCity;
  const entity = entityCity ? cityKey(entityCity) : (selectedArticle?.title || "guide");
  return `${entity}:${section}:${Number(idx) || 0}:${url || item?.blockTitle || "track"}`;
}

function emitGlobalPlayerState() {
  window.AG_PLAYER_STATE = globalPlayerState;
  try {
    window.dispatchEvent(new CustomEvent("ag:player-state", {
      detail: { ...globalPlayerState, queue: [...globalPlayerState.queue] },
    }));
  } catch {}
  syncInlineNowPlayingCards();
}

function shouldShowPlayerDock() {
  return !!playerDockPinned || !!(playerIsActive && Array.isArray(speakQueue) && speakQueue.length);
}

function showPlayerDock() {
  playerDockPinned = true;
  setPlayerVisible(true);
}

function hidePlayerDock() {
  playerDockPinned = false;
  setPlayerVisible(false);
}

function syncGlobalPlayerState(patch) {
  const idx = Number.isFinite(Number(currentChunkIdx)) ? Number(currentChunkIdx) : -1;
  const item = idx >= 0 ? speakQueue?.[idx] : null;
  const el = audioEl;
  const entityCity = playbackEntityCity || selectedCity;
  const currentTime = Number(el?.currentTime);
  const duration = Number(el?.duration);
  Object.assign(globalPlayerState, {
    currentTrackId: item ? trackIdFromQueueItem(item, idx) : globalPlayerState.currentTrackId,
    currentEntityType: entityCity?.kind || globalPlayerState.currentEntityType || "city",
    currentEntityId: entityCity ? cityKey(entityCity) : globalPlayerState.currentEntityId,
    currentEntityTitle: nowPlaying.cityTitle || cityDisplayName(entityCity) || selectedArticle?.title || cityDisplayName(selectedCity) || globalPlayerState.currentEntityTitle || "",
    currentSectionId: Number.isFinite(Number(nowPlaying.sectionIdx)) ? Number(nowPlaying.sectionIdx) : null,
    currentSectionTitle: nowPlaying.blockTitle || globalPlayerState.currentSectionTitle || "",
    currentAudioUrl: item ? String(item?.srcUrl || item?.url || "").trim() : globalPlayerState.currentAudioUrl,
    currentLanguage: activeAppLang,
    currentVoiceGender: voiceGender === "male" ? "male" : "female",
    queue: globalPlayerQueueSnapshot(),
    currentIndex: idx,
    isPlaying: !!(playerIsActive && !isPaused),
    isLoading: !!audioLoadState.active,
    loadingProgress: audioLoadState.total > 0 ? clamp((Number(audioLoadState.loaded) || 0) / Number(audioLoadState.total), 0, 1) : 0,
    currentTime: Number.isFinite(currentTime) ? currentTime : globalPlayerState.currentTime,
    duration: Number.isFinite(duration) ? duration : globalPlayerState.duration,
    volume: playerVolume,
    playbackRate: speechRate,
    error: null,
  }, patch || {});
  emitGlobalPlayerState();
}

function markAudioPausedFromElement() {
  if (audioTransitioning || audioIntentionalStop) return;
  if (!playerIsActive || playbackBackend !== "audio") return;
  showPlayerDock();
  isPaused = true;
  pauseStartedTs = (window.performance && typeof window.performance.now === "function")
    ? window.performance.now()
    : Date.now();
  if (nowPlaying.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setBadge(nowPlaying.sectionIdx, "PAUSED");
    setPlayingHighlight(nowPlaying.sectionIdx);
  }
  setPlayerLoading(false);
  renderPlayerProgress();
  persistPlaybackState(true);
  syncGlobalPlayerState({ isPlaying: false, isLoading: false });
}

function markAudioPlayingFromElement() {
  if (!playerIsActive || playbackBackend !== "audio") return;
  showPlayerDock();
  clearPlaybackUnlockHandler();
  isPaused = false;
  pauseStartedTs = 0;
  if (nowPlaying.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setBadge(nowPlaying.sectionIdx, "PLAYING");
    setPlayingHighlight(nowPlaying.sectionIdx);
  }
  setPlayerLoading(false);
  renderPlayerProgress();
  persistPlaybackState(true);
  syncGlobalPlayerState({ isPlaying: true, isLoading: false, error: null });
}

// Sections UI refs
let sectionEls = new Map();      // idx -> .sectionTop
let sectionBadgeEls = new Map(); // idx -> badge element
let sectionToggleBtns = new Map(); // idx -> toggle btn

let selectedSectionIdx = null;

const PLAYBACK_STATE_KEY = "ag_playback_state_v2";
const PLAYBACK_STATE_TTL_MS = 1000 * 60 * 60 * 8;
let playbackPersistTs = 0;
let resumeSeek = null; // { sessionId, chunkIdx, timeSec }
window.__AG_PLAYBACK_RESTORED = false;
window.__AG_PLAYBACK_RESTORE_PENDING = false;
let playbackUnlockHandler = null;
let softNavInFlight = null;
let softNavInstalled = false;

// ======================= Map =======================
function initMap() {
  if (!window.L) {
    return;
  }
  if (!$("map")) {
    return;
  }

  map = L.map("map").setView([39.4699, -0.3763], 7);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  markersLayer = L.layerGroup().addTo(map);
  placesLayer = L.layerGroup().addTo(map);

  const fix = () => { try { map.invalidateSize(true); } catch {} };
  setTimeout(fix, 120);
  setTimeout(fix, 350);
  setTimeout(fix, 900);
  window.addEventListener("resize", () => setTimeout(fix, 150));
}

function destroyMainMap() {
  try {
    if (map && typeof map.remove === "function") map.remove();
  } catch {}
  map = null;
  userMarker = null;
  userCircle = null;
  markersLayer = null;
  placesLayer = null;
  markersByKey.clear();
  placeMarkersBySlug.clear();
  activePlaceMarkerSlug = null;
}

function updateUserOnMap(lat, lon, accuracy) {
  if (!map) return;
  const ll = [lat, lon];

  if (!userMarker) {
    userMarker = L.marker(ll).addTo(map).bindPopup(escapeHtml(tr("you_are_here", "You are here")));
    userMarker.bindTooltip(escapeHtml(tr("you_are_here", "You are here")), {
      direction: "top",
      offset: [0, -12],
      opacity: 0.95,
    });
    userCircle = L.circle(ll, { radius: Math.max(accuracy || 30, 30) }).addTo(map);
    map.setView(ll, 12);
  } else {
    userMarker.setLatLng(ll);
    userCircle.setLatLng(ll).setRadius(Math.max(accuracy || 30, 30));
  }
}

function cityKey(c) {
  const kind = String(c?.kind || "city").toLowerCase();
  const countrySlug = String(c?.countrySlug || "").trim().toLowerCase();
  const citySlug = String(c?.citySlug || "").trim().toLowerCase();
  const placeSlug = String(c?.placeSlug || c?.slug || "").trim().toLowerCase();
  if (kind === "country" && countrySlug) {
    return `${kind}:${countrySlug}`;
  }
  if (countrySlug && citySlug) {
    return `${kind}:${countrySlug}:${citySlug}${placeSlug ? `:${placeSlug}` : ""}`;
  }
  if (c?.id !== undefined && c?.id !== null && String(c.id).trim()) {
    return `${kind}:id:${String(c.id).trim()}`;
  }
  const fallbackName = String(c?.name || "").trim().toLowerCase();
  const fallbackCountry = String(c?.country || c?.countryName || "").trim().toLowerCase();
  return `${kind}:${fallbackCountry}:${fallbackName}`;
}

function playbackEntityKey() {
  if (playbackEntityCity) return cityKey(playbackEntityCity);
  return String(globalPlayerState.currentEntityId || "").trim();
}

function currentPageEntityKey() {
  if (selectedCity) return cityKey(selectedCity);
  return "";
}

function activePlaybackBelongsToCurrentPage() {
  const playbackKey = playbackEntityKey();
  const pageKey = currentPageEntityKey();
  return !!playbackKey && !!pageKey && playbackKey === pageKey;
}

function playbackEntityTitle(fallback) {
  return String(
    nowPlaying?.cityTitle ||
    cityDisplayName(playbackEntityCity) ||
    globalPlayerState.currentEntityTitle ||
    fallback ||
    ""
  ).trim();
}

window.AG_CITY_KEY = cityKey;

function selectedCityMatches(c) {
  if (!selectedCity || !c) return false;
  return cityKey(selectedCity) === cityKey(c);
}

function cityGuideUrl(c) {
  const countrySlug = String(c?.countrySlug || "").trim();
  const citySlug = String(c?.citySlug || c?.slug || "").trim();
  if (!countrySlug || !citySlug) return "#storyPanel";
  return localizedRoute(activeAppLang || window.APP_LANG || "en", [countrySlug, citySlug]);
}

function cityPopupHtml(c) {
  const title = cityDisplayName(c);
  const countryLabel = countryDisplayName(c);
  const distance = Number.isFinite(Number(c?.distKm)) ? `≈ ${Number(c.distKm).toFixed(1)} km` : "";
  const url = cityGuideUrl(c);
  return `
    <div class="ag-mapPopup ag-cityPopup">
      <div class="ag-mapPopupTitle">${escapeHtml(title)}</div>
      <div class="ag-mapPopupMeta">${escapeHtml([countryLabel, distance].filter(Boolean).join(" • "))}</div>
      <div class="ag-mapPopupActions">
        <button class="ag-mapAction ag-mapActionPrimary" type="button" data-city-select="1" data-city-key="${escapeHtml(cityKey(c))}">${escapeHtml(tr("listen_all", "Play guide"))}</button>
        <a class="ag-mapAction" href="${url}">${escapeHtml(tr("open_guide", "Open guide"))}</a>
      </div>
    </div>
  `;
}

function clearMarkers() {
  if (!markersLayer) return;
  markersLayer.clearLayers();
  markersByKey.clear();
}

function clearPlaceMarkers() {
  if (!placesLayer) return;
  placesLayer.clearLayers();
  placeMarkersBySlug.clear();
  activePlaceMarkerSlug = null;
}

function setMarkers(found) {
  clearMarkers();
  if (!markersLayer) return;

  for (const c of found) {
    const key = cityKey(c);
    const m = L.marker([c.lat, c.lon]).addTo(markersLayer);
    m.__agCity = c;

    m.bindTooltip(escapeHtml(cityDisplayName(c)), {
      direction: "top",
      offset: [0, -12],
      opacity: 0.95,
    });
    m.bindPopup(cityPopupHtml(c));

    m.on("popupopen", () => {
      const el = m.getPopup()?.getElement?.();
      const btn = el?.querySelector?.("[data-city-select]");
      if (btn) btn.onclick = (ev) => {
        try { ev?.preventDefault?.(); ev?.stopPropagation?.(); } catch {}
        selectCityAndPlayAll(c, { scroll: true });
      };
    });
    m.on("click", () => m.openPopup());
    markersByKey.set(key, m);
  }
}

function openCityPopup(c) {
  const m = markersByKey.get(cityKey(c));
  if (m) m.openPopup();
}

async function selectCityAndPlayAll(c, opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  await onSelectCity(c, {
    scroll: options.scroll !== false,
    warm: false,
    autoPlayAfterLoad: true,
  });
}

function ensureCityMarker(c) {
  if (!map || !markersLayer || !window.L) return;
  const key = cityKey(c);
  if (markersByKey.has(key)) return;

  const countryLabel = countryDisplayName(c);
  const m = L.marker([c.lat, c.lon]).addTo(markersLayer);
  m.__agCity = c;
  m.bindTooltip(escapeHtml(cityDisplayName(c)), {
    direction: "top",
    offset: [0, -12],
    opacity: 0.95,
  });
  m.bindPopup(cityPopupHtml({ ...c, countryDisplayName: countryLabel }));
  m.on("popupopen", () => {
    const el = m.getPopup()?.getElement?.();
    const btn = el?.querySelector?.("[data-city-select]");
    if (btn) btn.onclick = (ev) => {
      try { ev?.preventDefault?.(); ev?.stopPropagation?.(); } catch {}
      selectCityAndPlayAll(c, { scroll: true });
    };
  });
  markersByKey.set(key, m);
}

async function fetchPlaceGeo(countrySlug, citySlug, placeSlug) {
  const url =
    `/api/place_geo?lang=${encodeURIComponent(activeAppLang)}` +
    `&country=${encodeURIComponent(countrySlug || "")}` +
    `&city=${encodeURIComponent(citySlug || "")}` +
    `&place=${encodeURIComponent(placeSlug || "")}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    const lat = Number(data?.lat);
    const lon = Number(data?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return { lat, lon };
  } catch {
    return null;
  }
}

function placePageContext() {
  if (window.PLACE_PAGE) {
    return {
      kind: "place",
      lang: String(window.APP_LANG || activeAppLang || "en").toLowerCase(),
      countrySlug: window.PLACE_PAGE.countrySlug,
      citySlug: window.PLACE_PAGE.citySlug,
      cityName: window.PLACE_PAGE.cityName,
      countryName: window.PLACE_PAGE.countryName,
      centerLat: Number(window.PLACE_PAGE.lat),
      centerLon: Number(window.PLACE_PAGE.lon),
      currentPlaceSlug: window.PLACE_PAGE.placeSlug,
    };
  }
  if (window.CITY_PAGE) {
    return {
      kind: "city",
      lang: String(window.APP_LANG || activeAppLang || "en").toLowerCase(),
      countrySlug: window.CITY_PAGE.countrySlug,
      citySlug: window.CITY_PAGE.citySlug,
      cityName: window.CITY_PAGE.name,
      countryName: window.CITY_PAGE.countryName,
      centerLat: Number(window.CITY_PAGE.lat),
      centerLon: Number(window.CITY_PAGE.lon),
      currentPlaceSlug: null,
    };
  }
  return null;
}

function placeUrl(ctx, placeSlug) {
  return localizedRoute(ctx?.lang || "en", [ctx?.countrySlug || "", ctx?.citySlug || "", placeSlug || ""]);
}

function placeImgUrl(ctx, placeSlug) {
  const l = "en";
  const ctry = encodeURIComponent(ctx?.countrySlug || "");
  const cty = encodeURIComponent(ctx?.citySlug || "");
  const pl = encodeURIComponent(placeSlug || "");
  return `/media/place/${l}/${ctry}/${cty}/${pl}`;
}

function placeCategoryLabel(p) {
  return String(p?.category || p?.kind || "Landmark")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function leafletPlaceIcon(place, active) {
  if (!window.L) return null;
  const category = placeCategoryLabel(place);
  const letter = (category.trim()[0] || "P").toUpperCase();
  return L.divIcon({
    className: "",
    iconSize: active ? [46, 46] : [38, 38],
    iconAnchor: active ? [23, 23] : [19, 19],
    html: `
      <button class="ag-placeMarker ${active ? "is-active" : ""}" type="button" aria-label="${escapeHtml(String(place?.name || "Place"))} marker">
        <span class="ag-placeMarkerGlyph" aria-hidden="true">${escapeHtml(letter)}</span>
      </button>
    `,
  });
}

function setActivePlaceMarker(slug) {
  activePlaceMarkerSlug = slug ? String(slug) : null;
  for (const [key, marker] of placeMarkersBySlug.entries()) {
    if (!marker) continue;
    const active = activePlaceMarkerSlug && key === activePlaceMarkerSlug;
    const place = marker.__agPlace || { name: key, category: "Landmark" };
    if (typeof marker.setIcon === "function") marker.setIcon(leafletPlaceIcon(place, active));
    marker.getElement?.()?.classList.toggle("is-active", !!active);
  }
  window.dispatchEvent(new CustomEvent("ag:place-marker-active", { detail: { slug: activePlaceMarkerSlug } }));
}

function emitPlaybackStopped() {
  try { window.AG_SET_ACTIVE_PLACE_MARKER?.(null); } catch {}
  try { window.dispatchEvent(new CustomEvent("ag:playback-stopped")); } catch {}
}

function cloneSectionForPlayback(sec, idx) {
  if (!sec || typeof sec !== "object") return null;
  return {
    title: String(sec.title || `Section ${idx + 1}`),
    text: String(sec.text || ""),
    words: Number.isFinite(Number(sec.words)) ? Number(sec.words) : 0,
    status: String(sec.status || "ready"),
    sectionIdx: idx,
    chunks: Array.isArray(sec.chunks)
      ? sec.chunks.map((ch) => ({
        url: String(ch?.url || "").trim(),
        words: Number.isFinite(Number(ch?.words)) ? Number(ch.words) : 0,
      })).filter((ch) => ch.url)
      : [],
  };
}

function capturePlaybackGuideSections() {
  const sections = Array.isArray(selectedArticle?.sections) ? selectedArticle.sections : [];
  playbackGuideSections = sections
    .map((sec, idx) => cloneSectionForPlayback(sec, idx))
    .filter(Boolean);
}

function getPlaybackGuideSections() {
  if (Array.isArray(playbackGuideSections) && playbackGuideSections.length) return playbackGuideSections;
  const sections = Array.isArray(selectedArticle?.sections) ? selectedArticle.sections : [];
  return sections.map((sec, idx) => cloneSectionForPlayback(sec, idx)).filter(Boolean);
}

function getPageGuideSections() {
  const sections = Array.isArray(selectedArticle?.sections) ? selectedArticle.sections : [];
  return sections.map((sec, idx) => cloneSectionForPlayback(sec, idx)).filter(Boolean);
}

function guideSectionsForPlaybackItems(opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  if (options.playbackContext) return getPlaybackGuideSections();
  return getPageGuideSections();
}

function buildSectionPlaybackItems(sectionIdx, opts) {
  const idx = Number(sectionIdx);
  if (!Number.isFinite(idx)) return [];
  const sections = guideSectionsForPlaybackItems(opts);
  const sec = sections[idx];
  if (!sec) return [];

  const blockTitle = sec.title || `Section ${idx + 1}`;
  if (playbackBackend === "audio" && Array.isArray(sec.chunks) && sec.chunks.length) {
    return sec.chunks.map((ch) => ({
      url: ch.url,
      words: Number.isFinite(Number(ch?.words)) ? Number(ch.words) : 0,
      blockTitle,
      sectionIdx: idx,
    })).filter((item) => item.url);
  }

  if (String(sec.text || "").trim()) {
    return [{
      text: sec.text,
      blockTitle,
      sectionIdx: idx,
    }];
  }
  return [];
}

function buildAllPlaybackItems(opts) {
  const sections = guideSectionsForPlaybackItems(opts);
  const items = [];
  sections.forEach((sec, idx) => {
    const sectionItems = buildSectionPlaybackItems(idx, opts);
    sectionItems.forEach((item) => items.push(item));
  });
  return items;
}

function hasPlayableSection(idx, opts) {
  return buildSectionPlaybackItems(idx, opts).length > 0;
}

function currentPlaybackSectionIdx() {
  if (Number.isFinite(Number(nowPlaying?.sectionIdx))) return Number(nowPlaying.sectionIdx);
  const current = Number.isFinite(Number(currentChunkIdx)) ? speakQueue?.[currentChunkIdx] : null;
  if (Number.isFinite(Number(current?.sectionIdx))) return Number(current.sectionIdx);
  if (lastPlayPlan?.mode === "section" && Number.isFinite(Number(lastPlayPlan.sectionIdx))) {
    return Number(lastPlayPlan.sectionIdx);
  }
  return null;
}

function currentPlaybackSectionMatches(sectionIdx) {
  const idx = Number(sectionIdx);
  if (!Number.isFinite(idx)) return false;
  const cur = currentPlaybackSectionIdx();
  return Number.isFinite(Number(cur)) && Number(cur) === idx;
}

function findAdjacentSectionIdx(direction) {
  const dir = direction < 0 ? -1 : 1;
  const sections = getPlaybackGuideSections();
  if (!sections.length) return null;
  const cur = currentPlaybackSectionIdx();
  const start = Number.isFinite(Number(cur))
    ? Number(cur) + dir
    : (dir > 0 ? 0 : sections.length - 1);
  for (let i = start; i >= 0 && i < sections.length; i += dir) {
    if (hasPlayableSection(i, { playbackContext: true })) return i;
  }
  return null;
}

function autoAdvanceToNextSection(sessionId) {
  if (sessionId !== playbackSession) return false;
  if (nowPlaying?.mode !== "section") return false;
  const nextSection = findAdjacentSectionIdx(1);
  if (nextSection == null) return false;
  lastPlayPlan = { mode: "section", sectionIdx: nextSection };
  return startSectionPlayback(nextSection, { preservePlaybackContext: true });
}

function startSectionPlayback(sectionIdx, opts) {
  if (requireLoginForPlayback()) return false;
  const options = (opts && typeof opts === "object") ? opts : {};
  const idx = Number(sectionIdx);
  if (!Number.isFinite(idx)) return false;

  if (selectedArticle?.audioPending || playbackBackend === "pending") {
    const sec = selectedArticle?.sections?.[idx];
    queuePendingPlayback("section", idx, sec?.title || `Section ${idx + 1}`);
    setBadge(idx, tr("audio_loading", "Loading audio…"));
    return true;
  }

  if (!options.preservePlaybackContext) setSelectedHighlight(idx);
  lastPlayPlan = { mode: "section", sectionIdx: idx };
  const items = buildSectionPlaybackItems(idx, { playbackContext: !!options.preservePlaybackContext });
  if (!items.length) {
    setStatus(tr("audio_loading", "Loading audio…"));
    return false;
  }
  startPlaybackQueue(items, "section", { preservePlaybackContext: !!options.preservePlaybackContext });
  if (activePlaybackBelongsToCurrentPage()) {
    setPlayingHighlight(idx);
    setBadge(idx, "PLAYING");
  }
  syncAllToggleIcons();
  return true;
}

function toggleSectionPlayback(sectionIdx) {
  if (requireLoginForPlayback()) return false;
  const idx = Number(sectionIdx);
  if (!Number.isFinite(idx)) return false;
  setSelectedHighlight(idx);

  const isCurrent = playerIsActive && activePlaybackBelongsToCurrentPage() && currentPlaybackSectionMatches(idx);
  if (!isCurrent) return startSectionPlayback(idx);

  if (isPaused) resumeSpeech();
  else pauseSpeech();
  syncAllToggleIcons();
  renderPlayerProgress();
  return true;
}

async function playPlaceGuide(place, opts) {
  if (requireLoginForPlayback()) return false;
  const ctx = placePageContext();
  if (!ctx || !place?.slug) return false;
  const options = (opts && typeof opts === "object") ? opts : {};
  let geo = options.geo || null;
  if (!geo) geo = await fetchPlaceGeo(ctx.countrySlug, ctx.citySlug, place.slug);

  const target = {
    kind: "place",
    name: place.name || "",
    displayName: place.name || "",
    countryName: ctx.countryName || "",
    countrySlug: ctx.countrySlug || "",
    cityName: ctx.cityName || "",
    citySlug: ctx.citySlug || "",
    placeSlug: place.slug || "",
    slug: place.slug || "",
    wikiTitle: place.wikiTitle || place.name || "",
    lat: geo?.lat ?? ctx.centerLat,
    lon: geo?.lon ?? ctx.centerLon,
  };

  setActivePlaceMarker(place.slug);
  window.dispatchEvent(new CustomEvent("ag:place-play-request", { detail: { slug: place.slug, place } }));
  const loaded = await onSelectCity(target, { scroll: false, warm: true });
  if (loaded !== false) {
    setTimeout(() => {
      try { els.btnSpeak?.click?.(); } catch {}
    }, 120);
  }
  return true;
}

window.AG_PLAY_PLACE_GUIDE = playPlaceGuide;
window.AG_SET_ACTIVE_PLACE_MARKER = setActivePlaceMarker;
window.AG_FETCH_PLACE_GEO = fetchPlaceGeo;
window.AG_PLACE_URL = placeUrl;
window.AG_PLACE_IMG_URL = placeImgUrl;
window.AG_PLACE_CATEGORY_LABEL = placeCategoryLabel;

async function renderPlacesOnMap() {
  const ctx = placePageContext();
  const places = Array.isArray(window.CITY_PLACES) ? window.CITY_PLACES : [];
  if (!ctx || !map || !window.L || !placesLayer) return;

  clearPlaceMarkers();
  if (!places.length) return;

  const sess = ++placeMarkersSession;
  const tasks = places.map(async (p) => {
    const slug = p?.slug;
    if (!slug) return null;
    const geo = await fetchPlaceGeo(ctx.countrySlug, ctx.citySlug, slug);
    if (geo) return { p, geo };
    return null;
  });

  const results = await Promise.all(tasks);
  if (sess !== placeMarkersSession) return;

  const pts = [];
  results.filter(Boolean).forEach(({ p, geo }) => {
    const slug = String(p.slug || "");
    const name = String(p.name || "");
    const isCurrent = ctx.currentPlaceSlug && slug === ctx.currentPlaceSlug;

    const url = p?.url ? String(p.url) : placeUrl(ctx, slug);
    const img = placeImgUrl(ctx, slug);
    const category = placeCategoryLabel(p);
    const tip = `
      <div class="ag-placeTip">
        <img class="ag-placeTipImg" src="${img}" alt="" loading="lazy" decoding="async"/>
        <div class="ag-placeTipTxt">
          <div class="ag-placeTipName">${escapeHtml(name)}</div>
          <div class="ag-placeTipMeta">${escapeHtml([category, ctx.cityName].filter(Boolean).join(" • "))}</div>
        </div>
      </div>
    `;
    const popup = `
      <div class="ag-mapPopup ag-placePopup" data-place-slug="${escapeHtml(slug)}">
        <img class="ag-mapPopupImg" src="${img}" alt="" loading="lazy" decoding="async"/>
        <div class="ag-mapPopupTitle">${escapeHtml(name)}</div>
        <div class="ag-mapPopupMeta">${escapeHtml([category, ctx.cityName].filter(Boolean).join(" • "))}</div>
        <div class="ag-mapPopupActions">
          <button class="ag-mapAction ag-mapActionPrimary" type="button" data-place-play="${escapeHtml(slug)}">${escapeHtml(tr("listen_now", "Play audio"))}</button>
          <button class="ag-mapAction" type="button" data-place-route="${escapeHtml(slug)}">Route</button>
          <a class="ag-mapAction" href="${url}">${escapeHtml(tr("open_guide", "Open guide"))}</a>
        </div>
      </div>
    `;
    const m = L.marker([geo.lat, geo.lon], {
      icon: leafletPlaceIcon(p, isCurrent),
      keyboard: true,
      title: name,
      alt: name,
    }).addTo(placesLayer);
    m.__agPlace = p;
    placeMarkersBySlug.set(slug, m);

    m.bindTooltip(tip, {
      direction: "top",
      offset: [0, -10],
      opacity: 1,
      className: "ag-placeTooltip",
      sticky: true,
    });
    m.bindPopup(popup);

    m.on("click", () => {
      setActivePlaceMarker(slug);
      window.dispatchEvent(new CustomEvent("ag:place-selected", { detail: { slug, place: p, geo } }));
      m.openPopup();
    });
    m.on("popupopen", () => {
      const popupEl = m.getPopup()?.getElement?.();
      const playBtn = popupEl?.querySelector?.("[data-place-play]");
      const routeBtn = popupEl?.querySelector?.("[data-place-route]");
      if (playBtn) {
        playBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          playPlaceGuide(p, { geo });
        }, { once: true });
      }
      if (routeBtn) {
        routeBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (window.AG_CITY_MAP?.openWithPlace) {
            window.AG_CITY_MAP.openWithPlace(slug, "route");
          } else {
            window.location.href = url;
          }
        }, { once: true });
      }
    });

    pts.push([geo.lat, geo.lon]);
  });

  const hasCenter = Number.isFinite(ctx.centerLat) && Number.isFinite(ctx.centerLon);
  if (pts.length >= 1 && hasCenter) pts.push([ctx.centerLat, ctx.centerLon]);
  if (pts.length >= 2) {
    try { map.fitBounds(pts, { padding: [26, 26], maxZoom: 13 }); } catch {}
  }
}

// ======================= Backend Nearby =======================
async function fetchNearby(lat, lon) {
  const url =
    `/api/nearby?lat=${encodeURIComponent(lat)}` +
    `&lon=${encodeURIComponent(lon)}` +
    `&r=${SEARCH_RADIUS_KM}` +
    `&limit=${MAX_MARKERS}` +
    `&lang=${encodeURIComponent(activeAppLang)}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Nearby HTTP ${res.status}`);
  const data = await res.json();
  if (!Array.isArray(data)) throw new Error("Nearby response is not an array");

  return data.map((c) => ({
    ...c,
    lat: Number(c.lat),
    lon: Number(c.lon),
    distKm: Number.isFinite(Number(c.distKm))
      ? Number(c.distKm)
      : haversineKm(lat, lon, Number(c.lat), Number(c.lon)),
  }));
}

// ======================= Pre-generated Audio Guides =======================
// Prefer the newest pre-generated audio (pyttsx3, etc), but keep older versions as fallback.
const AUDIO_GUIDE_VERSIONS = ["v7"];
const NATURAL_AUDIO_PROFILE = String.fromCharCode(115, 105, 114, 105);

function audioManifestUrl(city, appLang, gender, version) {
  const kind = String(city?.kind || "").toLowerCase();
  const v = encodeURIComponent(String(version || "").trim() || "v1");
  const l = encodeURIComponent(audioStorageLang(appLang));
  const g = encodeURIComponent(String(gender || "female").toLowerCase());
  const ctry = encodeURIComponent(String(city?.countrySlug || "").toLowerCase());
  const cty = encodeURIComponent(String(city?.citySlug || "").toLowerCase());
  if (!ctry) return null;

  if (kind === "country") {
    return `/static/audio/${v}/${l}/${g}/${ctry}/__country__/manifest.json`;
  }

  if (!cty) return null;

  if (kind === "place") {
    const pl = encodeURIComponent(String(city?.placeSlug || "").toLowerCase());
    if (!pl) return null;
    return `/static/audio/${v}/${l}/${g}/${ctry}/${cty}/${pl}/manifest.json`;
  }

  return `/static/audio/${v}/${l}/${g}/${ctry}/${cty}/manifest.json`;
}

function langLinksFromAvailable(appLangs) {
  const out = {};
  const list = Array.isArray(appLangs) ? appLangs : [];
  for (const slug of list) {
    const s = String(slug || "").toLowerCase();
    if (!LANG_META[s]) continue;
    out[s] = { app: s, wiki: APP_TO_WIKI[s] || s, title: "" };
  }
  return out;
}

async function fetchAudioManifest(city, appLang, gender) {
  for (const ver of AUDIO_GUIDE_VERSIONS) {
    const url = audioManifestUrl(city, appLang, gender, ver);
    if (!url) continue;
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) continue;
      const data = await res.json();
      if (!data || typeof data !== "object") continue;
      if (!Array.isArray(data.sections) || !data.sections.length) continue;
      const backend = String(data?.ttsBackend || "").toLowerCase();
      const profile = String(data?.voiceProfile || "").toLowerCase();
      if (backend !== "edge" || profile !== NATURAL_AUDIO_PROFILE) continue;
      data._manifestUrl = url;
      data._audioBase = url.replace(/\/manifest\.json$/i, "");
      data._audioVersion = ver;
      return data;
    } catch {
      continue;
    }
  }
  return null;
}

async function requestAudioBuild(city, appLang, gender) {
  const kind = String(city?.kind || "").toLowerCase();
  const country = String(city?.countrySlug || "").toLowerCase();
  const cty = kind === "country" ? "__country__" : String(city?.citySlug || "").toLowerCase();
  const place = (kind === "place") ? String(city?.placeSlug || "").toLowerCase() : "";
  if (!country || !cty) return { status: "bad_target" };
  try {
    const res = await fetch("/api/audio_build", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        lang: String(appLang || "en").toLowerCase(),
        gender: String(gender || "female").toLowerCase(),
        kind,
        country,
        city: cty,
        place,
      }),
    });
    if (!res.ok) return { status: "http_error" };
    return await res.json();
  } catch {
    return { status: "network_error" };
  }
}

async function requestAudioBuildStatus(city, appLang, gender) {
  const kind = String(city?.kind || "").toLowerCase();
  const country = String(city?.countrySlug || "").toLowerCase();
  const cty = kind === "country" ? "__country__" : String(city?.citySlug || "").toLowerCase();
  const place = (kind === "place") ? String(city?.placeSlug || "").toLowerCase() : "";
  if (!country || !cty) return { status: "bad_target", ready: false, progress: 0 };
  const qs = new URLSearchParams({
    lang: String(appLang || "en").toLowerCase(),
    gender: String(gender || "female").toLowerCase(),
    kind,
    country,
    city: cty,
  });
  if (place) qs.set("place", place);
  try {
    const res = await fetch(`/api/audio_build_status?${qs.toString()}`, { cache: "no-store" });
    if (!res.ok) return { status: "http_error", ready: false, progress: 0 };
    return await res.json();
  } catch {
    return { status: "network_error", ready: false, progress: 0 };
  }
}

async function waitForAudioManifest(city, appLang, gender, opts) {
  const o = (opts && typeof opts === "object") ? opts : {};
  const attempts = Math.max(1, Number(o.attempts) || 6);
  const delayMs = Math.max(800, Number(o.delayMs) || 2500);
  for (let i = 0; i < attempts; i++) {
    const m = await fetchAudioManifest(city, appLang, gender);
    if (m) return m;
    if (i < attempts - 1) await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return null;
}

function currentSelectionMatches(city, token) {
  if (token !== audioSelectionToken) return false;
  if (!selectedCity || !city) return false;
  return cityKey(selectedCity) === cityKey(city);
}

function pendingAudioKey(city, appLang, gender) {
  const kind = String(city?.kind || "city").toLowerCase();
  const country = String(city?.countrySlug || "").toLowerCase();
  const cty = kind === "country" ? "__country__" : String(city?.citySlug || "").toLowerCase();
  const place = kind === "place" ? String(city?.placeSlug || "").toLowerCase() : "";
  return `${kind}:${country}:${cty}:${place}:${String(appLang || "").toLowerCase()}:${String(gender || "").toLowerCase()}`;
}

async function refreshPendingAudioForSelection(city, appLang, gender, token) {
  const key = pendingAudioKey(city, appLang, gender);
  if (!key || pendingAudioRefreshKeys.has(key)) return;
  pendingAudioRefreshKeys.add(key);
  const applyReadyManifest = async (manifest) => {
    if (!manifest || !currentSelectionMatches(city, token)) return false;
    try {
      const meta = LANG_META[String(appLang || "").toLowerCase()] || LANG_META.en || {};
      const article = audioArticleFromManifest(manifest);
      const picked = {
        article,
        appLang,
        wikiLang: meta.wiki || appLang,
        speechLang: meta.speech || appLang,
        backend: "audio",
      };
      if (!applyPickedArticleToUi(city, picked, String(appLang || activeAppLang || "en").toLowerCase(), { keepActiveAudio: false })) {
        return false;
      }
      setAudioLoadProgress(false, 0, 0, "");
      setPlayerLoading(false);
      renderCitiesList(lastNearbyCities);
      return true;
    } catch {
      return false;
    }
  };
  try {
    for (let attempt = 0; attempt < 60; attempt++) {
      if (!currentSelectionMatches(city, token)) return;

      let manifest = await fetchAudioManifest(city, appLang, gender);
      if (!manifest) {
        const build = await requestAudioBuild(city, appLang, gender);
        const buildStatus = await requestAudioBuildStatus(city, appLang, gender);
        if (String(buildStatus?.status || "").toLowerCase() === "failed") {
          setAudioLoadProgress(false, 0, 0, "");
          setPlayerLoading(false);
          setStatus(tr("audio_chunk_error", "Audio fragment failed. Continuing…"));
          return;
        }
        const pct = clamp(Number(buildStatus?.progress ?? build?.progress ?? 0) || 0, 0, 100);
        const label = audioLoadingText(pct);
        setAudioLoadProgress(true, pct, 100, label);
        setPlayerLoading(true, label);
        setStatus(label);
        if (
          pendingPlayRequest &&
          pendingPlayRequest.cityKey === cityKey(city) &&
          pendingPlayRequest.mode === "section" &&
          Number.isFinite(Number(pendingPlayRequest.sectionIdx))
        ) {
          setBadge(Number(pendingPlayRequest.sectionIdx), `${Math.round(pct)}%`);
        }
        if (buildStatus?.ready || String(buildStatus?.status || "").toLowerCase() === "done" || pct >= 99.5) {
          for (let i = 0; i < 6 && !manifest; i++) {
            manifest = await fetchAudioManifest(city, appLang, gender);
            if (!manifest) await new Promise((resolve) => setTimeout(resolve, 650));
          }
        }
        if (!manifest) manifest = await waitForAudioManifest(city, appLang, gender, { attempts: 1, delayMs: 1200 });
      }

      if (manifest) {
        await applyReadyManifest(manifest);
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  } finally {
    try { pendingAudioRefreshKeys.delete(key); } catch {}
  }
}

function scrollStoryPanelIntoView() {
  const panel = els.storyPanel || document.getElementById("storyPanel");
  if (!panel || typeof panel.scrollIntoView !== "function") return;
  try {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch {
    try { panel.scrollIntoView(); } catch {}
  }
}

function warmAudioVariants(city) {
  const key = pendingAudioKey(city, "all", "all");
  if (!key || audioWarmKeys.has(key)) return;
  audioWarmKeys.add(key);

  const pageLang = String(window.APP_LANG || activeAppLang || "en").toLowerCase();
  const otherGender = voiceGender === "male" ? "female" : "male";
  const variants = [
    { lang: pageLang, gender: voiceGender },
    { lang: pageLang, gender: otherGender },
  ];
  (async () => {
    for (const variant of variants) {
      try { await requestAudioBuild(city, variant.lang, variant.gender); } catch {}
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
  })();
}

function shouldPrefetchLandingAudio() {
  return !!(document.body && document.body.classList && document.body.classList.contains("PageLanding"));
}

async function prefetchNearbyAudio(cities) {
  if (!shouldPrefetchLandingAudio()) return;
  const rows = Array.isArray(cities) ? cities.slice(0, 3) : [];
  if (!rows.length) return;
  const pageLang = String(window.APP_LANG || activeAppLang || "en").toLowerCase();
  for (const city of rows) {
    const country = String(city?.countrySlug || "").toLowerCase();
    const cty = String(city?.citySlug || "").toLowerCase();
    if (!country || !cty) continue;
    const prefetchKey = `${pageLang}:${voiceGender}:${country}/${cty}`;
    if (audioPrefetchKeys.has(prefetchKey)) continue;
    audioPrefetchKeys.add(prefetchKey);
    (async () => {
      try {
        const manifest = await fetchAudioManifest(city, pageLang, voiceGender);
        if (!manifest) await requestAudioBuild(city, pageLang, voiceGender);
      } catch {}
      setTimeout(() => {
        try { audioPrefetchKeys.delete(prefetchKey); } catch {}
      }, 120000);
    })();
  }
}

function audioArticleFromManifest(manifest) {
  const base = String(manifest?._audioBase || "").replace(/\/$/, "");
  const sectionsIn = Array.isArray(manifest?.sections) ? manifest.sections : [];
  const sections = sectionsIn
    .map((sec) => {
      const title = String(sec?.title || "").trim();
      const chunksIn = Array.isArray(sec?.chunks) ? sec.chunks : [];
      const chunks = chunksIn
        .map((ch) => {
          const file = String(ch?.file || "").trim();
          if (!file) return null;
          const url = base ? `${base}/${file}` : file;
          const words = Number.isFinite(Number(ch?.words)) ? Number(ch.words) : 0;
          const textHash = String(ch?.textHash || "").trim();
          const status = String(ch?.status || "ready").trim().toLowerCase() || "ready";
          return { url, file, words, textHash, status };
        })
        .filter(Boolean);

      const words = Number.isFinite(Number(sec?.words))
        ? Number(sec.words)
        : chunks.reduce((s, x) => s + (Number(x?.words) || 0), 0);

      return {
        title: title || "Section",
        words,
        textHash: String(sec?.textHash || "").trim(),
        status: String(sec?.status || "ready").trim().toLowerCase() || "ready",
        chunks,
      };
    })
    .filter((s) => s && s.title && Array.isArray(s.chunks) && s.chunks.length);

  return {
    backend: "audio",
    title: String(manifest?.title || "").trim(),
    sections,
    ttsBackend: String(manifest?.ttsBackend || "").trim().toLowerCase(),
    ttsModel: String(manifest?.ttsModel || "").trim(),
    voiceName: String(manifest?.voiceName || manifest?.voice || manifest?.voiceId || "").trim(),
    langLinks: langLinksFromAvailable(manifest?.availableLanguages || []),
  };
}

// ======================= Wikipedia (multi-lang) =======================
function looksLikeNonCityTitle(title) {
  const t = (title || "").toLowerCase();
  if (/\b(open|atp|wta|tournament|championship|cup|season|final|201\d|202\d|19\d\d)\b/.test(t)) return true;
  if (/\b(football|basketball|tennis|race|grand prix|album|song|film)\b/.test(t)) return true;
  return false;
}

const CITY_QUERY_HINTS = {
  fr: ["ville", "commune"],
  es: ["ciudad", "municipio"],
  it: ["città", "comune"],
  de: ["stadt", "gemeinde"],
  uk: ["місто", "містечко"],
  en: ["city", "municipality"],
};

function wikiHost(wikiLang) {
  const wl = String(wikiLang || "").toLowerCase().trim();
  return `https://${wl}.wikipedia.org`;
}

function normLoose(s) {
  return String(s || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\u00c0-\u024f\u0400-\u04ff]+/g, "");
}

async function fetchSummaryByTitle(wikiLang, title) {
  const url = `${wikiHost(wikiLang)}/api/rest_v1/page/summary/${encodeWikiTitle(title)}`;
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`summary HTTP ${res.status}`);
  const data = await res.json();
  if ((data?.type || "").toLowerCase() === "disambiguation") throw new Error("disambiguation");
  return data;
}

async function findBestCityTitle(wikiLang, city) {
  const kind = String(city?.kind || city?.type || "").toLowerCase();
  const isPlace = kind === "place";
  const isCountry = kind === "country";
  const name = city.wikiTitle || city.name;
  const parentCity = city.cityName || city.parentCityName || "";
  const country = city.countryName || city.country || "";

  const hints = CITY_QUERY_HINTS[String(wikiLang || "").toLowerCase()] || CITY_QUERY_HINTS.en;
  const h1 = String(hints[0] || "city");
  const h2 = String(hints[1] || h1);

  const queries = isCountry
    ? [
        `${name}`,
        `${name} country`,
        country && country !== name ? `${country}` : null,
      ].filter(Boolean)
    : isPlace
    ? [
        parentCity && country ? `"${name}" ${parentCity} ${country}` : null,
        parentCity ? `"${name}" ${parentCity}` : null,
        country ? `"${name}" ${country}` : null,
        parentCity && country ? `${name} ${parentCity} ${country}` : null,
        country ? `${name} ${country}` : null,
        `${name}`,
      ].filter(Boolean)
    : [
        `"${name}" ${h1}`,
        `"${name}" ${h2}`,
        `${name} ${country} ${h1}`,
        `${name} ${country}`,
        `${name}`,
      ];

  const nameN = normLoose(name);
  const h1lc = h1.toLowerCase();
  const h2lc = h2.toLowerCase();

  for (const q of queries) {
    const api =
      `${wikiHost(wikiLang)}/w/api.php?action=query&list=search` +
      `&srsearch=${encodeURIComponent(q)}` +
      `&srlimit=10&format=json&origin=*`;

    const res = await fetch(api);
    if (!res.ok) continue;
    const data = await res.json();
    const results = data?.query?.search || [];
    if (!results.length) continue;

    let best = null;
    for (const r of results) {
      const title = r.title || "";
      if (!title) continue;
      if (looksLikeNonCityTitle(title)) continue;

      let score = 0;
      if (normLoose(title) === nameN) score += 100;

      const lt = title.toLowerCase();
      if (h1lc && lt.includes(h1lc)) score += 10;
      if (h2lc && lt.includes(h2lc)) score += 6;

      score += Math.max(0, 12 - (r.rank || 12));
      if (!best || score > best.score) best = { title, score };
    }

    if (best) return best.title;
  }

  return null;
}

async function fetchFullArticleHtml(wikiLang, title) {
  const api =
    `${wikiHost(wikiLang)}/w/api.php?action=parse&format=json&origin=*` +
    `&prop=text&formatversion=2&page=${encodeURIComponent(title)}`;

  const res = await fetch(api);
  if (!res.ok) throw new Error(`parse HTTP ${res.status}`);
  const data = await res.json();
  const html = data?.parse?.text;
  if (!html) throw new Error("no parse.text");
  return html;
}

async function fetchLangLinks(wikiLang, title) {
  const api =
    `${wikiHost(wikiLang)}/w/api.php?action=query&prop=langlinks&format=json&origin=*` +
    `&titles=${encodeURIComponent(title)}&lllimit=500`;

  const res = await fetch(api);
  if (!res.ok) throw new Error(`langlinks HTTP ${res.status}`);
  const data = await res.json();

  const pages = data?.query?.pages || {};
  const page = Object.values(pages)[0] || {};
  const links = page?.langlinks || [];

  const out = new Map();
  for (const it of links) {
    const l = String(it?.lang || "").toLowerCase();
    const t = String(it?.["*"] || it?.title || "").trim();
    if (l && t) out.set(l, t);
  }
  return out;
}

function supportedLangLinks(wikiLang, title, llMap) {
  const out = {};
  const selfApp = WIKI_TO_APP[String(wikiLang || "").toLowerCase()] || String(wikiLang || "").toLowerCase();
  if (LANG_META[selfApp]) out[selfApp] = { app: selfApp, wiki: wikiLang, title };

  for (const [appSlug, meta] of Object.entries(LANG_META)) {
    const wl = meta.wiki;
    if (wl === wikiLang) continue;
    const t = llMap?.get?.(wl);
    if (t) out[appSlug] = { app: appSlug, wiki: wl, title: t };
  }
  return out;
}

function htmlToH2Sections(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");

  doc.querySelectorAll(
    "table, .infobox, .navbox, .metadata, .hatnote, sup, style, script, .mw-editsection"
  ).forEach((el) => el.remove());

  const content = doc.querySelector(".mw-parser-output") || doc.body;
  content.querySelectorAll("#toc, .toc, .reflist, ol.references, div.refbegin").forEach(el => el.remove());

  const SKIP_H2 = new Set([
    "contents",
    "see also",
    "notes",
    "references",
    "further reading",
    "external links",
    "bibliography",
    "citations",
    "sources",
    "gallery",
    "photo gallery",
    "images",
    "coordinates",
    "navigation",
    "links",
  ]);

  const sections = [];
  let currentTitle = "Introduction";
  let currentSkip = false;
  let parts = [];

  const flush = () => {
    if (currentSkip) { parts = []; return; }
    const joined = parts.join("\n").trim();
    const cleaned = cleanPlainText(joined);
    const words = countWords(cleaned);
    if (cleaned && words >= MIN_AUDIO_SECTION_WORDS) {
      sections.push({ title: currentTitle, text: cleaned, words });
    }
    parts = [];
  };

  const nodes = Array.from(content.querySelectorAll("h2, h3, h4, p, ul, ol"));
  for (const el of nodes) {
    if (el.closest("#toc, .toc, table, .navbox, .infobox, .metadata")) continue;

    if (el.matches("h2")) {
      flush();
      const raw = (el.textContent || "").replace("[edit]", "").trim() || "Section";
      currentSkip = SKIP_H2.has(raw.toLowerCase());
      currentTitle = currentSkip ? "SKIP" : raw;
      continue;
    }

    if (currentSkip) continue;

    if (el.matches("h3, h4")) {
      const t = (el.textContent || "").replace("[edit]", "").trim();
      if (t) parts.push(`\n${t}\n`);
      continue;
    }

    if (el.matches("p")) {
      const t = (el.textContent || "").trim();
      if (t) parts.push(t);
      continue;
    }

    if (el.matches("ul, ol")) {
      const items = Array.from(el.querySelectorAll("li"))
        .map(li => (li.textContent || "").trim())
        .filter(Boolean);
      if (items.length) parts.push(items.map(x => `- ${x}`).join("\n"));
      continue;
    }
  }

  flush();
  return sections.filter(s => s.title && s.text);
}

async function getCityArticle(city, wikiLang, preferredTitle) {
  const wl = String(wikiLang || "").toLowerCase();
  const cacheKey = `ag_wiki_article_v3_${wl}_${city.id || city.name}`;
  try {
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed && typeof parsed === "object" && Array.isArray(parsed.sections)) {
        if (!parsed.wikiLang) parsed.wikiLang = wl;
        return parsed;
      }
      try { localStorage.removeItem(cacheKey); } catch {}
    }
  } catch {}

  let title = preferredTitle || city.wikiTitle || city.name;

  try {
    const sum = await fetchSummaryByTitle(wl, title);
    title = sum.title || title;

    const html = await fetchFullArticleHtml(wl, title);
    const sections = htmlToH2Sections(html);

    const payload = {
      wikiLang: wl,
      title,
      url: sum.content_urls?.desktop?.page || `${wikiHost(wl)}/wiki/${encodeWikiTitle(title)}`,
      sections,
      coordinates: normalizeCoordinates(sum?.coordinates),
    };

    try {
      const ll = await fetchLangLinks(wl, title);
      payload.langLinks = supportedLangLinks(wl, title, ll);
    } catch {}

    try { localStorage.setItem(cacheKey, JSON.stringify(payload)); } catch {}
    return payload;
  } catch {}

  const best = await findBestCityTitle(wl, city);
  if (!best) throw new Error("No suitable page found");

  const sum2 = await fetchSummaryByTitle(wl, best);
  const finalTitle = sum2.title || best;

  const html2 = await fetchFullArticleHtml(wl, finalTitle);
  const sections2 = htmlToH2Sections(html2);

  const payload2 = {
    wikiLang: wl,
    title: finalTitle,
    url: sum2.content_urls?.desktop?.page || `${wikiHost(wl)}/wiki/${encodeWikiTitle(finalTitle)}`,
    sections: sections2,
    coordinates: normalizeCoordinates(sum2?.coordinates),
  };

  try {
    const ll2 = await fetchLangLinks(wl, finalTitle);
    payload2.langLinks = supportedLangLinks(wl, finalTitle, ll2);
  } catch {}

  try { localStorage.setItem(cacheKey, JSON.stringify(payload2)); } catch {}
  return payload2;
}

function applyAvailableLanguages(langLinks) {
  const menu = document.getElementById("langMenu");
  if (!menu) return;
  const links = Array.from(menu.querySelectorAll("a[data-lang]"));
  for (const a of links) {
    const slug = String(a.dataset.lang || "").toLowerCase();
    const href = langLinks && langLinks[slug];
    if (href) a.setAttribute("href", href);
    const row = a.closest("li") || a;
    row.style.display = "";
    a.removeAttribute("aria-disabled");
  }
}

// ======================= Selection / badges / highlight =======================
function sectionAudioStatusLabel(sec, idx) {
  const pending = !!selectedArticle?.audioPending || playbackBackend === "pending";
  if (pending) return idx === 0 ? tr("audio_generating", "Preparing") : tr("audio_queued", "In queue");
  const rawStatus = String(sec?.status || "ready").toLowerCase();
  if (rawStatus === "failed") return tr("audio_failed", "Failed");
  if (rawStatus === "outdated") return tr("audio_outdated", "Needs update");
  if (rawStatus === "skipped") return tr("audio_skipped", "Skipped");
  return tr("audio_ready", "Ready");
}

function clearAllBadges() {
  for (const [idx, el] of sectionBadgeEls.entries()) {
    const sec = selectedArticle?.sections?.[idx];
    const label = sec ? sectionAudioStatusLabel(sec, idx) : "";
    el.textContent = label;
    el.style.display = label ? "inline-flex" : "none";
  }
}

function setBadge(idx, text) {
  const el = sectionBadgeEls.get(idx);
  if (!el) return;
  if (!text) {
    el.textContent = "";
    el.style.display = "none";
    return;
  }
  el.textContent = text;
  el.style.display = "inline-flex";
}

function clearPlayingHighlight() {
  for (const el of sectionEls.values()) {
    el.classList.remove("isPlaying");
    const mini = el.querySelector?.(".ag-secMiniProgress i");
    if (mini) mini.style.width = "0%";
  }
}

function setPlayingHighlight(idx) {
  clearPlayingHighlight();
  if (playerIsActive && !activePlaybackBelongsToCurrentPage()) return;
  const el = sectionEls.get(idx);
  if (el) el.classList.add("isPlaying");
}

function updateSectionMiniProgress(idx, ratio) {
  const pct = `${(clamp(Number(ratio) || 0, 0, 1) * 100).toFixed(2)}%`;
  const canShowActiveProgress = playerIsActive && activePlaybackBelongsToCurrentPage();
  for (const [i, el] of sectionEls.entries()) {
    const mini = el.querySelector?.(".ag-secMiniProgress i");
    if (mini) mini.style.width = (canShowActiveProgress && idx != null && i === idx) ? pct : "0%";
  }
}

function setSelectedHighlight(idx) {
  selectedSectionIdx = idx;
  for (const [i, el] of sectionEls.entries()) {
    if (i === idx) el.classList.add("isSelected");
    else el.classList.remove("isSelected");
  }
}

function setToggleIcon(btn, isPlay) {
  if (!btn) return;
  const ICON_PLAY = `<svg class="ag-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7l7 5-7 5z"/></svg>`;
  const ICON_PAUSE = `<svg class="ag-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7v10M15 7v10"/></svg>`;
  btn.innerHTML = isPlay ? ICON_PLAY : ICON_PAUSE;
  btn.title = isPlay ? "Play / Resume" : "Pause";
}

function syncAllToggleIcons() {
  const canShowActiveSection = playerIsActive && activePlaybackBelongsToCurrentPage();
  for (const [idx, btn] of sectionToggleBtns.entries()) {
    const isCurrent = canShowActiveSection && currentPlaybackSectionMatches(idx);
    const sectionTitle =
      selectedArticle?.sections?.[idx]?.title ||
      getPlaybackGuideSections()?.[idx]?.title ||
      `Section ${Number(idx) + 1}`;
    if (!isCurrent) {
      setToggleIcon(btn, true);
      btn.setAttribute("aria-label", `Play ${sectionTitle}`);
    } else {
      setToggleIcon(btn, isPaused ? true : false);
      btn.setAttribute("aria-label", `${isPaused ? "Play" : "Pause"} ${sectionTitle}`);
    }
  }

  const plToggle = $("plToggle");
  if (plToggle) setToggleIcon(plToggle, !(playerIsActive && !isPaused)); // if playing -> show pause icon
}

function serializeCityState(city) {
  if (!city || typeof city !== "object") return null;
  const lat = Number(city.lat);
  const lon = Number(city.lon);
  return {
    id: city.id ?? null,
    name: city.name ?? cityDisplayName(city),
    countryName: city.countryName || city.countryDisplayName || city.country || "",
    country: city.country || city.countryCode || "",
    countrySlug: city.countrySlug || "",
    citySlug: city.citySlug || "",
    cityName: city.cityName || "",
    placeSlug: city.placeSlug || city.slug || "",
    wikiTitle: city.wikiTitle || city.name || "",
    kind: city.kind || "city",
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
  };
}

function clearPersistedPlaybackState() {
  try { localStorage.removeItem(PLAYBACK_STATE_KEY); } catch {}
}

let accountPlaybackPersistTs = 0;
function queueAccountListeningState(state, force = false) {
  if (!state || !Array.isArray(state.queue) || !state.queue.length) return;
  const nowTs = Date.now();
  if (!force && (nowTs - accountPlaybackPersistTs) < 12000) return;
  accountPlaybackPersistTs = nowTs;
  const idx = Math.max(0, Math.min(Number(state.currentChunkIdx) || 0, state.queue.length - 1));
  const item = state.queue[idx] || {};
  const entity = state.selectedCity || {};
  const duration = Number.isFinite(Number(audioEl?.duration)) ? Number(audioEl.duration) : 0;
  const currentTime = Number.isFinite(Number(state.currentTime)) ? Number(state.currentTime) : 0;
  const payload = {
    entityType: entity.kind === "place" || entity.placeSlug ? "place" : "city",
    entityId: entity.id || [entity.countrySlug, entity.citySlug, entity.placeSlug].filter(Boolean).join("/") || state.nowPlaying?.cityTitle || document.title,
    entityTitle: state.nowPlaying?.cityTitle || entity.name || document.title,
    country: entity.countryName || entity.country || "",
    city: entity.cityName || entity.name || "",
    pageUrl: currentGuideUrlWithPlayerAnchor(entity),
    language: state.appLang || window.APP_LANG || "en",
    voiceGender: state.voiceGender || "female",
    sectionId: String(state.nowPlaying?.sectionIdx ?? item.sectionIdx ?? idx),
    sectionTitle: state.nowPlaying?.blockTitle || item.blockTitle || "Audio story",
    audioUrl: item.url || "",
    duration,
    currentTime,
    progressPercent: duration ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0,
    completed: !!audioEl?.ended,
  };
  try {
    fetch("/api/account/listening", {
      method: "POST",
      credentials: "same-origin",
      keepalive: !!force,
      headers: csrfHeaders({ "Content-Type": "application/json", "Accept": "application/json" }),
      body: JSON.stringify(payload),
    }).catch(() => {});
  } catch {}
}

function currentGuideUrlWithPlayerAnchor(entity) {
  return currentGuideUrl(entity, true);
}

function currentGuideUrl(entity, withPlayerAnchor = false) {
  const countrySlug = String(entity?.countrySlug || "").trim();
  const citySlug = String(entity?.citySlug || entity?.slug || "").trim();
  const placeSlug = String(entity?.placeSlug || "").trim();
  let url = window.location.pathname + window.location.search;
  if (countrySlug && citySlug && placeSlug) {
    url = localizedRoute(activeAppLang || window.APP_LANG || "en", [countrySlug, citySlug, placeSlug]);
  } else if (countrySlug && citySlug) {
    url = localizedRoute(activeAppLang || window.APP_LANG || "en", [countrySlug, citySlug]);
  } else if (countrySlug && !citySlug) {
    url = localizedRoute(activeAppLang || window.APP_LANG || "en", [countrySlug]);
  }
  const clean = url.replace(/#.*$/, "");
  return withPlayerAnchor ? `${clean}#stickyPlayer` : clean;
}

function currentPlaybackGuideUrl(withPlayerAnchor = false) {
  const entity = playbackEntityCity || selectedCity || {};
  return currentGuideUrl(entity, withPlayerAnchor);
}

function currentPlaybackGuideTitle(fallback = "") {
  return String(
    cityDisplayName(playbackEntityCity || selectedCity) ||
    globalPlayerState.currentEntityTitle ||
    selectedArticle?.title ||
    document.querySelector("h1")?.textContent ||
    fallback ||
    ""
  ).trim();
}

function currentGuideImage() {
  const og = document.querySelector('meta[property="og:image"]');
  const ogUrl = og?.getAttribute("content");
  if (ogUrl) return ogUrl;
  const img = document.querySelector(".ux-guideCard img, .ux-placeHero img, .ux-cityHero img, .hero img");
  return img?.getAttribute("src") || "";
}

function currentGuideSavePayload() {
  const entity = playbackEntityCity || selectedCity || {};
  const body = document.body;
  const isPlace = entity.kind === "place" || !!entity.placeSlug || body?.classList.contains("PagePlace");
  const isCountry = entity.kind === "country" || body?.classList.contains("PageCountry");
  const entityType = isPlace ? "place" : (isCountry ? "country" : "city");
  const guideTitle = String(
    (playerIsActive && nowPlaying?.cityTitle) ||
    globalPlayerState.currentEntityTitle ||
    cityDisplayName(entity) ||
    selectedArticle?.title ||
    document.querySelector("h1")?.textContent ||
    document.title ||
    "Audio guide"
  ).trim();
  const audioTitle = String(
    (playerIsActive && nowPlaying?.blockTitle && nowPlaying.blockTitle !== "—" ? nowPlaying.blockTitle : "") ||
    globalPlayerState.currentSectionTitle ||
    ""
  ).trim();
  const entityId = String(
    (entity && cityKey(entity)) ||
    globalPlayerState.currentEntityId ||
    [entity.countrySlug, entity.citySlug, entity.placeSlug].filter(Boolean).join("/") ||
    window.location.pathname
  ).trim();
  return {
    entityType,
    entityId,
    title: guideTitle,
    audioTitle,
    city: String(entity.cityName || (entityType !== "country" ? (cityDisplayName(entity) || guideTitle) : "") || "").trim(),
    country: String(countryDisplayName(entity) || entity.countryName || entity.country || "").trim(),
    pageUrl: currentGuideUrlWithPlayerAnchor(entity),
    image: currentGuideImage(),
    language: String(activeAppLang || window.APP_LANG || "en").toLowerCase(),
  };
}

function guidePayloadFromSaveButton(btn) {
  if (!btn) return {};
  return {
    entityType: btn.getAttribute("data-entity-type") || "",
    entityId: btn.getAttribute("data-entity-id") || "",
    title: btn.getAttribute("data-title") || "",
    audioTitle: btn.getAttribute("data-audio-title") || "",
    city: btn.getAttribute("data-city") || "",
    country: btn.getAttribute("data-country") || "",
    pageUrl: btn.getAttribute("data-page-url") || "",
    image: btn.getAttribute("data-image") || "",
    language: btn.getAttribute("data-language") || String(activeAppLang || window.APP_LANG || "en").toLowerCase(),
  };
}

function syncGuideSaveButtons(payload, saved) {
  const type = String(payload?.entityType || "").trim();
  const id = String(payload?.entityId || "").trim();
  if (!type || !id) return;
  document.querySelectorAll("[data-hero-save-guide]").forEach((btn) => {
    if (btn.getAttribute("data-entity-type") !== type) return;
    if (btn.getAttribute("data-entity-id") !== id) return;
    btn.textContent = saved ? "Saved" : "Save";
    btn.classList.toggle("is-saved", !!saved);
    btn.setAttribute("aria-pressed", saved ? "true" : "false");
  });
}

async function saveCurrentGuide(sourceBtn) {
  if (!AG_USER_LOGGED_IN) {
    window.location.href = AG_LOGIN_URL;
    return;
  }
  const btn = sourceBtn || $("plSaveGuide");
  const original = btn?.textContent || "Save";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Saving";
  }
  const payload = {
    ...currentGuideSavePayload(),
    ...Object.fromEntries(Object.entries(guidePayloadFromSaveButton(btn)).filter(([, value]) => String(value || "").trim())),
  };
  try {
    const res = await fetch("/api/account/favorites/toggle", {
      method: "POST",
      credentials: "same-origin",
      headers: csrfHeaders({ "Content-Type": "application/json", "Accept": "application/json" }),
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      if (res.status === 403) {
        setStatus("Log in to save this guide.");
        try { document.querySelector("[data-auth-open]")?.click(); } catch {}
      } else {
        setStatus(data.error || "Could not save this guide.");
      }
      return;
    }
    if (btn) {
      btn.classList.toggle("is-saved", !!data.saved);
      btn.textContent = data.saved ? "Saved" : "Save";
      btn.setAttribute("aria-pressed", data.saved ? "true" : "false");
    }
    syncGuideSaveButtons(payload, !!data.saved);
    setStatus(data.saved ? "Guide saved." : "Guide removed from saved.");
  } catch {
    setStatus("Could not save this guide.");
  } finally {
    if (btn) {
      window.setTimeout(() => {
        btn.disabled = false;
        if (btn.textContent === "Saving") btn.textContent = original;
      }, 200);
    }
  }
}

function persistPlaybackState(force = false) {
  if (playbackBackend !== "audio") return;
  if (!Array.isArray(speakQueue) || !speakQueue.length) return;
  if (!playerIsActive && !isPaused && currentChunkIdx < 0) return;

  const now = Date.now();
  if (!force && (now - playbackPersistTs) < 700) return;
  playbackPersistTs = now;

  const idxRaw = Number.isFinite(Number(currentChunkIdx)) && currentChunkIdx >= 0
    ? Number(currentChunkIdx)
    : Math.max(0, Number(speakIdx || 0) - 1);
  const idx = clamp(idxRaw, 0, Math.max(0, speakQueue.length - 1));

  let curSec = 0;
  try {
    const t = Number(audioEl?.currentTime);
    if (Number.isFinite(t) && t > 0) curSec = t;
  } catch {}

  const queue = speakQueue.map((item) => ({
    url: String(item?.srcUrl || item?.url || "").trim(),
    words: Number.isFinite(Number(item?.words)) ? Number(item.words) : 0,
    blockTitle: String(item?.blockTitle || "Section"),
    sectionIdx: Number.isFinite(Number(item?.sectionIdx)) ? Number(item.sectionIdx) : null,
  })).filter((item) => item.url);
  if (!queue.length) return;

  const playbackSections = getPlaybackGuideSections().map((sec, idx) => cloneSectionForPlayback(sec, idx)).filter(Boolean);

  const state = {
    v: 2,
    ts: now,
    backend: "audio",
    queue,
    playbackSections,
    currentChunkIdx: idx,
    currentTime: curSec,
    isPaused: !!isPaused,
    playerDockPinned: !!playerDockPinned,
    nowPlaying: {
      mode: nowPlaying?.mode || "all",
      sectionIdx: Number.isFinite(Number(nowPlaying?.sectionIdx)) ? Number(nowPlaying.sectionIdx) : null,
      blockTitle: String(nowPlaying?.blockTitle || ""),
      cityTitle: String(nowPlaying?.cityTitle || selectedArticle?.title || cityDisplayName(playbackEntityCity || selectedCity) || ""),
    },
    lastPlayPlan: lastPlayPlan || null,
    selectedCity: serializeCityState(playbackEntityCity || selectedCity),
    voiceGender: voiceGender === "male" ? "male" : "female",
    speechRate: Number(speechRate) || 1.0,
    volume: Number(playerVolume) || 1.0,
    appLang: String(activeAppLang || window.APP_LANG || "en"),
  };
  try {
    localStorage.setItem(PLAYBACK_STATE_KEY, JSON.stringify(state));
  } catch {}
  queueAccountListeningState(state, force);
}

function readPersistedPlaybackState() {
  try {
    const raw = localStorage.getItem(PLAYBACK_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const ts = Number(parsed.ts);
    if (!Number.isFinite(ts)) return null;
    if ((Date.now() - ts) > PLAYBACK_STATE_TTL_MS) {
      clearPersistedPlaybackState();
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function restoreAudioPlaybackState(state) {
  if (!AG_USER_LOGGED_IN) {
    clearPersistedPlaybackState();
    return false;
  }
  if (!state || state.backend !== "audio") return false;
  const queue = Array.isArray(state.queue)
    ? state.queue.map((item) => ({
      url: String(item?.url || "").trim(),
      srcUrl: String(item?.url || "").trim(),
      words: Number.isFinite(Number(item?.words)) ? Number(item.words) : 0,
      blockTitle: String(item?.blockTitle || "Section"),
      sectionIdx: Number.isFinite(Number(item?.sectionIdx)) ? Number(item.sectionIdx) : null,
    })).filter((item) => item.url)
    : [];
  if (!queue.length) return false;

  playbackGuideSections = Array.isArray(state.playbackSections)
    ? state.playbackSections.map((sec, idx) => cloneSectionForPlayback(sec, Number.isFinite(Number(sec?.sectionIdx)) ? Number(sec.sectionIdx) : idx)).filter(Boolean)
    : [];

  stopSpeechHard();
  setPlayerLoading(false);
  setAudioLoadProgress(false, 0, 0, "");
  playbackBackend = "audio";

  speakQueue = queue;
  audioDurations = new Array(queue.length).fill(NaN);
  const startIdx = clamp(Number(state.currentChunkIdx) || 0, 0, queue.length - 1);
  speakIdx = startIdx;
  currentChunkIdx = -1;

  chunksDoneWords = queue.slice(0, startIdx).reduce((sum, item) => sum + (Number(item.words) || 0), 0);
  currentChunkWords = 0;
  currentChunkReadWords = 0;
  playerTotalWords = queue.reduce((sum, item) => sum + (Number(item.words) || 0), 0);
  playerReadWords = clamp(chunksDoneWords, 0, playerTotalWords);
  playerReadWordsTarget = playerReadWords;
  playerReadWordsDisplay = playerReadWords;

  isPaused = !!state.isPaused;
  playerDockPinned = state.playerDockPinned !== false;
  pauseStartedTs = 0;
  boundarySeenCount = 0;
  boundaryLastChar = -1;
  boundaryReliable = false;
  playerIsActive = true;

  const np = state.nowPlaying || {};
  nowPlaying = {
    mode: (np.mode === "section" || np.mode === "all") ? np.mode : "all",
    sectionIdx: Number.isFinite(Number(np.sectionIdx)) ? Number(np.sectionIdx) : null,
    blockTitle: String(np.blockTitle || ""),
    cityTitle: String(np.cityTitle || selectedArticle?.title || cityDisplayName(playbackEntityCity || selectedCity) || "—"),
  };
  lastPlayPlan = state.lastPlayPlan || { mode: "all" };

  setPlayerHeader(nowPlaying.cityTitle || "—", nowPlaying.blockTitle || tr("listen_all", "Play all"));
  setPlayerVisible(playerDockPinned);
  renderPlayerProgress();

  const sessionId = nextPlaybackSession();
  const startTime = Math.max(0, Number(state.currentTime) || 0);
  resumeSeek = { sessionId, chunkIdx: startIdx, timeSec: startTime };
  startRenderLoop(sessionId);
  setTimeout(() => {
    playNextAudioChunk(sessionId);
    if (isPaused) {
      setTimeout(() => {
        if (sessionId === playbackSession) pauseSpeech();
      }, 220);
    }
  }, 40);
  setStatus(tr("audio_playing", "Playing audio…"));
  return true;
}

async function tryRestorePersistedPlayback() {
  if (!AG_USER_LOGGED_IN) {
    clearPersistedPlaybackState();
    return false;
  }
  const state = readPersistedPlaybackState();
  if (!state) return false;
  window.__AG_PLAYBACK_RESTORE_PENDING = true;
  window.__AG_PLAYBACK_RESTORED = false;
  let restored = false;
  try {
    if (state.voiceGender === "male" || state.voiceGender === "female") {
      setVoiceGender(state.voiceGender, { reload: false });
    }
    if (Number.isFinite(Number(state.speechRate))) {
      setSpeechRate(Number(state.speechRate));
    }
    if (Number.isFinite(Number(state.volume))) {
      setPlayerVolume(Number(state.volume), false);
    }

    const savedCity = state.selectedCity;
    if (savedCity && typeof savedCity === "object") {
      selectedCity = { ...savedCity };
      playbackEntityCity = { ...savedCity };
      try { window.__AG_RESTORED_TARGET_KEY = cityKey(savedCity); } catch {}
    }
    restored = restoreAudioPlaybackState(state);
    window.__AG_PLAYBACK_RESTORED = !!restored;

    if (savedCity && typeof onSelectCity === "function") {
      onSelectCity(savedCity, {
        scroll: false,
        warm: false,
        preservePersistedState: true,
        keepPlayback: !!restored,
      }).catch(() => {});
    }
    return restored;
  } finally {
    window.__AG_PLAYBACK_RESTORE_PENDING = false;
    try {
      window.dispatchEvent(new CustomEvent("ag:playback-restore", { detail: { restored: !!restored } }));
    } catch {}
  }
}

async function tryLoadAccountContinueRequest() {
  let historyId = "";
  try {
    historyId = new URLSearchParams(window.location.search).get("continueListening") || "";
  } catch {}
  if (!historyId) return false;
  try {
    const res = await fetch(`/api/account/listening/${encodeURIComponent(historyId)}`, {
      credentials: "same-origin",
      headers: { "Accept": "application/json" },
    });
    const out = await res.json().catch(() => ({}));
    if (!res.ok || !out.ok || !out.item) return false;
    const item = out.item;
    const audioUrl = String(item.audioUrl || "").trim();
    if (!audioUrl) return false;
    const state = {
      v: 2,
      ts: Date.now(),
      backend: "audio",
      queue: [{
        url: audioUrl,
        words: 0,
        blockTitle: String(item.sectionTitle || "Audio story"),
        sectionIdx: Number.isFinite(Number(item.sectionId)) ? Number(item.sectionId) : 0,
      }],
      playbackSections: [{
        title: String(item.sectionTitle || "Audio story"),
        blockTitle: String(item.sectionTitle || "Audio story"),
        sectionIdx: Number.isFinite(Number(item.sectionId)) ? Number(item.sectionId) : 0,
      }],
      currentChunkIdx: 0,
      currentTime: Number(item.currentTime) || 0,
      isPaused: true,
      playerDockPinned: true,
      nowPlaying: {
        mode: "section",
        sectionIdx: Number.isFinite(Number(item.sectionId)) ? Number(item.sectionId) : 0,
        blockTitle: String(item.sectionTitle || "Audio story"),
        cityTitle: String(item.entityTitle || item.city || "Audio guide"),
      },
      lastPlayPlan: { mode: "section" },
      selectedCity: {
        id: String(item.entityId || ""),
        name: String(item.entityTitle || item.city || "Audio guide"),
        countryName: String(item.country || ""),
        cityName: String(item.city || ""),
        kind: String(item.entityType || "city"),
      },
      voiceGender: item.voiceGender === "male" ? "male" : "female",
      speechRate: Number(speechRate) || 1.0,
      volume: Number(playerVolume) || 1.0,
      appLang: String(item.language || window.APP_LANG || "en"),
    };
    localStorage.setItem(PLAYBACK_STATE_KEY, JSON.stringify(state));
    const restored = await tryRestorePersistedPlayback();
    if (restored) setStatus(tr("status_ready", "Ready. Tap Play to continue listening."));
    return !!restored;
  } catch {
    return false;
  }
}

// ======================= Sticky Player (bottom) =======================
function setPlayerVisible(show) {
  if (!playerEl) playerEl = document.getElementById("stickyPlayer");
  if (!playerEl) return;
  const vis = !!show;
  playerEl.hidden = !vis;
  document.body.classList.toggle("BodyHasPlayer", vis);
  if (!vis) setPlayerExpanded(false);
}

function setPlayerExpanded(open) {
  if (!playerEl) playerEl = document.getElementById("stickyPlayer");
  if (!playerEl) return;
  const active = !!open && !playerEl.hidden;
  playerSheetOpen = active;
  playerEl.classList.toggle("is-expanded", active);
  document.body.classList.toggle("ag-playerSheetOpen", active);
  const close = $("plCloseSheet");
  if (close) close.hidden = !active;
  renderPlayerQueueSheet();
}

function renderPlayerQueueSheet() {
  const q = $("plQueue");
  if (!q) return;
  q.innerHTML = "";
}

function setPlayerAuthGate(active) {
  if (!playerEl) playerEl = document.getElementById("stickyPlayer");
  const gate = $("plAuthGate");
  if (!playerEl || !gate) return;
  if (active) setPlayerExpanded(false);
  const inner = playerEl.querySelector(".ag-player-inner");
  playerEl.classList.toggle("is-auth-locked", !!active);
  gate.hidden = !active;
  gate.setAttribute("aria-hidden", active ? "false" : "true");
  if (inner) {
    if (active) inner.setAttribute("inert", "");
    else inner.removeAttribute("inert");
  }
}

function requireLoginForPlayback() {
  if (AG_USER_LOGGED_IN) {
    setPlayerAuthGate(false);
    return false;
  }
  showPlayerDock();
  setPlayerHeader(currentPlaybackGuideTitle("SonicCity"), tr("audio_guide_generic", "Audio guide"));
  setPlayerStatusLabel(tr("player_signup_cta", "Sign Up"));
  setPlayerAuthGate(true);
  setStatus(tr("player_auth_gate", "To Listen for Free, Sign Up."));
  return true;
}

function formatRateLabel(r) {
  const n = Number(r) || 1;
  const s = (Math.abs(n - Math.round(n)) < 1e-6) ? String(Math.round(n)) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return `${s}×`;
}

function setSpeechRate(nextRate) {
  const r = Number(nextRate) || 1.0;
  const clamped = clamp(r, 0.75, 2.0);
  speechRate = clamped;
  try { localStorage.setItem("ag_speech_rate", String(speechRate)); } catch {}

  const b = $("plSpeed");
  if (b) b.textContent = formatRateLabel(speechRate);

  try {
    if (audioEl) audioEl.playbackRate = Number(speechRate) || 1.0;
  } catch {}
  syncGlobalPlayerState({ playbackRate: speechRate });
}

function setPlayerVolume(nextVolume, persist = true) {
  const v = clamp(Number(nextVolume), 0, 1);
  playerVolume = Number.isFinite(v) ? v : 1.0;
  if (persist) {
    try { localStorage.setItem(PLAYER_VOLUME_KEY, String(playerVolume)); } catch {}
  }
  const input = $("plVolume");
  if (input && Math.abs(Number(input.value) - playerVolume) > 0.001) input.value = String(playerVolume);
  try {
    if (audioEl) audioEl.volume = playerVolume;
  } catch {}
  syncGlobalPlayerState({ volume: playerVolume });
}

function cycleSpeechRate() {
  const i = SPEEDS.findIndex((x) => Math.abs(x - speechRate) < 1e-6);
  const next = SPEEDS[(i >= 0 ? i + 1 : 1) % SPEEDS.length] || 1.0;
  setSpeechRate(next);
}

function syncVoiceButtons() {
  const f = $("voiceFemale");
  const m = $("voiceMale");
  const p = $("plVoice");
  if (f) f.setAttribute("aria-pressed", voiceGender === "female" ? "true" : "false");
  if (m) m.setAttribute("aria-pressed", voiceGender === "male" ? "true" : "false");
  if (p) p.textContent = voiceGender === "male" ? tr("voice_male", "Male") : tr("voice_female", "Female");
}

function inlineNowPlayingState() {
  const liveState = window.AG_PLAYER_STATE || globalPlayerState || {};
  const liveHasTrack = !!(playerIsActive && Array.isArray(speakQueue) && speakQueue.length);
  if (liveHasTrack) {
    return {
      hasTrack: true,
      label: liveState.isPlaying ? tr("player_now_playing", "Now playing") : tr("player_continue_listening", "Continue listening"),
      title: liveState.currentSectionTitle || nowPlaying.blockTitle || tr("listen_all", "Play all"),
      meta: liveState.currentEntityTitle || nowPlaying.cityTitle || "",
      metaUrl: currentPlaybackGuideUrl(false),
      currentTime: Number(liveState.currentTime),
      duration: Number(liveState.duration),
    };
  }

  const saved = readPersistedPlaybackState();
  if (saved?.backend === "audio" && Array.isArray(saved.queue) && saved.queue.length) {
    const idx = clamp(Number(saved.currentChunkIdx) || 0, 0, saved.queue.length - 1);
    const item = saved.queue[idx] || {};
    return {
      hasTrack: true,
      label: tr("player_continue_listening", "Continue listening"),
      title: String(saved.nowPlaying?.blockTitle || item.blockTitle || tr("listen_all", "Play all")),
      meta: String(saved.nowPlaying?.cityTitle || saved.selectedCity?.name || ""),
      metaUrl: currentGuideUrl(saved.selectedCity || {}, false),
      currentTime: Number(saved.currentTime),
      duration: 0,
    };
  }

  return {
    hasTrack: false,
    label: tr("player_no_track_label", "Choose an audio story"),
    title: tr("player_start_city_guide", "Start a city guide"),
    meta: tr("player_pick_city_topic", "Pick a city or topic to begin."),
    currentTime: 0,
    duration: 0,
  };
}

function syncInlineNowPlayingCards() {
  const cards = document.querySelectorAll("[data-ag-now-card]");
  if (!cards.length) return;
  const state = inlineNowPlayingState();
  const ratio = state.duration > 0
    ? clamp(state.currentTime / state.duration, 0, 1)
    : (state.hasTrack ? 0.18 : 0);
  cards.forEach((card) => {
    const label = card.querySelector("[data-ag-now-label]");
    const title = card.querySelector("[data-ag-now-title]");
    const fill = card.querySelector("[data-ag-now-fill]");
    const button = card.querySelector("[data-ag-continue-toggle]");
    if (label) {
      label.replaceChildren(document.createTextNode(state.label || ""));
      if (state.meta) {
        label.appendChild(document.createTextNode(" · "));
        const metaUrl = state.metaUrl || currentPlaybackGuideUrl(false);
        if (metaUrl) {
          const link = document.createElement("a");
          link.className = "ag-nowMetaLink";
          link.href = metaUrl;
          link.textContent = state.meta;
          label.appendChild(link);
        } else {
          label.appendChild(document.createTextNode(state.meta));
        }
      }
    }
    if (title) title.textContent = state.title;
    if (fill) fill.style.width = `${Math.round(ratio * 100)}%`;
    if (button) {
      const hasDefaultSection = Array.isArray(selectedArticle?.sections) && selectedArticle.sections.length > 0;
      button.disabled = !state.hasTrack && !lastPlayPlan && !hasDefaultSection;
      button.setAttribute("aria-label", state.hasTrack ? tr("player_continue_listening", "Continue listening") : tr("player_no_track_label", "Choose an audio story"));
    }
    card.classList.toggle("has-player-state", !!state.hasTrack);
  });
}

function scrollToGuidePlayerSurface() {
  const target = $("storyPanel") || $("storySections") || $("stickyPlayer");
  if (!target || typeof target.scrollIntoView !== "function") return;
  window.requestAnimationFrame(() => {
    try {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch {}
  });
}

function continueInlineNowPlaying() {
  if (playerIsActive) {
    if (isPaused) resumeSpeech();
    else {
      showPlayerDock();
      renderPlayerProgress();
    }
    scrollToGuidePlayerSurface();
    return;
  }
  const saved = readPersistedPlaybackState();
  if (saved?.backend === "audio") {
    const restored = restoreAudioPlaybackState(saved);
    if (restored) {
      setTimeout(() => {
        if (isPaused) resumeSpeech();
        else renderPlayerProgress();
        scrollToGuidePlayerSurface();
      }, 260);
      return;
    }
  }
  if (!lastPlayPlan && Array.isArray(selectedArticle?.sections) && selectedArticle.sections.length) {
    startSectionPlayback(0);
    scrollToGuidePlayerSurface();
    return;
  }
  playerToggleAction();
  scrollToGuidePlayerSurface();
}

async function restartCurrentBlockWithVoiceGender(entity, sectionIdx) {
  const target = entity && typeof entity === "object" ? { ...entity } : null;
  if (!target) return false;
  const idx = Number.isFinite(Number(sectionIdx)) ? Math.max(0, Number(sectionIdx)) : 0;
  const appLang = String(globalPlayerState.currentLanguage || activeAppLang || window.APP_LANG || "en").toLowerCase();
  const title = playbackEntityTitle(cityDisplayName(target) || selectedArticle?.title || "—") || "—";

  showPlayerDock();
  setPlayerHeader(title, audioLoadingText(0));
  setAudioLoadProgress(true, 0, 100, audioLoadingText(0));
  setPlayerLoading(true, audioLoadingText(0));
  setStatus(audioLoadingText(0));

  let manifest = await fetchAudioManifest(target, appLang, voiceGender);
  if (!manifest) {
    await requestAudioBuild(target, appLang, voiceGender);
    const status = await requestAudioBuildStatus(target, appLang, voiceGender);
    const pct = clamp(Number(status?.progress || 0) || 0, 0, 100);
    setAudioLoadProgress(true, pct, 100, audioLoadingText(pct));
    setPlayerLoading(true, audioLoadingText(pct));
    manifest = await waitForAudioManifest(target, appLang, voiceGender, { attempts: 8, delayMs: 1400 });
  }

  if (!manifest) {
    setPlayerLoading(false);
    setAudioLoadProgress(false, 0, 0, "");
    setStatus(tr("audio_loading", "Loading audio…"));
    renderPlayerProgress();
    return false;
  }

  const article = audioArticleFromManifest(manifest);
  const sections = Array.isArray(article.sections)
    ? article.sections.map((sec, i) => cloneSectionForPlayback(sec, i)).filter(Boolean)
    : [];
  if (!sections.length) return false;

  playbackBackend = "audio";
  playbackEntityCity = target;
  playbackGuideSections = sections;
  nowPlaying.mode = "section";
  nowPlaying.sectionIdx = clamp(idx, 0, sections.length - 1);
  nowPlaying.blockTitle = sections[nowPlaying.sectionIdx]?.title || `Section ${nowPlaying.sectionIdx + 1}`;
  nowPlaying.cityTitle = String(cityDisplayName(target) || article.title || title || "—").trim();
  lastPlayPlan = { mode: "section", sectionIdx: nowPlaying.sectionIdx };

  const items = buildSectionPlaybackItems(nowPlaying.sectionIdx, { playbackContext: true });
  if (!items.length) return false;
  startPlaybackQueue(items, "section", { preservePlaybackContext: true });
  return true;
}

function setVoiceGender(nextGender, opts) {
  const o = (opts && typeof opts === "object") ? opts : {};
  const shouldReload = o.reload !== false;
  const g = String(nextGender || "").toLowerCase();
  if (g !== "female" && g !== "male") return;
  if (voiceGender === g) return;
  voiceGender = g;
  try { localStorage.setItem("ag_voice_gender", voiceGender); } catch {}
  syncVoiceButtons();

  // If we're using pre-generated audio, reload the guide to pick the correct voice folder.
  if (shouldReload && playerIsActive && playbackBackend === "audio" && Array.isArray(speakQueue) && speakQueue.length) {
    const target = playbackEntityCity || selectedCity;
    const sectionIdx = currentPlaybackSectionIdx();
    restartCurrentBlockWithVoiceGender(target, sectionIdx).catch(() => {
      setPlayerLoading(false);
      setAudioLoadProgress(false, 0, 0, "");
      renderPlayerProgress();
    });
    return;
  }
  if (shouldReload && selectedCity && (playbackBackend === "audio" || playbackBackend === "pending")) {
    const keepPlayback = !!(playerIsActive && Array.isArray(speakQueue) && speakQueue.length);
    if (keepPlayback) {
      showPlayerDock();
      persistPlaybackState(true);
    }
    try {
      onSelectCity(selectedCity, {
        scroll: false,
        warm: false,
        keepPlayback,
        preservePersistedState: keepPlayback,
      });
    } catch {}
    if (keepPlayback) {
      setPlayerVisible(true);
      renderPlayerProgress();
    }
  }
}

function ensurePlayer() {
  playerEl = document.getElementById("stickyPlayer");
  if (!playerEl) return;

  if (playerEl.dataset.bound === "1") return;
  playerEl.dataset.bound = "1";

  // Load persisted speed (best-effort)
  try {
    const saved = parseFloat(localStorage.getItem("ag_speech_rate") || "");
    if (Number.isFinite(saved)) setSpeechRate(saved);
  } catch {
    setSpeechRate(speechRate);
  }
  try {
    const savedVolume = parseFloat(localStorage.getItem(PLAYER_VOLUME_KEY) || "");
    setPlayerVolume(Number.isFinite(savedVolume) ? savedVolume : playerVolume, false);
  } catch {
    setPlayerVolume(playerVolume, false);
  }

  const bindTap = (id, fn) => {
    const el = $(id);
    if (!el) return;
    let lastRunTs = 0;
    let lastPointerTs = 0;
    const handler = () => {
      const now = Date.now();
      if (now - lastRunTs < 180) return;
      lastRunTs = now;
      try { fn(); } catch (e) { setStatus(`⚠ ${e?.message || "Player error"}`); }
    };
    el.addEventListener("pointerup", (ev) => {
      if (ev && ev.pointerType === "mouse" && ev.button !== 0) return;
      lastPointerTs = Date.now();
      try { ev.preventDefault(); } catch {}
      handler();
    });
    el.addEventListener("click", (ev) => {
      const now = Date.now();
      if (now - lastPointerTs < 260) return;
      try { ev.preventDefault(); } catch {}
      handler();
    });
    el.addEventListener("keydown", (ev) => {
      if (!ev) return;
      if (ev.key === "Enter" || ev.key === " ") {
        try { ev.preventDefault(); } catch {}
        handler();
      }
    });
  };

  bindTap("plToggle", () => playerToggleAction());
  bindTap("plStop", () => stopSpeech());
  bindTap("plPrev", () => playerPrevAction());
  bindTap("plNext", () => playerNextAction());
  bindTap("plSpeed", () => playerSpeedAction());
  bindTap("plVoice", () => setVoiceGender(voiceGender === "male" ? "female" : "male"));
  bindTap("plSaveGuide", () => saveCurrentGuide($("plSaveGuide")));
  bindTap("plCloseSheet", () => setPlayerExpanded(false));

  const now = playerEl.querySelector(".ag-player-now");
  if (now) {
    now.setAttribute("role", "button");
    now.setAttribute("tabindex", "0");
    now.addEventListener("click", (ev) => {
      if (ev?.target?.closest?.("button,a,input,label")) return;
      setPlayerExpanded(true);
    });
    now.addEventListener("keydown", (ev) => {
      if (!ev) return;
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        setPlayerExpanded(true);
      }
    });
  }

  const inner = playerEl.querySelector(".ag-player-inner");
  if (inner) {
    inner.addEventListener("click", (ev) => {
      const target = ev?.target;
      if (!target || playerSheetOpen) return;
      if (target.closest?.(".ag-player-now,button,a,input,label,.ag-bar")) return;
      setPlayerExpanded(true);
    });
  }

  const queue = $("plQueue");
  if (queue) {
    queue.addEventListener("click", (ev) => {
      const btn = ev?.target?.closest?.("[data-player-queue-index]");
      if (!btn) return;
      ev.preventDefault();
      const idx = Number(btn.getAttribute("data-player-queue-index"));
      if (!Number.isFinite(idx)) return;
      if (!playerIsActive) {
        playerToggleAction();
        return;
      }
      jumpToChunk(idx);
    });
  }

  document.addEventListener("keydown", (ev) => {
    if (ev?.key === "Escape" && playerSheetOpen) setPlayerExpanded(false);
  });

  const volumeInput = $("plVolume");
  if (volumeInput) {
    volumeInput.value = String(playerVolume);
    volumeInput.addEventListener("input", () => {
      setPlayerVolume(volumeInput.value);
      persistPlaybackState(true);
    });
  }

  // visibility is controlled by renderPlayerProgress()
  setPlayerVisible(false);
  if (AG_USER_LOGGED_IN) setPlayerAuthGate(false);
}

function syncMediaSessionState() {
  try {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = playerIsActive
      ? (isPaused ? "paused" : "playing")
      : "none";
  } catch {}
}

function updateMediaSession() {
  try {
    if (!("mediaSession" in navigator) || typeof window.MediaMetadata !== "function") return;
    const pageTitle = (playerIsActive && nowPlaying?.cityTitle)
      ? nowPlaying.cityTitle
      : (selectedArticle?.title || cityDisplayName(selectedCity) || document.title || "SonicCity");
    const trackTitle = nowPlaying?.blockTitle && nowPlaying.blockTitle !== "—"
      ? nowPlaying.blockTitle
      : (lastPlayPlan?.mode === "all" ? tr("listen_all", "Play all") : pageTitle);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: trackTitle,
      artist: pageTitle,
      album: "SonicCity",
    });
    navigator.mediaSession.setActionHandler("play", () => {
      if (playerIsActive && isPaused) resumeSpeech();
      else playerToggleAction();
    });
    navigator.mediaSession.setActionHandler("pause", () => pauseSpeech());
    navigator.mediaSession.setActionHandler("previoustrack", () => playerPrevAction());
    navigator.mediaSession.setActionHandler("nexttrack", () => playerNextAction());
    navigator.mediaSession.setActionHandler("seekbackward", () => {
      try {
        const el = ensureAudioEl();
        if (playbackBackend === "audio" && el) el.currentTime = Math.max(0, Number(el.currentTime || 0) - 10);
      } catch {}
    });
    navigator.mediaSession.setActionHandler("seekforward", () => {
      try {
        const el = ensureAudioEl();
        if (playbackBackend === "audio" && el) el.currentTime = Math.min(Number(el.duration || Infinity), Number(el.currentTime || 0) + 10);
      } catch {}
    });
    navigator.mediaSession.setActionHandler("seekto", (details) => {
      try {
        const el = ensureAudioEl();
        if (playbackBackend === "audio" && el && Number.isFinite(Number(details?.seekTime))) {
          el.currentTime = Math.max(0, Number(details.seekTime));
        }
      } catch {}
    });
    syncMediaSessionState();
  } catch {}
}

function playbackHeaderMeta(fallback) {
  if (!playerIsActive) return fallback || "";
  const block = String(nowPlaying?.blockTitle || "").trim();
  if (block && block !== "—") {
    return nowPlaying?.mode === "all"
      ? `${block} • ${tr("listen_all", "Play all")}`
      : block;
  }
  return String(globalPlayerState.currentSectionTitle || fallback || "").trim();
}

function setPlayerHeader(blockTitle, metaText) {
  let titleText = String(blockTitle || "—").trim() || "—";
  let subText = String(metaText || "").trim();

  const activeTitle = String(
    playerIsActive
      ? (nowPlaying?.cityTitle || globalPlayerState.currentEntityTitle || cityDisplayName(playbackEntityCity) || "")
      : ""
  ).trim();

  if (activeTitle && titleText && titleText !== "—" && titleText !== activeTitle) {
    titleText = activeTitle;
    subText = playbackHeaderMeta(subText);
  }

  const t = $("plTitle");
  const m = $("plMeta");
  if (t) {
    t.replaceChildren();
    const titleUrl = titleText && titleText !== "—" ? currentPlaybackGuideUrl(false) : "";
    if (titleUrl) {
      const link = document.createElement("a");
      link.className = "ag-player-titleLink";
      link.href = titleUrl;
      link.textContent = titleText;
      t.appendChild(link);
    } else {
      t.textContent = titleText;
    }
  }
  if (m) m.textContent = subText;
  syncGlobalPlayerState({
    currentEntityTitle: titleText || "",
    currentSectionTitle: subText || "",
  });
  updateMediaSession();
}

function ensureAudioProgressPanel() {
  if (!els.storySections) return null;
  let panel = $("audioProgressPanel");
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "audioProgressPanel";
  panel.className = "ag-audioProgress";
  const parent = els.storySections.parentElement;
  if (parent) parent.insertBefore(panel, els.storySections);
  return panel;
}

function renderAudioProgressPanel() {
  const panel = ensureAudioProgressPanel();
  if (!panel) return;

  const sections = Array.isArray(selectedArticle?.sections) ? selectedArticle.sections : [];
  if (!sections.length && !audioLoadState.active) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }

  const total = Math.max(1, sections.length || Number(audioLoadState.total) || 1);
  const pending = !!selectedArticle?.audioPending || playbackBackend === "pending";
  const failed = sections.filter((s) => String(s?.status || "").toLowerCase() === "failed").length;
  const explicitReady = sections.filter((s) => String(s?.status || "ready").toLowerCase() === "ready").length;
  const loadRatio = audioLoadState.active
    ? clamp((Number(audioLoadState.loaded) || 0) / Math.max(1, Number(audioLoadState.total) || 1), 0, 1)
    : (pending ? 0 : 1);
  const ready = pending ? clamp(Math.floor(loadRatio * total), 0, total) : clamp(explicitReady || total, 0, total);
  const generating = pending && ready < total ? 1 : 0;
  const queued = pending ? Math.max(0, total - ready - generating - failed) : 0;
  const pct = clamp((pending ? loadRatio : (ready / total)) * 100, 0, 100);
  const label = pending
    ? tr("audio_generating_count", "Preparing audio: {ready} / {total} sections ready")
        .replace("{ready}", String(ready))
        .replace("{total}", String(total))
    : tr("audio_ready_count", "Audio ready: {ready} / {total}")
        .replace("{ready}", String(ready))
        .replace("{total}", String(total));
  const detail = [
    `${tr("audio_ready", "Ready")}: ${ready}`,
    `${tr("audio_generating", "Preparing")}: ${generating}`,
    `${tr("audio_queued", "In queue")}: ${queued}`,
    `${tr("audio_failed", "Failed")}: ${failed}`,
  ].join(" · ");

  panel.hidden = false;
  panel.innerHTML = `
    <div class="ag-audioProgressTop">
      <span>${escapeHtml(label)}</span>
      <b>${Math.round(pct)}%</b>
    </div>
    <div class="ag-audioProgressBar" aria-hidden="true">
      <i style="width:${pct.toFixed(2)}%"></i>
    </div>
    <div class="ag-audioProgressMeta">${escapeHtml(audioLoadState.label || detail)}</div>
  `;
}

function setAudioLoadProgress(active, loaded, total, label) {
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeLoaded = Math.max(0, Number(loaded) || 0);
  const pct = safeTotal > 0 ? clamp((safeLoaded / Math.max(1, safeTotal)) * 100, 0, 100) : undefined;
  audioLoadState = {
    active: !!active,
    loaded: safeLoaded,
    total: safeTotal,
    label: active ? sanitizeAudioLoadingLabel(label, pct) : "",
  };
  syncGlobalPlayerState({
    isLoading: !!active,
    loadingProgress: safeTotal > 0 ? clamp(safeLoaded / Math.max(1, safeTotal), 0, 1) : 0,
  });
  renderAudioProgressPanel();
  renderPlayerProgress();
  if (lastNearbyCities.length) renderCitiesList(lastNearbyCities);
}

async function fetchAudioUrlCached(url, onProgress) {
  const key = String(url || "").trim();
  if (!key) throw new Error("Missing audio URL");
  if (audioBlobUrlCache.has(key)) {
    if (typeof onProgress === "function") onProgress(1, 1);
    return audioBlobUrlCache.get(key);
  }
  if (audioBlobPromiseCache.has(key)) return audioBlobPromiseCache.get(key);

  const promise = (async () => {
    const res = await fetch(key, { cache: "force-cache" });
    if (!res.ok) throw new Error(`Audio HTTP ${res.status}`);

    const totalBytes = Number(res.headers.get("content-length") || 0);
    if (!res.body || typeof res.body.getReader !== "function") {
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      audioBlobUrlCache.set(key, objectUrl);
      if (typeof onProgress === "function") onProgress(totalBytes || blob.size || 1, totalBytes || blob.size || 1);
      return objectUrl;
    }

    const reader = res.body.getReader();
    const chunks = [];
    let loadedBytes = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        loadedBytes += value.byteLength || value.length || 0;
        if (typeof onProgress === "function") onProgress(loadedBytes, totalBytes || loadedBytes || 1);
      }
    }

    const blob = new Blob(chunks, { type: res.headers.get("content-type") || "audio/mpeg" });
    const objectUrl = URL.createObjectURL(blob);
    audioBlobUrlCache.set(key, objectUrl);
    if (typeof onProgress === "function") onProgress(totalBytes || blob.size || loadedBytes || 1, totalBytes || blob.size || loadedBytes || 1);
    return objectUrl;
  })();

  audioBlobPromiseCache.set(key, promise);
  try {
    return await promise;
  } finally {
    audioBlobPromiseCache.delete(key);
  }
}

async function primeAudioQueueItems(items, label) {
  const list = Array.isArray(items) ? items.filter((it) => String(it?.url || "").trim()) : [];
  const total = list.length;
  if (!total) return list;

  for (let i = 0; i < total; i++) {
    const item = list[i];
    const sourceUrl = String(item?.url || "").trim();
    item.srcUrl = sourceUrl;
    item.url = await fetchAudioUrlCached(sourceUrl, (loadedBytes, totalBytes) => {
      const frac = totalBytes > 0 ? clamp(loadedBytes / totalBytes, 0, 1) : 0;
      setAudioLoadProgress(true, i + frac, total, audioLoadingText(((i + frac) / Math.max(1, total)) * 100));
    });
    setAudioLoadProgress(true, i + 1, total, audioLoadingText(((i + 1) / Math.max(1, total)) * 100));
  }

  setAudioLoadProgress(false, 0, 0, "");
  return list;
}

function renderPlayerProgress() {
  syncMediaSessionState();
  if (audioLoadState.active && !playerIsActive) {
    const totalLoading = Math.max(1, Number(audioLoadState.total) || 1);
    const loaded = clamp(Number(audioLoadState.loaded) || 0, 0, totalLoading);
    const ratioLoading = clamp(loaded / totalLoading, 0, 1);
    const pctLoading = Math.floor(ratioLoading * 100);

    const plPctLoading = $("plPct");
    const plTimeLoading = $("plTime");
    const plFillLoading = $("plFill");
    const plKnobLoading = $("plKnob");
    const plKnobLabelLoading = $("plKnobLabel");

    if (plPctLoading) plPctLoading.textContent = `${pctLoading}%`;
    if (plTimeLoading) plTimeLoading.textContent = `${Math.min(totalLoading, Math.ceil(loaded))}/${totalLoading}`;
    if (plFillLoading) plFillLoading.style.width = `${(ratioLoading * 100).toFixed(2)}%`;

    const posLoading = clamp(ratioLoading * 100, 0, 100);
    const labelPosLoading = clamp(posLoading, 6, 94);
    if (plKnobLoading) plKnobLoading.style.left = `${posLoading}%`;
    if (plKnobLabelLoading) {
      plKnobLabelLoading.style.left = `${labelPosLoading}%`;
      plKnobLabelLoading.textContent = audioLoadingText(pctLoading);
    }
    setPlayerStatusLabel(audioLoadingText(pctLoading));

    const plStopLoading = $("plStop");
    const plPrevLoading = $("plPrev");
    const plNextLoading = $("plNext");
    if (plStopLoading) plStopLoading.disabled = false;
    if (plPrevLoading) plPrevLoading.disabled = true;
    if (plNextLoading) plNextLoading.disabled = true;
    if (els.btnStopSpeech) els.btnStopSpeech.disabled = true;
    if (els.btnPause) els.btnPause.disabled = true;
    if (els.btnResume) els.btnResume.disabled = true;
    setPlayerVisible(shouldShowPlayerDock());
    updateSectionMiniProgress(nowPlaying.sectionIdx, ratioLoading);
    syncAllToggleIcons();
    syncGlobalPlayerState({
      isLoading: true,
      loadingProgress: ratioLoading,
      isPlaying: false,
    });
    renderPlayerQueueSheet();
    return;
  }

  const total = Math.max(0, playerTotalWords || 0);
  const readF = clamp(Number(playerReadWordsDisplay || playerReadWords || 0), 0, total);
  let ratio = total ? (readF / total) : 0;
  let pct = total ? Math.floor(ratio * 100) : 0;
  let remText = "--:--";

  const plPct = $("plPct");
  const plTime = $("plTime");
  const plFill = $("plFill");
  const plKnob = $("plKnob");
  const plKnobLabel = $("plKnobLabel");

  if (total > 0) {
    const wps = (EST_WPM / 60) * (Number(speechRate) || 1.0);
    const remainingWords = Math.max(0, total - readF);
    const remainingSec = Math.ceil(remainingWords / Math.max(1e-6, wps));
    remText = `-${formatTime(remainingSec)}`;
  } else if (playbackBackend === "audio" && Array.isArray(speakQueue) && speakQueue.length) {
    const ap = audioPlaybackProgress();
    ratio = clamp(ap.ratio, 0, 1);
    pct = Math.floor(ratio * 100);
    remText = ap.hasTime ? `-${formatTime(ap.remainingSec)}` : `${pct}%`;
  } else {
    remText = `${pct}%`;
  }

  if (plPct) plPct.textContent = `${pct}%`;
  if (plFill) plFill.style.width = `${(ratio * 100).toFixed(2)}%`;
  if (plTime) plTime.textContent = remText;
  if (plKnobLabel) plKnobLabel.textContent = remText;
  setPlayerStatusLabel(
    playerIsActive
      ? (isPaused ? tr("audio_paused", "Paused") : tr("audio_playing", "Playing"))
      : tr("player_no_track_label", "Choose an audio story")
  );

  const pos = clamp(ratio * 100, 0, 100);
  const labelPos = clamp(pos, 6, 94);
  if (plKnob) plKnob.style.left = `${pos}%`;
  if (plKnobLabel) plKnobLabel.style.left = `${labelPos}%`;

  // buttons state
  const plStop = $("plStop");
  const plPrev = $("plPrev");
  const plNext = $("plNext");
  if (plStop) plStop.disabled = !playerIsActive;

  const hasQueue = Array.isArray(speakQueue) && speakQueue.length > 1;
  const hasPrevBlock = findAdjacentSectionIdx(-1) != null;
  const hasNextBlock = findAdjacentSectionIdx(1) != null;
  if (plPrev) plPrev.disabled = !(playerIsActive && (hasPrevBlock || (hasQueue && currentChunkIdx > 0)));
  if (plNext) plNext.disabled = !(playerIsActive && (hasNextBlock || (hasQueue && currentChunkIdx >= 0 && currentChunkIdx < (speakQueue.length - 1))));

  if (els.btnStopSpeech) els.btnStopSpeech.disabled = !playerIsActive;
  if (els.btnPause) els.btnPause.disabled = !(playerIsActive && !isPaused);
  if (els.btnResume) els.btnResume.disabled = !(playerIsActive && isPaused);

  setPlayerVisible(shouldShowPlayerDock());
  updateSectionMiniProgress(playerIsActive ? nowPlaying.sectionIdx : null, ratio);
  syncAllToggleIcons();
  syncGlobalPlayerState({
    isPlaying: !!(playerIsActive && !isPaused),
    isLoading: false,
  });
  renderPlayerQueueSheet();
}

function stopRenderLoop() {
  if (renderRafId) cancelAnimationFrame(renderRafId);
  renderRafId = null;
  renderLastUiTs = 0;
}

function updateTargetFromEstimate() {
  if (!playerIsActive) return;
  if (isPaused) return;

  if (playbackBackend === "audio") {
    const el = audioEl;
    const d = Number(el?.duration);
    const t = Number(el?.currentTime);
    if (!Number.isFinite(d) || d <= 0) return;
    if (!Number.isFinite(t) || t < 0) return;

    if (currentChunkWords > 0) {
      const frac = clamp(t / d, 0, 1);
      const readInChunk = clamp(Math.floor(frac * currentChunkWords), 0, currentChunkWords);
      if (readInChunk > currentChunkReadWords) currentChunkReadWords = readInChunk;

      const globalRead = clamp(chunksDoneWords + currentChunkReadWords, 0, playerTotalWords);
      if (globalRead > playerReadWordsTarget) playerReadWordsTarget = globalRead;
    }
    return;
  }

  if (!currentChunkWords) return;

  const now = (window.performance && typeof window.performance.now === "function")
    ? window.performance.now()
    : Date.now();
  const elapsedSec = Math.max(0, (now - chunkStartTs) / 1000);

  const estReadInChunk = Math.floor(elapsedSec * Math.max(1e-6, chunkWps));
  const readInChunk = clamp(estReadInChunk, 0, currentChunkWords);
  if (readInChunk > currentChunkReadWords) currentChunkReadWords = readInChunk;

  const globalRead = clamp(chunksDoneWords + currentChunkReadWords, 0, playerTotalWords);
  if (globalRead > playerReadWordsTarget) playerReadWordsTarget = globalRead;
}

function startRenderLoop(sessionId) {
  stopRenderLoop();

  const tick = (ts) => {
    if (sessionId !== playbackSession) return stopRenderLoop();

    updateTargetFromEstimate();

    const total = Math.max(0, playerTotalWords || 0);
    const target = clamp(playerReadWordsTarget || 0, 0, total);

    // Smooth, monotonic progress (prevents "jumping")
    const delta = target - playerReadWordsDisplay;
    if (delta > 0) {
      playerReadWordsDisplay += Math.max(0.25, delta * 0.12);
      if (playerReadWordsDisplay > target) playerReadWordsDisplay = target;
    }

    playerReadWords = Math.floor(clamp(playerReadWordsDisplay, 0, total));

    if (!renderLastUiTs || (ts - renderLastUiTs) > 33 || delta > 1.2) {
      renderLastUiTs = ts;
      renderPlayerProgress();
      persistPlaybackState(false);
    }

    const stillSmoothing = (target - playerReadWordsDisplay) > 0.4;
    const keepRunning = playerIsActive || stillSmoothing;
    if (keepRunning) renderRafId = requestAnimationFrame(tick);
    else stopRenderLoop();
  };

  renderRafId = requestAnimationFrame(tick);
}

// ======================= Playback =======================
function ensureAudioEl() {
  if (audioEl) return audioEl;
  try {
    audioEl = document.createElement("audio");
    audioEl.preload = "metadata";
    audioEl.crossOrigin = "anonymous";
    audioEl.volume = playerVolume;
    audioEl.style.display = "none";
    audioEl.dataset.agGlobalAudio = "1";
    audioEl.addEventListener("play", markAudioPlayingFromElement);
    audioEl.addEventListener("playing", markAudioPlayingFromElement);
    audioEl.addEventListener("pause", markAudioPausedFromElement);
    audioEl.addEventListener("timeupdate", () => {
      if (playbackBackend !== "audio") return;
      syncGlobalPlayerState({
        currentTime: Number.isFinite(Number(audioEl?.currentTime)) ? Number(audioEl.currentTime) : 0,
        duration: Number.isFinite(Number(audioEl?.duration)) ? Number(audioEl.duration) : globalPlayerState.duration,
      });
    });
    audioEl.addEventListener("error", () => {
      if (audioIntentionalStop || audioTransitioning) return;
      isPaused = true;
      setPlayerLoading(false);
      renderPlayerProgress();
      syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: tr("audio_chunk_error", "Audio fragment failed. Continuing…") });
    });
    document.body.appendChild(audioEl);
  } catch {
    audioEl = null;
  }
  return audioEl;
}

function stopAudioHard() {
  try {
    const el = ensureAudioEl();
    if (!el) return;
    audioIntentionalStop = true;
    el.onloadedmetadata = null;
    el.oncanplay = null;
    el.onplaying = null;
    el.onended = null;
    el.onerror = null;
    el.pause();
    el.removeAttribute("src");
    el.load();
  } catch {
  } finally {
    audioIntentionalStop = false;
  }
}

function clearPlaybackUnlockHandler() {
  if (!playbackUnlockHandler) return;
  const { fn } = playbackUnlockHandler;
  for (const ev of ["pointerdown", "touchstart", "click", "keydown"]) {
    try { window.removeEventListener(ev, fn, true); } catch {}
  }
  playbackUnlockHandler = null;
}

function armPlaybackUnlock(sessionId, blockTitle) {
  if (playbackUnlockHandler) return;
  const fn = () => {
    if (sessionId !== playbackSession || !playerIsActive) {
      clearPlaybackUnlockHandler();
      return;
    }
    const el = ensureAudioEl();
    if (!el) return;
    try {
      const p = el.play();
      if (p && typeof p.then === "function") {
        p.then(() => {
          clearPlaybackUnlockHandler();
          isPaused = false;
          setStatus(`${tr("audio_playing", "Playing audio…")} ${blockTitle ? `• ${blockTitle}` : ""}`.trim());
          persistPlaybackState(true);
        }).catch(() => {});
      } else {
        clearPlaybackUnlockHandler();
        isPaused = false;
        persistPlaybackState(true);
      }
    } catch {}
  };
  playbackUnlockHandler = { sessionId, fn };
  for (const ev of ["pointerdown", "touchstart", "click", "keydown"]) {
    try { window.addEventListener(ev, fn, true); } catch {}
  }
}

// ======================= Speech (Web Speech API) =======================
function invalidateUtterance() {
  activeUtterId += 1;
}

function stopSpeechHard() {
  invalidateUtterance();
  stopAudioHard();
  if (!canSpeak()) return;
  try { window.speechSynthesis.resume(); } catch {}
  try { window.speechSynthesis.cancel(); } catch {}
}

function stopSpeech(opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  const preservePersistedState = !!options.preservePersistedState;
  nextPlaybackSession();
  clearPlaybackUnlockHandler();
  stopSpeechHard();
  resumeSeek = null;
  setPlayerLoading(false);
  setAudioLoadProgress(false, 0, 0, "");
  pendingPlayRequest = null;

  speakQueue = [];
  speakIdx = 0;
  audioDurations = [];
  isPaused = false;
  playerDockPinned = false;
  playbackEntityCity = null;
  playbackGuideSections = [];
  pauseStartedTs = 0;

  playerIsActive = false;
  stopRenderLoop();

  playerTotalWords = 0;
  playerReadWords = 0;
  playerReadWordsTarget = 0;
  playerReadWordsDisplay = 0;

  chunksDoneWords = 0;
  currentChunkWords = 0;
  currentChunkReadWords = 0;
  currentChunkIdx = -1;

  boundarySeenCount = 0;
  boundaryLastChar = -1;
  boundaryReliable = false;

  nowPlaying = { mode: null, sectionIdx: null, blockTitle: "—", cityTitle: "" };

  clearPlayingHighlight();
  clearAllBadges();
  syncGlobalPlayerState({
    currentTrackId: null,
    currentSectionId: null,
    currentSectionTitle: "",
    currentAudioUrl: "",
    queue: [],
    currentIndex: -1,
    isPlaying: false,
    isLoading: false,
    loadingProgress: 0,
    currentTime: 0,
    duration: 0,
    error: null,
  });

  let fallbackMeta = "";
  if (lastPlayPlan?.mode === "all") {
    fallbackMeta = tr("listen_all", "Play all");
  } else if (lastPlayPlan?.mode === "section" && selectedArticle?.sections?.length) {
    const idx = lastPlayPlan.sectionIdx ?? null;
    const sec = (idx != null) ? selectedArticle.sections[idx] : null;
    fallbackMeta = sec?.title || (idx != null ? `Section ${idx + 1}` : "");
  }
  const fallbackTitle = selectedArticle?.title || cityDisplayName(selectedCity) || "—";
  setPlayerHeader(fallbackTitle, fallbackMeta);
  renderPlayerProgress();
  hidePlayerDock();
  renderCitiesList(lastNearbyCities);
  if (!preservePersistedState) clearPersistedPlaybackState();
  emitPlaybackStopped();
  if (selectedArticle || selectedCity) setStatus(tr("audio_stopped", "Playback stopped."));
}

function pauseSpeech() {
  if (!playerIsActive) return;
  showPlayerDock();

  pauseStartedTs = (window.performance && typeof window.performance.now === "function")
    ? window.performance.now()
    : Date.now();
  if (playbackBackend === "audio") {
    try {
      const el = ensureAudioEl();
      if (el && !el.paused) el.pause();
    } catch {}
    isPaused = true;
  } else {
    if (!canSpeak()) return;
    try { window.speechSynthesis.pause(); } catch {}
    isPaused = true;
  }

  if (nowPlaying.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setBadge(nowPlaying.sectionIdx, "PAUSED");
    setPlayingHighlight(nowPlaying.sectionIdx);
  }

  renderPlayerProgress();
  syncAllToggleIcons();
  setStatus(tr("audio_paused", "Playback paused."));
  persistPlaybackState(true);
  syncGlobalPlayerState({
    isPlaying: false,
    isLoading: false,
    currentTime: Number.isFinite(Number(audioEl?.currentTime)) ? Number(audioEl.currentTime) : globalPlayerState.currentTime,
    duration: Number.isFinite(Number(audioEl?.duration)) ? Number(audioEl.duration) : globalPlayerState.duration,
  });
}

function resumeSpeech() {
  if (!playerIsActive) return;
  showPlayerDock();

  if (playbackBackend === "audio") {
    pauseStartedTs = 0;
    try {
      const el = ensureAudioEl();
      if (el) el.playbackRate = Number(speechRate) || 1.0;
      const p = el?.play?.();
      isPaused = false;
      syncGlobalPlayerState({ isPlaying: true, isLoading: false, error: null });
      if (p && typeof p.then === "function") {
        p.then(() => {
          isPaused = false;
          syncGlobalPlayerState({ isPlaying: true, isLoading: false, error: null });
        }).catch((err) => {
          isPaused = true;
          syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: err?.message || "Playback failed" });
          renderPlayerProgress();
        });
      }
    } catch {}
  } else {
    if (!canSpeak()) return;
    const now = (window.performance && typeof window.performance.now === "function")
      ? window.performance.now()
      : Date.now();
    if (pauseStartedTs) {
      const pausedMs = Math.max(0, now - pauseStartedTs);
      chunkStartTs += pausedMs;
      pauseStartedTs = 0;
    }
    try { window.speechSynthesis.resume(); } catch {}
    isPaused = false;
  }

  if (nowPlaying.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setBadge(nowPlaying.sectionIdx, "PLAYING");
    setPlayingHighlight(nowPlaying.sectionIdx);
  }

  renderPlayerProgress();
  syncAllToggleIcons();
  setStatus(tr("audio_playing", "Playing audio…"));
  persistPlaybackState(true);
  syncGlobalPlayerState({ isPlaying: true, isLoading: false, error: null });
}

function startSpeakingQueue(chunks, mode, opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  if (!canSpeak()) {
    alert("Web Speech API not available. Try Chrome/Edge.");
    return;
  }

  showPlayerDock();
  stopSpeechHard();
  const sessionId = nextPlaybackSession();
  clearPlaybackUnlockHandler();
  stopRenderLoop();
  playerIsActive = false;
  isPaused = false;
  currentChunkIdx = -1;
  speakQueue = [];
  clearPlayingHighlight();
  clearAllBadges();

  const list = (chunks || [])
    .map((it) => ({
      text: String(it?.text || "").trim(),
      blockTitle: String(it?.blockTitle || "Section"),
      sectionIdx: (it?.sectionIdx ?? null),
    }))
    .filter(it => it.text);

  if (!list.length) {
    setStatus("⚠ Nothing to play (no text).");
    return;
  }

  if (!options.preservePlaybackContext) {
    playbackEntityCity = selectedCity ? { ...selectedCity } : null;
    capturePlaybackGuideSections();
  }
  const entityTitle = cityDisplayName(playbackEntityCity) || selectedArticle?.title || cityDisplayName(selectedCity) || "";
  speakQueue = list.map((it) => {
    const words = countWords(it.text);
    return {
      text: it.text,
      words,
      blockTitle: it.blockTitle,
      sectionIdx: it.sectionIdx,
      wordStarts: makeWordStarts(it.text),
    };
  });

  speakIdx = 0;
  currentChunkIdx = -1;
  isPaused = false;

  playerTotalWords = speakQueue.reduce((s, x) => s + (x.words || 0), 0);
  playerReadWords = 0;
  playerReadWordsTarget = 0;
  playerReadWordsDisplay = 0;

  chunksDoneWords = 0;
  currentChunkWords = 0;
  currentChunkReadWords = 0;

  boundarySeenCount = 0;
  boundaryLastChar = -1;
  boundaryReliable = false;

  playerIsActive = true;
  syncGlobalPlayerState({
    currentEntityType: (playbackEntityCity || selectedCity)?.kind || "city",
    currentEntityId: (playbackEntityCity || selectedCity) ? cityKey(playbackEntityCity || selectedCity) : null,
    currentEntityTitle: entityTitle,
    queue: globalPlayerQueueSnapshot(),
    currentIndex: -1,
    isPlaying: true,
    isLoading: false,
    error: null,
  });

  nowPlaying.mode = mode || "section";
  nowPlaying.cityTitle = entityTitle;

  startRenderLoop(sessionId);
  setTimeout(() => speakNextChunk(sessionId), 50);
}

function speakNextChunk(sessionId) {
  if (!canSpeak()) return;
  if (sessionId !== playbackSession) return;

  if (speakIdx >= speakQueue.length) {
    if (autoAdvanceToNextSection(sessionId)) return;
    // finished
    playerIsActive = false;
    isPaused = false;
    playerDockPinned = false;
    playerReadWordsTarget = playerTotalWords;

    clearPlayingHighlight();
    clearAllBadges();
    syncAllToggleIcons();
    renderPlayerProgress();
    setPlayerVisible(false);
    clearPersistedPlaybackState();
    emitPlaybackStopped();
    syncGlobalPlayerState({
      isPlaying: false,
      isLoading: false,
      currentIndex: -1,
      error: null,
    });
    return;
  }

  const item = speakQueue[speakIdx];
  currentChunkIdx = speakIdx;
  speakIdx += 1;

  nowPlaying.sectionIdx = item.sectionIdx;
  nowPlaying.blockTitle = item.blockTitle || "Section";
  nowPlaying.cityTitle = nowPlaying.cityTitle || selectedArticle?.title || cityDisplayName(playbackEntityCity || selectedCity) || "";

  // IMPORTANT: always show which H2 is playing
  const meta = nowPlaying.mode === "all"
    ? `${nowPlaying.blockTitle} • ${tr("listen_all", "Play all")}`
    : nowPlaying.blockTitle;
  setPlayerHeader(nowPlaying.cityTitle || "—", meta);
  syncGlobalPlayerState({
    currentTrackId: trackIdFromQueueItem(item, currentChunkIdx),
    currentEntityTitle: nowPlaying.cityTitle || "",
    currentSectionId: Number.isFinite(Number(item.sectionIdx)) ? Number(item.sectionIdx) : null,
    currentSectionTitle: item.blockTitle || "Section",
    currentAudioUrl: "",
    queue: globalPlayerQueueSnapshot(),
    currentIndex: currentChunkIdx,
    isPlaying: true,
    isLoading: false,
    error: null,
  });
  syncGlobalPlayerState({
    currentTrackId: trackIdFromQueueItem(item, currentChunkIdx),
    currentEntityType: (playbackEntityCity || selectedCity)?.kind || "city",
    currentEntityId: (playbackEntityCity || selectedCity) ? cityKey(playbackEntityCity || selectedCity) : null,
    currentEntityTitle: nowPlaying.cityTitle || "",
    currentSectionId: Number.isFinite(Number(item.sectionIdx)) ? Number(item.sectionIdx) : null,
    currentSectionTitle: item.blockTitle || "Section",
    currentAudioUrl: String(item?.srcUrl || item?.url || "").trim(),
    currentLanguage: activeAppLang,
    currentVoiceGender: voiceGender,
    queue: globalPlayerQueueSnapshot(),
    currentIndex: currentChunkIdx,
    isPlaying: false,
    isLoading: true,
    loadingProgress: 0,
    currentTime: 0,
    duration: 0,
    error: null,
  });

  clearAllBadges();
  if (item.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setPlayingHighlight(item.sectionIdx);
    setBadge(item.sectionIdx, isPaused ? "PAUSED" : "PLAYING");
  } else {
    clearPlayingHighlight();
  }

  currentChunkWords = item.words || 0;
  currentChunkReadWords = 0;

  chunkStartTs = (window.performance && typeof window.performance.now === "function")
    ? window.performance.now()
    : Date.now();
  pauseStartedTs = 0;
  chunkWps = (EST_WPM / 60) * (Number(speechRate) || 1.0);
  boundarySeenCount = 0;
  boundaryLastChar = -1;
  boundaryReliable = false;

  playerReadWordsTarget = Math.max(playerReadWordsTarget, chunksDoneWords);
  renderPlayerProgress();

  const u = new SpeechSynthesisUtterance(item.text);
  u.lang = activeSpeechLang || "en-US";
  u.rate = Number(speechRate) || 1.0;
  u.pitch = 1.0;
  u.volume = playerVolume;

  // Best-effort voice match
  try {
    const voices = window.speechSynthesis?.getVoices?.() || [];
    const want = String(u.lang || "").toLowerCase();
    const base = want.split("-")[0];
    const voice =
      voices.find(v => String(v.lang || "").toLowerCase() === want) ||
      voices.find(v => String(v.lang || "").toLowerCase().startsWith(base));
    if (voice) u.voice = voice;
  } catch {}

  const utterId = ++activeUtterId;

  u.onboundary = (ev) => {
    if (sessionId !== playbackSession) return;
    if (utterId !== activeUtterId) return;

    const ci = typeof ev?.charIndex === "number" ? ev.charIndex : null;
    if (ci == null) return;
    if (ci <= boundaryLastChar) return;

    boundaryLastChar = ci;
    boundarySeenCount += 1;
    if (boundarySeenCount >= 3) boundaryReliable = true;

    const w = countWordsByCharIndex(item.wordStarts, ci);
    const next = clamp(w, 0, currentChunkWords);
    if (next > currentChunkReadWords) currentChunkReadWords = next;

    const globalRead = clamp(chunksDoneWords + currentChunkReadWords, 0, playerTotalWords);
    if (globalRead > playerReadWordsTarget) playerReadWordsTarget = globalRead;
  };

  u.onend = () => {
    if (sessionId !== playbackSession) return;
    if (utterId !== activeUtterId) return;

    chunksDoneWords += (item.words || 0);
    currentChunkWords = 0;
    currentChunkReadWords = 0;
    playerReadWordsTarget = Math.max(playerReadWordsTarget, clamp(chunksDoneWords, 0, playerTotalWords));
    renderPlayerProgress();
    syncGlobalPlayerState({ isPlaying: false, isLoading: false });
    speakNextChunk(sessionId);
  };

  u.onerror = () => {
    if (sessionId !== playbackSession) return;
    if (utterId !== activeUtterId) return;

    chunksDoneWords += (item.words || 0);
    currentChunkWords = 0;
    currentChunkReadWords = 0;
    playerReadWordsTarget = Math.max(playerReadWordsTarget, clamp(chunksDoneWords, 0, playerTotalWords));
    renderPlayerProgress();
    syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: tr("audio_chunk_error", "Audio fragment failed. Continuing…") });
    speakNextChunk(sessionId);
  };

  try { window.speechSynthesis.speak(u); } catch {}
}

// ======================= Audio (pre-generated files) =======================
function startAudioQueue(chunks, mode, opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  showPlayerDock();
  stopSpeechHard();
  setPlayerLoading(false);
  setAudioLoadProgress(false, 0, 0, "");
  const sessionId = nextPlaybackSession();
  resumeSeek = null;
  clearPlaybackUnlockHandler();
  stopRenderLoop();
  playerIsActive = false;
  isPaused = false;
  currentChunkIdx = -1;
  speakQueue = [];
  audioDurations = [];
  playerTotalWords = 0;
  playerReadWords = 0;
  playerReadWordsTarget = 0;
  playerReadWordsDisplay = 0;
  chunksDoneWords = 0;
  currentChunkWords = 0;
  currentChunkReadWords = 0;
  clearPlayingHighlight();
  clearAllBadges();

  const list = (chunks || [])
    .map((it) => ({
      url: String(it?.url || "").trim(),
      words: Number.isFinite(Number(it?.words)) ? Number(it.words) : 0,
      blockTitle: String(it?.blockTitle || "Section"),
      sectionIdx: (it?.sectionIdx ?? null),
    }))
    .filter(it => it.url);

  if (!list.length) {
    setStatus("⚠ Nothing to play (no audio).");
    return;
  }

  if (!options.preservePlaybackContext) {
    playbackEntityCity = selectedCity ? { ...selectedCity } : null;
    capturePlaybackGuideSections();
  }
  const entityTitle = cityDisplayName(playbackEntityCity) || selectedArticle?.title || cityDisplayName(selectedCity) || "";
  const el = ensureAudioEl();
  if (!el) {
    setStatus("⚠ Audio player not available.");
    return;
  }

  const loadLabel = mode === "all"
    ? tr("listen_all", "Play all")
    : (list[0]?.blockTitle || tr("audio_loading", "Loading audio…"));
  setPlayerHeader(entityTitle || "—", loadLabel);
  setPlayerLoading(false);
  setStatus(tr("audio_loading", "Loading audio…"));
  setAudioLoadProgress(false, 0, 0, "");
  syncGlobalPlayerState({
    currentEntityType: (playbackEntityCity || selectedCity)?.kind || "city",
    currentEntityId: (playbackEntityCity || selectedCity) ? cityKey(playbackEntityCity || selectedCity) : null,
    currentEntityTitle: entityTitle,
    currentSectionTitle: loadLabel,
    currentLanguage: activeAppLang,
    currentVoiceGender: voiceGender,
    queue: list.map((item, idx) => ({
      id: trackIdFromQueueItem(item, idx),
      index: idx,
      title: item.blockTitle,
      sectionId: Number.isFinite(Number(item.sectionIdx)) ? Number(item.sectionIdx) : null,
      audioUrl: item.url,
      duration: 0,
    })),
    currentIndex: -1,
    isPlaying: false,
    isLoading: false,
    loadingProgress: 1,
    error: null,
  });

  speakQueue = list.map((it) => ({
    url: it.url,
    srcUrl: String(it?.url || "").trim(),
    words: it.words,
    blockTitle: it.blockTitle,
    sectionIdx: it.sectionIdx,
  }));
  audioDurations = new Array(speakQueue.length).fill(NaN);

  speakIdx = 0;
  currentChunkIdx = -1;
  isPaused = false;
  pauseStartedTs = 0;

  playerTotalWords = speakQueue.reduce((s, x) => s + (Number(x.words) || 0), 0);
  playerReadWords = 0;
  playerReadWordsTarget = 0;
  playerReadWordsDisplay = 0;

  chunksDoneWords = 0;
  currentChunkWords = 0;
  currentChunkReadWords = 0;

  boundarySeenCount = 0;
  boundaryLastChar = -1;
  boundaryReliable = false;

  playerIsActive = true;
  syncGlobalPlayerState({
    queue: globalPlayerQueueSnapshot(),
    currentIndex: -1,
    isPlaying: false,
    isLoading: false,
    loadingProgress: 1,
    error: null,
  });

  nowPlaying.mode = mode || "section";
  nowPlaying.cityTitle = entityTitle;

  startRenderLoop(sessionId);
  playNextAudioChunk(sessionId);
}

function playNextAudioChunk(sessionId) {
  const el = ensureAudioEl();
  if (!el) return;
  if (sessionId !== playbackSession) return;

  if (speakIdx >= speakQueue.length) {
    if (autoAdvanceToNextSection(sessionId)) return;
    clearPlaybackUnlockHandler();
    playerIsActive = false;
    isPaused = false;
    playerDockPinned = false;
    setPlayerLoading(false);
    playerReadWordsTarget = playerTotalWords;

    clearPlayingHighlight();
    clearAllBadges();
    syncAllToggleIcons();
    renderPlayerProgress();
    setPlayerVisible(false);
    clearPersistedPlaybackState();
    emitPlaybackStopped();
    syncGlobalPlayerState({
      isPlaying: false,
      isLoading: false,
      currentIndex: -1,
      error: null,
    });
    return;
  }

  const item = speakQueue[speakIdx];
  currentChunkIdx = speakIdx;
  speakIdx += 1;

  nowPlaying.sectionIdx = item.sectionIdx;
  nowPlaying.blockTitle = item.blockTitle || "Section";
  nowPlaying.cityTitle = nowPlaying.cityTitle || selectedArticle?.title || cityDisplayName(playbackEntityCity || selectedCity) || "";

  const meta = nowPlaying.mode === "all"
    ? `${nowPlaying.blockTitle} • ${tr("listen_all", "Play all")}`
    : nowPlaying.blockTitle;
  setPlayerHeader(nowPlaying.cityTitle || "—", meta);

  clearAllBadges();
  if (item.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setPlayingHighlight(item.sectionIdx);
    setBadge(item.sectionIdx, isPaused ? "PAUSED" : "PLAYING");
  } else {
    clearPlayingHighlight();
  }

  currentChunkWords = Number(item.words) || 0;
  currentChunkReadWords = 0;

  playerReadWordsTarget = Math.max(playerReadWordsTarget, chunksDoneWords);
  renderPlayerProgress();
  setPlayerLoading(true, tr("audio_loading", "Loading audio…"));
  setStatus(tr("audio_loading", "Loading audio…"));
  const shouldSeek =
    !!resumeSeek &&
    resumeSeek.sessionId === sessionId &&
    Number(resumeSeek.chunkIdx) === Number(currentChunkIdx) &&
    Number(resumeSeek.timeSec) > 0;
  const seekTargetSec = shouldSeek ? Math.max(0, Number(resumeSeek.timeSec) || 0) : 0;
  const applySeek = () => {
    if (!shouldSeek) return;
    try {
      const d = Number(el.duration);
      const maxSeek = Number.isFinite(d) && d > 0 ? Math.max(0, d - 0.2) : seekTargetSec;
      el.currentTime = clamp(seekTargetSec, 0, maxSeek);
    } catch {}
  };

  el.onloadedmetadata = () => {
    if (sessionId !== playbackSession) return;
    const d = Number(el.duration);
    if (Number.isFinite(d) && d > 0 && currentChunkIdx >= 0) audioDurations[currentChunkIdx] = d;
    applySeek();
    syncGlobalPlayerState({
      duration: Number.isFinite(d) ? d : 0,
      queue: globalPlayerQueueSnapshot(),
    });
  };
  el.oncanplay = () => {
    if (sessionId !== playbackSession) return;
    applySeek();
    setPlayerLoading(false);
    syncGlobalPlayerState({ isLoading: false, loadingProgress: 1 });
  };
  el.onplaying = () => {
    if (sessionId !== playbackSession) return;
    markAudioPlayingFromElement();
    if (shouldSeek) resumeSeek = null;
    setPlayerLoading(false);
    setStatus(`${tr("audio_playing", "Playing audio…")} ${item.blockTitle ? `• ${item.blockTitle}` : ""}`.trim());
    persistPlaybackState(true);
  };
  el.onended = () => {
    if (sessionId !== playbackSession) return;
    syncGlobalPlayerState({ isPlaying: false, isLoading: false, currentTime: Number(el.duration) || 0 });
    setPlayerLoading(false);
    chunksDoneWords += (Number(item.words) || 0);
    currentChunkWords = 0;
    currentChunkReadWords = 0;
    playerReadWordsTarget = Math.max(playerReadWordsTarget, clamp(chunksDoneWords, 0, playerTotalWords));
    renderPlayerProgress();
    persistPlaybackState(true);
    playNextAudioChunk(sessionId);
  };
  el.onerror = () => {
    if (sessionId !== playbackSession) return;
    clearPlaybackUnlockHandler();
    setPlayerLoading(false);
    isPaused = true;
    syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: tr("audio_chunk_error", "Audio fragment failed. Continuing…") });
    setStatus(tr("audio_chunk_error", "Audio fragment failed. Continuing…"));
    chunksDoneWords += (Number(item.words) || 0);
    currentChunkWords = 0;
    currentChunkReadWords = 0;
    playerReadWordsTarget = Math.max(playerReadWordsTarget, clamp(chunksDoneWords, 0, playerTotalWords));
    renderPlayerProgress();
    persistPlaybackState(true);
    playNextAudioChunk(sessionId);
  };

  try {
    audioTransitioning = true;
    el.pause();
    el.currentTime = 0;
  } catch {}

  try {
    el.src = String(item.url || "");
    el.playbackRate = Number(speechRate) || 1.0;
    const p = el.play();
    if (p && typeof p.then === "function") {
      p.then(() => {
        audioTransitioning = false;
        if (sessionId !== playbackSession) return;
        if (el.paused || isPaused) {
          isPaused = true;
          setPlayerLoading(false);
          renderPlayerProgress();
          syncGlobalPlayerState({ isPlaying: false, isLoading: false });
          persistPlaybackState(true);
          return;
        }
        markAudioPlayingFromElement();
      }).catch((err) => {
        audioTransitioning = false;
        if (sessionId !== playbackSession) return;
        isPaused = true;
        setPlayerLoading(false);
        syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: err?.message || tr("audio_tap_resume", "Tap anywhere to resume audio.") });
        setStatus(tr("audio_tap_resume", "Tap anywhere to resume audio."));
        renderPlayerProgress();
        persistPlaybackState(true);
        armPlaybackUnlock(sessionId, item.blockTitle || "");
      });
    } else {
      audioTransitioning = false;
    }
  } catch (err) {
    audioTransitioning = false;
    isPaused = true;
    syncGlobalPlayerState({ isPlaying: false, isLoading: false, error: err?.message || "Playback failed" });
  }
  persistPlaybackState(true);
}

function startPlaybackQueue(chunks, mode, opts) {
  if (requireLoginForPlayback()) return;
  if (playbackBackend === "audio") startAudioQueue(chunks, mode, opts);
  else startSpeakingQueue(chunks, mode, opts);
}

function playerToggleAction() {
  if (requireLoginForPlayback()) return;
  // If playing -> pause
  if (playerIsActive && !isPaused) {
    pauseSpeech();
    return;
  }

  // If paused -> resume (NOT restart)
  if (playerIsActive && isPaused) {
    resumeSpeech();
    return;
  }

  // Idle -> start last plan
  if (!lastPlayPlan) {
    setStatus(tr("choose_city_first", "Choose a city / section first."));
    return;
  }

  if (lastPlayPlan.mode === "section") {
    const idx = lastPlayPlan.sectionIdx;
    startSectionPlayback(idx);
    return;
  }

  // all
  const items = buildAllPlaybackItems();
  if (!items.length) return;
  startPlaybackQueue(items, "all");
}

function wordsBeforeIndex(idx) {
  const i = clamp(Number(idx) || 0, 0, Math.max(0, (speakQueue?.length || 0)));
  let sum = 0;
  for (let k = 0; k < i; k++) sum += Number(speakQueue[k]?.words || 0);
  return sum;
}

function jumpToChunk(idx) {
  if (!playerIsActive) return;
  if (!Array.isArray(speakQueue) || !speakQueue.length) return;

  const target = clamp(Number(idx) || 0, 0, speakQueue.length - 1);
  const sessionId = nextPlaybackSession();

  if (playbackBackend === "audio") {
    try { stopAudioHard(); } catch {}
    invalidateUtterance();

    speakIdx = target;
    currentChunkIdx = -1;
    isPaused = false;
    pauseStartedTs = 0;

    chunksDoneWords = wordsBeforeIndex(target);
    currentChunkWords = 0;
    currentChunkReadWords = 0;

    playerReadWordsTarget = clamp(chunksDoneWords, 0, playerTotalWords);
    playerReadWordsDisplay = playerReadWordsTarget;
    playerReadWords = Math.floor(playerReadWordsDisplay);

    startRenderLoop(sessionId);
    renderPlayerProgress();
    syncGlobalPlayerState({
      currentIndex: target,
      isPlaying: false,
      isLoading: true,
      error: null,
    });
    setTimeout(() => playNextAudioChunk(sessionId), 40);
    return;
  }

  // Cancel current utterance but keep the same playback session
  invalidateUtterance();
  try { window.speechSynthesis?.resume?.(); } catch {}
  try { window.speechSynthesis?.cancel?.(); } catch {}

  speakIdx = target;
  currentChunkIdx = -1;
  isPaused = false;
  pauseStartedTs = 0;

  chunksDoneWords = wordsBeforeIndex(target);
  currentChunkWords = 0;
  currentChunkReadWords = 0;

  playerReadWordsTarget = clamp(chunksDoneWords, 0, playerTotalWords);
  playerReadWordsDisplay = playerReadWordsTarget;
  playerReadWords = Math.floor(playerReadWordsDisplay);

  startRenderLoop(sessionId);
  renderPlayerProgress();
  syncGlobalPlayerState({
    currentIndex: target,
    isPlaying: true,
    isLoading: false,
    error: null,
  });
  setTimeout(() => speakNextChunk(sessionId), 50);
}

function playerPrevAction() {
  if (!playerIsActive) {
    playerToggleAction();
    return;
  }
  const prevSection = findAdjacentSectionIdx(-1);
  if (prevSection != null) {
    startSectionPlayback(prevSection, { preservePlaybackContext: true });
    return;
  }
  jumpToChunk(Math.max(0, currentChunkIdx - 1));
}

function playerNextAction() {
  if (!playerIsActive) {
    playerToggleAction();
    return;
  }
  const nextSection = findAdjacentSectionIdx(1);
  if (nextSection != null) {
    startSectionPlayback(nextSection, { preservePlaybackContext: true });
    return;
  }
  if (!Array.isArray(speakQueue) || !speakQueue.length || currentChunkIdx >= (speakQueue.length - 1)) {
    stopSpeech();
    return;
  }
  jumpToChunk(currentChunkIdx + 1);
}

function playerSpeedAction() {
  cycleSpeechRate();
  if (playbackBackend === "audio") {
    try {
      const el = ensureAudioEl();
      if (el) el.playbackRate = Number(speechRate) || 1.0;
    } catch {}
    renderPlayerProgress();
    return;
  }

  // Speech backend: apply speed immediately by restarting the current chunk
  if (playerIsActive && currentChunkIdx >= 0) jumpToChunk(currentChunkIdx);
}

function seekPlayer(timeSec) {
  const t = Math.max(0, Number(timeSec) || 0);
  if (playbackBackend === "audio") {
    try {
      const el = ensureAudioEl();
      if (!el) return;
      const d = Number(el.duration);
      el.currentTime = Number.isFinite(d) && d > 0 ? clamp(t, 0, d) : t;
      syncGlobalPlayerState({ currentTime: Number(el.currentTime) || 0 });
      renderPlayerProgress();
      persistPlaybackState(true);
    } catch {}
  }
}

function playTrack(track) {
  const item = track && typeof track === "object" ? track : null;
  const url = String(item?.url || item?.audioUrl || "").trim();
  if (!url) {
    setStatus(tr("audio_loading", "Loading audio…"));
    return false;
  }
  const sectionIdx = Number.isFinite(Number(item.sectionIdx ?? item.currentSectionId))
    ? Number(item.sectionIdx ?? item.currentSectionId)
    : null;
  startPlaybackQueue([{
    url,
    srcUrl: url,
    words: Number.isFinite(Number(item.words)) ? Number(item.words) : 0,
    blockTitle: String(item.sectionTitle || item.title || item.currentSectionTitle || "Audio story"),
    sectionIdx,
  }], "section");
  return true;
}

window.AG_GLOBAL_PLAYER = {
  playTrack,
  pause: pauseSpeech,
  resume: resumeSpeech,
  togglePlayPause: playerToggleAction,
  stop: stopSpeech,
  next: playerNextAction,
  previous: playerPrevAction,
  seek: seekPlayer,
  setVolume: setPlayerVolume,
  setPlaybackRate: setSpeechRate,
  getState: () => ({ ...globalPlayerState, queue: [...globalPlayerState.queue] }),
};

// ======================= UI Rendering =======================
function openStoryPanel() {
  if (els.storyPanel) els.storyPanel.dataset.open = "1";
  if (map) setTimeout(() => { try { map.invalidateSize(true); } catch {} }, 150);
}

function selectedCityInlineMarkup(city) {
  if (!selectedCityMatches(city)) return "";

  const pending = !selectedArticle || !!selectedArticle?.audioPending || playbackBackend === "pending";
  const progressPct = clamp(Number(audioLoadState.loaded) || 0, 0, Math.max(1, Number(audioLoadState.total) || 100));
  const progressTotal = Math.max(1, Number(audioLoadState.total) || 100);
  const progressRatio = clamp(progressPct / progressTotal, 0, 1);
  const progressText = audioLoadState.active
    ? `${Math.round(progressRatio * 100)}%`
    : "";
  const loadingLabel = audioLoadState.active ? audioLoadingText(Math.round(progressRatio * 100)) : tr("audio_loading", "Loading audio…");

  const sections = Array.isArray(selectedArticle?.sections) ? selectedArticle.sections.slice(0, 8) : [];
  const items = sections.map((sec, idx) => {
    const title = escapeHtml(sec?.title || tr("city_outline", "Audio stories"));
    const n = String(idx + 1).padStart(2, "0");
    return `
      <button class="ag-inlineTopic" type="button" data-inline-section="${idx}">
        <span>${n}</span>
        <b>${title}</b>
        <i>${escapeHtml(tr("listen_free", "Listen free"))}</i>
      </button>
    `;
  }).join("");

  return `
    <div class="ag-cityInline">
      <div class="ag-cityInlineTop">
        <strong>${escapeHtml(selectedArticle?.title || cityDisplayName(city) || tr("city_outline", "Audio stories"))}</strong>
        <button class="ag-inlineOpen" type="button" data-inline-play-all="1">${escapeHtml(tr("listen_all", "Play all"))}</button>
      </div>
      <div class="ag-cityInlineMeta">
        ${pending
          ? escapeHtml(loadingLabel)
          : escapeHtml(tr("wiki_loaded", "Guide is ready. Tap a section to play, or use Play all."))}
      </div>
      ${audioLoadState.active ? `
        <div class="ag-inlineProgress">
          <span class="ag-inlineProgressFill" style="width:${(progressRatio * 100).toFixed(2)}%"></span>
        </div>
      ` : ""}
      ${items ? `<div class="ag-inlinePlaylist" aria-label="${escapeHtml(tr("city_outline", "Audio stories"))}">${items}</div>` : ""}
    </div>
  `;
}

function cityPopulationRank(city) {
  const n = Number(
    city?.population ??
    city?.pop ??
    city?.populationNum ??
    city?.populationEstimate ??
    0
  );
  return Number.isFinite(n) ? n : 0;
}

function cityDistanceRank(city) {
  const n = Number(city?.distKm);
  return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
}

function rankCitiesByPopulation(cities) {
  return (Array.isArray(cities) ? cities.slice() : [])
    .sort((a, b) => {
      const byPopulation = cityPopulationRank(b) - cityPopulationRank(a);
      if (byPopulation) return byPopulation;
      const byDistance = cityDistanceRank(a) - cityDistanceRank(b);
      if (byDistance) return byDistance;
      return cityDisplayName(a).localeCompare(cityDisplayName(b));
    });
}

function renderCitiesList(found) {
  if (!els.citiesList) return;
  els.citiesList.innerHTML = "";

  const top = rankCitiesByPopulation(found).slice(0, MAX_LIST);
  lastNearbyCities = top;

  top.forEach((c) => {
    const li = document.createElement("li");
    li.className = "ag-cityRow";
    const btn = document.createElement("button");
    btn.className = `ag-cityListBtn ${selectedCityMatches(c) ? "is-selected" : ""}`;
    const flag = flagMarkup(c);
    const countryLabel = countryDisplayName(c);
    const cityLabel = cityDisplayName(c);
    const distanceText = Number.isFinite(Number(c.distKm)) ? `≈ ${Number(c.distKm).toFixed(1)} km` : "";
    btn.innerHTML = `
      <div class="ag-cityListMain">
        ${flag}
        <div class="ag-cityListText">
          <b>${escapeHtml(cityLabel)}</b>
          <span>${escapeHtml(countryLabel)}</span>
        </div>
        <small>${escapeHtml(distanceText)}</small>
      </div>
    `;
    btn.type = "button";
    btn.addEventListener("click", () => onSelectCity(c, { scroll: true, warm: false }));
    li.appendChild(btn);
    const inline = selectedCityInlineMarkup(c);
    if (inline) {
      const div = document.createElement("div");
      div.innerHTML = inline;
      const inlineEl = div.firstElementChild;
      if (inlineEl) {
        inlineEl.querySelectorAll("[data-inline-play-all]").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            scrollStoryPanelIntoView();
            playAllCurrentGuide();
          });
        });
        inlineEl.querySelectorAll("[data-inline-section]").forEach((chip) => {
          chip.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const idx = Number(chip.getAttribute("data-inline-section"));
            if (!Number.isFinite(idx) || !selectedArticle?.sections?.[idx]) {
              scrollStoryPanelIntoView();
              return;
            }
            scrollStoryPanelIntoView();
            if (selectedArticle?.audioPending || playbackBackend === "pending") {
              queuePendingPlayback("section", idx, selectedArticle.sections[idx]?.title || `Section ${idx + 1}`);
              setBadge(idx, tr("audio_loading", "Loading audio…"));
              return;
            }
            const secNode = sectionEls.get(idx);
            if (secNode && typeof secNode.click === "function") {
              secNode.click();
            }
          });
        });
        li.appendChild(inlineEl);
      }
    }
    els.citiesList.appendChild(li);
  });
}

function queuePendingPlayback(mode, sectionIdx, blockTitle) {
  if (requireLoginForPlayback()) return;
  if (!selectedCity) return;
  showPlayerDock();
  const cityK = cityKey(selectedCity);
  pendingPlayRequest = {
    cityKey: cityK,
    mode: mode === "all" ? "all" : "section",
    sectionIdx: mode === "section" ? Number(sectionIdx) : null,
    label: String(blockTitle || tr("audio_loading", "Loading audio…")),
  };
  lastPlayPlan = pendingPlayRequest.mode === "all"
    ? { mode: "all" }
    : { mode: "section", sectionIdx: pendingPlayRequest.sectionIdx };

  const pageLang = String(window.APP_LANG || activeAppLang || "ua").toLowerCase();
  setPlayerHeader(selectedArticle?.title || cityDisplayName(selectedCity) || "—", pendingPlayRequest.label);
  setAudioLoadProgress(true, 2, 100, audioLoadingText(2));
  setPlayerLoading(true, audioLoadingText(2));
  setStatus(audioLoadingText(2));
  renderPlayerProgress();
  renderCitiesList(lastNearbyCities);
  refreshPendingAudioForSelection(selectedCity, pageLang, voiceGender, audioSelectionToken);
}

function maybeRunPendingPlayback() {
  if (!pendingPlayRequest || !selectedCity || !selectedArticle || playbackBackend !== "audio") return;
  if (pendingPlayRequest.cityKey !== cityKey(selectedCity)) return;

  const req = pendingPlayRequest;
  pendingPlayRequest = null;

  if (req.mode === "section") {
    const idx = Number(req.sectionIdx);
    startSectionPlayback(idx);
    return;
  }

  lastPlayPlan = { mode: "all" };
  const items = buildAllPlaybackItems();
  if (items.length) startPlaybackQueue(items, "all");
}

function renderHeadingsOnly(article) {
  if (!els.storySections) return;
  els.storySections.innerHTML = "";

  sectionEls.clear();
  sectionBadgeEls.clear();
  sectionToggleBtns.clear();
  selectedSectionIdx = null;
  renderAudioProgressPanel();

  const sections = article?.sections || [];
  const audioPending = !!article?.audioPending;
  if (!sections.length) {
    els.storySections.innerHTML = `<div class="text-secondary fw-medium" style="font-size:12px;">No audio stories found yet.</div>`;
    if (els.btnSpeak) els.btnSpeak.disabled = true;
    return;
  }

  if (els.btnSpeak) els.btnSpeak.disabled = false;

  sections.forEach((sec, idx) => {
    const card = document.createElement("div");
    card.className = "ag-sec";

    const top = document.createElement("div");
    top.className = "ag-secTop";
    top.dataset.sectionIdx = String(idx);
    top.setAttribute("role", "button");
    top.setAttribute("tabindex", "0");
    top.setAttribute("aria-label", `${tr("listen_all", "Play all")}: ${sec.title || `Section ${idx + 1}`}`);

    const left = document.createElement("div");
    left.className = "ag-secContent";
    left.style.display = "flex";
    left.style.flexDirection = "column";
    left.style.gap = "5px";
    left.style.flex = "1";
    left.style.minWidth = "0";

    const titleRow = document.createElement("div");
    titleRow.style.display = "flex";
    titleRow.style.gap = "8px";
    titleRow.style.alignItems = "center";
    titleRow.style.flexWrap = "wrap";

    const title = document.createElement("div");
    title.className = "ag-secTitle";
    title.textContent = `${String(idx + 1).padStart(2, "0")} · ${sec.title || `Section ${idx + 1}`}`;

    const badge = document.createElement("span");
    badge.className = "ag-badge";

    const nowPill = document.createElement("span");
    nowPill.className = "ag-nowPill";
    nowPill.textContent = "Now playing";

    const wave = document.createElement("span");
    wave.className = "ag-wave";
    wave.setAttribute("aria-hidden", "true");
    wave.innerHTML = "<i></i><i></i><i></i><i></i>";

    titleRow.appendChild(title);
    titleRow.appendChild(badge);
    titleRow.appendChild(nowPill);
    titleRow.appendChild(wave);

    const meta = document.createElement("div");
    meta.className = "ag-secMeta";
    const w =
      (Number.isFinite(Number(sec?.words)) ? Number(sec.words) : 0) ||
      (Array.isArray(sec?.chunks) ? sec.chunks.reduce((s, x) => s + (Number(x?.words) || 0), 0) : 0) ||
      countWords(sec.text);
    const duration = w ? formatTime(Math.max(20, Math.ceil((w / EST_WPM) * 60))) : "";
    meta.textContent = duration
      ? `${w} ${tr("words_unit", "words")} · ${duration}`
      : `${w} ${tr("words_unit", "words")}`;

    const miniProgress = document.createElement("div");
    miniProgress.className = "ag-secMiniProgress";
    miniProgress.setAttribute("aria-hidden", "true");
    miniProgress.innerHTML = "<i></i>";

    left.appendChild(titleRow);
    left.appendChild(meta);
    left.appendChild(miniProgress);

    const controls = document.createElement("div");
    controls.className = "ag-secBtns";

	    const btnToggle = document.createElement("button");
	    btnToggle.className = "ag-iconBtn ag-iconBtnPrimary";
	    btnToggle.type = "button";
	    setToggleIcon(btnToggle, true);
	    btnToggle.title = "Play / Pause";
	    btnToggle.setAttribute("aria-label", `Play ${sec.title || `Section ${idx + 1}`}`);
	    const btnStop = document.createElement("button");
	    btnStop.className = "ag-iconBtn";
	    btnStop.type = "button";
	    btnStop.innerHTML = `<svg class="ag-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8h8v8h-8z"/></svg>`;
	    btnStop.title = "Stop";
	    btnStop.setAttribute("aria-label", `Stop ${sec.title || `Section ${idx + 1}`}`);

    controls.appendChild(btnToggle);
    controls.appendChild(btnStop);

    sectionEls.set(idx, top);
    sectionBadgeEls.set(idx, badge);
    sectionToggleBtns.set(idx, btnToggle);

    const statusLabel = sectionAudioStatusLabel(sec, idx);
    if (statusLabel) setBadge(idx, statusLabel);

    const toggleThisSection = () => {
      toggleSectionPlayback(idx);
    };

    top.addEventListener("click", (ev) => {
      if (ev?.target?.closest?.("button,a,input,label,select,textarea")) return;
      toggleThisSection();
    });
    top.addEventListener("keydown", (ev) => {
      if (!ev) return;
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        toggleThisSection();
      }
    });

    btnToggle.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleThisSection();
    });

    btnStop.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (audioPending) {
        pendingPlayRequest = null;
      }
      stopSpeech();
    });

    top.appendChild(left);
    top.appendChild(controls);
    card.appendChild(top);
    els.storySections.appendChild(card);
  });

  syncAllToggleIcons();
  if (playerIsActive && nowPlaying.sectionIdx != null && activePlaybackBelongsToCurrentPage()) {
    setPlayingHighlight(nowPlaying.sectionIdx);
    setBadge(nowPlaying.sectionIdx, isPaused ? "PAUSED" : "PLAYING");
    syncAllToggleIcons();
  }
  renderAudioProgressPanel();
}

// ======================= City select =======================
async function onSelectCity(city, opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  const keepPlayback = !!options.keepPlayback && playerIsActive && Array.isArray(speakQueue) && speakQueue.length;
  const loadToken = ++audioSelectionToken;
  selectedCity = city ? { ...city } : null;
  selectedArticle = null;

  openStoryPanel();
  if (!keepPlayback) {
    stopSpeech({ preservePersistedState: !!options.preservePersistedState });
  }

  if (els.storyTitle) els.storyTitle.textContent = cityDisplayName(city) || tr("city_outline", "Audio stories");
  if (els.storySource) els.storySource.textContent = "";
  if (els.storySections) els.storySections.innerHTML = `<div class="text-secondary fw-medium" style="font-size:12px;">${escapeHtml(tr("wiki_loading", "Loading guide…"))}</div>`;
  if (els.btnSpeak) els.btnSpeak.disabled = false;
  renderCitiesList(lastNearbyCities);

  if (map) {
    ensureCityMarker(selectedCity);
    map.setView([selectedCity.lat, selectedCity.lon], Math.max(map.getZoom(), 12));
    openCityPopup(selectedCity);
  }
  if (options.scroll !== false) scrollStoryPanelIntoView();
  if (options.warm !== false) warmAudioVariants(city);
  try { await renderPlacesOnMap(); } catch {}

  try {
    const pageLang = String(window.APP_LANG || activeAppLang || "ua").toLowerCase();
    const meta0 = LANG_META[pageLang];

    let picked = null;
    let pendingGender = voiceGender;

	    // Prefer pre-generated audio for the current UI language (best UX + best voice quality).
	    try {
	      if (meta0) {
          setPlayerLoading(true, tr("audio_loading", "Loading audio…"));
          setStatus(tr("audio_loading", "Loading audio…"));
        let manifest = await fetchAudioManifest(city, pageLang, voiceGender);
          if (!manifest) {
            await requestAudioBuild(city, pageLang, voiceGender);
          }

        if (manifest) {
	          const article = audioArticleFromManifest(manifest);
	          picked = { article, appLang: pageLang, wikiLang: meta0.wiki, speechLang: meta0.speech, backend: "audio" };
            setPlayerLoading(false);
	        }
	      }
	    } catch {}

	    if (!picked) {
      const order = [pageLang, ...Object.keys(LANG_META).filter((x) => x !== pageLang)];
      let lastErr = null;
	      for (const appLang of order) {
	        const meta = LANG_META[appLang];
        if (!meta) continue;
        try {
          const article = await getCityArticle(city, meta.wiki);
          article.audioPending = true;
          picked = { article, appLang, wikiLang: meta.wiki, speechLang: meta.speech, backend: "pending" };
          break;
        } catch (e) {
          lastErr = e;
        }
      }
      if (!picked) throw lastErr || new Error("No page found");
    }

    if (!picked) {
      setPlayerLoading(true, tr("audio_loading", "Loading audio…"));
      setStatus(tr("audio_loading", "Loading audio…"));
      if (els.storySections) {
        els.storySections.innerHTML = `<div class="text-secondary fw-medium" style="font-size:12px;">${escapeHtml(tr("audio_loading", "Loading audio…"))}</div>`;
      }
      lastPlayPlan = null;
      setPlayerHeader(cityDisplayName(city) || "—", tr("audio_loading", "Loading audio…"));
      renderPlayerProgress();
      return;
    }

    if (!currentSelectionMatches(selectedCity, loadToken)) return;
    if (!applyPickedArticleToUi(selectedCity, picked, pageLang, { keepActiveAudio: keepPlayback })) return;
    renderCitiesList(lastNearbyCities);

    if (options.autoPlayAfterLoad && !keepPlayback) {
      if (picked.backend === "pending" || selectedArticle?.audioPending || playbackBackend === "pending") {
        queuePendingPlayback("all", null, tr("listen_all", "Play all"));
      } else {
        lastPlayPlan = { mode: "all" };
        setTimeout(() => {
          if (!playerIsActive && selectedCity && cityKey(selectedCity) === cityKey(city)) {
            try { playerToggleAction(); } catch {}
          }
        }, 80);
      }
    }

    if (picked.backend === "pending" && meta0 && !keepPlayback) {
      refreshPendingAudioForSelection(selectedCity, pageLang, pendingGender, loadToken);
    }
	  } catch (e) {
    setPlayerLoading(false);
    setAudioLoadProgress(false, 0, 0, "");
    if (els.storySections) els.storySections.innerHTML = `<div class="text-secondary fw-medium" style="font-size:12px;">${escapeHtml(tr("wiki_failed", "Failed to load the guide."))}</div>`;
    if (els.storySource) els.storySource.textContent = "";
    if (els.btnSpeak) els.btnSpeak.disabled = false;

    lastPlayPlan = null;
    pendingPlayRequest = null;
    renderCitiesList(lastNearbyCities);

    setPlayerHeader("—", "");
    renderPlayerProgress();

    setStatus(`${tr("wiki_failed", "Failed to load the guide.")} ${e?.message ? `(${e.message})` : ""}`.trim());
  }
}

// ======================= Nearby update (driving realtime + optional auto) =======================
function autoEnabled() {
  return !!(els.autoMode && els.autoMode.checked);
}

async function maybeAutoPick(nearest) {
  if (!nearest) return;
  if (!autoEnabled()) return;

  const now = Date.now();
  if (autoLastSwitchTs && (now - autoLastSwitchTs) < AUTO_SWITCH_MIN_MS) return;

  const nextKey = cityKey(nearest);
  const curKey = selectedCity ? cityKey(selectedCity) : null;
  if (nextKey && curKey && nextKey === curKey) return;

  const currentIsCity = !selectedCity || !selectedCity.kind || String(selectedCity.kind).toLowerCase() === "city";
  if (!currentIsCity) return;

  if (curKey && lastGps) {
    const currentDist = haversineKm(lastGps.lat, lastGps.lon, Number(selectedCity?.lat), Number(selectedCity?.lon));
    const nearestDist = Number(nearest?.distKm);
    const clearlyCloser =
      !Number.isFinite(currentDist) ||
      !Number.isFinite(nearestDist) ||
      (currentDist - nearestDist) >= AUTO_SWITCH_MIN_IMPROVEMENT_KM ||
      (currentDist > SEARCH_RADIUS_KM * 0.75 && nearestDist < currentDist * 0.65);
    if (!clearlyCloser) return;
  }

  if (lastAutoPickGps && lastGps && curKey) {
    const movedSincePick = haversineKm(lastAutoPickGps.lat, lastAutoPickGps.lon, lastGps.lat, lastGps.lon);
    if (movedSincePick < AUTO_SWITCH_MOVE_CONFIRM_KM) return;
  }

  autoLastSwitchTs = now;
  lastAutoPickGps = lastGps ? { lat: lastGps.lat, lon: lastGps.lon } : null;
  await onSelectCity(nearest, { scroll: false, warm: false, autoPlayAfterLoad: true });
}

async function updateNearbyNow() {
  if (!lastGps) return;
  const { lat, lon } = lastGps;

  const found = await fetchNearby(lat, lon);
  const within = found
    .filter(c => Number.isFinite(c.distKm) && c.distKm <= SEARCH_RADIUS_KM);
  const ranked = rankCitiesByPopulation(within);

  if (!within.length) {
    setStatus(tr("nearby_none", "No supported cities over 10,000 people found within 10 km."));
    renderCitiesList([]);
    clearMarkers();
    return;
  }

  setStatus(tr("nearby_found", "Found {n} cities within 10 km.").replace("{n}", String(within.length)));
  renderCitiesList(ranked);
  setMarkers(ranked);
  try { await prefetchNearbyAudio(ranked); } catch {}

  // Auto-pick nearest city while driving (if enabled)
  const nearest = within.slice().sort((a, b) => cityDistanceRank(a) - cityDistanceRank(b))[0];
  await maybeAutoPick(nearest);
}

// ======================= GPS =======================
function armGpsSlowTimer() {
  if (gpsSlowTimerId) clearTimeout(gpsSlowTimerId);
  gpsSlowTimerId = setTimeout(() => {
    setStatus(tr("gps_slow", "Waiting for a fresh GPS position…"));
  }, GPS_SLOW_RESPONSE_MS);
}

function clearGpsSlowTimer() {
  if (gpsSlowTimerId) clearTimeout(gpsSlowTimerId);
  gpsSlowTimerId = null;
}

function shouldFetchNearbyForGps(lat, lon, now) {
  if (!lastNearbyFetch) return true;
  const elapsed = now - Number(lastNearbyFetch.ts || 0);
  if (elapsed < GPS_MIN_FETCH_MS) return false;

  const movedKm = haversineKm(lastNearbyFetch.lat, lastNearbyFetch.lon, lat, lon);
  if (movedKm >= GPS_MIN_MOVE_KM) return true;
  return elapsed >= GPS_STATIONARY_REFRESH_MS;
}

async function maybeFetchNearbyFromGps(force) {
  if (!lastGps) return;
  const now = Date.now();
  if (!force && !shouldFetchNearbyForGps(lastGps.lat, lastGps.lon, now)) return;
  await updateNearbyNow();
  lastNearbyFetch = { ts: now, lat: lastGps.lat, lon: lastGps.lon };
}

function startGeolocation() {
  if (!("geolocation" in navigator)) {
    setStatus(tr("geo_not_supported", "Geolocation is not supported."));
    return;
  }

  setStatus(tr("status_locating", "Requesting geolocation permission…"));
  if (els.btnLocate) els.btnLocate.disabled = true;
  if (els.btnStop) els.btnStop.disabled = false;
  armGpsSlowTimer();

  watchId = navigator.geolocation.watchPosition(
    async (pos) => {
      const { latitude, longitude, accuracy } = pos.coords;
      lastGps = { lat: latitude, lon: longitude, accuracy };
      armGpsSlowTimer();

      updateUserOnMap(latitude, longitude, accuracy);

      const now = Date.now();
      const weakAccuracy = Number.isFinite(Number(accuracy)) && Number(accuracy) > GPS_WEAK_ACCURACY_M;
      if (weakAccuracy && (!lastGpsStatusTs || (now - lastGpsStatusTs) > 10_000)) {
        lastGpsStatusTs = now;
        setStatus(tr("gps_weak_accuracy", "GPS accuracy is weak. Keep the phone near a window or outside."));
      }

      try {
        await maybeFetchNearbyFromGps(false);
      } catch (e) {
        setStatus(`${tr("nearby_error", "Nearby error")} ${e?.message ? `(${e.message})` : ""}`.trim());
      }
    },
    (err) => {
      clearGpsSlowTimer();
      if (err && err.code === 1) setStatus(tr("status_denied", "Geolocation permission denied."));
      else setStatus(`${tr("status_error", "Geolocation error.")} ${err?.message ? `(${err.message})` : ""}`.trim());
      if (els.btnLocate) els.btnLocate.disabled = false;
      if (els.btnStop) els.btnStop.disabled = true;
    },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
  );

  refreshTimerId = setInterval(async () => {
    try {
      await maybeFetchNearbyFromGps(false);
    }
    catch (e) { setStatus(`${tr("nearby_error", "Nearby error")} ${e?.message ? `(${e.message})` : ""}`.trim()); }
  }, GPS_REFRESH_MS);

  setStatus(tr("gps_started", "GPS started. Cities update while you move."));
}

function stopGeolocation() {
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  if (refreshTimerId) {
    clearInterval(refreshTimerId);
    refreshTimerId = null;
  }
  clearGpsSlowTimer();

  if (els.btnLocate) els.btnLocate.disabled = false;
  if (els.btnStop) els.btnStop.disabled = true;

  setStatus(tr("gps_stopped", "Geolocation stopped."));
}

// ======================= Wire up =======================
function playAllCurrentGuide() {
  if (requireLoginForPlayback()) return;
  if (!selectedArticle?.sections?.length) return;
  if (selectedArticle?.audioPending || playbackBackend === "pending") {
    queuePendingPlayback("all", null, tr("listen_all", "Play all"));
    return;
  }

  lastPlayPlan = { mode: "all" };

  const items = [];
  selectedArticle.sections.forEach((s, idx) => {
    const blockTitle = s.title || `Section ${idx + 1}`;
    if (playbackBackend === "audio" && Array.isArray(s?.chunks) && s.chunks.length) {
      s.chunks.forEach((ch) => {
        items.push({
          url: ch.url,
          words: Number.isFinite(Number(ch?.words)) ? Number(ch.words) : 0,
          blockTitle,
          sectionIdx: idx,
        });
      });
    } else {
      items.push({
        text: s.text,
        blockTitle,
        sectionIdx: idx,
      });
    }
  });

  startPlaybackQueue(items, "all");
}

function bindClickOnce(el, key, fn) {
  if (!el || !fn) return;
  const attr = `agBound${key}`;
  if (el.dataset && el.dataset[attr] === "1") return;
  if (el.dataset) el.dataset[attr] = "1";
  el.addEventListener("click", fn);
}

function bindHeroSaveButtons() {
  document.querySelectorAll("[data-hero-save-guide]").forEach((btn) => {
    if (btn.dataset.agHeroSaveBound === "1") return;
    btn.dataset.agHeroSaveBound = "1";
    btn.addEventListener("click", (ev) => {
      try { ev.preventDefault(); } catch {}
      saveCurrentGuide(btn);
    });
  });
}

function bindPageControls() {
  bindHeroSaveButtons();
  bindClickOnce(els.btnLocate, "Locate", startGeolocation);
  bindClickOnce(els.btnStop, "StopGeo", stopGeolocation);
  bindClickOnce(els.btnSpeak, "SpeakAll", playAllCurrentGuide);
  bindClickOnce(els.btnStopSpeech, "StopSpeech", stopSpeech);
  bindClickOnce(els.btnPause, "PauseSpeech", pauseSpeech);
  bindClickOnce(els.btnResume, "ResumeSpeech", resumeSpeech);
  bindClickOnce($("voiceFemale"), "VoiceFemale", () => setVoiceGender("female"));
  bindClickOnce($("voiceMale"), "VoiceMale", () => setVoiceGender("male"));
  document.querySelectorAll("[data-ag-now-card]").forEach((card) => {
    if (!card.hasAttribute("tabindex")) card.tabIndex = 0;
    if (!card.getAttribute("role")) card.setAttribute("role", "button");
    bindClickOnce(card, "ContinueNowCard", (ev) => {
      if (ev?.target?.closest?.("a,button,input,label,select,textarea")) return;
      continueInlineNowPlaying();
    });
    if (!card.dataset.agBoundContinueNowKey) {
      card.dataset.agBoundContinueNowKey = "1";
      card.addEventListener("keydown", (ev) => {
        if (!ev || (ev.key !== "Enter" && ev.key !== " ")) return;
        ev.preventDefault();
        continueInlineNowPlaying();
      });
    }
  });
  document.querySelectorAll("[data-ag-continue-toggle]").forEach((btn) => {
    bindClickOnce(btn, "ContinueInlineNowPlaying", continueInlineNowPlaying);
  });
  syncInlineNowPlayingCards();
  bindClickOnce($("dockGps"), "DockGps", () => {
    try { document.getElementById("live")?.scrollIntoView?.({ behavior: "smooth", block: "start" }); } catch {}
    if (watchId == null) {
      try { startGeolocation(); } catch {}
    }
  });
}

function findCityForPopupButton(btn) {
  const key = String(btn?.getAttribute?.("data-city-key") || "").trim();
  if (!key) return null;
  const fromList = (Array.isArray(lastNearbyCities) ? lastNearbyCities : []).find((c) => cityKey(c) === key);
  if (fromList) return fromList;
  if (selectedCity && cityKey(selectedCity) === key) return selectedCity;
  for (const marker of markersByKey.values()) {
    if (marker?.__agCity && cityKey(marker.__agCity) === key) return marker.__agCity;
  }
  return null;
}

document.addEventListener("click", (ev) => {
  const btn = ev.target?.closest?.("[data-city-select][data-city-key]");
  if (!btn) return;
  const city = findCityForPopupButton(btn);
  if (!city) return;
  ev.preventDefault();
  ev.stopPropagation();
  selectCityAndPlayAll(city, { scroll: true });
}, true);

function applyPickedArticleToUi(city, picked, pageLang, opts) {
  if (!picked || !picked.article) return false;
  const options = (opts && typeof opts === "object") ? opts : {};
  const keepActiveAudio = !!options.keepActiveAudio && playerIsActive && Array.isArray(speakQueue) && speakQueue.length;

  const isCityPage = !!window.CITY_PAGE;
  const citySlug = window.CITY_PAGE?.citySlug;
  const countrySlug = window.CITY_PAGE?.countrySlug;
  const isPlacePage = !!window.PLACE_PAGE;
  const placeSlug = window.PLACE_PAGE?.placeSlug;
  const placeCitySlug = window.PLACE_PAGE?.citySlug;
  const placeCountrySlug = window.PLACE_PAGE?.countrySlug;

  if (picked.backend !== "pending" && isCityPage && picked.appLang !== pageLang && citySlug && countrySlug) {
    setStatus(tr("no_wiki_lang", "No article in this language. Checking other languages…"));
    const target = localizedRoute(picked.appLang, [countrySlug, citySlug]);
    if (window.location.pathname !== target) {
      window.location.replace(target);
      return false;
    }
  }
  if (picked.backend !== "pending" && isPlacePage && picked.appLang !== pageLang && placeSlug && placeCitySlug && placeCountrySlug) {
    setStatus(tr("no_wiki_lang", "No article in this language. Checking other languages…"));
    const target = localizedRoute(picked.appLang, [placeCountrySlug, placeCitySlug, placeSlug]);
    if (window.location.pathname !== target) {
      window.location.replace(target);
      return false;
    }
  }

  activeAppLang = picked.appLang;
  activeWikiLang = picked.wikiLang;
  activeSpeechLang = picked.speechLang;
  window.APP_LANG = activeAppLang;
  window.WIKI_LANG = activeWikiLang;
  window.SPEECH_LANG = activeSpeechLang;
  if (!keepActiveAudio) {
    playbackBackend = (picked.backend === "audio") ? "audio" : (picked.backend === "pending" ? "pending" : "speech");
  }

  const activeLangEl = document.getElementById("activeLang");
  if (activeLangEl) activeLangEl.textContent = String(activeAppLang || "").toUpperCase();

  selectedArticle = picked.article;
  const currentEntityDisplayTitle = cityDisplayName(city) || "";
  if (selectedArticle && currentEntityDisplayTitle) selectedArticle.title = currentEntityDisplayTitle;

  if (els.storyTitle) els.storyTitle.textContent = picked.article.title || (cityDisplayName(city) || "");
  if (els.storySource) els.storySource.textContent = "";

  const wikiCoords = normalizeCoordinates(picked.article?.coordinates);
  if (wikiCoords && map) {
    const prevLat = Number(city?.lat);
    const prevLon = Number(city?.lon);
    const movedKm =
      (Number.isFinite(prevLat) && Number.isFinite(prevLon))
        ? haversineKm(prevLat, prevLon, wikiCoords.lat, wikiCoords.lon)
        : 9999;

    city.lat = wikiCoords.lat;
    city.lon = wikiCoords.lon;

    const mk = markersByKey.get(cityKey(city));
    if (mk && typeof mk.setLatLng === "function") mk.setLatLng([wikiCoords.lat, wikiCoords.lon]);

    const preferZoom = (String(city?.kind || "").toLowerCase() === "place") ? 13 : 12;
    if (movedKm > 0.3 || preferZoom > map.getZoom()) {
      map.setView([wikiCoords.lat, wikiCoords.lon], Math.max(map.getZoom(), preferZoom));
    }
  }

  renderHeadingsOnly(picked.article);
  renderCitiesList(lastNearbyCities);

  if ((isCityPage || isPlacePage) && picked.article?.langLinks) {
    applyAvailableLanguages(picked.article.langLinks);
    const hint = document.getElementById("langHint");
    const hintWrap = document.getElementById("langHintWrap");
    if (hint) {
      const avail = Object.keys(picked.article.langLinks || {}).map(x => String(x).toUpperCase()).join(", ");
      hint.textContent = avail ? avail : "";
      if (hintWrap) hintWrap.hidden = !avail;
    }
  }

  if (playbackBackend === "pending") {
    if (!pendingPlayRequest) lastPlayPlan = null;
    if (!keepActiveAudio) {
      setPlayerHeader(picked.article.title || (cityDisplayName(city) || "—"), tr("audio_loading", "Loading audio…"));
    }
    renderPlayerProgress();
    if (!keepActiveAudio) setPlayerLoading(true, tr("audio_loading", "Loading audio…"));
    setStatus(tr("audio_loading", "Loading audio…"));
  } else {
    if (!pendingPlayRequest && !keepActiveAudio) lastPlayPlan = { mode: "all" };
    if (!keepActiveAudio) {
      setPlayerHeader(picked.article.title || (cityDisplayName(city) || "—"), tr("listen_all", "Play all"));
    }
    renderPlayerProgress();
    if (!keepActiveAudio) setPlayerLoading(false);
    setStatus(tr("wiki_loaded", "Guide is ready. Tap a section to play, or use Play all."));
    maybeRunPendingPlayback();
  }
  return true;
}

// ======================= Soft navigation while audio plays =======================
function hasLivePlaybackForNavigation() {
  return !!(playerIsActive && Array.isArray(speakQueue) && speakQueue.length);
}

function isSoftNavigableLink(anchor, ev) {
  if (!anchor || !hasLivePlaybackForNavigation()) return false;
  if (ev && (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey)) return false;
  if (anchor.target && anchor.target !== "_self") return false;
  if (anchor.hasAttribute("download")) return false;
  if (anchor.closest("[data-no-soft-nav]")) return false;
  if (anchor.matches("[data-lang], #langMenu a, .dropdown-item[data-lang]")) return false;

  let url;
  try {
    url = new URL(anchor.getAttribute("href") || "", window.location.href);
  } catch {
    return false;
  }
  if (url.origin !== window.location.origin) return false;
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  const langPrefixes = new Set(["fr", "es", "it", "ua", "uk", "de"]);
  const currentFirst = window.location.pathname.split("/").filter(Boolean)[0] || "";
  const targetFirst = url.pathname.split("/").filter(Boolean)[0] || "";
  const currentLang = langPrefixes.has(currentFirst) ? currentFirst : "en";
  const targetLang = langPrefixes.has(targetFirst) ? targetFirst : "en";
  if (targetLang !== currentLang) return false;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/static/") || url.pathname.startsWith("/media/")) return false;
  if (url.pathname.startsWith("/admin")) return false;

  const samePath = url.pathname === window.location.pathname && url.search === window.location.search;
  if (samePath && url.hash) return false;
  if (url.pathname === window.location.pathname && url.search === window.location.search && !url.hash) return false;
  return true;
}

function clearPageGlobalsForSoftNav() {
  try {
    delete window.CITY_PAGE;
    delete window.PLACE_PAGE;
    delete window.COUNTRY_PAGE;
    delete window.CITY_PLACES;
    delete window.AUTO_START_GPS;
  } catch {
    window.CITY_PAGE = undefined;
    window.PLACE_PAGE = undefined;
    window.COUNTRY_PAGE = undefined;
    window.CITY_PLACES = undefined;
    window.AUTO_START_GPS = undefined;
  }
}

function runSoftNavDataScripts(doc) {
  clearPageGlobalsForSoftNav();
  const dataScriptRe = /window\.(CITY_PAGE|PLACE_PAGE|COUNTRY_PAGE|CITY_PLACES|APP_LANG|WIKI_LANG|SPEECH_LANG|I18N|AUTO_START_GPS)\s*=/;
  doc.querySelectorAll("script:not([src])").forEach((script) => {
    const code = script.textContent || "";
    if (!dataScriptRe.test(code)) return;
    try {
      new Function(code)();
    } catch (e) {
      console.warn("Audio guide soft navigation data failed", e);
    }
  });
}

function targetFromSoftNavCityPage() {
  const p = window.CITY_PAGE;
  if (!p) return null;
  return {
    id: p.id,
    kind: "city",
    name: p.name,
    countryName: p.countryName,
    country: p.countryCode,
    countrySlug: p.countrySlug,
    citySlug: p.citySlug,
    lat: p.lat,
    lon: p.lon,
    wikiTitle: p.wikiTitle,
  };
}

function targetFromSoftNavPlacePage() {
  const p = window.PLACE_PAGE;
  if (!p) return null;
  return {
    id: p.id,
    kind: "place",
    name: p.name,
    countryName: p.countryName,
    country: p.countryCode,
    countrySlug: p.countrySlug,
    cityName: p.cityName,
    citySlug: p.citySlug,
    placeSlug: p.placeSlug,
    lat: p.lat,
    lon: p.lon,
    wikiTitle: p.wikiTitle,
  };
}

function targetFromSoftNavCountryPage() {
  const p = window.COUNTRY_PAGE;
  if (!p) return null;
  return {
    id: p.id || `country_${p.countrySlug || ""}`,
    kind: "country",
    name: p.name || p.countryName,
    countryName: p.countryName || p.name,
    country: p.countryCode || p.countryName || "",
    countrySlug: p.countrySlug,
    citySlug: "__country__",
    lat: p.lat ?? p.centerLat,
    lon: p.lon ?? p.centerLon,
    wikiTitle: p.wikiTitle || p.countryName || p.name,
  };
}

async function loadSoftNavEnhancer(src) {
  if (!src) return;
  const url = new URL(src, window.location.href);
  const path = url.pathname;
  if (/\/static\/app\.js$/i.test(path)) return;
  if (/\/static\/(city_boot|place_boot|country_boot)\.js$/i.test(path)) return;
  if (!/\/static\/(city_map|country)\.js$/i.test(path)) return;

  await new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = url.href;
    s.async = false;
    s.onload = resolve;
    s.onerror = resolve;
    document.body.appendChild(s);
  });
}

async function hydrateSoftNavigatedPage(doc, targetUrl) {
  refreshEls();
  bindPageControls();
  initMap();
  ensurePlayer();
  syncVoiceButtons();
  renderPlayerProgress();
  setPlayerVisible(shouldShowPlayerDock());

  const keepPlayback = hasLivePlaybackForNavigation();
  const cityTarget = targetFromSoftNavCityPage();
  const placeTarget = targetFromSoftNavPlacePage();
  const countryTarget = targetFromSoftNavCountryPage();

  if (cityTarget && typeof onSelectCity === "function") {
    await onSelectCity(cityTarget, {
      scroll: false,
      warm: false,
      keepPlayback,
      preservePersistedState: true,
      autoPlayAfterLoad: false,
    });
  } else if (placeTarget && typeof onSelectCity === "function") {
    await onSelectCity(placeTarget, {
      scroll: false,
      warm: false,
      keepPlayback,
      preservePersistedState: true,
      autoPlayAfterLoad: false,
    });
  } else if (countryTarget && typeof onSelectCity === "function") {
    await onSelectCity(countryTarget, {
      scroll: false,
      warm: false,
      keepPlayback,
      preservePersistedState: true,
      autoPlayAfterLoad: false,
    });
  }

  const scriptPromises = [];
  doc.querySelectorAll("script[src]").forEach((script) => {
    scriptPromises.push(loadSoftNavEnhancer(script.getAttribute("src")));
  });
  await Promise.all(scriptPromises);

  if (targetUrl.hash) {
    const id = targetUrl.hash.slice(1);
    const el = id ? document.getElementById(id) : null;
    if (el) setTimeout(() => el.scrollIntoView({ block: "start" }), 40);
  } else {
    try { window.scrollTo({ top: 0, behavior: "instant" }); } catch { window.scrollTo(0, 0); }
  }
}

async function replaceDocumentForSoftNav(doc, targetUrl) {
  const nextMain = doc.querySelector("main.main");
  const currentMain = document.querySelector("main.main");
  if (!nextMain || !currentMain) throw new Error("Soft navigation target has no main content.");

  destroyMainMap();
  runSoftNavDataScripts(doc);

  document.title = doc.title || document.title;
  if (doc.documentElement?.lang) document.documentElement.lang = doc.documentElement.lang;

  const shouldKeepPlayerClass = shouldShowPlayerDock();
  document.body.className = doc.body?.className || "";
  if (shouldKeepPlayerClass) document.body.classList.add("BodyHasPlayer");

  currentMain.replaceWith(nextMain);

  const nextPrefooter = doc.querySelector(".ct-prefooter");
  const currentPrefooter = document.querySelector(".ct-prefooter");
  if (nextPrefooter && currentPrefooter) currentPrefooter.replaceWith(nextPrefooter);

  const nextFooter = doc.querySelector("footer.ct-footer");
  const currentFooter = document.querySelector("footer.ct-footer");
  if (nextFooter && currentFooter) currentFooter.replaceWith(nextFooter);

  await hydrateSoftNavigatedPage(doc, targetUrl);
}

async function softNavigateTo(href, opts) {
  const options = (opts && typeof opts === "object") ? opts : {};
  const targetUrl = new URL(href, window.location.href);
  if (softNavInFlight) {
    try { softNavInFlight.abort(); } catch {}
  }
  const controller = new AbortController();
  softNavInFlight = controller;

  try {
    persistPlaybackState(true);
    setStatus(tr("loading_page", "Loading guide…"));
    const res = await fetch(targetUrl.href, {
      credentials: "same-origin",
      signal: controller.signal,
      headers: { "X-Requested-With": "AudioGuideSoftNavigation" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    await replaceDocumentForSoftNav(doc, targetUrl);
    if (options.push !== false) {
      history.pushState({ agSoftNav: true }, "", targetUrl.href);
    }
    setPlayerVisible(shouldShowPlayerDock());
  } catch (e) {
    if (e?.name === "AbortError") return;
    window.location.href = targetUrl.href;
  } finally {
    if (softNavInFlight === controller) softNavInFlight = null;
  }
}

function installSoftNavigation() {
  if (softNavInstalled) return;
  softNavInstalled = true;
  document.addEventListener("click", (ev) => {
    const anchor = ev.target?.closest?.("a[href]");
    if (!isSoftNavigableLink(anchor, ev)) return;
    ev.preventDefault();
    softNavigateTo(anchor.href).catch(() => {
      window.location.href = anchor.href;
    });
  }, true);

  window.addEventListener("popstate", () => {
    if (!hasLivePlaybackForNavigation()) return;
    softNavigateTo(window.location.href, { push: false }).catch(() => {
      window.location.reload();
    });
  });
}

// ======================= Persist playback on refresh / pagehide =======================
function persistOnUnload() {
  try { persistPlaybackState(true); } catch {}
}
window.addEventListener("beforeunload", persistOnUnload);
window.addEventListener("pagehide", persistOnUnload);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") persistOnUnload();
});

// ======================= Boot =======================
(function boot() {
  refreshEls();
  initMap();
  ensurePlayer();
  bindPageControls();
  installSoftNavigation();
  renderPlayerProgress();
  syncVoiceButtons();
  if (!document.body?.classList?.contains("PageLanding")) {
    tryLoadAccountContinueRequest().then((handled) => {
      if (!handled) tryRestorePersistedPlayback();
    }).catch(() => {
      tryRestorePersistedPlayback();
    });
  } else {
    hidePlayerDock();
  }

  if (!els.status) return;
  setPlayerLoading(false);
  setStatus(tr("status_ready", 'Ready. Tap “Enable GPS”.'));

  // Landing: show nearby list immediately (fallback by current map center)
  if (document.body && document.body.classList.contains("PageLanding")) {
    setTimeout(async () => {
      if (watchId != null) return;
      try {
        const center = map && typeof map.getCenter === "function" ? map.getCenter() : null;
        const lat = Number(center && center.lat);
        const lon = Number(center && center.lng);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        lastGps = { lat, lon, accuracy: 40 };
        await updateNearbyNow();
        lastNearbyFetch = { ts: Date.now(), lat, lon };
      } catch {}
    }, 220);
  }

  // Landing requirement: prompt GPS immediately on entry (best-effort).
  if (window.AUTO_START_GPS && typeof startGeolocation === "function") {
    setTimeout(() => {
      if (watchId != null) return;
      try { startGeolocation(); } catch {}
    }, 650);
  }
})();

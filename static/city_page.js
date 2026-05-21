// ------------------ Helpers ------------------
const $ = (id) => document.getElementById(id);

function tr(key, fallback) {
  return String((window.I18N && window.I18N[key]) || fallback || key || "");
}

function canSpeak() {
  return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
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

// Remove (...) deeply
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

  text = text.replace(/[\u2010\u2011\u2012\u2013\u2014\u2212]/g, "-"); // hyphens
  text = text.replace(/\[[^\]]*]/g, ""); // citations
  text = stripParenthesesDeep(text); // parentheses
  text = text.replace(/\b([A-Za-zÀ-ÿ'-]+)(\s+\1\b)+/gi, "$1"); // dup words
  text = text.replace(/\s{2,}/g, " ").trim();
  return text;
}

function countWords(text) {
  return String(text || "").trim().split(/\s+/).filter(Boolean).length;
}

function clamp(n, a, b) {
  return Math.max(a, Math.min(b, n));
}

// ------------------ Elements ------------------
const els = {
  status: $("status"),
  mapBox: $("mapCity"),
  sections: $("sections"),
  wikiSource: $("wikiSource"),

  btnLoadWiki: $("btnLoadWiki"),
  btnStopSpeech: $("btnStopSpeech"),

  sticky: $("stickyPlayer"),
  plTitle: $("plTitle"),
  plMeta: $("plMeta"),
  plPlayPause: $("plPlayPause"),
  plStop: $("plStop"),
  plPlayAll: $("plPlayAll"),
  plProgressText: $("plProgressText"),
  plProgress: $("plProgress"),
};

// ------------------ State ------------------
const CITY = window.__CITY__;

let map = null;
let cityMarker = null;

let article = null; // {title,url,sections:[{title,text,words}]}
let activeSectionIdx = -1;

let mode = "idle"; // idle|section|all
let queue = []; // array of {title,text,words}
let qIndex = 0;

let utter = null;
let isPaused = false;

// progress state
let totalWords = 0;
let spokenWords = 0;
let progressTimer = null;

// for boundary fallback
let estTotalMs = 0;
let startMs = 0;

// ------------------ UI helpers ------------------
function setStatus(t) {
  if (els.status) els.status.textContent = t;
}

function showPlayer(show) {
  if (!els.sticky) return;
  els.sticky.hidden = !show;
  // keep content visible above player
  document.body.style.paddingBottom = show ? "110px" : "0px";
}

function setPlayerTitle(main, meta) {
  if (els.plTitle) els.plTitle.textContent = main || tr("audio_ready", "Ready");
  if (els.plMeta) els.plMeta.textContent = meta || `${CITY.name}, ${CITY.country}`;
}

function setControls({ playPauseEnabled, stopEnabled, playAllEnabled }) {
  if (els.plPlayPause) els.plPlayPause.disabled = !playPauseEnabled;
  if (els.plStop) els.plStop.disabled = !stopEnabled;
  if (els.plPlayAll) els.plPlayAll.disabled = !playAllEnabled;
  if (els.btnStopSpeech) els.btnStopSpeech.disabled = !stopEnabled;
}

function setPlayPauseIcon() {
  if (!els.plPlayPause) return;
  els.plPlayPause.textContent = isPaused ? "▶" : "⏸";
}

function updateProgressUI() {
  const pct = totalWords ? Math.floor((spokenWords / totalWords) * 100) : 0;
  const safePct = clamp(pct, 0, 100);

  if (els.plProgressText) {
    els.plProgressText.textContent = `${safePct}% (${spokenWords}/${totalWords} words)`;
  }
  if (els.plProgress) {
    els.plProgress.value = String(clamp(Math.floor((safePct / 100) * 1000), 0, 1000));
  }
}

function clearActiveHighlights() {
  const nodes = els.sections ? Array.from(els.sections.querySelectorAll(".AccItem")) : [];
  for (const n of nodes) n.classList.remove("Active");
}

function setActiveHighlight(idx) {
  clearActiveHighlights();
  if (!els.sections) return;
  const node = els.sections.querySelector(`.AccItem[data-idx="${idx}"]`);
  if (node) node.classList.add("Active");
}

// ------------------ Map ------------------
function initMap() {
  if (!window.L || !els.mapBox) return;

  map = L.map("mapCity").setView([CITY.lat, CITY.lon], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  cityMarker = L.marker([CITY.lat, CITY.lon]).addTo(map).bindPopup(`${CITY.name}, ${CITY.country}`);
  cityMarker.on("click", () => map.setView([CITY.lat, CITY.lon], 12));

  setTimeout(() => { try { map.invalidateSize(true); } catch {} }, 250);
  window.addEventListener("resize", () => setTimeout(() => { try { map.invalidateSize(true); } catch {} }, 180));
}

// ------------------ Wikipedia EN fetch ------------------
function looksLikeNonCityTitle(title) {
  const t = (title || "").toLowerCase();
  if (/\b(open|atp|wta|tournament|championship|cup|season|final|201\d|202\d|19\d\d)\b/.test(t)) return true;
  if (/\b(football|basketball|tennis|race|grand prix|album|song|film)\b/.test(t)) return true;
  return false;
}

async function fetchSummaryEnByTitle(title) {
  const url = `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeWikiTitle(title)}`;
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`EN summary HTTP ${res.status}`);
  const data = await res.json();
  if ((data?.type || "").toLowerCase() === "disambiguation") throw new Error("disambiguation");
  return data;
}

async function findBestCityTitleEn(city) {
  const name = city.wikiTitle || city.name;
  const country = city.country || "";

  const queries = [
    `"${name}" city`,
    `"${name}" municipality`,
    `${name} ${country} city`,
    `${name} ${country}`,
    `${name}`,
  ];

  const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");

  for (const q of queries) {
    const api =
      `https://en.wikipedia.org/w/api.php?action=query&list=search` +
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
      if (norm(title) === norm(name)) score += 100;

      const lt = title.toLowerCase();
      if (lt.includes("city")) score += 10;
      if (lt.includes("municipality")) score += 10;

      score += Math.max(0, 12 - (r.rank || 12));
      if (!best || score > best.score) best = { title, score };
    }

    if (best) return best.title;
  }

  return null;
}

async function fetchFullArticleHtmlEn(title) {
  const api =
    `https://en.wikipedia.org/w/api.php?action=parse&format=json&origin=*` +
    `&prop=text&formatversion=2&page=${encodeURIComponent(title)}`;

  const res = await fetch(api);
  if (!res.ok) throw new Error(`parse HTTP ${res.status}`);
  const data = await res.json();
  const html = data?.parse?.text;
  if (!html) throw new Error("no parse.text");
  return html;
}

function htmlToH2Sections(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll(
    "table, .infobox, .navbox, .metadata, .hatnote, sup, style, script, .mw-editsection"
  ).forEach((el) => el.remove());

  const content = doc.querySelector(".mw-parser-output") || doc.body;
  content.querySelectorAll("#toc, .toc, .reflist, ol.references, div.refbegin").forEach(el => el.remove());

  const SKIP_H2 = new Set([
    "contents", "see also", "notes", "references", "further reading", "external links", "bibliography", "citations"
  ]);

  const sections = [];
  let currentTitle = "Introduction";
  let currentSkip = false;
  let parts = [];

  const flush = () => {
    if (currentSkip) { parts = []; return; }
    const joined = parts.join("\n").trim();
    const cleaned = cleanPlainText(joined);
    if (cleaned) {
      sections.push({ title: currentTitle, text: cleaned, words: countWords(cleaned) });
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

async function loadWikipediaForCity() {
  const cacheKey = `wiki_city_en_${CITY.slug}`;
  const cached = localStorage.getItem(cacheKey);
  if (cached) return JSON.parse(cached);

  let title = CITY.wikiTitle || CITY.name;

  // direct
  try {
    const sum = await fetchSummaryEnByTitle(title);
    title = sum.title || title;

    const html = await fetchFullArticleHtmlEn(title);
    const sections = htmlToH2Sections(html);

    const payload = {
      title,
      url: sum.content_urls?.desktop?.page || `https://en.wikipedia.org/wiki/${encodeWikiTitle(title)}`,
      sections,
    };
    localStorage.setItem(cacheKey, JSON.stringify(payload));
    return payload;
  } catch {
    // search
  }

  const best = await findBestCityTitleEn(CITY);
  if (!best) throw new Error("No suitable guide page found");

  const sum2 = await fetchSummaryEnByTitle(best);
  const finalTitle = sum2.title || best;

  const html2 = await fetchFullArticleHtmlEn(finalTitle);
  const sections2 = htmlToH2Sections(html2);

  const payload2 = {
    title: finalTitle,
    url: sum2.content_urls?.desktop?.page || `https://en.wikipedia.org/wiki/${encodeWikiTitle(finalTitle)}`,
    sections: sections2,
  };

  localStorage.setItem(cacheKey, JSON.stringify(payload2));
  return payload2;
}

// ------------------ Render accordion ------------------
function renderAccordion(sections) {
  els.sections.innerHTML = "";

  const frag = document.createDocumentFragment();

  sections.forEach((sec, idx) => {
    const item = document.createElement("div");
    item.className = "AccItem";
    item.dataset.idx = String(idx);

    const head = document.createElement("div");
    head.className = "AccHead";
    head.innerHTML = `
      <div>
        <div class="AccTitle">${escapeHtml(sec.title)}</div>
        <div class="Muted Small"><span class="Badge">${sec.words} words</span></div>
      </div>
      <div class="AccBtns">
        <button class="IconBtn" type="button" data-act="toggle" title="Play/Pause">▶</button>
        <button class="IconBtn" type="button" data-act="stop" title="Stop">⏹</button>
      </div>
    `;

    const body = document.createElement("div");
    body.className = "AccBody";
    body.textContent = sec.text; // optional display (SEO copy is yours anyway)

    // head click toggles open
    head.addEventListener("dblclick", () => {
      item.classList.toggle("Open");
    });

    // buttons
    const btnToggle = head.querySelector('[data-act="toggle"]');
    const btnStop = head.querySelector('[data-act="stop"]');

    btnToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      onSectionToggle(idx);
    });
    btnStop.addEventListener("click", (e) => {
      e.stopPropagation();
      if (activeSectionIdx === idx) stopAll();
      else {
        // stop any current and keep selection
        stopAll();
        setActiveHighlight(idx);
        activeSectionIdx = idx;
        setPlayerTitle(`Section: ${sections[idx].title}`, `${CITY.name}, ${CITY.country}`);
        showPlayer(true);
      }
    });

    item.appendChild(head);
    item.appendChild(body);
    frag.appendChild(item);
  });

  els.sections.appendChild(frag);
}

// ------------------ Speech engine ------------------
function stopSpeechHard() {
  if (!canSpeak()) return;
  try { window.speechSynthesis.cancel(); } catch {}
}

function stopAll() {
  stopSpeechHard();
  utter = null;
  isPaused = false;
  mode = "idle";
  queue = [];
  qIndex = 0;
  spokenWords = 0;
  totalWords = 0;
  estTotalMs = 0;
  startMs = 0;
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = null;

  setPlayPauseIcon();
  updateProgressUI();
  setControls({ playPauseEnabled: true, stopEnabled: false, playAllEnabled: !!article });
  // keep highlight (user asked not to lose)
  setStatus("Stopped.");
}

function pauseOrResume() {
  if (!canSpeak()) return;

  if (!utter) return;

  if (!isPaused) {
    try { window.speechSynthesis.pause(); } catch {}
    isPaused = true;
    setStatus("Paused.");
  } else {
    try { window.speechSynthesis.resume(); } catch {}
    isPaused = false;
    setStatus("Playing…");
  }
  setPlayPauseIcon();
}

function startQueue(items, titleForPlayer) {
  if (!canSpeak()) {
    alert("Web Speech API not available. Try Chrome/Edge.");
    return;
  }

  stopSpeechHard();
  utter = null;
  isPaused = false;

  queue = items.map(x => ({ title: x.title, text: x.text, words: x.words }));
  qIndex = 0;

  totalWords = queue.reduce((s, it) => s + (it.words || 0), 0);
  spokenWords = 0;

  // estimate time fallback: 160 wpm ~ 2.666 w/s
  const wps = 160 / 60;
  estTotalMs = totalWords ? Math.round((totalWords / wps) * 1000) : 0;
  startMs = Date.now();

  setPlayerTitle(titleForPlayer, `${CITY.name}, ${CITY.country}`);
  showPlayer(true);

  setControls({ playPauseEnabled: true, stopEnabled: true, playAllEnabled: !!article });
  setPlayPauseIcon();
  updateProgressUI();

  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(() => {
    if (!utter || isPaused) return;
    // fallback: if boundary not available, animate by elapsed time
    if (!totalWords) return;

    // only apply fallback when spokenWords not moving
    // (we still keep it gentle)
    const elapsed = Date.now() - startMs;
    if (elapsed > 0 && spokenWords < totalWords) {
      const approx = Math.floor((elapsed / Math.max(1, estTotalMs)) * totalWords);
      spokenWords = Math.max(spokenWords, clamp(approx, 0, totalWords));
      updateProgressUI();
    }
  }, 450);

  speakNext();
}

function speakNext() {
  if (!canSpeak()) return;

  if (qIndex >= queue.length) {
    // finished
    spokenWords = totalWords;
    updateProgressUI();
    if (progressTimer) clearInterval(progressTimer);
    progressTimer = null;

    utter = null;
    isPaused = false;

    setControls({ playPauseEnabled: true, stopEnabled: false, playAllEnabled: !!article });
    setPlayPauseIcon();
    setStatus("Finished.");
    return;
  }

  const item = queue[qIndex];
  const chunkText = item.text;

  // update title to show which block is playing
  setPlayerTitle(`Playing: ${item.title}`, `${CITY.name}, ${CITY.country}`);

  // highlight current section when possible
  if (mode === "section") {
    // already highlighted
  } else {
    // all mode: highlight the section as it plays
    const idx = article.sections.findIndex(s => s.title === item.title);
    if (idx >= 0) setActiveHighlight(idx);
  }

  utter = new SpeechSynthesisUtterance(chunkText);
  utter.lang = "en-US";
  utter.rate = 1.0;
  utter.pitch = 1.0;

  // word boundary (works in many Chromium builds)
  utter.onboundary = (ev) => {
    try {
      if (ev.name === "word" || ev.charIndex >= 0) {
        // estimate words spoken from substring
        const upto = chunkText.slice(0, ev.charIndex || 0);
        const w = countWords(upto);
        // spokenWords base = sum of previous chunks + w
        const prev = queue.slice(0, qIndex).reduce((s, it) => s + (it.words || 0), 0);
        spokenWords = clamp(prev + w, 0, totalWords);
        updateProgressUI();
      }
    } catch {}
  };

  utter.onend = () => {
    // when a chunk ends, add full chunk words
    const prev = queue.slice(0, qIndex).reduce((s, it) => s + (it.words || 0), 0);
    spokenWords = clamp(prev + (queue[qIndex].words || 0), 0, totalWords);
    updateProgressUI();

    qIndex += 1;
    speakNext();
  };

  utter.onerror = () => {
    qIndex += 1;
    speakNext();
  };

  try {
    window.speechSynthesis.speak(utter);
    isPaused = false;
    setPlayPauseIcon();
    setStatus("Playing…");
  } catch {
    qIndex += 1;
    speakNext();
  }
}

// ------------------ Section controls ------------------
function onSectionToggle(idx) {
  if (!article) return;

  // If same active section:
  if (activeSectionIdx === idx && mode === "section" && utter) {
    pauseOrResume();
    // update icon in row
    syncRowIcons();
    return;
  }

  // Switch to new section: stop current and play selected from start
  stopAll();

  activeSectionIdx = idx;
  mode = "section";
  setActiveHighlight(idx);

  const sec = article.sections[idx];
  startQueue([{ title: sec.title, text: sec.text, words: sec.words }], `Section: ${sec.title}`);
  syncRowIcons();
}

function playAll() {
  if (!article) return;
  stopAll();
  mode = "all";
  activeSectionIdx = -1;
  clearActiveHighlights();
  startQueue(article.sections.map(s => ({ title: s.title, text: s.text, words: s.words })), `All sections: ${article.title}`);
  syncRowIcons();
}

function syncRowIcons() {
  // Update per-row icons: active row shows pause when playing, play when paused, others show play.
  if (!els.sections) return;

  const items = Array.from(els.sections.querySelectorAll(".AccItem"));
  for (const it of items) {
    const idx = Number(it.dataset.idx);
    const btn = it.querySelector('[data-act="toggle"]');
    if (!btn) continue;

    if (mode === "section" && idx === activeSectionIdx && utter) {
      btn.textContent = isPaused ? "▶" : "⏸";
    } else {
      btn.textContent = "▶";
    }
  }

  setPlayPauseIcon();
}

// ------------------ Wire up ------------------
async function onLoadWiki() {
  setStatus("Loading guide content…");
  els.btnLoadWiki.disabled = true;

  try {
    article = await loadWikipediaForCity();
    setStatus(`Loaded: ${article.title}`);
    els.wikiSource.textContent = "";

    renderAccordion(article.sections);
    showPlayer(true);

    setPlayerTitle(tr("audio_ready", "Ready"), `${CITY.name}, ${CITY.country}`);
    totalWords = 0;
    spokenWords = 0;
    updateProgressUI();

    setControls({ playPauseEnabled: true, stopEnabled: false, playAllEnabled: true });
  } catch (e) {
    setStatus(`Failed to load guide content: ${e?.message || e}`);
    els.btnLoadWiki.disabled = false;
    setControls({ playPauseEnabled: false, stopEnabled: false, playAllEnabled: false });
  } finally {
    els.btnLoadWiki.disabled = false;
  }
}

function initPlayerUI() {
  showPlayer(true);
  setPlayerTitle(tr("audio_ready", "Ready"), `${CITY.name}, ${CITY.country}`);
  updateProgressUI();
  setControls({ playPauseEnabled: true, stopEnabled: false, playAllEnabled: false });
  setPlayPauseIcon();

  // progress is read-only (no seek)
  els.plProgress.addEventListener("input", () => {
    els.plProgress.value = String(clamp(Number(els.plProgress.value || 0), 0, 1000));
    // snap back on next update
    updateProgressUI();
  });

  els.plPlayPause.addEventListener("click", () => {
    if (!canSpeak()) return;

    if (!utter) {
      // If nothing playing: if a section selected -> play it; else if article -> play all
      if (article && activeSectionIdx >= 0) {
        onSectionToggle(activeSectionIdx);
      } else if (article) {
        playAll();
      } else {
        setStatus("Load guide content first.");
      }
      return;
    }
    pauseOrResume();
    syncRowIcons();
  });

  els.plStop.addEventListener("click", () => {
    stopAll();
    syncRowIcons();
  });

  els.plPlayAll.addEventListener("click", () => {
    playAll();
  });

  els.btnStopSpeech.addEventListener("click", () => {
    stopAll();
    syncRowIcons();
  });
}

// stop speech on refresh/pagehide
function stopOnUnload() {
  try { stopSpeechHard(); } catch {}
}

(function boot() {
  initMap();
  initPlayerUI();

  if (!canSpeak()) setStatus("⚠ Web Speech API not available. Try Chrome/Edge.");

  els.btnLoadWiki.addEventListener("click", onLoadWiki);

  window.addEventListener("beforeunload", stopOnUnload);
  window.addEventListener("pagehide", stopOnUnload);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") stopOnUnload();
  });

  // auto-load wiki for convenience (optional):
  // onLoadWiki();
})();

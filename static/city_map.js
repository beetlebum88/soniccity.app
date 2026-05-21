(function () {
  "use strict";

  const page = window.CITY_PAGE || null;
  const rawPlaces = Array.isArray(window.CITY_PLACES) ? window.CITY_PLACES : [];
  if (!page || !rawPlaces.length) return;

  const $ = (id) => document.getElementById(id);
  const overlay = $("cityMapOverlay");
  const mapEl = $("cityFullMap");
  if (!overlay || !mapEl || !window.L) return;

  const lang = String(window.APP_LANG || "en").toLowerCase();
  const routePrefix = lang === "en" ? "/" : `/${lang}/`;
  const tr = (key, fallback) => (window.I18N && window.I18N[key]) || fallback || key;
  const placeRows = new Map();
  document.querySelectorAll("[data-place-row]").forEach((row) => {
    const slug = String(row.getAttribute("data-place-row") || "");
    if (!slug) return;
    placeRows.set(slug, {
      category: row.getAttribute("data-place-category") || "landmark",
    });
  });

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function cssEscape(value) {
    const raw = String(value || "");
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(raw);
    return raw.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function normalizeCategory(value) {
    return String(value || "Landmark")
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (m) => m.toUpperCase());
  }

  function placeUrl(place) {
    if (place && place.url) return String(place.url);
    if (window.AG_PLACE_URL) {
      return window.AG_PLACE_URL({
        lang,
        countrySlug: page.countrySlug,
        citySlug: page.citySlug,
      }, place.slug);
    }
    return `${routePrefix}${page.countrySlug}/${page.citySlug}/${place.slug}`;
  }

  function placeImg(place) {
    if (window.AG_PLACE_IMG_URL) {
      return window.AG_PLACE_IMG_URL({
        lang: "en",
        countrySlug: page.countrySlug,
        citySlug: page.citySlug,
      }, place.slug);
    }
    return `/media/place/en/${page.countrySlug}/${page.citySlug}/${place.slug}`;
  }

  const places = rawPlaces
    .filter((p) => p && p.slug && p.name)
    .map((p) => {
      const row = placeRows.get(String(p.slug));
      return {
        ...p,
        slug: String(p.slug),
        name: String(p.name),
        category: normalizeCategory(p.category || row?.category || "Landmark"),
        url: placeUrl(p),
        image: placeImg(p),
      };
    });

  let fullMap = null;
  let markersLayer = null;
  let routeLayer = null;
  let userMarker = null;
  let userCircle = null;
  let userPosition = null;
  let selectedSlug = null;
  let routeStatus = "idle";
  let sheetState = "half";
  let mapPlayerSyncTimer = null;
  let currentPlayingPlaceSlug = null;
  let latestPlayerState = window.AG_PLAYER_STATE || null;
  let dragStartY = null;
  const markerBySlug = new Map();
  const geoBySlug = new Map();
  const missingGeoSlugs = new Set();

  async function resolveGeo(place) {
    if (geoBySlug.has(place.slug)) return geoBySlug.get(place.slug);
    if (missingGeoSlugs.has(place.slug)) return null;
    const inlineLat = Number(place.lat ?? place.latitude);
    const inlineLon = Number(place.lon ?? place.lng ?? place.longitude);
    if (Number.isFinite(inlineLat) && Number.isFinite(inlineLon)) {
      const geo = { lat: inlineLat, lon: inlineLon, title: place.name || place.slug, source: "inline" };
      geoBySlug.set(place.slug, geo);
      markCoordinateStatus(place.slug, true);
      return geo;
    }
    let geo = null;
    if (window.AG_FETCH_PLACE_GEO) {
      geo = await window.AG_FETCH_PLACE_GEO(page.countrySlug, page.citySlug, place.slug);
    }
    if (geo && Number.isFinite(Number(geo.lat)) && Number.isFinite(Number(geo.lon))) {
      geo = { ...geo, lat: Number(geo.lat), lon: Number(geo.lon) };
      geoBySlug.set(place.slug, geo);
      markCoordinateStatus(place.slug, true);
      return geo;
    }
    missingGeoSlugs.add(place.slug);
    markCoordinateStatus(place.slug, false);
    return geo;
  }

  function markCoordinateStatus(slug, hasCoordinates) {
    const safeSlug = cssEscape(slug);
    document.querySelectorAll(`[data-place-row="${safeSlug}"], [data-place-slug="${safeSlug}"], [data-side-place-slug="${safeSlug}"]`).forEach((el) => {
      el.classList.toggle("has-no-coordinates", !hasCoordinates);
      let badge = el.querySelector(".ag-noCoordsBadge");
      if (!hasCoordinates && !badge) {
        badge = document.createElement("span");
        badge.className = "ag-noCoordsBadge";
        badge.textContent = "No coordinates";
        const target = el.querySelector(".ux-cardMeta, small, .ux-miniPlaceActions") || el;
        target.appendChild(badge);
      }
      if (hasCoordinates && badge) badge.remove();
    });
    document.querySelectorAll(`[data-place-route="${safeSlug}"]`).forEach((btn) => {
      btn.disabled = !hasCoordinates;
      btn.setAttribute("aria-disabled", hasCoordinates ? "false" : "true");
      btn.title = hasCoordinates ? "Build route" : "No coordinates for this place";
    });
  }

  function haversineKm(a, b, c, d) {
    const R = 6371;
    const toRad = (x) => (Number(x) * Math.PI) / 180;
    const dLat = toRad(c - a);
    const dLon = toRad(d - b);
    const lat1 = toRad(a);
    const lat2 = toRad(c);
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function formatDistance(km) {
    if (!Number.isFinite(km)) return "Distance available with GPS";
    if (km < 1) return `${Math.round(km * 1000)} m`;
    return `${km.toFixed(km < 10 ? 1 : 0)} km`;
  }

  function formatWalk(km) {
    if (!Number.isFinite(km)) return "";
    return `${Math.max(1, Math.round((km / 4.8) * 60))} min walk`;
  }

  function formatMeters(meters) {
    const m = Number(meters);
    if (!Number.isFinite(m)) return "";
    if (m < 1000) return `${Math.max(1, Math.round(m))} m`;
    return `${(m / 1000).toFixed(m < 10000 ? 1 : 0)} km`;
  }

  function formatSeconds(seconds) {
    const s = Number(seconds);
    if (!Number.isFinite(s)) return "";
    const mins = Math.max(1, Math.round(s / 60));
    if (mins < 60) return `${mins} min walk`;
    const h = Math.floor(mins / 60);
    const rest = mins % 60;
    return rest ? `${h} h ${rest} min` : `${h} h`;
  }

  function setRouteInfo(text, mode) {
    const el = $("cityMapRouteInfo");
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
    el.dataset.state = mode || routeStatus;
    const clear = $("cityMapClearRoute");
    if (clear) clear.hidden = routeStatus !== "ready";
  }

  function setRouteLoading(active) {
    document.querySelectorAll("[data-place-route], #cityMapRoutePlace").forEach((btn) => {
      if (!btn) return;
      btn.classList.toggle("is-loading", !!active);
      if (active) btn.setAttribute("aria-busy", "true");
      else btn.removeAttribute("aria-busy");
    });
  }

  function isMobileMap() {
    return window.matchMedia && window.matchMedia("(max-width: 767.98px)").matches;
  }

  function setSheetState(state) {
    const allowed = new Set(["collapsed", "half", "expanded"]);
    sheetState = allowed.has(state) ? state : "half";
    overlay.dataset.sheetState = sheetState;
    setTimeout(() => {
      try { fullMap?.invalidateSize?.(true); } catch {}
    }, 140);
  }

  function nextSheetState() {
    if (sheetState === "collapsed") return "half";
    if (sheetState === "half") return "expanded";
    return "collapsed";
  }

  function isGlobalPlaying() {
    if (latestPlayerState && typeof latestPlayerState === "object") {
      return !!latestPlayerState.isPlaying;
    }
    const btn = $("plToggle");
    return /pause/i.test(String(btn?.title || ""));
  }

  function syncMapMiniPlayer() {
    const title = String($("plTitle")?.textContent || "").trim();
    const meta = String($("plMeta")?.textContent || "").trim();
    const fill = $("plFill")?.style?.width || "0%";
    const nowTitle = $("cityMapNowTitle");
    const nowMeta = $("cityMapNowMeta");
    const miniFill = $("cityMapMiniProgress");
    const toggle = $("cityMapPlayerToggle");
    const hasTrack = !!title && title !== "—";
    if (nowTitle) nowTitle.textContent = hasTrack ? title : tr("player_no_track_label", "Choose an audio story");
    if (nowMeta) nowMeta.textContent = hasTrack ? (meta || tr("audio_guide_generic", "Audio guide")) : tr("map_select_place_tap", "Select a place and tap Play.");
    if (miniFill) miniFill.style.width = hasTrack ? fill : "0%";
    if (toggle) {
      toggle.textContent = hasTrack && isGlobalPlaying() ? tr("pause", "Pause") : tr("common_play", "Play");
      toggle.disabled = !hasTrack;
    }
    updatePlayButtonLabels();
  }

  function startMapPlayerSync() {
    stopMapPlayerSync();
    syncMapMiniPlayer();
    mapPlayerSyncTimer = window.setInterval(syncMapMiniPlayer, 500);
  }

  function stopMapPlayerSync() {
    if (mapPlayerSyncTimer) window.clearInterval(mapPlayerSyncTimer);
    mapPlayerSyncTimer = null;
  }

  function updatePlayButtonLabels() {
    const samePlacePlaying = !!selectedSlug && currentPlayingPlaceSlug === selectedSlug && isGlobalPlaying();
    const label = samePlacePlaying ? tr("pause", "Pause") : tr("listen_all", "Play audio");
    const selectedBtn = $("cityMapPlayPlace");
    if (selectedBtn) selectedBtn.textContent = label;
    document.querySelectorAll("[data-place-play]").forEach((btn) => {
      if (String(btn.getAttribute("data-place-play") || "") !== String(selectedSlug || "")) return;
      btn.textContent = samePlacePlaying ? tr("pause", "Pause") : (btn.classList.contains("ag-mapPlacePlay") ? tr("common_play", "Play") : tr("listen_all", "Play audio"));
    });
  }

  function initMap() {
    if (fullMap) return;
    fullMap = L.map(mapEl, { zoomControl: true }).setView([Number(page.lat) || 39.4699, Number(page.lon) || -0.3763], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(fullMap);
    markersLayer = L.layerGroup().addTo(fullMap);
    routeLayer = L.layerGroup().addTo(fullMap);
    renderMarkers();
  }

  function markerIcon(place, active) {
    const category = normalizeCategory(place.category || "Landmark");
    const letter = (category.trim()[0] || "P").toUpperCase();
    return L.divIcon({
      className: "",
      iconSize: active ? [46, 46] : [38, 38],
      iconAnchor: active ? [23, 23] : [19, 19],
      html: `
        <button class="ag-placeMarker ${active ? "is-active" : ""}" type="button" aria-label="${escapeHtml(place.name)} marker">
          <span class="ag-placeMarkerGlyph" aria-hidden="true">${escapeHtml(letter)}</span>
        </button>
      `,
    });
  }

  async function renderMarkers() {
    if (!markersLayer) return;
    markersLayer.clearLayers();
    markerBySlug.clear();
    const points = [];
    for (const place of places) {
      const geo = await resolveGeo(place);
      if (!geo) continue;
      const marker = L.marker([geo.lat, geo.lon], {
        icon: markerIcon(place, place.slug === selectedSlug),
        keyboard: true,
        title: place.name,
        alt: place.name,
      }).addTo(markersLayer);
      marker.bindTooltip(escapeHtml(place.name), {
        direction: "top",
        offset: [0, -10],
        opacity: 0.95,
      });
      marker.on("click", () => selectPlace(place.slug, { pan: false, fromMarker: true }));
      markerBySlug.set(place.slug, marker);
      points.push([geo.lat, geo.lon]);
    }
    const cityLat = Number(page.lat);
    const cityLon = Number(page.lon);
    if (Number.isFinite(cityLat) && Number.isFinite(cityLon)) points.push([cityLat, cityLon]);
    if (points.length > 1) {
      try { fullMap.fitBounds(points, { padding: [34, 34], maxZoom: 14 }); } catch {}
    }
  }

  function updateMarkerStyles() {
    for (const [slug, marker] of markerBySlug.entries()) {
      const place = places.find((p) => p.slug === slug);
      const active = slug === selectedSlug || slug === currentPlayingPlaceSlug;
      if (place && typeof marker.setIcon === "function") marker.setIcon(markerIcon(place, active));
      marker.getElement?.()?.classList.toggle("is-active", active);
    }
  }

  function updateListActive() {
    document.querySelectorAll("[data-place-row]").forEach((row) => {
      const active = row.getAttribute("data-place-row") === selectedSlug;
      row.classList.toggle("is-active", active);
    });
    document.querySelectorAll(".ag-placeCard").forEach((card) => {
      const active = card.getAttribute("data-place-slug") === selectedSlug;
      card.classList.toggle("is-active", active);
    });
    document.querySelectorAll("[data-side-place-slug]").forEach((card) => {
      const active = card.getAttribute("data-side-place-slug") === selectedSlug;
      card.classList.toggle("is-active", active);
    });
  }

  async function selectPlace(slug, opts) {
    const place = places.find((p) => p.slug === slug);
    if (!place) return null;
    const geo = await resolveGeo(place);
    selectedSlug = place.slug;
    window.AG_SET_ACTIVE_PLACE_MARKER?.(selectedSlug);
    updateMarkerStyles();
    updateListActive();

    const card = $("cityMapPlaceCard");
    const empty = $("cityMapEmptyCard");
    const img = $("cityMapPlaceImg");
    const name = $("cityMapPlaceName");
    const category = $("cityMapPlaceCategory");
    const meta = $("cityMapPlaceMeta");
    const open = $("cityMapOpenPlace");
    if (card) card.hidden = false;
    if (empty) empty.hidden = true;
    if (img) {
      img.src = place.image;
      img.alt = place.name;
    }
    if (name) name.textContent = place.name;
    if (category) category.textContent = place.category;
    const distance = userPosition && geo
      ? haversineKm(userPosition.lat, userPosition.lon, geo.lat, geo.lon)
      : NaN;
    if (meta) {
      meta.textContent = [page.name, page.countryName, formatDistance(distance), formatWalk(distance)]
        .filter(Boolean)
        .join(" • ");
    }
    if (open) open.href = place.url;
    if (fullMap && geo && opts?.pan !== false) fullMap.panTo([geo.lat, geo.lon], { animate: true });
    if (isMobileMap() && opts?.fromMarker) setSheetState("collapsed");
    updatePlayButtonLabels();
    window.dispatchEvent(new CustomEvent("ag:place-selected", { detail: { slug: place.slug, place, geo } }));
    return { place, geo };
  }

  function updateUserMarker(position) {
    if (!fullMap || !position) return;
    const ll = [position.lat, position.lon];
    if (!userMarker) {
      userMarker = L.marker(ll).addTo(fullMap).bindTooltip("You are here", {
        direction: "top",
        offset: [0, -12],
        opacity: 0.95,
      });
      userCircle = L.circle(ll, { radius: Math.max(20, Number(position.accuracy) || 25) }).addTo(fullMap);
    } else {
      userMarker.setLatLng(ll);
      userCircle?.setLatLng(ll).setRadius(Math.max(20, Number(position.accuracy) || 25));
    }
  }

  function requestLocation() {
    if (!navigator.geolocation) {
      setRouteInfo("GPS is not available in this browser.", "unavailable");
      return Promise.resolve(null);
    }
    setRouteInfo("Finding your location…", "loading");
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition((pos) => {
        userPosition = {
          lat: Number(pos.coords.latitude),
          lon: Number(pos.coords.longitude),
          accuracy: Number(pos.coords.accuracy) || 30,
        };
        updateUserMarker(userPosition);
        setRouteInfo("", "idle");
        resolve(userPosition);
      }, () => {
        setRouteInfo("Enable GPS to build a route from your location.", "unavailable");
        resolve(null);
      }, {
        enableHighAccuracy: true,
        maximumAge: 15000,
        timeout: 9000,
      });
    });
  }

  function clearRoute() {
    routeLayer?.clearLayers();
    routeStatus = "idle";
    setRouteInfo("", "idle");
    const clear = $("cityMapClearRoute");
    if (clear) clear.hidden = true;
  }

  function csrfHeaders(headers) {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = (window.AG_CSRF_TOKEN || meta?.getAttribute("content") || "").trim();
    const out = Object.assign({}, headers || {});
    if (token) out["X-CSRF-Token"] = token;
    return out;
  }

  async function buildRoute(slug) {
    if (!slug) return;
    const selected = await selectPlace(slug, { pan: false });
    if (!selected?.geo) {
      setRouteInfo("This place has no coordinates yet.", "unavailable");
      return;
    }
    if (isMobileMap()) setSheetState("collapsed");
    if (!userPosition) {
      const pos = await requestLocation();
      if (!pos) return;
    }
    routeStatus = "loading";
    setRouteInfo("Building route…", "loading");
    setRouteLoading(true);
    routeLayer?.clearLayers();
    try {
      const res = await fetch("/api/route", {
        method: "POST",
        headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          mode: "walking",
          from: { lat: userPosition.lat, lng: userPosition.lon },
          to: { lat: selected.geo.lat, lng: selected.geo.lon },
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || data.status !== "ready" || !data.geometry) {
        routeStatus = data?.status || "failed";
        setRouteInfo(data?.error || "Route provider failed.", routeStatus);
        return;
      }
      const accent = getComputedStyle(document.documentElement).getPropertyValue("--nx-cyan").trim() || "#38bdf8";
      const route = L.geoJSON(data.geometry, {
        style: {
          color: accent,
          weight: 6,
          opacity: 0.92,
          lineCap: "round",
          lineJoin: "round",
          className: "ag-routeLine",
        },
      }).addTo(routeLayer);
      try {
        const bounds = route.getBounds();
        bounds.extend([userPosition.lat, userPosition.lon]);
        bounds.extend([selected.geo.lat, selected.geo.lon]);
        fullMap.fitBounds(bounds, { padding: [64, 64], maxZoom: 16 });
      } catch {}
      routeStatus = "ready";
      setRouteInfo(`Route to ${selected.place.name}: ${formatMeters(data.distanceMeters)} • ${formatSeconds(data.durationSeconds)}.`, "ready");
      if (isMobileMap()) setSheetState("half");
    } catch {
      routeStatus = "failed";
      setRouteInfo("Route provider failed.", "failed");
    } finally {
      setRouteLoading(false);
    }
  }

  async function playPlace(slug) {
    const selected = await selectPlace(slug, { pan: true });
    if (!selected?.place) return;
    if (currentPlayingPlaceSlug === slug && window.AG_GLOBAL_PLAYER) {
      window.AG_GLOBAL_PLAYER.togglePlayPause();
      syncMapMiniPlayer();
      return;
    }
    currentPlayingPlaceSlug = slug;
    updateMarkerStyles();
    updateListActive();
    updatePlayButtonLabels();
    window.AG_PLAY_PLACE_GUIDE?.(selected.place, { geo: selected.geo });
    startMapPlayerSync();
  }

  function openOverlay(slug, action) {
    overlay.hidden = false;
    document.body.classList.add("ag-mapOverlayOpen");
    setSheetState(slug ? "collapsed" : "half");
    startMapPlayerSync();
    initMap();
    setTimeout(() => {
      try { fullMap.invalidateSize(true); } catch {}
    }, 80);
    const target = slug || selectedSlug;
    if (target) {
      selectPlace(target, { pan: true }).then(() => {
        if (action === "route") buildRoute(target);
        if (action === "play") playPlace(target);
      });
    }
  }

  function closeOverlay() {
    overlay.hidden = true;
    document.body.classList.remove("ag-mapOverlayOpen");
    stopMapPlayerSync();
  }

  function applyListFilters() {
    const query = String($("cityMapSearch")?.value || "").trim().toLowerCase();
    const activeFilter = document.querySelector(".ag-mapFilters .is-active")?.getAttribute("data-map-filter") || "all";
    document.querySelectorAll("[data-place-row]").forEach((row) => {
      const slug = String(row.getAttribute("data-place-row") || "");
      const place = places.find((p) => p.slug === slug);
      const cat = String(row.getAttribute("data-place-category") || "").toLowerCase();
      const matchesFilter = activeFilter === "all" || cat.includes(activeFilter);
      const matchesSearch = !query || String(place?.name || "").toLowerCase().includes(query);
      row.hidden = !(matchesFilter && matchesSearch);
    });
  }

  function wire() {
    $("btnOpenFullMap")?.addEventListener("click", () => openOverlay());
    $("btnOpenFullMapDock")?.addEventListener("click", () => openOverlay());
    $("btnCloseFullMap")?.addEventListener("click", closeOverlay);
    $("btnUseLocation")?.addEventListener("click", () => {
      openOverlay();
      requestLocation();
    });
    $("btnFullUseLocation")?.addEventListener("click", requestLocation);
    $("btnMapSheetToggle")?.addEventListener("click", () => setSheetState(sheetState === "expanded" ? "half" : "expanded"));
    $("cityMapPlayerToggle")?.addEventListener("click", () => {
      if (window.AG_GLOBAL_PLAYER) window.AG_GLOBAL_PLAYER.togglePlayPause();
      else $("plToggle")?.click();
      setTimeout(syncMapMiniPlayer, 80);
    });
    const handle = $("cityMapSheetHandle");
    if (handle) {
      handle.addEventListener("click", () => setSheetState(nextSheetState()));
      handle.addEventListener("pointerdown", (ev) => {
        dragStartY = ev.clientY;
        try { handle.setPointerCapture(ev.pointerId); } catch {}
      });
      handle.addEventListener("pointerup", (ev) => {
        if (dragStartY == null) return;
        const delta = ev.clientY - dragStartY;
        dragStartY = null;
        if (delta < -28) setSheetState(sheetState === "collapsed" ? "half" : "expanded");
        else if (delta > 28) setSheetState(sheetState === "expanded" ? "half" : "collapsed");
      });
    }
    $("cityMapSearch")?.addEventListener("input", applyListFilters);
    document.querySelectorAll("[data-map-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-map-filter]").forEach((x) => x.classList.remove("is-active"));
        btn.classList.add("is-active");
        applyListFilters();
      });
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !overlay.hidden) closeOverlay();
    });
    document.addEventListener("click", (ev) => {
      const select = ev.target.closest?.("[data-place-select]");
      const play = ev.target.closest?.("[data-place-play]");
      const route = ev.target.closest?.("[data-place-route]");
      if (select) {
        ev.preventDefault();
        openOverlay(select.getAttribute("data-place-select"));
        return;
      }
      if (play) {
        ev.preventDefault();
        const slug = play.getAttribute("data-place-play");
        playPlace(slug);
        return;
      }
      if (route) {
        ev.preventDefault();
        openOverlay(route.getAttribute("data-place-route"), "route");
      }
    });
    $("cityMapPlayPlace")?.addEventListener("click", () => {
      if (selectedSlug) playPlace(selectedSlug);
    });
    $("cityMapRoutePlace")?.addEventListener("click", () => {
      if (selectedSlug) buildRoute(selectedSlug);
    });
    $("cityMapClearRoute")?.addEventListener("click", clearRoute);
    window.addEventListener("ag:place-play-request", (ev) => {
      const slug = ev.detail?.slug;
      if (!slug) return;
      selectedSlug = slug;
      currentPlayingPlaceSlug = slug;
      updateMarkerStyles();
      updateListActive();
      updatePlayButtonLabels();
      startMapPlayerSync();
    });
    window.addEventListener("ag:playback-stopped", () => {
      currentPlayingPlaceSlug = null;
      updateMarkerStyles();
      updateListActive();
      updatePlayButtonLabels();
      syncMapMiniPlayer();
    });
    window.addEventListener("ag:player-state", (ev) => {
      latestPlayerState = ev.detail || window.AG_PLAYER_STATE || null;
      if (latestPlayerState?.currentEntityType === "place" && latestPlayerState.currentEntityId) {
        const id = String(latestPlayerState.currentEntityId);
        const matched = places.find((p) => id.endsWith(`:${p.slug}`));
        if (matched) currentPlayingPlaceSlug = matched.slug;
      }
      if (!latestPlayerState?.currentTrackId && !latestPlayerState?.isPlaying) currentPlayingPlaceSlug = null;
      updateMarkerStyles();
      updateListActive();
      updatePlayButtonLabels();
      syncMapMiniPlayer();
    });
    window.addEventListener("resize", () => {
      if (!overlay.hidden) setTimeout(() => fullMap?.invalidateSize?.(true), 120);
    });
  }

  wire();
  window.AG_CITY_MAP = {
    open: openOverlay,
    openWithPlace: openOverlay,
    close: closeOverlay,
    selectPlace,
    playPlace,
    buildRoute,
    clearRoute,
    requestLocation,
  };
})();

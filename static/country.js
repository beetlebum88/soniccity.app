(function () {
  if (!window.COUNTRY_PAGE || !window.L) return;

  const el = document.getElementById("countryMap");
  if (!el) return;

  const I18N = window.I18N || {};
  const tr = (key, fallback) => (I18N && I18N[key]) ? I18N[key] : (fallback ?? key);

  const { centerLat, centerLon, cities, lang } = window.COUNTRY_PAGE;

  function esc(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  const map = L.map(el).setView([centerLat, centerLon], 6);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  const layer = L.layerGroup().addTo(map);

  const pts = [];
  (cities || []).slice(0, 50).forEach((c) => {
    if (!c.lat || !c.lon) return;

    const citySlug = String(c.citySlug || "");
    const countrySlug = String(c.countrySlug || "");
    const langPrefix = lang && String(lang).toLowerCase() !== "en" ? `/${encodeURIComponent(lang)}` : "";
    const cityUrl = (countrySlug && citySlug) ? `${langPrefix}/${encodeURIComponent(countrySlug)}/${encodeURIComponent(citySlug)}` : "";
    const popText = Number(c.population || 0) > 0 ? Number(c.population || 0).toLocaleString() : "—";
    const placesText = Number(c.placesCount || 0);
    const infoHtml = `
      <div style="min-width:190px;">
        <div style="font-weight:800;font-size:15px;">${esc(c.name)}</div>
        <div style="font-size:12px;opacity:.88;margin-top:2px;">${esc(tr("stat_population", "Population"))}: ${esc(popText)}</div>
        <div style="font-size:12px;opacity:.88;">${esc(tr("stat_places", "places"))}: ${esc(String(placesText))}</div>
        ${cityUrl ? `<a href="${cityUrl}" style="display:inline-block;margin-top:8px;font-size:12px;font-weight:700;">${esc(tr("open_guide", "Open guide"))}</a>` : ""}
      </div>
    `;

    const m = L.marker([c.lat, c.lon]).addTo(layer);
    m.bindPopup(infoHtml);
    m.bindTooltip(esc(c.name), { direction: "top", offset: [0, -8] });
    pts.push([c.lat, c.lon]);
  });

  if (pts.length >= 2) {
    map.fitBounds(pts, { padding: [20, 20] });
  }
})();

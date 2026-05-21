(function () {
  if (!window.COUNTRY_PAGE) return;

  const targetFromPage = () => {
    const p = window.COUNTRY_PAGE;
    return {
      id: p.id || `country_${p.countrySlug}`,
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
  };

  const boot = () => {
    const target = targetFromPage();
    if (typeof onSelectCity !== "function") return;

    const keepRestoredPlayback = !!window.__AG_PLAYBACK_RESTORED;

    onSelectCity(target, {
      scroll: false,
      warm: false,
      keepPlayback: keepRestoredPlayback,
      preservePersistedState: keepRestoredPlayback,
      autoPlayAfterLoad: false,
    });
  };

  if (window.__AG_PLAYBACK_RESTORE_PENDING) {
    window.addEventListener("ag:playback-restore", boot, { once: true });
    return;
  }
  boot();
})();

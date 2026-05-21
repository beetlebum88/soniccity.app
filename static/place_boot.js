(function () {
  if (!window.PLACE_PAGE) return;

  const targetFromPage = () => {
    const p = window.PLACE_PAGE;
    return {
      id: p.id,
      name: p.name,
      countryName: p.countryName,
      country: p.countryCode,
      countrySlug: p.countrySlug,
      lat: p.lat,
      lon: p.lon,
      wikiTitle: p.wikiTitle,
      kind: "place",
      cityName: p.cityName,
      citySlug: p.citySlug,
      placeSlug: p.placeSlug,
    };
  };

  const boot = () => {
    const target = targetFromPage();
    if (typeof onSelectCity === "function") {
      const keepRestoredPlayback = !!window.__AG_PLAYBACK_RESTORED;
      onSelectCity(target, {
        scroll: false,
        warm: false,
        keepPlayback: keepRestoredPlayback,
        preservePersistedState: keepRestoredPlayback,
        autoPlayAfterLoad: false,
      });
    } else if (window.map && window.map.setView) {
      window.map.setView([target.lat, target.lon], 13);
    }
  };

  if (window.__AG_PLAYBACK_RESTORE_PENDING) {
    window.addEventListener("ag:playback-restore", boot, { once: true });
    return;
  }
  boot();
})();

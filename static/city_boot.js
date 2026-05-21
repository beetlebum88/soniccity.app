(function () {
  if (!window.CITY_PAGE) return;

  const targetFromPage = () => {
    const { id, lat, lon, name, countryName, countryCode, countrySlug, citySlug, wikiTitle } = window.CITY_PAGE;
    return {
      id,
      kind: "city",
      name,
      countryName,
      country: countryCode,
      countrySlug,
      citySlug,
      lat,
      lon,
      wikiTitle
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
      window.map.setView([target.lat, target.lon], 12);
    }
  };

  if (window.__AG_PLAYBACK_RESTORE_PENDING) {
    window.addEventListener("ag:playback-restore", boot, { once: true });
    return;
  }
  boot();
})();

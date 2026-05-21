(function () {
  const nav = document.getElementById("navPlaces");
  const mega = document.getElementById("megaPlaces");
  if (!nav || !mega) return;

  let loaded = false;
  let data = null;

  function open(isOpen) {
    nav.dataset.open = isOpen ? "1" : "0";
  }

  async function ensureLoaded() {
    if (loaded) return;
    loaded = true;

    try {
      const res = await fetch("/api/menu/places", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      data = await res.json();
      render();
    } catch (e) {
      mega.querySelector(".MegaWideInner").innerHTML = `<div class="DropLoading">Failed to load Places.</div>`;
    }
  }

  function render() {
    const inner = mega.querySelector(".MegaWideInner");
    if (!inner) return;

    const conts = data?.continents || [];
    const countries = data?.countries || [];
    const cities = data?.cities || [];

    const contHtml = conts.map(c => `<div class="MegaPill">${c}</div>`).join("");

    const countriesHtml = countries.map(c => `
      <div class="MegaItem" data-url="/${encodeURIComponent(c.slug)}/">
        <div class="MegaItemTitle">${c.flag || "🌍"} ${c.country}</div>
        <div class="MegaItemMeta">Top country (by city populations)</div>
      </div>
    `).join("");

    const citiesHtml = cities.map(c => `
      <div class="MegaItem" data-url="${c.url}">
        <div class="MegaItemTitle">${c.name}</div>
        <div class="MegaItemMeta">${c.flag || "🌍"} ${c.country} • ${Number(c.population||0).toLocaleString()}</div>
      </div>
    `).join("");

    inner.innerHTML = `
      <div class="MegaSectionTitle">Continents</div>
      <div class="MegaGrid5">${contHtml}</div>

      <div class="MegaSectionTitle" style="margin-top:14px;">Countries (Top 25)</div>
      <div class="MegaGrid5">${countriesHtml}</div>

      <div class="MegaSectionTitle" style="margin-top:14px;">Largest Cities (Top 50)</div>
      <div class="MegaGrid5">${citiesHtml}</div>
    `;

    inner.querySelectorAll("[data-url]").forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const url = el.getAttribute("data-url");
        if (url) window.location.href = url;
      });
    });
  }

  // Hover open / close
  nav.addEventListener("mouseenter", async () => {
    open(true);
    await ensureLoaded();
  });
  nav.addEventListener("mouseleave", () => open(false));

  // Click toggle for mobile
  const btn = nav.querySelector(".NavBtn");
  if (btn) {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const nowOpen = nav.dataset.open === "1";
      open(!nowOpen);
      if (!nowOpen) await ensureLoaded();
    });
  }

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!nav.contains(e.target)) open(false);
  });
})();
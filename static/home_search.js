(function () {
  const tr = (key, fallback) => (window.I18N && window.I18N[key]) ? window.I18N[key] : (fallback ?? key);
  const input = document.getElementById("homeSearch");
  const box = document.getElementById("homeSuggest");
  const chips = document.getElementById("countryChips");
  if (!input || !box || !chips) return;

  let t = null;

  function hide() {
    box.hidden = true;
    box.innerHTML = "";
  }

  function renderSuggest(data) {
    const cities = data?.cities || [];
    const countries = data?.countries || [];

    const items = [];
    for (const c of countries) {
      items.push({
        label: `${c.emoji || "🌍"} ${c.name}`,
        right: "country",
        url: `/${encodeURIComponent(c.slug)}/`,
      });
    }
    for (const c of cities) {
      items.push({
        label: `${c.emoji || "🌍"} ${c.name}`,
        right: c.country,
        url: `/city/${encodeURIComponent(c.slug)}/`,
      });
    }

    if (!items.length) {
      box.innerHTML = `<div class="SugItem"><div class="SugLeft">${tr("search_no_results", "No results")}</div><div class="SugRight"></div></div>`;
      box.hidden = false;
      return;
    }

    box.innerHTML = items
      .slice(0, 12)
      .map(
        (it) => `
        <div class="SugItem" data-url="${it.url}">
          <div class="SugLeft">${it.label}</div>
          <div class="SugRight">${it.right}</div>
        </div>`
      )
      .join("");

    box.hidden = false;

    Array.from(box.querySelectorAll(".SugItem")).forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const url = el.getAttribute("data-url");
        if (url) window.location.href = url;
      });
    });
  }

  async function apiSearch(q) {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=10`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  }

  input.addEventListener("input", () => {
    const q = (input.value || "").trim();
    if (!q) return hide();

    if (t) clearTimeout(t);
    t = setTimeout(async () => {
      try {
        const data = await apiSearch(q);
        if (!data) return hide();
        renderSuggest(data);
      } catch {
        hide();
      }
    }, 110);
  });

  document.addEventListener("click", (e) => {
    if (!box.contains(e.target) && e.target !== input) hide();
  });

  // Country chips (list)
  async function loadCountries() {
    const res = await fetch("/api/countries?limit=60", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();

    chips.innerHTML = data
      .map((c) => {
        const url = `/${encodeURIComponent(c.slug)}/`;
        return `<button class="Chip" data-url="${url}">${c.emoji || "🌍"} ${c.country}</button>`;
      })
      .join("");

    Array.from(chips.querySelectorAll(".Chip")).forEach((b) => {
      b.addEventListener("click", () => {
        const url = b.getAttribute("data-url");
        if (url) window.location.href = url;
      });
    });
  }

  loadCountries();
})();

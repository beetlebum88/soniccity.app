window.SearchShared = (function () {
  const tr = (key, fallback) => (window.I18N && window.I18N[key]) ? window.I18N[key] : (fallback ?? key);
  async function apiSearch(q, limit) {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=${limit || 14}`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  }

  function bindSearch({ inputId, boxId, limit }) {
    const input = document.getElementById(inputId);
    const box = document.getElementById(boxId);
    if (!input || !box) return;

    let timer = null;

    function hide() {
      box.hidden = true;
      box.innerHTML = "";
    }

    function render(data) {
      const cities = data?.cities || [];
      const countries = data?.countries || [];

      const items = [];

      // countries first
      for (const c of countries) {
        items.push({
          left: `${c.flag || "🌍"} ${c.name}`,
          right: "country",
          url: c.url || `/${c.slug}/`
        });
      }

      // then cities
      for (const c of cities) {
        items.push({
          left: `${c.flag || "🌍"} ${c.name}`,
          right: c.country || "",
          url: c.url || `/${c.country_slug}/${c.city_slug}/`
        });
      }

      if (!items.length) {
        box.innerHTML = `<div class="SugItem"><div class="SugLeft">${tr("search_no_results", "No results")}</div><div class="SugRight"></div></div>`;
        box.hidden = false;
        return;
      }

      box.innerHTML = items.slice(0, limit || 14).map(it => `
        <div class="SugItem" data-url="${it.url}">
          <div class="SugLeft">${it.left}</div>
          <div class="SugRight">${it.right}</div>
        </div>
      `).join("");

      box.hidden = false;

      box.querySelectorAll(".SugItem").forEach((el) => {
        el.addEventListener("mousedown", (e) => {
          e.preventDefault();
          const url = el.getAttribute("data-url");
          if (url) window.location.href = url;
        });
      });
    }

    input.addEventListener("input", () => {
      const q = (input.value || "").trim();
      if (!q) return hide();

      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const data = await apiSearch(q, limit || 14);
          if (!data) return hide();
          render(data);
        } catch {
          hide();
        }
      }, 110);
    });

    document.addEventListener("click", (e) => {
      if (!box.contains(e.target) && e.target !== input) hide();
    });
  }

  return { bindSearch };
})();

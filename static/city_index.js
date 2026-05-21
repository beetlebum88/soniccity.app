const $ = (id) => document.getElementById(id);

const els = {
  q: $("q"),
  country: $("country"),
  alpha: $("alpha"),
  cityList: $("cityList"),
  countInfo: $("countInfo"),
  listHint: $("listHint"),
  clearBtn: $("clearBtn"),
};

const state = {
  starts: "",
  q: "",
  country: "",
  debounceId: null,
};

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildAlphaButtons() {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
  els.alpha.innerHTML = "";
  for (const ch of letters) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = ch;
    b.addEventListener("click", () => {
      // toggle
      state.starts = (state.starts === ch.toLowerCase()) ? "" : ch.toLowerCase();
      renderAlphaActive();
      loadCities();
    });
    els.alpha.appendChild(b);
  }
}

function renderAlphaActive() {
  const buttons = Array.from(els.alpha.querySelectorAll("button"));
  for (const b of buttons) {
    const active = state.starts && b.textContent.toLowerCase() === state.starts;
    b.classList.toggle("Active", !!active);
  }
}

async function loadCountries() {
  const res = await fetch("/api/countries", { cache: "no-store" });
  if (!res.ok) throw new Error("Countries HTTP " + res.status);
  const data = await res.json();

  els.country.innerHTML = `<option value="">All countries</option>`;
  for (const row of data) {
    const opt = document.createElement("option");
    opt.value = row.country;
    opt.textContent = `${row.country} (${row.count})`;
    els.country.appendChild(opt);
  }
}

function renderCities(items) {
  els.cityList.innerHTML = "";

  const frag = document.createDocumentFragment();
  for (const c of items) {
    const li = document.createElement("li");
    li.className = "CityItem";
    li.innerHTML = `
      <div>
        <a class="CityLink" href="/city/${encodeURIComponent(c.slug)}/">${escapeHtml(c.name)}</a>
        <div class="CityMeta">${escapeHtml(c.country)}</div>
      </div>
      <div class="CityMeta">${c.population ? `pop ${Number(c.population).toLocaleString()}` : ""}</div>
    `;
    frag.appendChild(li);
  }
  els.cityList.appendChild(frag);
}

async function loadCities() {
  const q = (els.q.value || "").trim();
  const country = els.country.value || "";
  state.q = q;
  state.country = country;

  els.countInfo.textContent = "Loading…";

  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.starts) params.set("starts", state.starts);
  if (state.country) params.set("country", state.country);
  // pull a lot, because you wanted ALL cities visible
  params.set("limit", "200000");

  const res = await fetch(`/api/cities?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    els.countInfo.textContent = `Error HTTP ${res.status}`;
    return;
  }
  const items = await res.json();

  els.countInfo.textContent = `${items.length.toLocaleString()} cities shown`;
  els.listHint.textContent = `Filters: ${state.q ? `q="${state.q}" ` : ""}${state.starts ? `starts="${state.starts.toUpperCase()}" ` : ""}${state.country ? `country="${state.country}"` : ""}`.trim() || "No filters";

  renderCities(items);
}

function debounceLoad() {
  if (state.debounceId) clearTimeout(state.debounceId);
  state.debounceId = setTimeout(loadCities, 120);
}

function clearFilters() {
  els.q.value = "";
  els.country.value = "";
  state.q = "";
  state.country = "";
  state.starts = "";
  renderAlphaActive();
  loadCities();
}

(function boot() {
  buildAlphaButtons();
  renderAlphaActive();

  els.q.addEventListener("input", debounceLoad);
  els.country.addEventListener("change", loadCities);
  els.clearBtn.addEventListener("click", clearFilters);

  loadCountries()
    .then(loadCities)
    .catch((e) => {
      els.countInfo.textContent = "Failed to load.";
      console.error(e);
    });
})();
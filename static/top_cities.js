(async function () {
  const grid = document.getElementById("topCitiesGrid");
  if (!grid) return;

  const res = await fetch("/api/top-cities?limit=50", { cache: "no-store" });
  if (!res.ok) {
    grid.innerHTML = "Failed to load.";
    return;
  }
  const data = await res.json();

  grid.innerHTML = data.map(c => {
    return `
      <div class="CityItemBig">
        <a class="CityLink" href="/city/${encodeURIComponent(c.slug)}/">${c.name}</a>
        <div class="Muted Small">${c.emoji || "🌍"} <a href="/${encodeURIComponent(c.country_slug)}/" style="color:inherit;text-decoration:underline">${c.country}</a> · pop ${Number(c.population || 0).toLocaleString()}</div>
      </div>
    `;
  }).join("");
})();
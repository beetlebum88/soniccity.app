(async function () {
  const wrap = document.getElementById("continentsWrap");
  if (!wrap) return;

  const res = await fetch("/api/continents", { cache: "no-store" });
  if (!res.ok) {
    wrap.innerHTML = "Failed to load.";
    return;
  }
  const data = await res.json();

  wrap.innerHTML = data.map(block => {
    const rows = (block.countries || []).map(c => {
      return `
        <div class="CityItemBig">
          <a class="CityLink" href="/${encodeURIComponent(c.slug)}/">${c.emoji || "🌍"} ${c.country}</a>
          <div class="Muted Small">${c.count} cities</div>
        </div>
      `;
    }).join("");

    return `
      <div class="Card" style="margin-bottom:12px;">
        <div class="CardHeader">
          <h2 class="H2">${block.continent}</h2>
          <div class="Muted Small">Top 10 countries by city count</div>
        </div>
        <div class="CardBody">
          <div class="Grid2">${rows}</div>
        </div>
      </div>
    `;
  }).join("");
})();
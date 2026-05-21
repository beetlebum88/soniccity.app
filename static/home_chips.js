(function () {
  const chips = document.getElementById("countryChips");
  if (!chips) return;

  async function load() {
    try {
      const res = await fetch("/api/menu/places", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const countries = (data?.countries || []).slice(0, 25);

      chips.innerHTML = countries.map(c => `
        <button class="Chip" data-url="/${encodeURIComponent(c.slug)}/">
          ${c.flag || "🌍"} ${c.country}
        </button>
      `).join("");

      chips.querySelectorAll(".Chip").forEach((b) => {
        b.addEventListener("click", () => {
          const url = b.getAttribute("data-url");
          if (url) window.location.href = url;
        });
      });
    } catch {}
  }

  load();
})();
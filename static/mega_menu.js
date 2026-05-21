(function () {
  const navContinents = document.getElementById("navContinents");
  const navTop = document.getElementById("navTop");
  const dropContinents = document.getElementById("dropContinents");
  const dropTop = document.getElementById("dropTop");

  if (!navContinents || !navTop || !dropContinents || !dropTop) return;

  let continentsData = null;
  let topData = null;

  function openDrop(navEl, isOpen) {
    navEl.dataset.open = isOpen ? "1" : "0";
  }

  function closeAll() {
    openDrop(navContinents, false);
    openDrop(navTop, false);
  }

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!navContinents.contains(e.target) && !navTop.contains(e.target)) {
      closeAll();
    }
  });

  // Hover open (desktop) + click toggle (mobile)
  function bindHover(navEl, loaderFn) {
    navEl.addEventListener("mouseenter", async () => {
      closeAll();
      openDrop(navEl, true);
      await loaderFn();
    });
    navEl.addEventListener("mouseleave", () => {
      openDrop(navEl, false);
    });

    const btn = navEl.querySelector(".NavBtn");
    if (btn) {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const nowOpen = navEl.dataset.open === "1";
        closeAll();
        openDrop(navEl, !nowOpen);
        if (!nowOpen) await loaderFn();
      });
    }
  }

  async function loadContinents() {
    if (continentsData) return;
    const res = await fetch("/api/menu/continents", { cache: "no-store" });
    if (!res.ok) {
      dropContinents.innerHTML = `<div class="DropLoading">Failed to load.</div>`;
      return;
    }
    continentsData = await res.json();
    renderContinents();
  }

  function renderContinents() {
    const data = continentsData || [];
    if (!data.length) {
      dropContinents.innerHTML = `<div class="DropLoading">No data.</div>`;
      return;
    }

    const tabs = data.map((x, i) => `
      <div class="DropTab ${i === 0 ? "Active" : ""}" data-i="${i}">
        ${x.continent}
      </div>
    `).join("");

    dropContinents.innerHTML = `
      <div class="DropGrid">
        <div class="DropLeft">${tabs}</div>
        <div class="DropRight">
          <div class="DropList" id="contList"></div>
        </div>
      </div>
    `;

    const listEl = dropContinents.querySelector("#contList");
    const tabEls = Array.from(dropContinents.querySelectorAll(".DropTab"));

    function setActive(idx) {
      tabEls.forEach(t => t.classList.remove("Active"));
      tabEls[idx].classList.add("Active");

      const block = data[idx];
      const items = (block.countries || []).map(c => `
        <div class="DropItem" data-url="/${encodeURIComponent(c.slug)}/">
          <div class="DropItemTitle">${c.flag || "🌍"} ${c.country}</div>
          <div class="DropItemMeta">${c.count} cities</div>
        </div>
      `).join("");

      listEl.innerHTML = items;

      Array.from(listEl.querySelectorAll(".DropItem")).forEach(it => {
        it.addEventListener("mousedown", (e) => {
          e.preventDefault();
          const url = it.getAttribute("data-url");
          if (url) window.location.href = url;
        });
      });
    }

    tabEls.forEach(t => {
      t.addEventListener("mouseenter", () => setActive(Number(t.dataset.i || "0")));
      t.addEventListener("click", () => setActive(Number(t.dataset.i || "0")));
    });

    setActive(0);
  }

  async function loadTop() {
    if (topData) return;
    const res = await fetch("/api/menu/top", { cache: "no-store" });
    if (!res.ok) {
      dropTop.innerHTML = `<div class="DropLoading">Failed to load.</div>`;
      return;
    }
    topData = await res.json();
    renderTop();
  }

  function renderTop() {
    const data = topData || [];
    if (!data.length) {
      dropTop.innerHTML = `<div class="DropLoading">No data.</div>`;
      return;
    }

    // 10 countries in columns
    const cols = data.map(block => {
      const cities = (block.cities || []).map(c => `
        <div class="DropCity">
          <a href="/city/${encodeURIComponent(c.slug)}/">${c.name}</a>
          <div class="DropCityMeta">${Number(c.population || 0).toLocaleString()}</div>
        </div>
      `).join("");

      return `
        <div class="DropCol">
          <div class="DropColTitle">
            <a href="/${encodeURIComponent(block.slug)}/" style="color:inherit;text-decoration:none">
              ${block.flag || "🌍"} ${block.country}
            </a>
          </div>
          ${cities}
        </div>
      `;
    }).join("");

    dropTop.innerHTML = `<div class="DropCols">${cols}</div>`;
  }

  bindHover(navContinents, loadContinents);
  bindHover(navTop, loadTop);
})();
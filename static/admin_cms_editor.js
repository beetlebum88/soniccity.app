(function () {
  "use strict";

  const allowedTags = new Set([
    "DIV", "SECTION", "ARTICLE", "ASIDE", "SPAN", "H1", "H2", "H3", "H4", "H5", "H6", "P", "BR",
    "STRONG", "EM", "B", "I", "U", "S", "MARK", "SMALL", "SUP", "SUB", "UL", "OL", "LI", "A",
    "BLOCKQUOTE", "HR", "FIGURE", "FIGCAPTION", "IMG", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD",
    "CODE", "PRE", "DETAILS", "SUMMARY"
  ]);
  const allowedAttrs = {
    "*": new Set(["class", "id", "role", "aria-label", "aria-labelledby", "aria-describedby"]),
    A: new Set(["href", "title", "rel", "target", "class", "id", "aria-label"]),
    IMG: new Set(["src", "alt", "title", "loading", "width", "height", "class"]),
    TH: new Set(["colspan", "rowspan", "scope"]),
    TD: new Set(["colspan", "rowspan"])
  };
  let dirty = false;

  function sanitizeHtml(html) {
    const tpl = document.createElement("template");
    tpl.innerHTML = html || "";
    Array.from(tpl.content.querySelectorAll("*")).forEach((el) => {
      if (!allowedTags.has(el.tagName)) {
        el.replaceWith(document.createTextNode(el.textContent || ""));
        return;
      }
      Array.from(el.attributes).forEach((attr) => {
        const name = attr.name.toLowerCase();
        const local = allowedAttrs[el.tagName];
        const global = allowedAttrs["*"];
        if (name.startsWith("on") || ((!local || !local.has(name)) && (!global || !global.has(name)))) {
          el.removeAttribute(attr.name);
          return;
        }
        if ((name === "href" || name === "src") && /^\s*javascript:/i.test(attr.value)) el.removeAttribute(attr.name);
      });
      if (el.tagName === "A" && !el.getAttribute("rel")) el.setAttribute("rel", "noopener");
      if (el.tagName === "IMG" && !el.getAttribute("loading")) el.setAttribute("loading", "lazy");
    });
    return tpl.innerHTML;
  }

  function btn(label, action, title) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.action = action;
    if (title) b.title = title;
    return b;
  }

  function exec(visual, command, value) {
    visual.focus();
    document.execCommand(command, false, value || null);
  }

  function insertHtml(visual, html) {
    visual.focus();
    document.execCommand("insertHTML", false, sanitizeHtml(html));
  }

  function tableHtml(rows, cols) {
    const r = Math.max(1, Math.min(20, Number(rows) || 3));
    const c = Math.max(1, Math.min(10, Number(cols) || 3));
    let out = "<table><thead><tr>";
    for (let i = 0; i < c; i += 1) out += `<th scope="col">Header ${i + 1}</th>`;
    out += "</tr></thead><tbody>";
    for (let y = 0; y < r; y += 1) {
      out += "<tr>";
      for (let x = 0; x < c; x += 1) out += "<td>Cell</td>";
      out += "</tr>";
    }
    return out + "</tbody></table>";
  }

  function toolbar() {
    const t = document.createElement("div");
    t.className = "cms-rich-toolbar";
    t.appendChild(btn("More", "toggleToolbar", "Show the full toolbar"));
    const advanced = new Set(["undo", "redo", "underline", "strikeThrough", "inlineCode", "removeFormat", "checklist", "internalLink", "faq", "cta", "related", "copyHtml", "fullscreen"]);
    [
      ["Undo", "undo"], ["Redo", "redo"], ["P", "p"], ["H1", "h1"], ["H2", "h2"], ["H3", "h3"], ["H4", "h4"],
      ["B", "bold"], ["I", "italic"], ["U", "underline"], ["S", "strikeThrough"], ["Code", "inlineCode"], ["Clear", "removeFormat"],
      ["UL", "insertUnorderedList"], ["OL", "insertOrderedList"], ["Checklist", "checklist"],
      ["Link", "link"], ["Unlink", "unlink"], ["Internal", "internalLink"], ["Image", "image"],
      ["Quote", "quote"], ["Table", "table"], ["HR", "hr"], ["FAQ", "faq"], ["CTA", "cta"], ["Related", "related"],
      ["HTML", "copyHtml"], ["Full", "fullscreen"]
    ].forEach(([label, action]) => {
      const button = btn(label, action);
      if (advanced.has(action)) button.classList.add("cms-rich-advanced");
      t.appendChild(button);
    });
    return t;
  }

  function stats(wrapper, html) {
    const plain = (html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const words = plain ? plain.split(/\s+/).length : 0;
    const headings = (html.match(/<h[1-6]\b/gi) || []).length;
    const links = (html.match(/<a\b/gi) || []).length;
    const images = (html.match(/<img\b/gi) || []).length;
    const missingAlt = (html.match(/<img\b(?![^>]*\salt=)/gi) || []).length;
    wrapper.querySelector("[data-rich-stats]").textContent = `${words} words · ${plain.length} chars · ${headings} headings · ${links} links · ${images} images${missingAlt ? " · missing alt: " + missingAlt : ""}`;
  }

  function initEditor(textarea, index) {
    if (textarea.dataset.cmsRichReady === "1") return;
    textarea.dataset.cmsRichReady = "1";
    const compact = textarea.dataset.cmsRichEditor === "compact";
    const wrap = document.createElement("section");
    wrap.className = compact ? "cms-rich cms-rich-compact" : "cms-rich";

    const mode = document.createElement("div");
    mode.className = "cms-rich-mode";
    mode.append(btn("Visual", "visual"), btn("HTML source", "html"), btn("Preview", "preview"));
    const bar = toolbar();
    const visual = document.createElement("div");
    visual.className = "cms-rich-visual";
    visual.contentEditable = "true";
    visual.setAttribute("role", "textbox");
    visual.setAttribute("aria-label", textarea.dataset.editorLabel || "HTML editor");
    visual.innerHTML = sanitizeHtml(textarea.value);
    const preview = document.createElement("article");
    preview.className = "cms-rich-preview";
    preview.hidden = true;
    const info = document.createElement("div");
    info.className = "cms-rich-stats";
    info.dataset.richStats = "1";

    textarea.classList.add("cms-rich-source-active");
    textarea.hidden = true;
    textarea.parentNode.insertBefore(wrap, textarea);
    wrap.append(mode, bar, visual, textarea, preview, info);

    function syncFromVisual() {
      textarea.value = sanitizeHtml(visual.innerHTML);
      preview.innerHTML = textarea.value || "<p>Preview</p>";
      stats(wrap, textarea.value);
      dirty = true;
    }
    function syncToVisual() {
      textarea.value = sanitizeHtml(textarea.value);
      visual.innerHTML = textarea.value;
      preview.innerHTML = textarea.value || "<p>Preview</p>";
      stats(wrap, textarea.value);
    }
    function setMode(value) {
      const isHtml = value === "html";
      const isPreview = value === "preview";
      if (isHtml || isPreview) textarea.value = sanitizeHtml(visual.innerHTML);
      visual.hidden = isHtml || isPreview;
      textarea.hidden = !isHtml;
      preview.hidden = !isPreview;
      if (isPreview) preview.innerHTML = textarea.value || "<p>Preview</p>";
      if (!isHtml && !isPreview) syncToVisual();
    }

    bar.addEventListener("click", async (event) => {
      const target = event.target.closest("button[data-action]");
      if (!target) return;
      const a = target.dataset.action;
      if (a === "toggleToolbar") {
        wrap.classList.toggle("is-expanded-toolbar");
        target.textContent = wrap.classList.contains("is-expanded-toolbar") ? "Less" : "More";
        return;
      }
      if (["p", "h1", "h2", "h3", "h4"].includes(a)) exec(visual, "formatBlock", a);
      else if (["undo", "redo", "bold", "italic", "underline", "strikeThrough", "insertUnorderedList", "insertOrderedList", "removeFormat"].includes(a)) exec(visual, a);
      else if (a === "inlineCode") insertHtml(visual, `<code>${String(document.getSelection() || "code")}</code>`);
      else if (a === "checklist") insertHtml(visual, "<ul><li>[ ] Checklist item</li><li>[ ] Another item</li></ul>");
      else if (a === "unlink") exec(visual, "unlink");
      else if (a === "link" || a === "internalLink") {
        const href = window.prompt(a === "internalLink" ? "Internal URL, for example /spain/valencia" : "Link URL");
        if (href) {
          const label = window.prompt("Link text", String(document.getSelection() || href)) || href;
          const rel = window.prompt("rel attribute: noopener, nofollow, sponsored, ugc", "noopener") || "noopener";
          const targetAttr = window.confirm("Open in new tab?") ? ' target="_blank"' : "";
          insertHtml(visual, `<a href="${href}" rel="${rel}"${targetAttr}>${label}</a>`);
        }
      } else if (a === "image") {
        const src = window.prompt("Image URL or media path");
        if (src) {
          const alt = window.prompt("Alt text", "") || "";
          const caption = window.prompt("Caption", "") || "";
          insertHtml(visual, `<figure><img src="${src}" alt="${alt}" loading="lazy">${caption ? `<figcaption>${caption}</figcaption>` : ""}</figure>`);
        }
      } else if (a === "quote") insertHtml(visual, "<blockquote>Quote or editorial note.</blockquote>");
      else if (a === "table") insertHtml(visual, tableHtml(window.prompt("Rows", "3"), window.prompt("Columns", "3")));
      else if (a === "hr") insertHtml(visual, "<hr>");
      else if (a === "faq") insertHtml(visual, "<details><summary>Question</summary><p>Answer with a useful internal link.</p></details>");
      else if (a === "cta") insertHtml(visual, '<section class="seo-callout"><h2>Listen free with this Audio Guide</h2><p>Choose a city or place and start listening.</p><p><a class="ct-primaryBtn" href="/countries">Explore guides</a></p></section>');
      else if (a === "related") insertHtml(visual, '<div class="seo-columns"><div><h3>Related city guide</h3><p><a href="/spain/valencia">Valencia Audio Guide</a></p></div><div><h3>Related place</h3><p><a href="/spain/valencia/valencia-cathedral">Valencia Cathedral</a></p></div></div>');
      else if (a === "copyHtml") {
        textarea.value = sanitizeHtml(visual.innerHTML);
        await navigator.clipboard.writeText(textarea.value).catch(() => {});
      } else if (a === "fullscreen") wrap.classList.toggle("is-fullscreen");
      syncFromVisual();
    });
    mode.addEventListener("click", (event) => {
      const target = event.target.closest("button[data-action]");
      if (target) setMode(target.dataset.action);
    });
    visual.addEventListener("input", syncFromVisual);
    textarea.addEventListener("input", () => { syncToVisual(); dirty = true; });
    syncFromVisual();
  }

  function slugify(value) {
    const map = {"а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ie","ж":"zh","з":"z","и":"y","і":"i","ї":"i","й":"i","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch","ь":"","ю":"iu","я":"ia","ы":"y","э":"e","ъ":""};
    return (value || "").toLowerCase().replace(/[а-яіїєґыэъ]/g, (ch) => map[ch] || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80).replace(/-+$/g, "");
  }

  function initSlug() {
    const h1 = document.getElementById("pageH1Input") || document.getElementById("blogTitleInput");
    const slug = document.getElementById("contentSlugInput");
    const manual = document.getElementById("slugManualInput");
    const regen = document.getElementById("regenerateSlugBtn");
    const preview = document.getElementById("slugUrlPreview");
    if (!h1 || !slug) return;
    let touched = manual && manual.value === "1";
    function sync(force) {
      if (force) touched = false;
      if (!touched) slug.value = slugify(h1.value);
      if (manual) manual.value = touched ? "1" : "0";
      if (preview) preview.textContent = preview.textContent.split(":")[0] + ": /" + (window.APP_LANG || "en") + "/" + (slug.value || "auto-slug");
    }
    h1.addEventListener("input", () => sync(false));
    slug.addEventListener("input", () => { touched = Boolean(slug.value.trim()); if (manual) manual.value = "1"; });
    if (regen) regen.addEventListener("click", () => sync(true));
    sync(false);
  }

  function initModePanels() {
    const select = document.getElementById("seoEditorMode");
    if (!select) return;
    const panels = Array.from(document.querySelectorAll("[data-editor-panel]"));
    function update() {
      panels.forEach((panel) => { panel.hidden = panel.dataset.editorPanel !== select.value; });
    }
    select.addEventListener("change", update);
    update();
  }

  function initTabs() {
    document.querySelectorAll("[data-cms-editor-form]").forEach((form) => {
      const tabLinks = Array.from(form.querySelectorAll("[data-cms-tab]"));
      const panels = Array.from(form.querySelectorAll(".cms-editor-panel[id]"));
      if (!tabLinks.length || !panels.length) return;
      function show(id, updateHash) {
        panels.forEach((panel) => { panel.hidden = panel.id !== id; });
        tabLinks.forEach((link) => {
          const active = link.dataset.cmsTab === id;
          link.classList.toggle("is-active", active);
          if (active) link.setAttribute("aria-current", "page");
          else link.removeAttribute("aria-current");
        });
        if (updateHash && window.history && window.history.replaceState) {
          window.history.replaceState(null, "", `#${id}`);
        }
      }
      const hash = (window.location.hash || "").replace("#", "");
      const initial = panels.some((panel) => panel.id === hash) ? hash : (tabLinks[0].dataset.cmsTab || panels[0].id);
      show(initial, false);
      tabLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          show(link.dataset.cmsTab, true);
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSlug();
    initModePanels();
    initTabs();
    const sources = Array.from(document.querySelectorAll("[data-cms-rich-editor]"));
    if (sources.length) {
      const loader = document.createElement("div");
      loader.className = "cms-editor-skeleton";
      loader.textContent = "Loading full HTML editor...";
      sources[0].parentNode.insertBefore(loader, sources[0]);
      window.requestAnimationFrame(() => {
        sources.forEach(initEditor);
        loader.remove();
      });
    }
    document.addEventListener("submit", (event) => {
      event.target.querySelectorAll("[data-cms-rich-editor]").forEach((textarea) => {
        const wrap = textarea.closest(".cms-rich");
        const visual = wrap && wrap.querySelector(".cms-rich-visual");
        if (visual && !visual.hidden) textarea.value = sanitizeHtml(visual.innerHTML);
        else textarea.value = sanitizeHtml(textarea.value);
      });
      dirty = false;
    });
  });

  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();

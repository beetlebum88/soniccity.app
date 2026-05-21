(function () {
  function tr(key, fallback) {
    const dict = window.I18N || {};
    const value = dict[key];
    return value == null || value === "" ? (fallback ?? key) : value;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function flagMarkup(item) {
    const emoji = escapeHtml(item?.flagEmoji || "🌍");
    if (!item?.flag) return `<span class="FlagFallback">${emoji}</span>`;
    return `<span class="FlagFallback" hidden>${emoji}</span><img class="Flag" src="${escapeHtml(item.flag)}" alt="" loading="lazy" onerror="this.hidden=true;this.previousElementSibling.hidden=false"/>`;
  }

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return (window.AG_CSRF_TOKEN || meta?.getAttribute("content") || "").trim();
  }

  function csrfHeaders(headers) {
    const out = Object.assign({}, headers || {});
    const token = csrfToken();
    if (token) out["X-CSRF-Token"] = token;
    return out;
  }

  function addCsrfToFormData(data) {
    const token = csrfToken();
    if (token && data && typeof data.set === "function") data.set("csrf_token", token);
    return data;
  }

  function installCsrfHiddenFields() {
    const token = csrfToken();
    if (!token) return;
    document.querySelectorAll("form").forEach((form) => {
      const method = String(form.getAttribute("method") || "get").toLowerCase();
      if (method !== "post" || form.querySelector('input[name="csrf_token"]')) return;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = token;
      form.prepend(input);
    });
  }
  installCsrfHiddenFields();
  window.SonicCityCSRF = { token: csrfToken, headers: csrfHeaders, formData: addCsrfToFormData };

  // -------- Language switching (keep current page when possible) --------
  const langMenu = document.getElementById("langMenu");

  function getSupportedLangs() {
    if (!langMenu) return new Set();
    const links = Array.from(langMenu.querySelectorAll("a[data-lang]"));
    return new Set(links.map((a) => String(a.dataset.lang || "").toLowerCase()).filter(Boolean));
  }

  function replaceLangInPath(pathname, newLang) {
    const supported = getSupportedLangs();
    const nl = String(newLang || "").toLowerCase();
    if (!supported.has(nl)) return null;

    const parts = String(pathname || "").split("/").filter(Boolean);
    const reserved = new Set(["api", "media", "static", "img", "admin", "main", "c", "robots.txt", "sitemap.xml", "favicon.ico"]);
    const head = String(parts[0] || "").toLowerCase();

    if (!parts.length) {
      return nl === "en" ? "/" : `/${nl}`;
    }

    if (supported.has(head)) {
      const tail = parts.slice(1);
      if (!tail.length) return nl === "en" ? "/" : `/${nl}`;
      return nl === "en" ? `/${tail.join("/")}` : `/${[nl, ...tail].join("/")}`;
    }

    if (reserved.has(head)) return null;
    return nl === "en" ? `/${parts.join("/")}` : `/${[nl, ...parts].join("/")}`;
  }

  if (langMenu) {
    langMenu.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-lang]");
      if (!a) return;
      e.preventDefault();

      const target = replaceLangInPath(window.location.pathname, a.dataset.lang);
      if (target) window.location.href = target + window.location.search;
      else window.location.href = a.href;
    });
  }

  // -------- Search (city + country) --------
  const input = document.getElementById("navSearchInput");
  const dd = document.getElementById("navSearchDropdown");
  let t = null;

  function hideDD() {
    if (!dd) return;
    dd.hidden = true;
    dd.innerHTML = "";
  }

  function render(items) {
    if (!dd) return;
    if (!items.length) return hideDD();
    dd.hidden = false;
    dd.innerHTML = items
      .map((x) => {
        const flag = flagMarkup(x);
        const metaText =
          x.type === "city"
            ? (x.countryName || "")
            : x.type === "place"
              ? [x.cityName, x.countryName].filter(Boolean).join(", ")
              : "";
        const badge = x.label ? `<span class="ag-pill">${x.label}</span>` : "";
        const meta = metaText ? `<div class="ag-search-meta">${metaText}</div>` : `<div class="ag-search-meta"></div>`;
        return `
          <div class="ag-search-item" data-url="${x.url || ""}">
            ${flag}
            <div style="display:flex;flex-direction:column;gap:2px;min-width:0;">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-width:0;">
                <b style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${x.name}</b>
                ${badge}
              </div>
              ${meta}
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function doSearch(q) {
    const lang = window.APP_LANG || "ua";
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&lang=${encodeURIComponent(lang)}`, { cache: "no-store" });
    if (!res.ok) return hideDD();
    const data = await res.json();
    render(data.items || []);
  }

  if (input && dd) {
    input.addEventListener("input", () => {
      const q = input.value.trim();
      if (t) clearTimeout(t);
      if (q.length < 2) return hideDD();
      t = setTimeout(() => doSearch(q), 120);
    });

    dd.addEventListener("click", (e) => {
      const item = e.target.closest(".ag-search-item");
      if (!item) return;
      const url = item.dataset.url;

      hideDD();
      input.blur();
      if (url) window.location.href = url;
    });

    document.addEventListener("click", (e) => {
      if (!dd.contains(e.target) && e.target !== input) hideDD();
    });
  }

  // -------- Subscription popup (progressive enhancement) --------
  const subscribeOverlay = document.getElementById("subscribeOverlay");
  const subscribeClose = document.getElementById("subscribeClose");
  const subscribeForm = document.getElementById("subscribeForm");
  const subscribeFeedback = document.getElementById("subscribeFeedback");
  const subscribeKey = "ag_subscribe_popup_done";

  function hideSubscribe(save) {
    if (!subscribeOverlay) return;
    subscribeOverlay.hidden = true;
    subscribeOverlay.setAttribute("aria-hidden", "true");
    document.body.classList.remove("ct-subscribeOpen");
    if (save) {
      try { localStorage.setItem(subscribeKey, String(Date.now())); } catch {}
    }
  }

  function showSubscribe() {
    if (!subscribeOverlay) return;
    try {
      if (localStorage.getItem(subscribeKey)) return;
    } catch {}
    subscribeOverlay.hidden = false;
    subscribeOverlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("ct-subscribeOpen");
    const email = document.getElementById("subscribeEmail");
    setTimeout(() => { try { email?.focus?.(); } catch {} }, 60);
  }

  if (subscribeOverlay) {
    setTimeout(showSubscribe, 5000);
    subscribeClose?.addEventListener("click", () => hideSubscribe(true));
    subscribeOverlay.addEventListener("click", (e) => {
      if (e.target === subscribeOverlay) hideSubscribe(true);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !subscribeOverlay.hidden) hideSubscribe(true);
    });
    subscribeForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = subscribeForm.querySelector("button[type='submit']");
      const data = addCsrfToFormData(new FormData(subscribeForm));
      data.set("sourcePage", window.location.href);
      if (subscribeFeedback) subscribeFeedback.textContent = "";
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch("/api/subscribe", {
          method: "POST",
          headers: csrfHeaders({ "Accept": "application/json" }),
          body: data
        });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || tr("subscription_error", "Subscription failed"));
        if (subscribeFeedback) subscribeFeedback.textContent = tr("subscription_success", "Thank you. We saved your request.");
        setTimeout(() => hideSubscribe(true), 900);
      } catch (err) {
        if (subscribeFeedback) subscribeFeedback.textContent = err?.message || tr("subscription_error", "Please check your email and try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // -------- Public user login / sign-in --------
  const authOverlay = document.getElementById("authOverlay");
  const authClose = document.getElementById("authClose");
  const authForm = document.getElementById("authForm");
  const authTitle = document.getElementById("authTitle");
  const authIntro = document.getElementById("authIntro");
  const authSubmit = document.getElementById("authSubmit");
  const authSwitch = document.getElementById("authSwitch");
  const authForgot = document.getElementById("authForgot");
  const authResend = document.getElementById("authResend");
  const authFeedback = document.getElementById("authFeedback");
  const authEmail = document.getElementById("authEmail");
  const authPassword = document.getElementById("authPassword");
  const authRepeatPassword = document.getElementById("authRepeatPassword");
  const authCountry = document.getElementById("authCountry");

  function setAuthMode(mode) {
    if (!authForm) return;
    const nextMode = mode === "register" ? "register" : "login";
    authForm.dataset.mode = nextMode;
    if (authTitle) authTitle.textContent = nextMode === "register" ? tr("auth_signup_title", "Create account") : tr("auth_login_title", "Log In");
    if (authIntro) authIntro.textContent = nextMode === "register"
      ? tr("auth_signup_intro", "Create an account to save listening progress and continue on any page.")
      : tr("auth_login_intro", "Use your email and password to continue.");
    if (authSubmit) authSubmit.textContent = nextMode === "register" ? tr("auth_signup_submit", "Sign Up") : tr("auth_login_submit", "Log In");
    if (authSwitch) authSwitch.textContent = nextMode === "register"
      ? tr("auth_switch_login", "Already registered? Log In")
      : tr("auth_switch_signup", "No account yet? Sign Up");
    if (authForgot) authForgot.hidden = nextMode === "register";
    if (authResend) authResend.hidden = true;
    if (authPassword) {
      authPassword.autocomplete = nextMode === "register" ? "new-password" : "current-password";
      authPassword.minLength = 8;
    }
    if (authRepeatPassword) {
      authRepeatPassword.hidden = nextMode !== "register";
      authRepeatPassword.required = nextMode === "register";
    }
    if (authCountry) {
      authCountry.hidden = nextMode !== "register";
    }
    if (authFeedback) authFeedback.textContent = "";
  }

  function showAuth(mode) {
    if (!authOverlay) return;
    setAuthMode(mode || "login");
    authOverlay.hidden = false;
    authOverlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("ct-authOpen");
    setTimeout(() => { try { authEmail?.focus?.(); } catch {} }, 60);
  }

  function hideAuth() {
    if (!authOverlay) return;
    authOverlay.hidden = true;
    authOverlay.setAttribute("aria-hidden", "true");
    document.body.classList.remove("ct-authOpen");
  }

  document.querySelectorAll("[data-auth-open]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const mode = btn.getAttribute("data-auth-mode") === "register" ? "register" : "login";
      try { e.preventDefault(); } catch {}
      showAuth(mode);
    });
  });

  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("login") === "1") {
      const mode = params.get("mode") === "register" || params.get("signup") === "1" ? "register" : "login";
      showAuth(mode);
    }
  } catch {}

  document.querySelectorAll("[data-auth-logout]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await fetch("/api/auth/logout", { method: "POST", headers: csrfHeaders({ "Accept": "application/json" }) });
      } finally {
        window.location.reload();
      }
    });
  });

  document.querySelectorAll("[data-account-resend]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const original = btn.textContent;
      try {
        const res = await fetch("/api/auth/resend-verification", { method: "POST", headers: csrfHeaders({ "Accept": "application/json" }) });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || tr("auth_verification_failed", "Could not send verification email."));
        btn.textContent = out.message || tr("auth_verification_sent", "Verification email sent.");
      } catch (err) {
        btn.textContent = err?.message || tr("errors_try_again", "Please try again.");
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.textContent = original;
        }, 1800);
      }
    });
  });

  if (authOverlay) {
    authClose?.addEventListener("click", hideAuth);
    authOverlay.addEventListener("click", (e) => {
      if (e.target === authOverlay) hideAuth();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !authOverlay.hidden) hideAuth();
    });
    authSwitch?.addEventListener("click", () => {
      setAuthMode(authForm?.dataset.mode === "register" ? "login" : "register");
    });
    authForgot?.addEventListener("click", async () => {
      const email = (authEmail?.value || "").trim();
      if (!email) {
        if (authFeedback) authFeedback.textContent = tr("auth_enter_email_first", "Enter your email first.");
        return;
      }
      authForgot.disabled = true;
      try {
        const fd = addCsrfToFormData(new FormData());
        fd.set("email", email);
        const res = await fetch("/api/auth/request-password-reset", { method: "POST", headers: csrfHeaders({ "Accept": "application/json" }), body: fd });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || tr("auth_reset_failed", "Could not send reset email."));
        if (authFeedback) authFeedback.textContent = out.message || tr("auth_reset_sent", "If this email exists, we sent password reset instructions.");
      } catch (err) {
        if (authFeedback) authFeedback.textContent = err?.message || tr("errors_try_again", "Please try again.");
      } finally {
        authForgot.disabled = false;
      }
    });
    authResend?.addEventListener("click", async () => {
      const email = (authEmail?.value || "").trim();
      const fd = addCsrfToFormData(new FormData());
      if (email) fd.set("email", email);
      authResend.disabled = true;
      try {
        const res = await fetch("/api/auth/resend-verification", { method: "POST", headers: csrfHeaders({ "Accept": "application/json" }), body: fd });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || tr("auth_verification_failed", "Could not send verification email."));
        if (authFeedback) authFeedback.textContent = out.message || tr("auth_verification_sent", "Verification email sent.");
      } catch (err) {
        if (authFeedback) authFeedback.textContent = err?.message || tr("errors_try_again", "Please try again.");
      } finally {
        authResend.disabled = false;
      }
    });
    authForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const mode = authForm.dataset.mode === "register" ? "register" : "login";
      const endpoint = mode === "register" ? "/api/auth/register" : "/api/auth/login";
      const submitBtn = authSubmit || authForm.querySelector("button[type='submit']");
      if (authFeedback) authFeedback.textContent = "";
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: csrfHeaders({ "Accept": "application/json" }),
          body: addCsrfToFormData(new FormData(authForm))
        });
        const out = await res.json().catch(() => ({}));
        if (!res.ok || !out.ok) throw new Error(out.error || tr("auth_failed", "Authentication failed."));
        if (authFeedback) authFeedback.textContent = out.message || (mode === "register" ? tr("auth_check_email", "Check your email to confirm your account.") : tr("auth_logged_in", "Logged in."));
        if (authResend) authResend.hidden = !out.requiresVerification;
        setTimeout(() => window.location.reload(), out.requiresVerification ? 1400 : 500);
      } catch (err) {
        if (authFeedback) authFeedback.textContent = err?.message || tr("errors_try_again", "Please try again.");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // -------- Auto-submit star ratings --------
  document.querySelectorAll("[data-auto-rating-form]").forEach((form) => {
    const status = form.querySelector("[data-auto-rating-status]");
    form.addEventListener("change", (event) => {
      const input = event.target;
      if (!(input instanceof HTMLInputElement) || input.name !== "rating" || !input.checked) return;
      if (form.dataset.ratingSubmitting === "1") return;
      form.dataset.ratingSubmitting = "1";
      form.classList.add("is-submitting");
      if (status) status.textContent = tr("rating_saving", "Saving your rating...");
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  });

  // -------- CSS-only layout animations (JS only toggles visibility) --------
  const revealEls = Array.from(document.querySelectorAll("[data-reveal]"));
  if (revealEls.length) {
    document.body.classList.add("ag-motion");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
      revealEls.forEach((el) => io.observe(el));
    } else {
      revealEls.forEach((el) => el.classList.add("is-visible"));
    }
  }
})();

(function () {
  "use strict";

  function debounce(fn, delay) {
    let timer = 0;
    return function () {
      window.clearTimeout(timer);
      const args = arguments;
      timer = window.setTimeout(() => fn.apply(this, args), delay);
    };
  }

  function resetPage(form) {
    const page = form.querySelector('input[name="page"]');
    if (page) page.value = "1";
  }

  document.querySelectorAll("form[data-admin-filter]").forEach((form) => {
    const search = form.querySelector('input[name="q"], input[type="search"]');
    if (!search) return;
    const submit = debounce(() => {
      resetPage(form);
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
    }, 500);
    search.addEventListener("input", submit);
  });

  document.querySelectorAll(".ux-adminTableWrap").forEach((wrap) => {
    if (!wrap.querySelector("table")) return;
    wrap.setAttribute("data-ready", "true");
  });
})();

(function () {
  try {
    document.documentElement.classList.add("ag-hasGalleryJS");
  } catch (e) {
    // ignore
  }

  function initPlaceGallery() {
    var cards = Array.prototype.slice.call(document.querySelectorAll(".ag-placeCard"));
    if (!cards.length) return;

    // Reveal animation
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(
        function (entries, obs) {
          entries.forEach(function (e) {
            if (!e.isIntersecting) return;
            e.target.classList.add("is-in");
            obs.unobserve(e.target);
          });
        },
        { root: null, rootMargin: "80px", threshold: 0.12 }
      );
      cards.forEach(function (c) {
        io.observe(c);
      });
    } else {
      cards.forEach(function (c) {
        c.classList.add("is-in");
      });
    }

    // Image fade-in
    var imgs = Array.prototype.slice.call(document.querySelectorAll(".ag-placeCard-img"));
    imgs.forEach(function (img) {
      function mark() {
        img.classList.add("is-loaded");
      }
      if (img.complete && img.naturalWidth) {
        mark();
      } else {
        img.addEventListener("load", mark, { once: true });
        img.addEventListener("error", mark, { once: true });
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPlaceGallery);
  } else {
    initPlaceGallery();
  }
})();


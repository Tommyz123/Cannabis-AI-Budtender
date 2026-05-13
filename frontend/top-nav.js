/**
 * TopNav — wires the top navigation bar.
 *
 * Owns:
 *   - global search input → Store.setManual("query", value) on input
 *   - cart trigger → opens the cart drawer (handled by cart.js elsewhere)
 *
 * The search box debounces typing so the grid doesn't re-render on every
 * keystroke. After 180ms of stillness the value lands in Store.
 *
 * No subscribe — the input is one-way (user → store). It does NOT mirror
 * Store back into the field, because the AI doesn't issue free-text queries.
 */
(() => {
  const DEBOUNCE_MS = 180;

  function init() {
    const search = document.getElementById("global-search");
    if (search) {
      let timer = null;
      search.addEventListener("input", () => {
        const v = search.value.trim();
        clearTimeout(timer);
        timer = setTimeout(() => {
          window.Store.setManual("query", v);
        }, DEBOUNCE_MS);
      });
      // Enter triggers immediately (cancel debounce)
      search.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          clearTimeout(timer);
          window.Store.setManual("query", search.value.trim());
        }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

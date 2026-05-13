/**
 * CategoryBar — horizontal scrollable category chips below the top nav.
 *
 * Behavior:
 *   - Renders one chip per category from Store.state.filterMetadata.categories
 *     (after /filters has loaded).
 *   - "All" is the first chip; clicking it clears the category filter.
 *   - Active chip mirrors Store.state.filters.category.
 *   - Click → Store.setManual("category", name).
 *   - Subscribes to ai_filters_applied / filters_reset / metadata_loaded so
 *     when the AI sets category=Flower, the matching chip lights up.
 *
 * Emoji map is shared with placeholders.js (CATEGORY_EMOJI).
 */
(() => {
  const list = () => document.getElementById("cat-list");

  function render() {
    const el = list();
    if (!el) return;
    const meta = window.Store.state.filterMetadata;
    if (!meta || !Array.isArray(meta.categories)) {
      el.innerHTML = "";
      return;
    }
    const current = window.Store.state.filters.category;
    const total = meta.total || 0;

    const allChip = `
      <li class="cat-item">
        <button
          class="cat-chip${current === null ? " active" : ""}"
          data-category=""
          type="button"
          role="tab"
          aria-selected="${current === null}">
          <span class="cat-chip-emoji">🌐</span>
          <span class="cat-chip-label">All</span>
          <span class="cat-chip-count">${total}</span>
        </button>
      </li>
    `;

    const items = meta.categories
      .map((c) => {
        const emoji = (window.CATEGORY_EMOJI && window.CATEGORY_EMOJI[c.name]) || "🌿";
        const isActive = current === c.name;
        return `
          <li class="cat-item">
            <button
              class="cat-chip${isActive ? " active" : ""}"
              data-category="${escapeAttr(c.name)}"
              type="button"
              role="tab"
              aria-selected="${isActive}">
              <span class="cat-chip-emoji">${emoji}</span>
              <span class="cat-chip-label">${escapeHTML(c.name)}</span>
              <span class="cat-chip-count">${c.count}</span>
            </button>
          </li>
        `;
      })
      .join("");

    el.innerHTML = allChip + items;
  }

  function onClick(e) {
    const btn = e.target.closest(".cat-chip");
    if (!btn) return;
    const name = btn.getAttribute("data-category") || "";
    window.Store.setManual("category", name || null);
  }

  function init() {
    const el = list();
    if (!el) return;
    el.addEventListener("click", onClick);

    window.Store.subscribe((event) => {
      if (
        event.type === "metadata_loaded" ||
        event.type === "manual_filter_change" ||
        event.type === "ai_filters_applied" ||
        event.type === "filter_removed" ||
        event.type === "filters_reset"
      ) {
        render();
      }
    });
  }

  // Tiny HTML helpers (avoid pulling in a util module just for this).
  function escapeHTML(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function escapeAttr(s) {
    return escapeHTML(s).replace(/"/g, "&quot;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

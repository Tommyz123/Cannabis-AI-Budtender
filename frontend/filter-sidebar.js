/**
 * FilterSidebar — the HW-style left rail.
 *
 * Sections rendered (top → bottom):
 *   1. On Sale toggle
 *   2. Strain (Hybrid / Indica / Sativa / Indica-Hybrid / Sativa-Hybrid)
 *   3. Price slider (max_price)
 *   4. THC% slider (max_thc; uses thc_pct_range from /filters)
 *   5. Effects (Happy, Relaxed, Energetic, …) — checklist
 *   6. Brands — checklist with a search filter on top
 *
 * Bi-directional binding:
 *   - User clicks → Store.setManual / toggleArrayItem
 *   - Store changes (AI or chip ×) → re-render checked state
 *
 * Reset button clears Store.filters (Store.resetAll).
 */
(() => {
  let brandQuery = "";

  function root() {
    return document.getElementById("sidebar-sections");
  }

  function render() {
    const el = root();
    if (!el) return;
    const meta = window.Store.state.filterMetadata;
    if (!meta) {
      el.innerHTML = '<div class="sidebar-loading">Loading filters…</div>';
      return;
    }
    const f = window.Store.state.filters;

    el.innerHTML = [
      renderOnSale(meta, f),
      renderStrains(meta, f),
      renderPriceSlider(meta, f),
      renderThcSlider(meta, f),
      renderEffects(meta, f),
      renderBrands(meta, f),
    ].join("");
  }

  // ── On Sale ─────────────────────────────────────────────────────────
  function renderOnSale(meta, f) {
    return `
      <section class="filter-section">
        <label class="sale-toggle">
          <input
            type="checkbox"
            data-toggle-sale
            ${f.on_sale ? "checked" : ""}
          />
          <span>On sale only <span class="filter-option-count">(${meta.on_sale_count})</span></span>
        </label>
      </section>
    `;
  }

  // ── Strain types ────────────────────────────────────────────────────
  function renderStrains(meta, f) {
    const items = (meta.strain_types || [])
      .map((s) => {
        const checked = f.strain_type.includes(s.name);
        return `
          <label class="filter-option">
            <span class="filter-option-label">
              <input
                type="checkbox"
                data-multi="strain_type"
                data-value="${escapeAttr(s.name)}"
                ${checked ? "checked" : ""}
              />
              ${escapeHTML(s.name)}
            </span>
            <span class="filter-option-count">${s.count}</span>
          </label>
        `;
      })
      .join("");
    return `
      <section class="filter-section">
        <h3 class="filter-section-title">Strain</h3>
        ${items}
      </section>
    `;
  }

  // ── Price slider ────────────────────────────────────────────────────
  function renderPriceSlider(meta, f) {
    const min = Math.floor(meta.price_range.min);
    const max = Math.ceil(meta.price_range.max);
    const cur = typeof f.max_price === "number" ? f.max_price : max;
    return `
      <section class="filter-section">
        <h3 class="filter-section-title">Max price</h3>
        <div class="range-slider-wrap">
          <input
            type="range"
            data-range="max_price"
            min="${min}"
            max="${max}"
            step="1"
            value="${cur}"
          />
          <div class="range-slider-display">
            <span>$${min}</span>
            <span><strong data-range-display="max_price">$${cur}</strong></span>
            <span>$${max}</span>
          </div>
        </div>
      </section>
    `;
  }

  // ── THC% slider ─────────────────────────────────────────────────────
  function renderThcSlider(meta, f) {
    const r = meta.thc_pct_range || { min: 0, max: 100 };
    const min = Math.floor(r.min);
    const max = Math.ceil(r.max);
    const cur = typeof f.max_thc === "number" ? f.max_thc : max;
    return `
      <section class="filter-section">
        <h3 class="filter-section-title">Max THC (%)</h3>
        <div class="range-slider-wrap">
          <input
            type="range"
            data-range="max_thc"
            min="${min}"
            max="${max}"
            step="1"
            value="${cur}"
          />
          <div class="range-slider-display">
            <span>${min}%</span>
            <span><strong data-range-display="max_thc">${cur}%</strong></span>
            <span>${max}%</span>
          </div>
        </div>
      </section>
    `;
  }

  // ── Effects ─────────────────────────────────────────────────────────
  function renderEffects(meta, f) {
    const items = (meta.effects || [])
      .map((e) => {
        const checked = f.effects.includes(e.name);
        return `
          <label class="filter-option">
            <span class="filter-option-label">
              <input
                type="checkbox"
                data-multi="effects"
                data-value="${escapeAttr(e.name)}"
                ${checked ? "checked" : ""}
              />
              ${escapeHTML(e.name)}
            </span>
            <span class="filter-option-count">${e.count}</span>
          </label>
        `;
      })
      .join("");
    return `
      <section class="filter-section">
        <h3 class="filter-section-title">Effects</h3>
        ${items}
      </section>
    `;
  }

  // ── Brands (with search) ────────────────────────────────────────────
  function renderBrands(meta, f) {
    const q = brandQuery.toLowerCase();
    const brands = (meta.brands || []).filter(
      (b) => !q || b.name.toLowerCase().includes(q)
    );
    const items = brands
      .map((b) => {
        const checked = f.brand.includes(b.name);
        return `
          <label class="filter-option">
            <span class="filter-option-label">
              <input
                type="checkbox"
                data-multi="brand"
                data-value="${escapeAttr(b.name)}"
                ${checked ? "checked" : ""}
              />
              ${escapeHTML(b.name)}
            </span>
            <span class="filter-option-count">${b.count}</span>
          </label>
        `;
      })
      .join("");
    const empty =
      brands.length === 0
        ? '<div class="filter-option-count" style="text-align:center;padding:8px;">No brands match</div>'
        : "";
    return `
      <section class="filter-section">
        <h3 class="filter-section-title">Brands</h3>
        <div class="brand-search-wrap">
          <input
            type="search"
            placeholder="Search brands…"
            value="${escapeAttr(brandQuery)}"
            data-brand-search
          />
        </div>
        <div class="brand-list">
          ${items || empty}
        </div>
      </section>
    `;
  }

  // ── Event delegation ────────────────────────────────────────────────
  function bind() {
    const el = root();
    if (!el) return;

    // Checkbox toggles
    el.addEventListener("change", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement)) return;

      if (t.matches("[data-toggle-sale]")) {
        window.Store.setManual("on_sale", t.checked);
        return;
      }
      const multi = t.getAttribute("data-multi");
      if (multi) {
        const value = t.getAttribute("data-value") || "";
        window.Store.toggleArrayItem(multi, value);
      }
    });

    // Range sliders — live display, commit on `change` (mouseup / keyup)
    el.addEventListener("input", (e) => {
      const t = e.target;
      if (t instanceof HTMLInputElement) {
        const field = t.getAttribute("data-range");
        if (field) {
          const display = el.querySelector(`[data-range-display="${field}"]`);
          if (display) {
            display.textContent =
              field === "max_price" ? `$${t.value}` : `${t.value}%`;
          }
        }
        // Brand search — re-render brand list only
        if (t.matches("[data-brand-search]")) {
          brandQuery = t.value;
          // Local re-render — preserve other section state by re-rendering all
          // (cheap: dataset is small). Avoids subtle focus-loss on the input
          // by restoring focus after.
          render();
          const again = root().querySelector("[data-brand-search]");
          if (again) {
            again.focus();
            // place caret at end
            const v = again.value;
            again.value = "";
            again.value = v;
          }
        }
      }
    });

    el.addEventListener("change", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLInputElement)) return;
      const field = t.getAttribute("data-range");
      if (field) {
        const n = Number(t.value);
        const meta = window.Store.state.filterMetadata || {};
        // If user maxes out the slider, treat it as "no cap" so we don't keep
        // an unnecessary chip in the active filters row.
        let max = null;
        if (field === "max_price") max = Math.ceil(meta.price_range?.max ?? n);
        if (field === "max_thc") max = Math.ceil(meta.thc_pct_range?.max ?? n);
        const isMax = max !== null && n >= max;
        window.Store.setManual(field, isMax ? null : n);
      }
    });

    // Reset button
    const reset = document.getElementById("sidebar-reset");
    if (reset) {
      reset.addEventListener("click", () => {
        brandQuery = "";
        window.Store.resetAll();
      });
    }
  }

  function init() {
    bind();
    window.Store.subscribe((event) => {
      if (
        event.type === "metadata_loaded" ||
        event.type === "ai_filters_applied" ||
        event.type === "filter_removed" ||
        event.type === "filters_reset"
      ) {
        render();
      }
      // For manual_filter_change, skip re-render: the user just clicked,
      // their own DOM is already in sync. Re-rendering would flicker.
    });
  }

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

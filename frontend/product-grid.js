/**
 * ProductGrid module — renders the product grid, filter chips, and top-pick row.
 *
 * Public API (locked for Module 6):
 *   ProductGrid.init() -> Promise<void>
 *   ProductGrid.applyUIAction(uiAction) -> Promise<void>    // resolves ~700ms
 *   ProductGrid.pulseSpoken(productIds: number[]) -> void
 *
 * Internal state is private to this IIFE.
 *
 * Filter-chip removal emits a CustomEvent `filter-chip-removed`
 * with detail { field, value }. Module 6 (chat.js refactor) will listen for it.
 * This module does NOT wire chip-× click handlers yet.
 */

const ProductGrid = (() => {
  const state = {
    allProducts: [],
    byId: new Map(),
    currentFilters: {},
    spokenIds: new Set(),
    pickIds: new Set(),
    picks: [],
    totalMatched: null, // null = no filter applied; show all
  };

  // ── DOM refs (resolved on init) ─────────────────────────────────────
  let gridEl = null;
  let chipsEl = null;
  let metaEl = null;
  let pickRowEl = null;
  let pickCardsEl = null;

  // ── Public ──────────────────────────────────────────────────────────

  async function init() {
    gridEl = document.getElementById("product-grid");
    chipsEl = document.getElementById("filter-chips");
    metaEl = document.getElementById("result-meta");
    pickRowEl = document.getElementById("top-pick-row");
    pickCardsEl = document.getElementById("top-pick-cards");

    try {
      const res = await fetch(`${API_BASE}/products`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.allProducts = Array.isArray(data.products) ? data.products : [];
    } catch (err) {
      // Backend missing /products (Module 4 not yet done) — graceful degrade
      state.allProducts = [];
      if (metaEl) {
        metaEl.textContent =
          "Could not load products (backend /products endpoint not available).";
      }
      console.warn("ProductGrid.init: /products fetch failed:", err);
    }

    state.byId = new Map();
    for (const p of state.allProducts) {
      if (p && typeof p.id === "number") state.byId.set(p.id, p);
    }

    // Let Cart resolve names/prices when rendering the drawer
    if (window.Cart && typeof window.Cart.setProductLookup === "function") {
      window.Cart.setProductLookup((id) => state.byId.get(id) || null);
    }

    renderGrid();
    renderChips();
    renderPicks([]);
    updateMeta(null);

    wireGridClicks();
  }

  function applyUIAction(uiAction) {
    return new Promise((resolve) => {
      const action = uiAction || {};
      const newFilters = action.filters || {};
      const newPicks = action.picks || [];

      // Determine which chips are newly added (for .new slide-in animation)
      const prevKeys = chipKeysOf(state.currentFilters);
      const nextKeys = chipKeysOf(newFilters);
      const newlyAdded = new Set();
      for (const k of nextKeys) if (!prevKeys.has(k)) newlyAdded.add(k);

      state.currentFilters = newFilters;
      state.picks = newPicks;
      state.pickIds = new Set(newPicks.map((p) => p.id));
      state.totalMatched =
        typeof action.total_matched === "number" ? action.total_matched : null;

      // T+0: chips render with .new class on newly added
      renderChips(newlyAdded);

      // T+250: grid re-renders (matched vs dim)
      setTimeout(() => {
        renderGrid();
        // T+700: pick row renders with stagger; meta updates; resolve
        setTimeout(() => {
          renderPicks(newPicks);
          updateMeta(state.totalMatched);
          resolve();
        }, 450);
      }, 250);
    });
  }

  function pulseSpoken(ids) {
    const list = Array.isArray(ids) ? ids : [];
    state.spokenIds = new Set(list);
    let firstScrolled = false;
    list.forEach((id) => {
      const card = document.querySelector(`.product-card[data-id="${id}"]`);
      if (card) {
        card.classList.remove("pulse");
        // force reflow to restart animation if applied repeatedly
        void card.offsetWidth;
        card.classList.add("pulse");
        if (!firstScrolled) {
          firstScrolled = true;
          card.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        setTimeout(() => card.classList.remove("pulse"), 1600);
      }
    });
  }

  // ── Filter / matching logic ─────────────────────────────────────────

  function matches(product, filters) {
    if (!filters) return true;
    if (filters.category && product.cat !== filters.category) return false;
    if (filters.strain_type && product.t !== filters.strain_type) return false;
    if (filters.effects) {
      const wanted = Array.isArray(filters.effects)
        ? filters.effects
        : [filters.effects];
      const has = (product.f || "").toLowerCase();
      const hit = wanted.some((w) => has.includes(String(w).toLowerCase()));
      if (!hit) return false;
    }
    if (typeof filters.max_price === "number") {
      if ((product.p || 0) > filters.max_price) return false;
    }
    return true;
  }

  function chipKeysOf(filters) {
    const keys = new Set();
    if (!filters) return keys;
    for (const [field, value] of Object.entries(filters)) {
      if (Array.isArray(value)) {
        for (const v of value) keys.add(`${field}:${v}`);
      } else if (value !== null && value !== undefined && value !== "") {
        keys.add(`${field}:${value}`);
      }
    }
    return keys;
  }

  // ── Render: filter chips ────────────────────────────────────────────

  const FIELD_LABEL = {
    category: "Form",
    strain_type: "Strain",
    effects: "Effect",
    max_price: "Under",
  };

  function chipText(field, value) {
    if (field === "max_price") return `Under $${value}`;
    return `${FIELD_LABEL[field] || field}: ${value}`;
  }

  function renderChips(newlyAdded = new Set()) {
    if (!chipsEl) return;
    const filters = state.currentFilters || {};
    const tags = [];
    for (const [field, value] of Object.entries(filters)) {
      if (value === null || value === undefined || value === "") continue;
      if (Array.isArray(value)) {
        for (const v of value) tags.push({ field, value: v });
      } else {
        tags.push({ field, value });
      }
    }

    if (tags.length === 0) {
      chipsEl.innerHTML = "";
      return;
    }

    chipsEl.innerHTML = tags
      .map(({ field, value }) => {
        const key = `${field}:${value}`;
        const isNew = newlyAdded.has(key);
        const label = chipText(field, value);
        const ariaVal = String(value);
        return `
          <button
            class="filter-chip${isNew ? " new" : ""}"
            data-field="${field}"
            data-value="${escapeAttr(ariaVal)}"
            aria-label="Remove ${escapeAttr(label)} filter">
            <span class="chip-text">${escapeHTML(label)}</span>
            <span class="chip-x" aria-hidden="true">×</span>
          </button>
        `;
      })
      .join("");
  }

  // ── Render: product grid ────────────────────────────────────────────

  function renderGrid() {
    if (!gridEl) return;
    const filters = state.currentFilters || {};
    const hasFilters = Object.keys(filters).length > 0;

    const html = state.allProducts
      .map((p) => productCardHTML(p, hasFilters && !matches(p, filters), false))
      .join("");
    gridEl.innerHTML = html;
  }

  function productCardHTML(product, isDim, isPickContext) {
    const placeholder = makePlaceholder(product);
    const isPick = state.pickIds.has(product.id);
    const isSpoken = state.spokenIds.has(product.id);
    const classes = ["product-card"];
    if (isDim) classes.push("dim");
    if (isPick && !isPickContext) classes.push("is-pick");
    if (isSpoken) classes.push("pulse");
    if (isPickContext) classes.push("pick-card");

    const saleBadge = product.sale
      ? `<div class="sale-badge">SALE -${product.disc}%</div>`
      : "";
    const priceHTML = product.sale
      ? `<span class="price-sale">$${formatPrice(product.p)}</span>
         <span class="price-original">$${formatPrice(product.op)}</span>`
      : `<span class="price">$${formatPrice(product.p)}</span>`;

    const thcHTML = product.thc
      ? `<span class="thc">THC ${escapeHTML(product.thc)}</span>`
      : "";

    const pickReason =
      isPickContext && product.pick_reason
        ? `<div class="pick-reason">${escapeHTML(product.pick_reason)}</div>`
        : "";

    return `
      <article class="${classes.join(" ")}" data-id="${product.id}" role="listitem">
        ${saleBadge}
        ${placeholder}
        <div class="product-body">
          <div class="product-name" title="${escapeAttr(product.s)}">${escapeHTML(
      product.s
    )}</div>
          <div class="product-brand">${escapeHTML(product.c || "")}</div>
          <div class="product-meta">
            ${priceHTML}
            ${thcHTML}
          </div>
          <button class="add-btn" data-id="${product.id}" aria-label="Add ${escapeAttr(
      product.s
    )} to cart">Add</button>
        </div>
        ${pickReason}
      </article>
    `;
  }

  // ── Render: top-pick row ────────────────────────────────────────────

  function renderPicks(picks) {
    if (!pickRowEl || !pickCardsEl) return;
    if (!picks || picks.length === 0) {
      pickRowEl.hidden = true;
      pickCardsEl.innerHTML = "";
      return;
    }
    pickRowEl.hidden = false;
    pickCardsEl.innerHTML = picks
      .map((p, idx) => {
        // Merge pick_reason into product data for rendering
        const fullProduct = state.byId.get(p.id) || p;
        const merged = Object.assign({}, fullProduct, {
          pick_reason: p.pick_reason || p.reason || "",
        });
        const html = productCardHTML(merged, false, true);
        // Wrap in a stagger animation by adding a style with delay
        return html.replace(
          '<article ',
          `<article style="animation-delay:${idx * 80}ms" `
        );
      })
      .join("");
  }

  // ── Meta line ───────────────────────────────────────────────────────

  function updateMeta(totalMatched) {
    if (!metaEl) return;
    const total = state.allProducts.length;
    if (totalMatched === null || totalMatched === undefined) {
      metaEl.textContent = `Showing ${total} of ${total}`;
    } else {
      metaEl.textContent = `Showing ${totalMatched} of ${total}`;
    }
  }

  // ── Click delegation ────────────────────────────────────────────────

  function wireGridClicks() {
    document.addEventListener("click", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;

      // Add-to-cart from grid and pick row
      if (t.classList.contains("add-btn")) {
        const id = Number(t.getAttribute("data-id"));
        if (Number.isFinite(id) && window.Cart) {
          window.Cart.add(id);
          // Brief visual pulse on the button
          t.classList.add("added");
          setTimeout(() => t.classList.remove("added"), 600);
        }
        return;
      }

      // Filter chip × removal — bubble up from inner span to the button
      const chipBtn = t.closest(".filter-chip");
      if (chipBtn instanceof HTMLElement) {
        const field = chipBtn.getAttribute("data-field");
        const value = chipBtn.getAttribute("data-value");
        if (field && value !== null) {
          window.dispatchEvent(
            new CustomEvent("filter-chip-removed", {
              detail: { field, value },
            })
          );
        }
      }
    });
  }

  // ── Utility ─────────────────────────────────────────────────────────

  function formatPrice(p) {
    const n = Number(p) || 0;
    return n.toFixed(2);
  }

  function escapeHTML(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHTML(s);
  }

  return { init, applyUIAction, pulseSpoken };
})();

window.ProductGrid = ProductGrid;

// Auto-init on DOMContentLoaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    ProductGrid.init();
  });
} else {
  ProductGrid.init();
}

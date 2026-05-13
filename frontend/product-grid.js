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
    compareIds: new Set(), // products selected for comparison
  };

  // ── DOM refs (resolved on init) ─────────────────────────────────────
  let gridEl = null;
  let gridTitleEl = null;
  let chipsEl = null;
  let metaEl = null;
  let pickRowEl = null;
  let pickCardsEl = null;

  // ── Public ──────────────────────────────────────────────────────────

  async function init() {
    gridEl = document.getElementById("product-grid");
    gridTitleEl = document.getElementById("grid-title");
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
    const hasPicks = state.picks && state.picks.length > 0;

    const products = hasFilters
      ? state.allProducts.filter((p) => matches(p, filters))
      : state.allProducts;

    if (gridTitleEl) {
      gridTitleEl.hidden = !(hasFilters && hasPicks && products.length > 0);
    }

    if (hasFilters && products.length === 0) {
      gridEl.innerHTML =
        '<div class="grid-empty">No other products match these filters. Try removing one of the chips above.</div>';
      return;
    }

    const html = products
      .map((p) => productCardHTML(p, false, false))
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
    const inCompare = state.compareIds.has(product.id);
    const compareChip = isPickContext
      ? ""
      : `<button class="compare-chip${
          inCompare ? " active" : ""
        }" data-compare-toggle="${product.id}" aria-label="${
          inCompare ? "Remove from compare" : "Add to compare"
        }">${inCompare ? "✓" : "+"}</button>`;
    const priceHTML = product.sale
      ? `<span class="price-sale">$${formatPrice(product.p)}</span>`
      : `<span class="price">$${formatPrice(product.p)}</span>`;

    const thcHTML = product.thc
      ? `<span class="thc">THC ${escapeHTML(product.thc)}</span>`
      : "";

    const strainBadgeHTML = product.t
      ? `<span class="strain-badge strain-${strainClass(product.t)}" title="${escapeAttr(
          product.t
        )}">${escapeHTML(product.t)}</span>`
      : "";

    const pickReason =
      isPickContext && product.pick_reason
        ? `<div class="pick-reason">${escapeHTML(product.pick_reason)}</div>`
        : "";

    return `
      <article class="${classes.join(" ")}" data-id="${product.id}" role="listitem">
        ${saleBadge}
        ${compareChip}
        ${placeholder}
        <div class="product-body">
          <div class="product-name" title="${escapeAttr(product.s)}">${escapeHTML(
      product.s
    )}</div>
          <div class="product-brand">${escapeHTML(product.c || "")}</div>
          <div class="product-tags">
            ${strainBadgeHTML}
            <span class="category-badge">${escapeHTML(product.cat || "")}</span>
          </div>
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

      // Modal close
      if (t.hasAttribute("data-modal-close")) {
        closeModal();
        return;
      }

      // Quick-question chip inside modal → send to chat
      if (t.hasAttribute("data-quick-q")) {
        const q = t.getAttribute("data-quick-q") || "";
        if (q && window.Chat && typeof window.Chat.ask === "function") {
          const sent = window.Chat.ask(q);
          if (sent) closeModal();
        }
        return;
      }

      // Compare toggle (in modal or on card chip)
      if (t.hasAttribute("data-compare-toggle")) {
        const id = Number(t.getAttribute("data-compare-toggle"));
        if (Number.isFinite(id)) toggleCompare(id);
        e.stopPropagation();
        return;
      }

      // Compare tray actions
      if (t.hasAttribute("data-compare-action")) {
        const action = t.getAttribute("data-compare-action");
        if (action === "go") doCompare();
        else if (action === "clear") clearCompare();
        return;
      }

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
        return;
      }

      // Product card click → open detail modal
      // (only when not clicking interactive elements above)
      const card = t.closest(".product-card");
      if (card instanceof HTMLElement) {
        const id = Number(card.getAttribute("data-id"));
        if (Number.isFinite(id)) openModal(id);
      }
    });

    // Esc to close modal
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeModal();
    });
  }

  // ── Compare: tray + state ───────────────────────────────────────────

  const MAX_COMPARE = 3;

  function toggleCompare(id) {
    if (state.compareIds.has(id)) {
      state.compareIds.delete(id);
    } else {
      if (state.compareIds.size >= MAX_COMPARE) {
        // Drop the oldest (first insertion) to make room
        const oldest = state.compareIds.values().next().value;
        if (oldest !== undefined) state.compareIds.delete(oldest);
      }
      state.compareIds.add(id);
    }
    renderCompareTray();
    // Refresh modal if open so toggle button updates
    const modal = document.getElementById("product-modal");
    if (modal && !modal.hidden) {
      // Re-render only if we have a current product still in modal
      const titleEl = document.getElementById("modal-title");
      if (titleEl) {
        const p = [...state.byId.values()].find((x) => x.s === titleEl.textContent);
        if (p) openModal(p.id);
      }
    }
    // Refresh card chips
    refreshCompareChipsOnCards();
  }

  function clearCompare() {
    state.compareIds.clear();
    renderCompareTray();
    refreshCompareChipsOnCards();
  }

  function doCompare() {
    if (state.compareIds.size < 2) return;
    const names = [...state.compareIds]
      .map((id) => state.byId.get(id))
      .filter(Boolean)
      .map((p) => p.s);
    if (names.length < 2) return;
    const msg =
      names.length === 2
        ? `How does ${names[0]} compare to ${names[1]}?`
        : `Please compare these products: ${names.join(", ")}.`;
    if (window.Chat && typeof window.Chat.ask === "function") {
      const sent = window.Chat.ask(msg);
      if (sent) {
        clearCompare();
        closeModal();
      }
    }
  }

  function refreshCompareChipsOnCards() {
    document.querySelectorAll(".compare-chip").forEach((el) => {
      const id = Number(el.getAttribute("data-compare-toggle"));
      const on = state.compareIds.has(id);
      el.classList.toggle("active", on);
      el.textContent = on ? "✓" : "+";
      el.setAttribute("aria-label", on ? "Remove from compare" : "Add to compare");
    });
  }

  function renderCompareTray() {
    let tray = document.getElementById("compare-tray");
    if (!tray) {
      tray = document.createElement("div");
      tray.id = "compare-tray";
      document.body.appendChild(tray);
    }
    const ids = [...state.compareIds];
    if (ids.length === 0) {
      tray.hidden = true;
      tray.innerHTML = "";
      return;
    }
    tray.hidden = false;
    const items = ids
      .map((id) => state.byId.get(id))
      .filter(Boolean)
      .map(
        (p) =>
          `<span class="compare-tray-item">
            ${escapeHTML(p.s)}
            <button class="compare-tray-x" data-compare-toggle="${p.id}" aria-label="Remove ${escapeAttr(
            p.s
          )} from compare">×</button>
          </span>`
      )
      .join("");
    const canGo = ids.length >= 2;
    tray.innerHTML = `
      <div class="compare-tray-inner">
        <div class="compare-tray-label">Compare (${ids.length}/${MAX_COMPARE}):</div>
        <div class="compare-tray-items">${items}</div>
        <div class="compare-tray-actions">
          <button class="compare-tray-clear" data-compare-action="clear">Clear</button>
          <button class="compare-tray-go" data-compare-action="go" ${
            canGo ? "" : "disabled"
          }>Compare in chat →</button>
        </div>
      </div>
    `;
  }

  // ── Modal: product detail ───────────────────────────────────────────

  function openModal(productId) {
    const modal = document.getElementById("product-modal");
    const body = document.getElementById("modal-body");
    const product = state.byId.get(productId);
    if (!modal || !body || !product) return;

    body.innerHTML = renderDetailHTML(product);
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    const modal = document.getElementById("product-modal");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function renderDetailHTML(p) {
    const placeholder = makePlaceholder(p);
    const saleBadge = p.sale
      ? `<span class="modal-sale-badge">SALE −${p.disc}%</span>`
      : "";
    const priceHTML = p.sale
      ? `<span class="modal-price-sale">$${formatPrice(p.p)}</span>`
      : `<span class="modal-price">$${formatPrice(p.p)}</span>`;

    const subtitleParts = [p.c, p.cat, p.t].filter(Boolean);
    const subtitle = subtitleParts.map(escapeHTML).join(" · ");

    const narrative = buildNarrative(p);
    const quickQs = buildQuickQuestions(p);

    const rows = [];
    const pushRow = (label, value) => {
      if (value === null || value === undefined || value === "") return;
      rows.push(
        `<div class="modal-row"><span class="modal-row-label">${escapeHTML(
          label
        )}</span><span class="modal-row-value">${escapeHTML(value)}</span></div>`
      );
    };
    pushRow("Size", p.wt);
    pushRow("THC", p.thc);
    pushRow("Effects", (p.f || "").split(",").join(", "));
    pushRow("Flavor", (p.flv || "").split(",").join(", "));
    pushRow("Best for", (p.sc || "").split(",").join(", "));
    pushRow("Time of day", p.tod);
    pushRow("Experience level", p.xl);
    pushRow("Consumption", p.cm);
    pushRow("Onset", p.on);
    pushRow("Duration", p.dur);
    pushRow("Sub-category", p.sub);
    pushRow("Price tier", p.pr);

    const inCompare = state.compareIds.has(p.id);
    const compareLabel = inCompare ? "✓ In Compare" : "+ Compare";

    return `
      <div class="modal-header">
        <div class="modal-placeholder">${placeholder}</div>
        <div class="modal-header-text">
          <h2 id="modal-title" class="modal-title">${escapeHTML(p.s)}</h2>
          <div class="modal-subtitle">${subtitle}</div>
          <div class="modal-price-row">
            ${priceHTML}
            ${saleBadge}
          </div>
        </div>
      </div>

      <div class="modal-section-label">Product details</div>
      <div class="modal-rows">
        ${rows.join("")}
      </div>

      <div class="modal-section-label">Budtender's note</div>
      <div class="modal-narrative">${narrative}</div>

      <div class="modal-quick-qs">
        <div class="modal-quick-qs-label">Ask the budtender:</div>
        <div class="modal-quick-qs-row">
          ${quickQs
            .map(
              (q) =>
                `<button class="quick-q-btn" data-quick-q="${escapeAttr(
                  q.send
                )}">${escapeHTML(q.label)}</button>`
            )
            .join("")}
        </div>
      </div>

      <div class="modal-actions">
        <button class="compare-toggle-btn${
          inCompare ? " active" : ""
        }" data-compare-toggle="${p.id}">${compareLabel}</button>
        <button class="add-btn modal-add-btn" data-id="${p.id}" aria-label="Add ${escapeAttr(
      p.s
    )} to cart">Add to Cart</button>
      </div>
    `;
  }

  // ── Narrative: budtender-style product intro ────────────────────────

  function buildNarrative(p) {
    const name = `<strong>${escapeHTML(p.s)}</strong>`;
    const brand = p.c ? ` by ${escapeHTML(p.c)}` : "";
    const strain = p.t ? escapeHTML(p.t).toLowerCase() : "";
    const cat = p.cat ? escapeHTML(p.cat).toLowerCase() : "product";
    const sentences = [];

    // Lead-in
    let lead = `Meet ${name}${brand} — a ${strain ? strain + " " : ""}${cat}`;
    if (p.thc) lead += ` packing ${escapeHTML(p.thc)} THC`;
    if (p.wt) lead += ` (${escapeHTML(p.wt)})`;
    lead += ".";
    sentences.push(lead);

    // Effects + vibe
    const effects = (p.f || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (effects.length > 0) {
      const top = effects.slice(0, 3).map((e) => e.toLowerCase());
      const lastJoined =
        top.length > 1
          ? top.slice(0, -1).join(", ") + " and " + top[top.length - 1]
          : top[0];
      const scenario = p.sc
        ? ` — well-suited for ${escapeHTML(p.sc.toLowerCase().replace(/,/g, ", "))}`
        : "";
      sentences.push(`Expect ${escapeHTML(lastJoined)} vibes${scenario}.`);
    }

    // Flavor
    const flv = (p.flv || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (flv.length > 0) {
      const list =
        flv.length > 1
          ? flv.slice(0, -1).join(", ") + " and " + flv[flv.length - 1]
          : flv[0];
      sentences.push(`Flavor leans ${escapeHTML(list)}.`);
    }

    // Onset + duration + time of day
    const practical = [];
    if (p.on) practical.push(`kicks in ${escapeHTML(p.on)}`);
    if (p.dur) practical.push(`lasts ${escapeHTML(p.dur)}`);
    if (practical.length > 0) {
      let s = capitalize(practical.join(", "));
      if (p.tod) s += ` — a ${escapeHTML(p.tod.toLowerCase())} pick`;
      s += ".";
      sentences.push(s);
    }

    // Experience guidance
    if (p.xl) {
      const xl = p.xl.toLowerCase();
      if (xl.includes("beginner") || xl.includes("new")) {
        sentences.push("Friendly for newcomers — start low and go slow.");
      } else if (xl.includes("experienced")) {
        sentences.push("Best for experienced users — this one packs a punch.");
      } else if (xl.includes("intermediate")) {
        sentences.push("A solid fit for intermediate users.");
      }
    }

    return sentences.join(" ");
  }

  function capitalize(s) {
    return s ? s[0].toUpperCase() + s.slice(1) : s;
  }

  // ── Quick-question chips ────────────────────────────────────────────

  function buildQuickQuestions(p) {
    const name = p.s;
    const list = [
      { label: "Tell me more", send: `Tell me more about ${name}` },
      { label: "How strong is it?", send: `How strong is ${name}?` },
      {
        label: "How fast does it hit?",
        send: `How fast does ${name} hit and how long does it last?`,
      },
    ];
    // Beginner-relevant context
    if (p.xl && /experienced/i.test(p.xl)) {
      list.push({
        label: "Is this OK for a beginner?",
        send: `Is ${name} OK for a beginner, or should I pick something lighter?`,
      });
    } else {
      list.push({
        label: "Good for relaxing?",
        send: `Is ${name} good for relaxing in the evening?`,
      });
    }
    return list;
  }

  // ── Utility ─────────────────────────────────────────────────────────

  function formatPrice(p) {
    const n = Number(p) || 0;
    return n.toFixed(2);
  }

  function strainClass(strainType) {
    const s = String(strainType || "").toLowerCase();
    if (s.includes("sativa") && s.includes("hybrid")) return "sativa-hybrid";
    if (s.includes("indica") && s.includes("hybrid")) return "indica-hybrid";
    if (s.includes("sativa")) return "sativa";
    if (s.includes("indica")) return "indica";
    if (s.includes("hybrid")) return "hybrid";
    if (s.includes("cbd")) return "cbd";
    return "other";
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

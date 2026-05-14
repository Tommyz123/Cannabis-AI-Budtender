/**
 * ProductGrid — renders the product area: active chips, top-pick row, grid,
 * product detail modal, compare tray.
 *
 * Architecture
 * ------------
 *   - State lives in window.Store (state.js). This module is a pure view.
 *   - On init: fetch /products + /filters, populate Store, then render once.
 *   - Subscribes to Store events:
 *       products_loaded / metadata_loaded   → first render
 *       manual_filter_change / sort_changed → immediate re-render (no flourish)
 *       ai_filters_applied                  → staged render with chip slide-in
 *                                              + dim transition + pick row pop
 *       filter_removed / filters_reset      → immediate re-render
 *
 * Public methods (called by chat.js)
 *   ProductGrid.init() -> Promise<void>
 *   ProductGrid.applyUIAction(uiAction) -> Promise<void>
 *       Delegates to Store.applyAIFilters(uiAction). Resolves ~700ms later so
 *       chat.js's typewriter waits for the UI animations to finish.
 *   ProductGrid.pulseSpoken(productIds) -> void
 *
 * Existing features kept verbatim from the previous module:
 *   - Product detail modal (click a card)
 *   - Compare tray (max 3 products)
 *   - Quick-question chips inside the modal
 *   - Add-to-cart wiring
 *
 * Chip × removal dispatches `filter-chip-removed` with detail {field, value}.
 * chat.js listens and decides whether to round-trip the backend.
 */
const ProductGrid = (() => {
  const FIELD_LABEL = {
    category: "Form",
    strain_type: "Strain",
    brand: "Brand",
    effects: "Effect",
    max_price: "Under",
    max_thc: "Max THC",
    on_sale: "Filter",
    query: "Search",
  };

  // Backend understands these for removed_filters re-search. Other fields
  // (brand, max_thc, on_sale, query) are frontend-only — chip × on those
  // removes locally without calling /chat.
  const AI_KNOWN_FIELDS = new Set(["category", "strain_type", "effects", "max_price"]);

  // ── DOM refs (resolved on init) ─────────────────────────────────────
  let gridEl = null;
  let gridTitleEl = null;
  let chipsEl = null;
  let metaEl = null;
  let pickRowEl = null;
  let pickCardsEl = null;
  let sortEl = null;

  // ── Local UI state ──────────────────────────────────────────────────
  const local = {
    byId: new Map(),
    spokenIds: new Set(),
    compareIds: new Set(),
    // chips added since last render — used to flash .new animation
    newChipKeys: new Set(),
  };

  // ── Public ──────────────────────────────────────────────────────────
  async function init() {
    gridEl = document.getElementById("product-grid");
    gridTitleEl = document.getElementById("grid-title");
    chipsEl = document.getElementById("active-chips");
    metaEl = document.getElementById("result-meta");
    pickRowEl = document.getElementById("top-pick-row");
    pickCardsEl = document.getElementById("top-pick-cards");
    sortEl = document.getElementById("sort-select");

    // Fetch products + filter metadata in parallel.
    try {
      const [productsRes, filtersRes] = await Promise.all([
        fetch(`${API_BASE}/products`),
        fetch(`${API_BASE}/filters`),
      ]);
      if (productsRes.ok) {
        const data = await productsRes.json();
        window.Store.setProducts(Array.isArray(data.products) ? data.products : []);
      }
      if (filtersRes.ok) {
        const meta = await filtersRes.json();
        window.Store.setFilterMetadata(meta);
      }
    } catch (err) {
      console.warn("ProductGrid.init: backend fetch failed", err);
      if (metaEl) {
        metaEl.textContent = "Could not load products — is the backend running?";
      }
    }

    // Build id → product lookup; share with cart for name/price resolution.
    local.byId = new Map();
    for (const p of window.Store.state.allProducts) {
      if (p && typeof p.id === "number") local.byId.set(p.id, p);
    }
    if (window.Cart && typeof window.Cart.setProductLookup === "function") {
      window.Cart.setProductLookup((id) => local.byId.get(id) || null);
    }

    // Sort dropdown → Store
    if (sortEl) {
      sortEl.addEventListener("change", () => {
        window.Store.setSort(sortEl.value);
      });
    }

    wireClicks();

    // Subscribe to Store events; render reacts based on event type.
    window.Store.subscribe((event) => {
      if (event.type === "ai_filters_applied") {
        // The Promise returned by applyUIAction below resolves after this
        // staged render completes (and resolves the typewriter wait).
        return; // staging handled by applyUIAction's own scheduler
      }
      renderAll();
    });

    renderAll();
  }

  function applyUIAction(uiAction) {
    // Diff the chip keys against current to figure out which chips are newly
    // added by this AI turn, then run the staged-render animation.
    const prevKeys = chipKeysOf(window.Store.activeChipList());
    window.Store.applyAIFilters(uiAction);
    const nextKeys = chipKeysOf(window.Store.activeChipList());
    local.newChipKeys = new Set([...nextKeys].filter((k) => !prevKeys.has(k)));

    return new Promise((resolve) => {
      // T+0: chips with .new class
      renderChips();
      // T+250: grid re-render (dim transition)
      setTimeout(() => {
        renderGrid();
        // T+700: pick row + meta + resolve
        setTimeout(() => {
          renderPicks();
          renderMeta();
          local.newChipKeys.clear();
          resolve();
        }, 450);
      }, 250);
    });
  }

  function pulseSpoken(ids) {
    const list = Array.isArray(ids) ? ids : [];
    local.spokenIds = new Set(list);
    let firstScrolled = false;
    list.forEach((id) => {
      const card = document.querySelector(`.product-card[data-id="${id}"]`);
      if (card) {
        card.classList.remove("pulse");
        void card.offsetWidth; // force reflow to restart animation
        card.classList.add("pulse");
        if (!firstScrolled) {
          firstScrolled = true;
          card.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        setTimeout(() => card.classList.remove("pulse"), 1600);
      }
    });
  }

  // ── Render: full ────────────────────────────────────────────────────
  function renderAll() {
    // Build/refresh byId in case products loaded after subscribe wired up
    if (local.byId.size === 0 && window.Store.state.allProducts.length) {
      for (const p of window.Store.state.allProducts) {
        if (p && typeof p.id === "number") local.byId.set(p.id, p);
      }
    }
    renderChips();
    renderGrid();
    renderPicks();
    renderMeta();
  }

  // ── Render: chips row ───────────────────────────────────────────────
  function chipKeysOf(chips) {
    const keys = new Set();
    for (const { field, value } of chips) {
      keys.add(`${field}:${value}`);
    }
    return keys;
  }

  function chipText(field, value) {
    if (field === "max_price") return `Under $${value}`;
    if (field === "max_thc") return `Max THC ${value}%`;
    if (field === "on_sale") return "On sale";
    if (field === "query") return `"${value}"`;
    return `${FIELD_LABEL[field] || field}: ${value}`;
  }

  function renderChips() {
    if (!chipsEl) return;
    const chips = window.Store.activeChipList();
    if (chips.length === 0) {
      chipsEl.innerHTML = "";
      return;
    }
    chipsEl.innerHTML = chips
      .map(({ field, value }) => {
        const key = `${field}:${value}`;
        const isNew = local.newChipKeys.has(key);
        const label = chipText(field, value);
        return `
          <button
            class="filter-chip${isNew ? " new" : ""}"
            data-field="${field}"
            data-value="${escapeAttr(String(value))}"
            type="button"
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
    const filtered = window.Store.sortProducts(window.Store.filteredProducts());
    const total = window.Store.state.allProducts.length;
    const hasActiveFilters = window.Store.activeChipList().length > 0;
    const picksVisible = window.Store.state.picks.length > 0;

    if (gridTitleEl) {
      gridTitleEl.hidden = !(picksVisible && filtered.length > 0);
    }

    if (filtered.length === 0) {
      gridEl.innerHTML = `
        <div class="grid-empty">
          ${hasActiveFilters
            ? "No products match these filters. Try removing a chip above."
            : "No products available."}
        </div>
      `;
      return;
    }

    gridEl.innerHTML = filtered
      .map((p) => productCardHTML(p, false, false))
      .join("");
  }

  function productCardHTML(product, isDim, isPickContext) {
    const placeholder = makePlaceholder(product);
    const isPick = window.Store.state.pickIds.has(product.id);
    const isSpoken = local.spokenIds.has(product.id);
    const classes = ["product-card"];
    if (isDim) classes.push("dim");
    if (isPick && !isPickContext) classes.push("is-pick");
    if (isSpoken) classes.push("pulse");
    if (isPickContext) classes.push("pick-card");

    const saleBadge = product.sale
      ? `<div class="sale-badge">SALE -${product.disc}%</div>`
      : "";
    const inCompare = local.compareIds.has(product.id);
    const compareChip = isPickContext
      ? ""
      : `<button class="compare-chip${inCompare ? " active" : ""}"
            data-compare-toggle="${product.id}"
            type="button"
            aria-label="${inCompare ? "Remove from compare" : "Add to compare"}">${
            inCompare ? "✓" : "+"
          }</button>`;
    const priceHTML = product.sale
      ? `<span class="price-sale">$${formatPrice(product.p)}</span>`
      : `<span class="price">$${formatPrice(product.p)}</span>`;

    const thcHTML = product.thc
      ? `<span class="thc">THC ${escapeHTML(product.thc)}</span>`
      : "";

    const strainBadgeHTML = product.t
      ? `<span class="strain-badge strain-${strainClass(product.t)}"
           title="${escapeAttr(product.t)}">${escapeHTML(product.t)}</span>`
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
          <div class="product-brand">${escapeHTML(product.c || "")}</div>
          <div class="product-name" title="${escapeAttr(product.s)}">${escapeHTML(product.s)}</div>
          <div class="product-tags">
            ${strainBadgeHTML}
            <span class="category-badge">${escapeHTML(product.cat || "")}</span>
          </div>
          <div class="product-meta">
            ${priceHTML}
            ${thcHTML}
          </div>
          <button class="add-btn" data-id="${product.id}" type="button"
            aria-label="Add ${escapeAttr(product.s)} to cart">Add</button>
        </div>
        ${pickReason}
      </article>
    `;
  }

  // ── Render: top-pick row ────────────────────────────────────────────
  function renderPicks() {
    if (!pickRowEl || !pickCardsEl) return;
    const picks = window.Store.state.picks;
    if (!picks || picks.length === 0) {
      pickRowEl.hidden = true;
      pickCardsEl.innerHTML = "";
      return;
    }
    pickRowEl.hidden = false;
    pickCardsEl.innerHTML = picks
      .map((p, idx) => {
        const full = local.byId.get(p.id) || p;
        const merged = Object.assign({}, full, {
          pick_reason: p.pick_reason || p.reason || "",
        });
        const html = productCardHTML(merged, false, true);
        // Stagger the cardPop animation
        return html.replace(
          '<article ',
          `<article style="animation-delay:${idx * 80}ms" `
        );
      })
      .join("");
  }

  // ── Render: meta line ───────────────────────────────────────────────
  function renderMeta() {
    if (!metaEl) return;
    const total = window.Store.state.allProducts.length;
    const matched = window.Store.filteredProducts().length;
    if (matched === total) {
      metaEl.innerHTML = `<strong>${total}</strong> products`;
    } else {
      metaEl.innerHTML = `<strong>${matched}</strong> of ${total} products`;
    }
  }

  // ── Click delegation ────────────────────────────────────────────────
  function wireClicks() {
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

      // Compare toggle (on card or in modal)
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

      // Add-to-cart
      if (t.classList.contains("add-btn")) {
        const id = Number(t.getAttribute("data-id"));
        if (Number.isFinite(id) && window.Cart) {
          window.Cart.add(id);
          t.classList.add("added");
          setTimeout(() => t.classList.remove("added"), 600);
        }
        e.stopPropagation();
        return;
      }

      // Filter chip × removal — dispatch + remove from Store
      const chipBtn = t.closest(".filter-chip");
      if (chipBtn instanceof HTMLElement) {
        const field = chipBtn.getAttribute("data-field");
        const value = chipBtn.getAttribute("data-value");
        if (field) {
          // Always update local Store immediately so grid re-renders snappy.
          window.Store.removeFilter(field, value);
          // For AI-known fields, also dispatch so chat.js round-trips the
          // backend with removed_filters; AI can comment + re-search.
          if (AI_KNOWN_FIELDS.has(field)) {
            window.dispatchEvent(
              new CustomEvent("filter-chip-removed", {
                detail: { field, value },
              })
            );
          }
        }
        return;
      }

      // Product card click → open detail modal
      const card = t.closest(".product-card");
      if (card instanceof HTMLElement) {
        const id = Number(card.getAttribute("data-id"));
        if (Number.isFinite(id)) openModal(id);
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeModal();
    });
  }

  // ── Compare tray ────────────────────────────────────────────────────
  const MAX_COMPARE = 3;

  function toggleCompare(id) {
    if (local.compareIds.has(id)) {
      local.compareIds.delete(id);
    } else {
      if (local.compareIds.size >= MAX_COMPARE) {
        const oldest = local.compareIds.values().next().value;
        if (oldest !== undefined) local.compareIds.delete(oldest);
      }
      local.compareIds.add(id);
    }
    renderCompareTray();
    refreshCompareChipsOnCards();
    // Refresh modal if open and showing the toggled product
    const modal = document.getElementById("product-modal");
    if (modal && !modal.hidden) {
      const titleEl = document.getElementById("modal-title");
      if (titleEl) {
        const p = [...local.byId.values()].find((x) => x.s === titleEl.textContent);
        if (p) openModal(p.id);
      }
    }
  }

  function clearCompare() {
    local.compareIds.clear();
    renderCompareTray();
    refreshCompareChipsOnCards();
  }

  function doCompare() {
    if (local.compareIds.size < 2) return;
    const ids = [...local.compareIds];
    const names = ids
      .map((id) => local.byId.get(id))
      .filter(Boolean)
      .map((p) => p.s);
    if (names.length < 2) return;
    const msg =
      names.length === 2
        ? `How does ${names[0]} compare to ${names[1]}?`
        : `Please compare these products: ${names.join(", ")}.`;
    if (window.Chat && typeof window.Chat.ask === "function") {
      // Pass IDs alongside the readable message so the backend can fetch
      // each product via `get_product_details(product_id=…)` instead of
      // fuzzy-matching the names with `smart_search` (which collapses on
      // the agent loop's per-turn dedup and crosses into descriptions).
      const sent = window.Chat.ask(msg, { compare_product_ids: ids });
      if (sent) {
        clearCompare();
        closeModal();
      }
    }
  }

  function refreshCompareChipsOnCards() {
    document.querySelectorAll(".compare-chip").forEach((el) => {
      const id = Number(el.getAttribute("data-compare-toggle"));
      const on = local.compareIds.has(id);
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
    const ids = [...local.compareIds];
    if (ids.length === 0) {
      tray.hidden = true;
      tray.innerHTML = "";
      return;
    }
    tray.hidden = false;
    const items = ids
      .map((id) => local.byId.get(id))
      .filter(Boolean)
      .map(
        (p) =>
          `<span class="compare-tray-item">
            ${escapeHTML(p.s)}
            <button class="compare-tray-x" data-compare-toggle="${p.id}"
              type="button" aria-label="Remove ${escapeAttr(p.s)} from compare">×</button>
          </span>`
      )
      .join("");
    const canGo = ids.length >= 2;
    tray.innerHTML = `
      <div class="compare-tray-inner">
        <div class="compare-tray-label">Compare (${ids.length}/${MAX_COMPARE}):</div>
        <div class="compare-tray-items">${items}</div>
        <div class="compare-tray-actions">
          <button class="compare-tray-clear" data-compare-action="clear" type="button">Clear</button>
          <button class="compare-tray-go" data-compare-action="go" type="button" ${canGo ? "" : "disabled"}>Compare in chat →</button>
        </div>
      </div>
    `;
  }

  // ── Modal ───────────────────────────────────────────────────────────
  function openModal(productId) {
    const modal = document.getElementById("product-modal");
    const body = document.getElementById("modal-body");
    const product = local.byId.get(productId);
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
        `<div class="modal-row"><span class="modal-row-label">${escapeHTML(label)}</span><span class="modal-row-value">${escapeHTML(value)}</span></div>`
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

    const inCompare = local.compareIds.has(p.id);
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
                `<button class="quick-q-btn" data-quick-q="${escapeAttr(q.send)}" type="button">${escapeHTML(q.label)}</button>`
            )
            .join("")}
        </div>
      </div>

      <div class="modal-actions">
        <button class="compare-toggle-btn${inCompare ? " active" : ""}"
          data-compare-toggle="${p.id}" type="button">${compareLabel}</button>
        <button class="add-btn modal-add-btn" data-id="${p.id}" type="button"
          aria-label="Add ${escapeAttr(p.s)} to cart">Add to Cart</button>
      </div>
    `;
  }

  function buildNarrative(p) {
    const name = `<strong>${escapeHTML(p.s)}</strong>`;
    const brand = p.c ? ` by ${escapeHTML(p.c)}` : "";
    const strain = p.t ? escapeHTML(p.t).toLowerCase() : "";
    const cat = p.cat ? escapeHTML(p.cat).toLowerCase() : "product";
    const sentences = [];

    let lead = `Meet ${name}${brand} — a ${strain ? strain + " " : ""}${cat}`;
    if (p.thc) lead += ` packing ${escapeHTML(p.thc)} THC`;
    if (p.wt) lead += ` (${escapeHTML(p.wt)})`;
    lead += ".";
    sentences.push(lead);

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

    const practical = [];
    if (p.on) practical.push(`kicks in ${escapeHTML(p.on)}`);
    if (p.dur) practical.push(`lasts ${escapeHTML(p.dur)}`);
    if (practical.length > 0) {
      let s = capitalize(practical.join(", "));
      if (p.tod) s += ` — a ${escapeHTML(p.tod.toLowerCase())} pick`;
      s += ".";
      sentences.push(s);
    }

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

// Auto-init
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => ProductGrid.init());
} else {
  ProductGrid.init();
}

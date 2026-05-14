/**
 * Store — single source of truth for the storefront's active filter state.
 *
 * Sidebar checkboxes/sliders, the category bar, the chip × removal flow,
 * and the AI's ui_action all write into ONE state object here. Anything
 * that needs to react (product grid, sidebar UI, chip row, top-pick row)
 * subscribes for change events.
 *
 * Filter source tracking ("ai" | "manual" | "init") lets subscribers
 * animate differently based on who changed the state — manual flips
 * should be silent, AI flips slide in with a flourish.
 *
 * Public methods on window.Store:
 *   subscribe(fn) -> unsubscribe              // fn(event, state) — event.type narrows what changed
 *   setProducts(list)                          // called once after /products fetch
 *   setFilterMetadata(meta)                    // called once after /filters fetch
 *   applyAIFilters(uiAction)                   // merge AI's ui_action filters/picks/spoken
 *   setManual(field, value)                    // sidebar set scalar/string field
 *   toggleArrayItem(field, value)              // sidebar toggle one item in a list field
 *   removeFilter(field, value)                 // chip × removal — drops one value
 *   resetAll()                                 // clear all filters and AI state
 *   matchProduct(product) -> bool              // single source of truth for "is this product visible"
 *   getManualFiltersPayload() -> dict          // serialized snapshot for /chat POST
 *   filteredProducts() -> list                 // applies matchProduct over the loaded catalog
 *
 * Filter shape (state.filters):
 *   category:    string | null       single-select via category bar
 *   strain_type: string[]            multi-select
 *   brand:       string[]            multi-select
 *   effects:     string[]            multi-select
 *   max_price:   number | null
 *   max_thc:     number | null
 *   on_sale:     boolean
 *   query:       string              global search box
 */
const Store = (() => {
  const state = {
    filters: {
      category: null,
      strain_type: [],
      brand: [],
      effects: [],
      max_price: null,
      max_thc: null,
      on_sale: false,
      query: "",
    },
    filterSource: "init",
    allProducts: [],
    filterMetadata: null,
    picks: [],
    pickIds: new Set(),
    spokenIds: [],
    totalMatched: null,
    sort: "newest", // newest | price-asc | price-desc | thc-desc
  };

  const subscribers = new Set();

  function subscribe(fn) {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  }

  function notify(event) {
    for (const fn of subscribers) {
      try {
        fn(event, state);
      } catch (err) {
        console.error("[Store] subscriber error:", err);
      }
    }
  }

  // ── Data loading ──────────────────────────────────────────────────────
  function setProducts(list) {
    state.allProducts = Array.isArray(list) ? list : [];
    notify({ type: "products_loaded" });
  }
  function setFilterMetadata(meta) {
    state.filterMetadata = meta || null;
    notify({ type: "metadata_loaded" });
  }

  // ── Filter mutators ───────────────────────────────────────────────────
  function setManual(field, value) {
    state.filterSource = "manual";
    state.filters[field] = value;
    notify({ type: "manual_filter_change", field, value });
  }

  function toggleArrayItem(field, value) {
    state.filterSource = "manual";
    const arr = state.filters[field];
    if (!Array.isArray(arr)) return;
    const idx = arr.indexOf(value);
    if (idx >= 0) arr.splice(idx, 1);
    else arr.push(value);
    notify({ type: "manual_filter_change", field, value });
  }

  function removeFilter(field, value) {
    const cur = state.filters[field];
    if (Array.isArray(cur)) {
      state.filters[field] = cur.filter((v) => String(v) !== String(value));
    } else if (typeof cur === "boolean") {
      state.filters[field] = false;
    } else if (typeof cur === "string") {
      state.filters[field] = "";
    } else {
      state.filters[field] = null;
    }
    notify({ type: "filter_removed", field, value });
  }

  function resetAll() {
    state.filters = {
      category: null,
      strain_type: [],
      brand: [],
      effects: [],
      max_price: null,
      max_thc: null,
      on_sale: false,
      query: "",
    };
    state.filterSource = "manual";
    state.picks = [];
    state.pickIds = new Set();
    state.spokenIds = [];
    state.totalMatched = null;
    notify({ type: "filters_reset" });
  }

  // ── AI integration ────────────────────────────────────────────────────
  function applyAIFilters(uiAction) {
    const a = uiAction || {};
    const f = a.filters || {};
    state.filterSource = "ai";

    // AI replaces what it sets; leaves untouched fields untouched.
    if ("category" in f && f.category) state.filters.category = f.category;
    if ("strain_type" in f && f.strain_type) {
      const v = Array.isArray(f.strain_type) ? f.strain_type : [f.strain_type];
      state.filters.strain_type = v;
    }
    if ("effects" in f && f.effects) {
      const v = Array.isArray(f.effects) ? f.effects : [f.effects];
      state.filters.effects = v;
    }
    if ("brand" in f && f.brand) {
      const v = Array.isArray(f.brand) ? f.brand : [f.brand];
      state.filters.brand = v;
    }
    if ("max_price" in f && typeof f.max_price === "number") {
      state.filters.max_price = f.max_price;
    }
    if ("max_thc" in f && typeof f.max_thc === "number") {
      state.filters.max_thc = f.max_thc;
    }

    state.picks = Array.isArray(a.picks) ? a.picks : [];
    state.pickIds = new Set(state.picks.map((p) => p.id));
    state.spokenIds = Array.isArray(a.spoken_product_ids)
      ? a.spoken_product_ids
      : [];
    state.totalMatched =
      typeof a.total_matched === "number" ? a.total_matched : null;
    notify({ type: "ai_filters_applied" });
  }

  function setSort(sort) {
    state.sort = sort;
    notify({ type: "sort_changed", sort });
  }

  // ── Predicates / selectors ────────────────────────────────────────────
  function thcNumeric(thcStr) {
    if (!thcStr) return null;
    const m = String(thcStr).match(/^([\d.]+)/);
    return m ? parseFloat(m[1]) : null;
  }

  function matchProduct(p) {
    const f = state.filters;
    if (!p) return false;
    if (f.category && p.cat !== f.category) return false;
    if (f.strain_type.length) {
      const t = String(p.t || "").toLowerCase();
      const hit = f.strain_type.some((st) => t === String(st).toLowerCase());
      if (!hit) return false;
    }
    if (f.brand.length) {
      if (!f.brand.includes(p.c)) return false;
    }
    if (f.effects.length) {
      const productEffects = String(p.f || "").toLowerCase();
      const hit = f.effects.some((e) =>
        productEffects.includes(String(e).toLowerCase())
      );
      if (!hit) return false;
    }
    if (typeof f.max_price === "number") {
      if ((Number(p.p) || 0) > f.max_price) return false;
    }
    if (typeof f.max_thc === "number") {
      const n = thcNumeric(p.thc);
      if (n !== null && n > f.max_thc) return false;
    }
    if (f.on_sale && !p.sale) return false;
    if (f.query) {
      const q = String(f.query).toLowerCase();
      const blob = [p.s, p.c, p.cat, p.t, p.f, p.flv]
        .map((x) => String(x || "").toLowerCase())
        .join(" ");
      if (!blob.includes(q)) return false;
    }
    return true;
  }

  function filteredProducts() {
    return state.allProducts.filter(matchProduct);
  }

  function sortProducts(list) {
    const arr = list.slice();
    switch (state.sort) {
      case "price-asc":
        return arr.sort((a, b) => (a.p || 0) - (b.p || 0));
      case "price-desc":
        return arr.sort((a, b) => (b.p || 0) - (a.p || 0));
      case "thc-desc":
        return arr.sort((a, b) => (thcNumeric(b.thc) || 0) - (thcNumeric(a.thc) || 0));
      case "newest":
      default:
        // No stable timestamp in compact dict — keep DB order, which is insertion order.
        return arr;
    }
  }

  function getManualFiltersPayload() {
    const f = state.filters;
    const out = {};
    if (f.category) out.category = f.category;
    if (f.strain_type.length) out.strain_type = f.strain_type.slice();
    if (f.brand.length) out.brand = f.brand.slice();
    if (f.effects.length) out.effects = f.effects.slice();
    if (typeof f.max_price === "number") out.max_price = f.max_price;
    if (typeof f.max_thc === "number") out.max_thc = f.max_thc;
    if (f.on_sale) out.on_sale = true;
    if (f.query) out.query = f.query;
    return out;
  }

  function activeChipList() {
    const f = state.filters;
    const chips = [];
    if (f.category) chips.push({ field: "category", value: f.category });
    f.strain_type.forEach((v) => chips.push({ field: "strain_type", value: v }));
    f.brand.forEach((v) => chips.push({ field: "brand", value: v }));
    f.effects.forEach((v) => chips.push({ field: "effects", value: v }));
    if (typeof f.max_price === "number")
      chips.push({ field: "max_price", value: f.max_price });
    if (typeof f.max_thc === "number")
      chips.push({ field: "max_thc", value: f.max_thc });
    if (f.on_sale) chips.push({ field: "on_sale", value: true });
    if (f.query) chips.push({ field: "query", value: f.query });
    return chips;
  }

  return {
    state,
    subscribe,
    setProducts,
    setFilterMetadata,
    setManual,
    toggleArrayItem,
    removeFilter,
    resetAll,
    applyAIFilters,
    setSort,
    matchProduct,
    filteredProducts,
    sortProducts,
    getManualFiltersPayload,
    activeChipList,
  };
})();

window.Store = Store;

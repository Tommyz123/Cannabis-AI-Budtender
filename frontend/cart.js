/**
 * Cart module — localStorage-backed shopping cart.
 *
 * Storage key: budtender_cart_v1
 * Schema: [{ id: number, qty: number }]
 *
 * Exposes window.Cart:
 *   - add(id)
 *   - remove(id)
 *   - count() -> total qty across items
 *
 * Side effects on save():
 *   - updates #cart-count badge
 *   - re-renders #cart-drawer contents if open
 *
 * Cart.setProductLookup(fn) is called by product-grid.js after products load
 * so the drawer can resolve names/prices for displayed items.
 */

const Cart = (() => {
  const KEY = "budtender_cart_v1";

  let items = [];
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        items = parsed.filter(
          (it) =>
            it &&
            typeof it.id === "number" &&
            typeof it.qty === "number" &&
            it.qty > 0
        );
      }
    }
  } catch (e) {
    items = [];
  }

  let productLookup = null;

  function setProductLookup(fn) {
    productLookup = fn;
    render();
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(items));
    } catch (e) {
      // Quota exceeded or disabled; ignore for MVP
    }
    render();
  }

  function add(id) {
    const pid = Number(id);
    if (!Number.isFinite(pid)) return;
    const existing = items.find((it) => it.id === pid);
    if (existing) {
      existing.qty += 1;
    } else {
      items.push({ id: pid, qty: 1 });
    }
    save();
  }

  function remove(id) {
    const pid = Number(id);
    items = items.filter((it) => it.id !== pid);
    save();
  }

  function changeQty(id, delta) {
    const pid = Number(id);
    const existing = items.find((it) => it.id === pid);
    if (!existing) return;
    existing.qty += delta;
    if (existing.qty <= 0) {
      items = items.filter((it) => it.id !== pid);
    }
    save();
  }

  function count() {
    return items.reduce((s, it) => s + it.qty, 0);
  }

  function total() {
    if (!productLookup) return 0;
    let sum = 0;
    for (const it of items) {
      const p = productLookup(it.id);
      if (p && typeof p.p === "number") {
        sum += p.p * it.qty;
      }
    }
    return sum;
  }

  function renderBadge() {
    const badge = document.getElementById("cart-count");
    if (badge) badge.textContent = String(count());
  }

  function renderDrawer() {
    const drawer = document.getElementById("cart-drawer");
    if (!drawer) return;

    if (items.length === 0) {
      drawer.innerHTML = `
        <div class="cart-drawer-header">
          <h2>🛒 Your Cart</h2>
          <button class="cart-drawer-close" aria-label="Close cart">&times;</button>
        </div>
        <div class="cart-empty">Your cart is empty.</div>
      `;
    } else {
      const rows = items
        .map((it) => {
          const p = productLookup ? productLookup(it.id) : null;
          const name = p ? p.s : `Product #${it.id}`;
          const price = p && typeof p.p === "number" ? p.p : 0;
          const lineTotal = price * it.qty;
          return `
            <div class="cart-item" data-id="${it.id}">
              <div class="cart-item-name">${escapeHTML(name)}</div>
              <div class="cart-item-row">
                <div class="cart-qty">
                  <button class="cart-qty-dec" aria-label="Decrease quantity" data-id="${it.id}">−</button>
                  <span class="cart-qty-val">${it.qty}</span>
                  <button class="cart-qty-inc" aria-label="Increase quantity" data-id="${it.id}">+</button>
                </div>
                <div class="cart-item-price">$${lineTotal.toFixed(2)}</div>
                <button class="cart-item-remove" aria-label="Remove item" data-id="${it.id}">&times;</button>
              </div>
            </div>
          `;
        })
        .join("");

      drawer.innerHTML = `
        <div class="cart-drawer-header">
          <h2>🛒 Your Cart</h2>
          <button class="cart-drawer-close" aria-label="Close cart">&times;</button>
        </div>
        <div class="cart-items">${rows}</div>
        <div class="cart-total">
          <span>Total</span>
          <span class="cart-total-val">$${total().toFixed(2)}</span>
        </div>
      `;
    }
  }

  function render() {
    renderBadge();
    renderDrawer();
  }

  function escapeHTML(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function openDrawer() {
    const drawer = document.getElementById("cart-drawer");
    if (!drawer) return;
    drawer.hidden = false;
    // force reflow so the transition triggers
    void drawer.offsetWidth;
    drawer.classList.add("open");
  }

  function closeDrawer() {
    const drawer = document.getElementById("cart-drawer");
    if (!drawer) return;
    drawer.classList.remove("open");
    // wait for transition then hide
    setTimeout(() => {
      drawer.hidden = true;
    }, 300);
  }

  function wire() {
    const trigger = document.getElementById("cart-trigger");
    if (trigger) {
      trigger.addEventListener("click", () => {
        const drawer = document.getElementById("cart-drawer");
        if (drawer && drawer.hidden) openDrawer();
        else closeDrawer();
      });
    }

    const drawer = document.getElementById("cart-drawer");
    if (drawer) {
      drawer.addEventListener("click", (e) => {
        const target = e.target;
        if (!(target instanceof HTMLElement)) return;
        if (target.classList.contains("cart-drawer-close")) {
          closeDrawer();
        } else if (target.classList.contains("cart-item-remove")) {
          remove(target.getAttribute("data-id"));
        } else if (target.classList.contains("cart-qty-inc")) {
          changeQty(target.getAttribute("data-id"), +1);
        } else if (target.classList.contains("cart-qty-dec")) {
          changeQty(target.getAttribute("data-id"), -1);
        }
      });
    }

    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  return { add, remove, count, setProductLookup };
})();

window.Cart = Cart;

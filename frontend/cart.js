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

    const header = `
      <div class="cart-drawer-header">
        <h2 class="cart-drawer-title">🛒 Your Cart</h2>
        <button class="cart-drawer-close" aria-label="Close cart" type="button">&times;</button>
      </div>
    `;

    if (items.length === 0) {
      drawer.innerHTML = `${header}
        <div class="cart-drawer-body">
          <div class="cart-empty">Your cart is empty.</div>
        </div>`;
      return;
    }

    const rows = items
      .map((it) => {
        const p = productLookup ? productLookup(it.id) : null;
        const name = p ? p.s : `Product #${it.id}`;
        const brand = p && p.c ? p.c : "";
        const price = p && typeof p.p === "number" ? p.p : 0;
        const lineTotal = price * it.qty;
        return `
          <div class="cart-item" data-id="${it.id}">
            <div class="cart-item-info">
              ${brand ? `<div class="cart-item-brand">${escapeHTML(brand)}</div>` : ""}
              <div class="cart-item-name">${escapeHTML(name)}</div>
              <div class="cart-item-controls">
                <button class="cart-qty-btn cart-qty-dec" aria-label="Decrease quantity" data-id="${it.id}" type="button">−</button>
                <span class="cart-item-qty">${it.qty}</span>
                <button class="cart-qty-btn cart-qty-inc" aria-label="Increase quantity" data-id="${it.id}" type="button">+</button>
                <div class="cart-item-price">$${lineTotal.toFixed(2)}</div>
                <button class="cart-item-remove" aria-label="Remove item" data-id="${it.id}" type="button">&times;</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");

    drawer.innerHTML = `${header}
      <div class="cart-drawer-body">${rows}</div>
      <div class="cart-drawer-footer">
        <div class="cart-total-row">
          <span>Total</span>
          <span>$${total().toFixed(2)}</span>
        </div>
        <button class="cart-checkout-btn" type="button">Proceed to checkout</button>
      </div>
    `;
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

  // CSS-driven slide: #cart-drawer[hidden] is positioned off-screen with
  // translateX(100%) but kept display:flex so the transition runs. Toggling
  // the `hidden` attribute is enough.
  function openDrawer() {
    const drawer = document.getElementById("cart-drawer");
    if (!drawer) return;
    drawer.hidden = false;
  }

  function closeDrawer() {
    const drawer = document.getElementById("cart-drawer");
    if (!drawer) return;
    drawer.hidden = true;
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
        } else if (target.classList.contains("cart-checkout-btn")) {
          alert("Checkout is a demo only — no real payment flow.");
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

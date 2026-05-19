/**
 * Product placeholder image generator.
 *
 * Exposes:
 *   - API_BASE constant (consumed by product-grid.js and chat.js)
 *   - brandColor(brand) -> string  (deterministic HSL from brand name)
 *   - makePlaceholder(product) -> string  (HTML for emoji-on-color block)
 *   - CATEGORY_EMOJI map  (category name -> emoji)
 */

const API_BASE = "http://localhost:8000";

const CATEGORY_EMOJI = {
  Flower: "🌿",
  "Pre-rolls": "💨",
  Edibles: "🍬",
  Vaporizers: "💨",
  Beverages: "🥤",
  Concentrates: "💎",
  Tincture: "💧",
  Topicals: "🧴",
};

function brandColor(brand) {
  let h = 0;
  const s = brand || "";
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) % 360;
  }
  return `hsl(${h}, 55%, 78%)`;
}

function makePlaceholder(product) {
  const emoji = CATEGORY_EMOJI[product.cat] || "🌿";
  const color = brandColor(product.c);
  return `<div class="placeholder" style="background:${color}">${emoji}</div>`;
}

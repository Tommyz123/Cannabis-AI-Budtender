# Two-Pane AI Budtender — Execution Plan v2

> **v2 changes**: incorporates all 5 blockers and 7 strong concerns from the v1 review. Key shifts: no signature breakage on `get_recommendation` (use out-param), `removed_filters` API field instead of synthetic user message, effect mapping table, per-unit "best value", product-name scan tolerates punctuation, Tier 7 fallback for picks, pre-computed pick metadata.

---

## 0. Locked spec (unchanged from chat alignment)

| Item | Decision |
|---|---|
| Layout | Two-pane: product grid 60% + chat 40% (desktop); stacked on mobile |
| Product images | Placeholder (emoji + brand color block) |
| Cart | Frontend localStorage with header badge + side drawer; key `budtender_cart_v1` |
| Unmatched products | Grayscale 50% + opacity 0.4, kept in grid |
| Filter chip × | Clickable; sends `removed_filters` API field (NOT a synthetic user message) |
| Spoken highlight | Backend scans reply text, returns `spoken_product_ids` |
| Top Pick count | 1–3, always shown when filtered set non-empty (Tier 7 fallback) |
| Pick scoring | Backend rule-based, pre-computed at DB load + per-call scoring |
| Pick reason | Fixed templates (7 categories incl. fallback) |
| Pick visual | Top dedicated row, 1.5× cards, green tint, reason banner |
| Sale data | Migration mocks ~20% products as on-sale, deterministic |
| Streaming | Off for MVP; `/chat/stream` preserved but documented as legacy |
| Backend compatibility | `/chat` response gains optional `ui_action`; `get_recommendation` keeps `str` return |
| Eval regression | Must remain 25/25 100% |

---

## 1. Architecture overview (unchanged from v1)

```
Frontend (4 JS files, strict load order)
├─ placeholders.js    (emoji/color from category + brand)
├─ cart.js            (localStorage, key v1)
├─ product-grid.js    (state, filter, animations, picks render)
└─ chat.js            (API calls, typewriter, removed_filters wiring)

Backend
├─ /products GET      → list of compact dicts (with sale fields)
├─ /chat POST         → { reply, session_id, response_time_ms, ui_action? }
│   in: ChatRequest gains optional removed_filters: dict
│   out: ui_action = { filters, picks, spoken_product_ids, total_matched }
└─ /chat/stream POST  → unchanged (no ui_action delivery; legacy)

SQLite
└─ products table + is_on_sale INTEGER + discount_pct INTEGER
```

---

## 2. Module breakdown (6 modules)

### Module 1 — DB schema + sale mock data

**Files**
- `scripts/setup_db.py` — add columns to `CREATE TABLE products`
- `scripts/seed_sale_data.py` — NEW, idempotent seed using deterministic RNG

**Schema additions** (apply via setup_db.py recreation OR ALTER on existing DB):
```sql
ALTER TABLE products ADD COLUMN is_on_sale INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN discount_pct INTEGER DEFAULT 0;
```

**Seed rule**
```python
import random
random.seed(42)  # deterministic
sale_count = 43   # floor(217 * 0.2)
discount_choices = [10, 15, 20, 25]
# Pick 43 ids uniformly from existing product ids, assign discount uniformly
```

**Integration**
- `setup_db.py` only declares columns (DDL). It does NOT call the seeder.
- `migrate_csv_to_sqlite.py` is unchanged.
- README + cowork_log get a one-line update: "after migration, run `python scripts/seed_sale_data.py`."
- For CI/tests: `tests/conftest.py` fixture invokes seeder against the test DB (see Module 2 acceptance).

**Acceptance**
- `SELECT COUNT(*) WHERE is_on_sale=1` → 43
- `SELECT COUNT(DISTINCT discount_pct) WHERE is_on_sale=1` ≥ 3
- Re-running seeder produces identical id set (seed=42 deterministic)
- `setup_db.py` re-run is idempotent: ALTER guarded with `try/except OperationalError` for "duplicate column name"

---

### Module 2 — ProductManager: sale fields + pre-computed pick metadata + scoring

**Files**
- `backend/product_manager.py`
- `backend/pick_scoring.py` — NEW, pure functions for scoring

**Effect intent → DB effect mapping** (Blocker B3 fix)
```python
EFFECT_INTENT_TO_DB = {
    "sleep":    "Sleepy",
    "sleepy":   "Sleepy",
    "relax":    "Relaxed",
    "relaxed":  "Relaxed",
    "unwind":   "Relaxed",
    "chill":    "Relaxed",
    "calm":     "Calm",
    "energy":   "Energetic",
    "energetic":"Energetic",
    "focus":    "Focused",
    "creative": "Creative",
    "happy":    "Happy",
    "uplifted": "Uplifted",
    "euphoric": "Happy",
    "sedated":  "Sleepy",
    "stress":   "Calm",
    "anxious":  "Calm",
}
```

**THC numeric extractor** (Blocker B4 fix)
```python
def thc_numeric(thc_string: str) -> tuple[float, str] | None:
    """'22%' → (22.0, '%'); '5mg' → (5.0, 'mg'); '' → None"""
    if not thc_string:
        return None
    m = re.match(r"^([\d.]+)(%|mg)?$", thc_string.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or ""
    return (val, unit) if val > 0 else None
```

**Pre-computed pick metadata** (Suggestion Sg3)
- During `ProductManager.load()`, after loading the DataFrame, build `self._pick_meta: dict[int, dict]` keyed by product id with:
  ```python
  {
      "is_on_sale": bool,
      "discount_pct": int,
      "is_premium": price_range == "Premium",
      "price_per_thc": float | None,  # price / thc_val (only if thc_val > 0)
      "thc_unit": "%" | "mg" | "",
      "effects_set": set[str],         # parsed from comma-joined effects
      "experience_level": str,
  }
  ```
- `_row_to_compact` adds optional sale fields:
  ```python
  if pd.notna(row.get("is_on_sale")) and row.get("is_on_sale"):
      record["sale"] = True
      record["disc"] = int(row["discount_pct"])
      record["op"] = round(row["price"] / (1 - row["discount_pct"]/100), 2)
  ```

**Public method** (called by ui_action_builder):
```python
def score_picks(self, filtered: list[dict], profile: dict, limit: int = 3) -> list[dict]:
    """
    Returns up to `limit` picks with 'pick_reason' attached.
    Always returns ≥1 pick if filtered non-empty (Tier 7 fallback).
    """
```

**Tier table** (Blocker B4 + Strong S2 fix)
| Tier | Reason key | Trigger | Template | Cap |
|---|---|---|---|---|
| 1 | `sale_big` | meta.is_on_sale and disc ≥ 20 | `"{disc}% off this week"` | unlimited |
| 2 | `sale_small` | meta.is_on_sale and disc < 20 | `"{disc}% off"` | unlimited |
| 3 | `best_value` | min `price_per_thc` **within the dominant THC unit cohort** of filtered set | `"Best value in this filter"` | 1 |
| 4 | `fit` | size of (mapped_intent_effects ∩ meta.effects_set) ≥ 2 | `"Matches your {top_effect} vibe"` | unlimited |
| 5 | `beginner` | profile.experience_level == "beginner" AND product passes beginner safety | `"Gentle for first-timers"` | unlimited |
| 6 | `premium` | meta.is_premium | `"Top-shelf pick"` | 1 |
| 7 | `fallback` | always; only consulted if tiers 1-6 yielded zero | `"Recommended for you"` | up to `limit` |

**Selection algorithm**
1. For each product in `filtered`, compute the highest-priority tier it qualifies for (1 wins over 6).
2. Bucket products by tier.
3. Walk tiers 1→6 in order, draining buckets, respecting per-tier caps, until `limit` reached.
4. If after tier 6 still empty → Tier 7 takes first `limit` from filtered.
5. Return list with `pick_reason` field set (templated).

**Dominant THC unit cohort** (Tier 3 detail)
- Count products by `meta.thc_unit` in filtered. Pick the unit with max count. Tier 3 only ranks products in that cohort.
- Skip Tier 3 if no product has a numeric THC.

**Acceptance**
- Pre-computed `_pick_meta` covers all 217 products
- Tier 7 fallback guarantees non-empty pick output for non-empty input
- "Best value" never crosses % vs mg
- Effects set parses `"Relaxed,Sleepy,Calm"` correctly (split on `,`, strip whitespace)
- Unit tests in `tests/test_pick_scoring.py` cover: each tier triggers, caps respected, Tier 7 fallback, mixed-unit filter, beginner gating, divide-by-zero THC

---

### Module 3 — llm_service: capture tool calls (out-param trace) + build ui_action

**Files**
- `backend/llm_service.py`
- `backend/ui_action_builder.py` — NEW

**Out-param pattern** (Blocker B1 fix)
- `get_recommendation` keeps signature `→ str` for back-compat with eval/tests
- Add keyword-only `trace: dict | None = None` parameter
- When `trace` is provided, populate it as a side channel; existing callers unaffected

```python
def get_recommendation(
    history: list[dict],
    user_message: str,
    product_manager,
    is_beginner: bool = False,
    *,
    trace: dict | None = None,
) -> str:
    profile = extract_profile_signals(user_message, history)
    if trace is not None:
        trace["profile"] = profile  # avoid double-extraction (Sg S4 fix)
    ...
    # In agent loop: after each successful smart_search, record:
    if trace is not None and fn_name == "smart_search":
        trace["last_smart_search"] = {
            "args": fn_args,           # already parsed dict (B2 fix)
            "result": result,
        }
    # In fast path: after _run_fast_path success, record:
    if trace is not None:
        trace["last_smart_search"] = {
            "args": search_params,     # snake_case kwargs dict
            "result": search_result,
        }
    return reply
```

- Both fast-path and agent-loop must capture into the **same key** with the **same dict shape**: `{args: parsed_dict, result: dict}`. Verified parity: both sources are snake_case keyed kwargs that `ProductManager.search_products` accepts.
- `get_recommendation_stream` is **not** modified for MVP (no streaming consumer in new frontend).

**NEW `backend/ui_action_builder.py`**
```python
"""Build the ui_action payload returned alongside chat replies."""
import re
from typing import Iterable

# Whitelist of smart_search args that map to user-visible filter chips.
# Deliberately EXCLUDES is_beginner (session attribute) and hardware_type
# (not in TOOLS_SCHEMA — derived field on results).
VISIBLE_FILTER_FIELDS = {"category", "strain_type", "effects", "max_price"}


def build_ui_action(
    trace: dict,
    reply_text: str,
    product_manager,
) -> dict | None:
    last = trace.get("last_smart_search")
    if not last:
        return None
    profile = trace.get("profile", {})

    visible_filters = {
        k: v for k, v in last["args"].items()
        if k in VISIBLE_FILTER_FIELDS and v
    }
    filtered_products = last["result"].get("products", [])
    picks = product_manager.score_picks(filtered_products, profile, limit=3)
    spoken_ids = _scan_reply_for_product_ids(reply_text, filtered_products)

    return {
        "filters": visible_filters,
        "picks": picks,
        "spoken_product_ids": spoken_ids,
        "total_matched": last["result"].get("total", 0),
    }


def _scan_key(name: str) -> str:
    """Take first segment of pipe-separated name, e.g. 'Half & Half | UP | 10mg' → 'Half & Half'."""
    return name.split("|", 1)[0].strip()


def _scan_reply_for_product_ids(reply: str, candidates: list[dict]) -> list[int]:
    """
    Find product names in reply. Tolerates flanking markdown/punctuation by
    using non-word-char lookarounds instead of \b (which fails next to &, |, *, etc.).
    Scans against the shortened 'key' (first |-segment) since the LLM rarely
    reproduces the full SKU-laden product name verbatim.
    """
    hits: list[tuple[int, int]] = []
    seen: set[int] = set()
    for prod in candidates:
        full_name = prod.get("s", "")
        if not full_name:
            continue
        key = _scan_key(full_name)
        if not key:
            continue
        pattern = re.compile(
            rf"(?<!\w){re.escape(key)}(?!\w)",
            re.IGNORECASE,
        )
        m = pattern.search(reply)
        if m and prod["id"] not in seen:
            hits.append((m.start(), prod["id"]))
            seen.add(prod["id"])
    hits.sort(key=lambda h: h[0])
    return [pid for _, pid in hits]
```

**Acceptance**
- Both fast-path and agent-loop capture `last_smart_search` with identical schema
- `build_ui_action` returns `None` for greeting/info-gathering turns (no smart_search)
- `spoken_product_ids` correctly matches `"Half & Half"` even when full DB name is `"Half & Half | UP | 2:1 | Single | 10mg"`
- Markdown bold `**Product Name**` matches (asterisks are non-word chars, satisfy lookaround)
- Unit tests in `tests/test_ui_action_builder.py` cover: no search, single search, fast-path search, multi-search dedupe, name with pipes, name with `&`, markdown-bolded names

---

### Module 4 — API surface: /products endpoint + ChatRequest/Response extensions

**Files**
- `backend/main.py`
- `backend/models.py`
- `backend/product_manager.py` (one new method)

**models.py additions**
```python
class UIAction(BaseModel):
    filters: dict = Field(default_factory=dict)
    picks: list[dict] = Field(default_factory=list)
    spoken_product_ids: list[int] = Field(default_factory=list)
    total_matched: int = 0


class ChatRequest(BaseModel):
    # ... existing fields
    removed_filters: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Filters the user just removed via chip × in the UI. "
            "Keys: 'category', 'strain_type', 'effects', 'max_price'. "
            "Values: the removed filter value (used to compose an instruction "
            "for the LLM without injecting a synthetic user message)."
        ),
    )


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    response_time_ms: float
    ui_action: UIAction | None = None  # NEW, defaults None
```

**product_manager.py addition**
```python
def get_all_compact_list(self) -> list[dict]:
    """Return all products as a list of compact dicts (parallel to get_all_compact_json)."""
    return [_row_to_compact(row) for _, row in self._df.iterrows()]
```

**main.py changes**
1. Add `GET /products`:
   ```python
   @app.get("/products")
   def list_products():
       products = _product_manager.get_all_compact_list()
       return {"products": products, "total": len(products)}
   ```
2. `POST /chat` adapts:
   ```python
   trace: dict = {}
   reply = get_recommendation(history, user_message, _product_manager,
                              is_beginner=request.is_beginner, trace=trace)
   ui_action = build_ui_action(trace, reply, _product_manager)
   return ChatResponse(reply=reply, ..., ui_action=ui_action)
   ```
3. `removed_filters` handling — when non-empty, prepend a deterministic instruction to the system prompt:
   ```python
   if request.removed_filters:
       # Inject before get_recommendation runs (modify history or pass through)
       # Simplest: synthesize a system-side instruction message added to history
       # for THIS turn only, marked clearly so the LLM treats it as a UI signal:
       removal_text = _format_removed_filters(request.removed_filters)
       history = history + [{"role": "system", "content": removal_text}]
   ```
   `_format_removed_filters` produces text like:
   `"[UI SIGNAL] The customer just removed these filters via the chip × UI: strain_type=Sativa. Continue the conversation by acknowledging the change and re-searching without that constraint."`

**Acceptance**
- `GET /products` returns 217 products with sale fields populated on ~43
- `POST /chat` greeting → `ui_action=null`
- `POST /chat` "I want sativa flower" → `ui_action.filters == {category: "Flower", strain_type: "Sativa", effects: ["Energetic","Uplifted"]}`
- `POST /chat` with `removed_filters={"strain_type": "Sativa"}` AND empty `user_message` triggers an AI acknowledgment + re-search
- Existing `tests/test_api.py` continues to pass (response gains optional field; `get_recommendation` mock still returns str)

---

### Module 5 — Frontend layout + product grid + cart drawer + placeholders

**Files**
- `frontend/index.html` — full rewrite (drop floating widget, two-pane layout)
- `frontend/style.css` — full rewrite
- `frontend/placeholders.js` — NEW
- `frontend/cart.js` — NEW (localStorage key `budtender_cart_v1`)
- `frontend/product-grid.js` — NEW
- `frontend/chat.js` — refactored (covered in Module 6)

**Script load order (Strong S6 fix — state explicitly)**
```html
<script src="placeholders.js"></script>
<script src="cart.js"></script>
<script src="product-grid.js"></script>
<script src="chat.js"></script>
```

**HTML skeleton**
```html
<header id="app-header">
  <h1>🌿 Verdant</h1>
  <div class="header-right">
    <span class="age-badge">21+ ✓</span>
    <button id="cart-trigger" aria-label="Open cart">🛒 <span id="cart-count">0</span></button>
  </div>
</header>

<main class="layout">
  <section id="product-pane" aria-label="Products">
    <div id="filter-chips" aria-label="Active filters"></div>
    <div id="result-meta" aria-live="polite">Showing 217 of 217</div>
    <section id="top-pick-row" hidden>
      <h2 class="pick-row-title">✨ AI's Top Pick for You</h2>
      <div id="top-pick-cards"></div>
    </section>
    <div id="product-grid" role="list"></div>
  </section>

  <aside id="chat-pane" aria-label="Chat">
    <div id="budtender-messages" role="log" aria-live="polite"></div>
    <div id="budtender-input-area">
      <input id="budtender-input" type="text" placeholder="Ask me anything..." />
      <button id="budtender-send">Send</button>
    </div>
  </aside>
</main>

<aside id="cart-drawer" hidden aria-label="Cart contents"></aside>
```

**placeholders.js** (~30 LoC)
```js
const CATEGORY_EMOJI = {
  Flower: "🌿", "Pre-rolls": "💨", Edibles: "🍬",
  Vaporizers: "💨", Beverages: "🥤",
  Concentrates: "💎", Tincture: "💧", Topicals: "🧴",
};
function brandColor(brand) {
  let h = 0;
  for (const c of brand || "") h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 55%, 78%)`;
}
function makePlaceholder(product) {
  const emoji = CATEGORY_EMOJI[product.cat] || "🌿";
  const color = brandColor(product.c);
  return `<div class="placeholder" style="background:${color}">${emoji}</div>`;
}
```

**cart.js** (~80 LoC)
```js
const Cart = (() => {
  const KEY = "budtender_cart_v1";
  let items = JSON.parse(localStorage.getItem(KEY) || "[]");
  function save() { localStorage.setItem(KEY, JSON.stringify(items)); render(); }
  function add(id) { /* increment qty or push new */ save(); }
  function remove(id) { /* ... */ save(); }
  function count() { return items.reduce((s, x) => s + x.qty, 0); }
  function render() {
    document.getElementById("cart-count").textContent = count();
    // render drawer contents if open
  }
  // Drawer open/close handlers
  return { add, remove, count };
})();
```

**product-grid.js** (~250 LoC) — full API:
```js
const ProductGrid = (() => {
  const state = {
    allProducts: [],
    currentFilters: {},
    spokenIds: new Set(),
    pickIds: new Set(),
  };
  async function init() {
    const res = await fetch(`${API_BASE}/products`);
    const data = await res.json();
    state.allProducts = data.products;
    renderGrid();
    document.getElementById("result-meta").textContent =
      `Showing ${data.total} of ${data.total}`;
  }
  function applyUIAction(uiAction) {
    return new Promise((resolve) => {
      state.currentFilters = uiAction.filters || {};
      state.pickIds = new Set((uiAction.picks || []).map(p => p.id));
      renderChips();
      setTimeout(() => {
        renderGrid();
        setTimeout(() => {
          renderPicks(uiAction.picks || []);
          updateMeta(uiAction.total_matched);
          resolve();  // ~700ms total before chat.js types text
        }, 450);
      }, 250);
    });
  }
  function pulseSpoken(ids) {
    state.spokenIds = new Set(ids);
    ids.forEach(id => {
      const card = document.querySelector(`[data-id="${id}"]`);
      if (card) {
        card.classList.add("pulse");
        if (ids[0] === id) card.scrollIntoView({behavior: "smooth", block: "center"});
        setTimeout(() => card.classList.remove("pulse"), 1500);
      }
    });
  }
  function removeFilter(field, value) {
    // Emit event consumed by chat.js
    window.dispatchEvent(new CustomEvent("filter-chip-removed", {
      detail: { field, value }
    }));
  }
  // _matches, renderChips, renderGrid, renderPicks, updateMeta — internal
  return { init, applyUIAction, pulseSpoken };
})();
```

**Animation timeline**
- T+0: chat.js receives response
- T+0: `applyUIAction()` starts; chips render with `.new` class (CSS keyframe: slide-in + green flash 1.2s)
- T+250: grid re-renders (matched class change + opacity transition 400ms; FLIP-style reorder optional, hide+fade is acceptable fallback per Minor N7)
- T+700: pick row renders with stagger (each card .pop animation 200ms staggered 80ms)
- T+700: `applyUIAction` resolves → chat.js begins typewriter
- T+~2500: when typewriter completes, chat.js calls `ProductGrid.pulseSpoken(ids)` → gold pulse 1.5s + scroll first into view

**Card rendering rules**
- All cards: same DOM template, classed via JS state
- Unmatched: `.dim` class → filter: grayscale(50%) opacity(0.4); kept in DOM
- Matched: normal
- Pick (in `pickIds`): `.is-pick` adds gold border + sale badge
- Spoken: `.pulse` keyframe animation 1.5s

**Cart integration**
- Each card has `<button class="add-btn" data-id="...">Add</button>`
- Delegated click handler calls `Cart.add(productId)` → header badge updates immediately

**Accessibility (Risk F1 fix)**
- Filter chips: `<button>` element so keyboard can Tab and Enter to dismiss
- Cart trigger: ARIA label
- Pick row: `<h2>` heading so screen readers announce it

**Acceptance**
- Cold load: 217 cards rendered in grid, 0 chips, picks row hidden, cart count 0
- Filter applied: chips animate, unmatched dim, matched stay sharp, picks render in top row
- Cart add: count increments without page reload, persists across reload
- Keyboard: Tab through chips, Enter removes one (fires `filter-chip-removed` event)
- Mobile @600px: panes stack; product grid above chat (or hideable)

---

### Module 6 — chat.js refactor + ui_action consumption + chip-× wiring

**Files**
- `frontend/chat.js`

**Changes**
1. Drop floating-button code; chat is now always visible in right pane
2. Welcome message renders on init
3. `callChatAPI` takes optional `extraPayload`:
   ```js
   async function callChatAPI(userMessage, extraPayload = {}) {
     const payload = {
       session_id: sessionId,
       messages: conversationHistory,
       is_beginner: false,
       user_message: userMessage,
       ...extraPayload,
     };
     const res = await fetch(`${API_BASE}/chat`, { method: "POST", ... });
     return await res.json();  // full response: { reply, ui_action, ... }
   }
   ```
4. `sendMessage` orchestrates timing:
   ```js
   async function sendMessage(text, { silent = false, extraPayload = {} } = {}) {
     if (!silent) appendMessage("user", text);
     setInputEnabled(false);
     const typingEl = showTypingIndicator();
     try {
       const { reply, ui_action } = await callChatAPI(text, extraPayload);
       typingEl.remove();
       if (ui_action) await ProductGrid.applyUIAction(ui_action);
       await typewriterAppend("ai", reply);  // typewriter ~40 char/s
       if (ui_action?.spoken_product_ids?.length) {
         setTimeout(() => ProductGrid.pulseSpoken(ui_action.spoken_product_ids), 100);
       }
       addToHistory("user", text);   // even if silent, history gets the prompt? See decision below
       addToHistory("assistant", reply);
     } catch (err) {
       typingEl.remove();
       appendMessage("ai", "Sorry, something went wrong. Please try again.");
     } finally { setInputEnabled(true); }
   }
   ```
5. **Chip × handling** (Blocker B5 final design):
   - Frontend does NOT inject a synthetic user message at all.
   - Frontend keeps a record of removed filters locally and includes them in the NEXT POST `/chat` via `extraPayload.removed_filters`.
   - Alternative: send immediately with empty `user_message` and `removed_filters` populated.
   - **Chosen**: send immediately on chip ×, with `user_message: ""` and `removed_filters: {field: value}`. UI shows a special chat bubble:
     ```
     ┌──────────────────────────────┐
     │ 🔧 Filter removed: Sativa     │  ← styled muted, not "user said"
     └──────────────────────────────┘
     ```
   - This bubble is visual only, NOT pushed into `conversationHistory`. The next /chat call still passes the unchanged history; backend receives `removed_filters` and injects its own system instruction (see Module 4 step 3). LLM responds → bubble + re-search appear.
6. `composeRemovalBubble(field, value)`:
   ```js
   const PRETTY = {
     strain_type: "Strain", category: "Form", effects: "Effect", max_price: "Price cap",
   };
   function composeRemovalBubble(field, value) {
     return `🔧 Filter removed: ${PRETTY[field] || field} = ${value}`;
   }
   ```
7. Event listener:
   ```js
   window.addEventListener("filter-chip-removed", async (e) => {
     const { field, value } = e.detail;
     appendSystemBubble(composeRemovalBubble(field, value));
     await sendMessage("", {
       silent: true,
       extraPayload: { removed_filters: { [field]: value } },
     });
   });
   ```
8. Typewriter (`typewriterAppend`):
   - Render text char-by-char at ~40 chars/sec (~25ms per char), batched per requestAnimationFrame
   - Click anywhere in the AI bubble during typing → skip to full text
   - Sanitize HTML same as current `renderMarkdown` (escape, then bold + br)

**Acceptance**
- User types → message bubble → typing indicator → UI animates → text typewriters in
- Chip × → muted system bubble appears immediately; typing indicator; AI responds; chip disappears from chips row
- conversationHistory does NOT contain synthetic chip-removal text
- Removed filter passed via `extraPayload.removed_filters` on the single API call

---

## 3. Cross-module dependencies + execution order

```
M1 (DB schema + seed)
   ↓
M2 (ProductManager: sale fields, pick_meta, score_picks)
   ↓
M3 (llm_service trace + ui_action_builder)        ┐
M4 (API: /products, ChatRequest.removed_filters,   ├─ parallel after M2
    ChatResponse.ui_action, removed_filters inject)┘
   ↓
M5 (frontend layout + grid + cart + placeholders) ← parallel with M3+M4
   ↓
M6 (chat.js refactor — depends on M4 contract + M5 ProductGrid API)
```

**Sub-agent dispatch sequence**
1. Wave 1 (sequential): M1, then M2
2. Wave 2 (parallel, 3 agents): M3, M4, M5
3. Wave 3 (sequential): M6
4. Wave 4 (Claude validates): per-module checks
5. Wave 5 (Claude integration): eval + 4 manual flows

---

## 4. Risk register & mitigations (v2)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Breaking eval / tests via signature change | RESOLVED | — | Out-param `trace`; `get_recommendation` still returns `str` |
| R2 | Non-visualizable filter fields confuse UI | RESOLVED | — | Whitelist excludes `is_beginner`, `hardware_type` |
| R3 | Reply mentions product not in `filtered_products` | LOW | LOW | Scan only against filtered_products; misses silent |
| R4 | localStorage cart desync after id changes | LOW | LOW | Stable PKs in SQLite; cart key versioned `_v1`; validate on render |
| R5 | Chip × triggers compliance gate | RESOLVED | — | Backend `removed_filters` injection, no synthetic user message |
| R6 | Pick scoring picks a non-visible product | RESOLVED | — | Scoring input is already-filtered list |
| R7 | best_value div-by-0 | RESOLVED | — | `thc_numeric` skips zero/NaN |
| R8 | Mobile layout breaks | MED | LOW | CSS `@media (max-width: 700px)` stacks panes; basic responsive only for MVP |
| R9 | CORS on /products | LOW | LOW | Global CORS in main.py |
| R10 | /chat/stream diverges | LOW | LOW | Documented as legacy; not consumed by new frontend |
| R11 | Product name scan misses `&`/`|` names | RESOLVED | — | `_scan_key` first-segment + non-word-char lookarounds |
| R12 | Effect intent → DB effect mismatch | RESOLVED | — | EFFECT_INTENT_TO_DB mapping table |
| R13 | Tier 7 missing → empty picks row | RESOLVED | — | Fallback tier 7 added |
| R14 | Double profile extraction | RESOLVED | — | Profile stored in `trace`, reused by builder |
| R15 | JS load order races | RESOLVED | — | Explicit script tag order documented |
| R16 | Accessibility — chips not keyboard-removable | RESOLVED | — | Chips are `<button>` elements with ARIA labels |
| R17 | Seed script not in CI/test fixtures | MED | LOW | `tests/conftest.py` invokes seeder for test DB; CI runs full setup |
| R18 | `removed_filters` instruction conflicts with router fast-path | LOW | MED | Treat `removed_filters` flow as bypassing fast-path; LLM handles directly (see M4 detail) |

---

## 5. Test plan (v2)

### 5.1 Unit tests (new)
- `tests/test_pick_scoring.py` (~12 cases)
  - each tier triggers in isolation
  - caps (best_value=1, premium=1)
  - tier 7 fallback when no other tier matches
  - mixed THC unit cohorts → best_value scoped to majority unit
  - empty input → empty output
  - effect intent mapping resolves correctly (`'sleep'` → matches product with `"Sleepy"` in effects)
  - beginner gating (skips product when experience_level mismatches)
  - thc_numeric extractor (`'22%'`, `'5mg'`, empty, malformed)

- `tests/test_ui_action_builder.py` (~6 cases)
  - no smart_search in trace → `None`
  - agent-loop trace → ui_action populated
  - fast-path trace → ui_action populated (same shape)
  - scan picks up name with `|` separator
  - scan picks up bolded `**Name**` markdown
  - is_beginner / hardware_type filtered out of `filters`

### 5.2 API tests (update existing)
- `tests/test_api.py::test_get_products` — new
- `tests/test_api.py::test_chat_includes_ui_action_on_search` — new
- `tests/test_api.py::test_chat_no_ui_action_on_greeting` — new
- `tests/test_api.py::test_chat_with_removed_filters` — new

### 5.3 Eval regression
- `python eval/run_eval.py` — must remain 25/25 (no test case touches `ui_action`)
- `get_recommendation` returns `str` so `eval/run_eval.py:367` line unchanged

### 5.4 Manual validation (4 flows)
**Flow A — Cold load**
- Open `http://localhost:3000`
- ✅ 217 products visible, no chips, no picks row, cart=0

**Flow B — Stepwise filter**
- Type "I want sativa" → ✅ chip "Sativa" slides in BEFORE text
- ✅ non-Sativa products dim
- ✅ Top Pick row shows 1-3 Sativa picks with reasons
- Type "flower" → ✅ chip "Flower" slides in; intersection filters; picks re-score
- ✅ AI text appears after UI updates; mentions products with gold pulse on those cards

**Flow C — Change mind**
- Continuing from B, type "actually, indica"
- ✅ "Sativa" chip animates out, "Indica" chip animates in
- ✅ grid + picks reshuffle to Indica

**Flow D — Chip × removal**
- With Sativa + Flower chips active, click × on Sativa chip
- ✅ muted system bubble: "🔧 Filter removed: Strain = Sativa"
- ✅ AI responds (typing indicator → reply): "Sure — opening up beyond Sativa..."
- ✅ chip disappears; grid expands to all Flower; new picks score

**Flow E — Cart**
- Click "Add" on any card → ✅ header count +1, persists on reload
- Click cart trigger → drawer opens, item visible
- Click × in drawer → ✅ removed, count -1

---

## 6. Out-of-scope (phase 2+)
- Streaming with ui_action
- Real product images
- Real inventory sync
- Cart checkout / payment
- Detailed mobile polish, gestures
- A/B testing pick-reason templates
- User accounts / persisted prefs
- Sale data persistence in setup_db.py auto-run

---

## 7. Estimated effort (v2)

| Module | LoC delta | Difficulty |
|---|---|---|
| M1 | ~50 (script + tests) | Trivial |
| M2 | ~180 (scoring + pre-compute + tests) | Medium |
| M3 | ~100 (trace + builder + tests) | Medium |
| M4 | ~60 (endpoints + request/response + injection) | Trivial-Medium |
| M5 | ~600 (4 JS files + CSS rewrite + HTML) | High |
| M6 | ~180 (chat.js + typewriter + chip-× wiring) | Medium |
| **Total** | **~1170** | — |

LoC growth from v1 (780) reflects:
- effect mapping table + thc_numeric (M2)
- product name scan punctuation handling (M3)
- removed_filters API field + injection (M4)
- accessibility refinements + system bubble + typewriter polish (M5/M6)

---

## 8. Decision log (resolved in v2)

| Decision | Choice | Why |
|---|---|---|
| Signature breakage | Out-param `trace` keyword | Zero break to eval/tests |
| Chip × mechanism | Backend `removed_filters` field | Avoids regex collision; clean history |
| Picks min count | Tier 7 fallback ensures ≥1 when filtered non-empty | UX consistency |
| Best value cohort | Majority THC unit in filtered set | Avoid % vs mg cross-unit nonsense |
| Effect mapping | Explicit dict EFFECT_INTENT_TO_DB | Lowercase verbs ≠ DB PascalCase |
| Product name scan | First-pipe-segment + non-word lookarounds | Tolerates `&`, `|`, `*`, etc. |
| Pre-compute pick meta | At ProductManager.load() | One-time cost, simpler score_picks |
| Cart key | `budtender_cart_v1` | Future migration headroom |
| Streaming | Legacy only, no MVP consumer | Less surface area, no ui_action streaming |

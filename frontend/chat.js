/**
 * Chat — bottom sticky drawer that hosts the AI Budtender conversation.
 *
 * Responsibilities:
 *   - Toggle expand/collapse on the bottom drawer.
 *   - Render welcome message after init.
 *   - Send user message → POST /chat with manual_filters from Store →
 *     run ProductGrid.applyUIAction → typewriter the AI reply → pulse spoken.
 *   - Listen for `filter-chip-removed` events from ProductGrid; for fields
 *     the AI understands, round-trip /chat with removed_filters (and a
 *     visual "filter removed" bubble). For fields it doesn't (brand,
 *     max_thc, on_sale, query), the chip × already updated Store locally
 *     and we don't pester the AI.
 *   - Typewriter effect with click-to-skip.
 *
 * Dependencies:
 *   - window.Store          (state.js)
 *   - window.ProductGrid    (product-grid.js)
 *   - window.Cart           (cart.js)
 *   - API_BASE              (placeholders.js)
 */

const MAX_HISTORY = 20;

let sessionId = generateUUID();
let conversationHistory = [];
let isSending = false;

function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

let messagesEl = null;
let inputEl = null;
let sendBtn = null;
let drawerEl = null;
let toggleBtn = null;
let bodyEl = null;
let closeBtn = null;

const PRETTY = {
  strain_type: "Strain",
  category: "Form",
  effects: "Effect",
  max_price: "Price cap",
};

// ── Bootstrap ────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  drawerEl = document.getElementById("chat-drawer");
  toggleBtn = document.getElementById("chat-drawer-toggle");
  bodyEl = document.getElementById("chat-drawer-body");
  closeBtn = document.getElementById("chat-drawer-close");
  messagesEl = document.getElementById("budtender-messages");
  inputEl = document.getElementById("budtender-input");
  sendBtn = document.getElementById("budtender-send");

  if (toggleBtn) toggleBtn.addEventListener("click", toggleDrawer);
  if (closeBtn) closeBtn.addEventListener("click", collapseDrawer);
  if (sendBtn) sendBtn.addEventListener("click", onSendClick);
  if (inputEl) {
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSendClick();
      }
    });
  }

  // Render welcome once on load (drawer remains collapsed by default).
  appendMessage(
    "ai",
    "Hey there! 👋 I'm your AI Budtender. Tell me the vibe you're after — relaxing, social, focused, sleep — and I'll narrow the menu for you."
  );
});

// ── Drawer expand/collapse ───────────────────────────────────────────────────
function toggleDrawer() {
  if (!drawerEl) return;
  if (drawerEl.classList.contains("expanded")) {
    collapseDrawer();
  } else {
    expandDrawer();
  }
}
function expandDrawer() {
  if (!drawerEl) return;
  drawerEl.classList.remove("collapsed");
  drawerEl.classList.add("expanded");
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
  if (bodyEl) bodyEl.hidden = false;
  setTimeout(() => {
    if (inputEl) inputEl.focus();
    scrollToBottom();
  }, 60);
}
function collapseDrawer() {
  if (!drawerEl) return;
  drawerEl.classList.remove("expanded");
  drawerEl.classList.add("collapsed");
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
  if (bodyEl) bodyEl.hidden = true;
}

// ── Send flow ────────────────────────────────────────────────────────────────
function onSendClick() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text || isSending) return;
  inputEl.value = "";
  sendMessage(text);
}

async function sendMessage(text, extras = {}) {
  if (drawerEl && !drawerEl.classList.contains("expanded")) {
    expandDrawer();
  }
  appendMessage("user", text);
  setInputEnabled(false);
  const typingEl = showTypingIndicator();

  try {
    const fullReply = await streamFlow(text, extras);
    if (!fullReply.firstChunkArrived) {
      // Defensive: no chunks at all (shouldn't happen for a non-empty reply)
      typingEl.remove();
      appendMessage("ai", "(no reply received)");
    }

    addToHistory("user", text);
    addToHistory("assistant", fullReply.text || "");
  } catch (err) {
    if (typingEl && typingEl.remove) typingEl.remove();
    appendMessage("ai", "Sorry, something went wrong. Please try again.");
    console.error("Chat error:", err);
  } finally {
    setInputEnabled(true);
  }

  /**
   * Inline helper that orchestrates the SSE → DOM pipeline for one turn:
   *   - on ui_action: fire-and-forget ProductGrid.applyUIAction (animation
   *     runs in parallel with the text streaming below)
   *   - on first chunk: remove typing indicator, create AI bubble, append
   *   - on later chunks: append to the same bubble, scroll to bottom
   *   - on spoken event: pulse the named cards
   */
  async function streamFlow(userMessage, extraPayload) {
    let aiBubble = null;
    let rawText = "";
    let firstChunkArrived = false;

    await streamChatAPI(userMessage, extraPayload, {
      onUIAction(uiAction) {
        if (window.ProductGrid) {
          window.ProductGrid.applyUIAction(uiAction);
        }
      },
      onChunk(chunk) {
        if (!firstChunkArrived) {
          firstChunkArrived = true;
          if (typingEl && typingEl.remove) typingEl.remove();
          aiBubble = document.createElement("div");
          aiBubble.className = "message ai";
          messagesEl.appendChild(aiBubble);
        }
        rawText += chunk;
        aiBubble.innerHTML = renderMarkdown(rawText);
        scrollToBottom();
      },
      onSpoken(ids) {
        if (window.ProductGrid && Array.isArray(ids) && ids.length > 0) {
          window.ProductGrid.pulseSpoken(ids);
        }
      },
      onPicks(picks) {
        if (window.ProductGrid && typeof window.ProductGrid.applyPicks === "function") {
          window.ProductGrid.applyPicks(picks);
        }
      },
    });

    return { text: rawText, firstChunkArrived };
  }
}

// ── Filter-chip × handler ────────────────────────────────────────────────────
// ProductGrid removed the filter from Store already; here we round-trip the
// backend (with removed_filters) so the AI can comment + re-search via the
// streaming endpoint.
window.addEventListener("filter-chip-removed", async (e) => {
  if (isSending) return;
  const detail = (e && e.detail) || {};
  const { field, value } = detail;
  if (!field) return;

  if (drawerEl && !drawerEl.classList.contains("expanded")) {
    expandDrawer();
  }

  appendSystemBubble(
    `🔧 Filter removed: ${PRETTY[field] || field} = ${value}`
  );

  setInputEnabled(false);
  const typingEl = showTypingIndicator();

  let aiBubble = null;
  let rawText = "";
  let firstChunkArrived = false;

  try {
    await streamChatAPI(
      "",
      { removed_filters: { [field]: String(value) } },
      {
        onUIAction(uiAction) {
          if (window.ProductGrid) {
            window.ProductGrid.applyUIAction(uiAction);
          }
        },
        onChunk(chunk) {
          if (!firstChunkArrived) {
            firstChunkArrived = true;
            typingEl.remove();
            aiBubble = document.createElement("div");
            aiBubble.className = "message ai";
            messagesEl.appendChild(aiBubble);
          }
          rawText += chunk;
          aiBubble.innerHTML = renderMarkdown(rawText);
          scrollToBottom();
        },
        onSpoken(ids) {
          if (window.ProductGrid && Array.isArray(ids) && ids.length > 0) {
            window.ProductGrid.pulseSpoken(ids);
          }
        },
        onPicks(picks) {
          if (window.ProductGrid && typeof window.ProductGrid.applyPicks === "function") {
            window.ProductGrid.applyPicks(picks);
          }
        },
      }
    );

    if (!firstChunkArrived) {
      typingEl.remove();
    }
    addToHistory("assistant", rawText || "");
  } catch (err) {
    if (typingEl && typingEl.remove) typingEl.remove();
    appendMessage("ai", "Sorry, something went wrong.");
    console.error("Chip-removal chat error:", err);
  } finally {
    setInputEnabled(true);
  }
});

function addToHistory(role, content) {
  conversationHistory.push({ role, content });
  while (conversationHistory.length > MAX_HISTORY) {
    conversationHistory.splice(0, 2);
  }
}

// ── SSE / streaming chat call ────────────────────────────────────────────────
/**
 * POST /chat/stream and parse the typed SSE response.
 *
 * Wire format (see backend/main.py):
 *   event: ui_action  → filters + total_matched (picks always empty here)
 *   data:  {chunk: "..."}  → reply text, may arrive in many chunks
 *   event: spoken     → [id, id, ...] ordered list of product ids
 *   event: picks      → [{id, pick_reason, ...}, ...] Top Pick row content,
 *                       derived from the spoken ids after reply completes
 *   data:  [DONE]
 *
 * Callbacks
 *   onUIAction(uiAction)  — once (or zero times) per turn
 *   onChunk(text)         — many times
 *   onSpoken(ids)         — once (or zero times)
 *   onPicks(picks)        — once (or zero times)
 *
 * Always includes the current sidebar state as `manual_filters` so the AI
 * sees what's narrowed; backend uses it as low-priority context.
 */
async function streamChatAPI(userMessage, extras = {}, callbacks = {}) {
  const manualFilters = window.Store
    ? window.Store.getManualFiltersPayload()
    : {};

  const payload = {
    session_id: sessionId,
    messages: conversationHistory,
    is_beginner: false,
    user_message: userMessage,
    ...(Object.keys(manualFilters).length ? { manual_filters: manualFilters } : {}),
    ...extras,
  };

  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    throw new Error(`API error: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by a blank line ("\n\n"). Find the boundary
    // and drain complete events from the buffer; the tail (incomplete) stays.
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const evt = parseSSEEvent(rawEvent);
      if (!evt) continue;

      if (evt.data === "[DONE]") {
        return;
      }
      if (evt.event === "ui_action") {
        try {
          callbacks.onUIAction && callbacks.onUIAction(JSON.parse(evt.data));
        } catch (e) {
          console.warn("Malformed ui_action SSE:", e);
        }
      } else if (evt.event === "spoken") {
        try {
          callbacks.onSpoken && callbacks.onSpoken(JSON.parse(evt.data));
        } catch (e) {
          console.warn("Malformed spoken SSE:", e);
        }
      } else if (evt.event === "picks") {
        try {
          callbacks.onPicks && callbacks.onPicks(JSON.parse(evt.data));
        } catch (e) {
          console.warn("Malformed picks SSE:", e);
        }
      } else {
        // Default event (no `event:` line): chunk or error
        try {
          const parsed = JSON.parse(evt.data);
          if (parsed.error) {
            throw new Error(parsed.error);
          }
          if (typeof parsed.chunk === "string") {
            callbacks.onChunk && callbacks.onChunk(parsed.chunk);
          }
        } catch (e) {
          // Swallow malformed payloads silently — keep parsing further events.
          console.warn("Malformed chunk SSE:", e);
        }
      }
    }
  }
}

function parseSSEEvent(raw) {
  if (!raw) return null;
  const lines = raw.split("\n");
  let event = null;
  let data = "";
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // Per spec, data lines accumulate with newline separators. Our backend
      // uses single-line data, so trim works.
      data += line.slice(5).trim();
    }
  }
  return { event, data };
}

// ── DOM helpers ──────────────────────────────────────────────────────────────
function renderMarkdown(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function appendMessage(role, text) {
  if (!messagesEl) return null;
  const el = document.createElement("div");
  el.className = `message ${role}`;
  if (role === "ai") {
    el.innerHTML = renderMarkdown(text);
  } else {
    el.textContent = text;
  }
  messagesEl.appendChild(el);
  scrollToBottom();
  return el;
}

function appendSystemBubble(text) {
  if (!messagesEl) return null;
  const el = document.createElement("div");
  el.className = "message system";
  el.textContent = text;
  messagesEl.appendChild(el);
  scrollToBottom();
  return el;
}

function typewriterAppend(role, text) {
  return new Promise((resolve) => {
    if (!messagesEl) return resolve();
    const safeText = String(text == null ? "" : text);

    const el = document.createElement("div");
    el.className = `message ${role}`;
    messagesEl.appendChild(el);

    let i = 0;
    let skipped = false;
    let done = false;

    function finish() {
      if (done) return;
      done = true;
      el.innerHTML = renderMarkdown(safeText);
      scrollToBottom();
      resolve();
    }

    el.addEventListener("click", () => {
      skipped = true;
      finish();
    });

    function step() {
      if (done) return;
      if (skipped || i >= safeText.length) {
        return finish();
      }
      i = Math.min(safeText.length, i + 4);
      el.textContent = safeText.slice(0, i);
      scrollToBottom();
      setTimeout(step, 100);
    }

    if (safeText.length === 0) {
      finish();
    } else {
      step();
    }
  });
}

function showTypingIndicator() {
  if (!messagesEl) return { remove() {} };
  const el = document.createElement("div");
  el.className = "typing-indicator";
  el.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(el);
  scrollToBottom();
  return el;
}

function scrollToBottom() {
  if (!messagesEl) return;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setInputEnabled(enabled) {
  isSending = !enabled;
  if (inputEl) inputEl.disabled = !enabled;
  if (sendBtn) sendBtn.disabled = !enabled;
  if (enabled && inputEl) inputEl.focus();
}

// ── Public API for other modules ─────────────────────────────────────────────
window.Chat = {
  /**
   * Programmatically send a user message to the budtender (e.g. from the
   * product modal's quick-question chip or the compare tray's "Compare in chat"
   * button). Expands the drawer if collapsed.
   *
   * `extras` is forwarded to the chat API payload — used by the compare
   * tray to send `compare_product_ids: [n, n, n]` so the backend resolves
   * the products by ID instead of by free-text name.
   */
  ask(text, extras = {}) {
    const t = String(text || "").trim();
    if (!t || isSending) return false;
    sendMessage(t, extras);
    return true;
  },
  expand: expandDrawer,
  collapse: collapseDrawer,
};

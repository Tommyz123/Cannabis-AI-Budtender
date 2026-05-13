/**
 * AI Budtender Chat — Module 6 refactor.
 *
 * Responsibilities:
 *   - Render welcome message after product grid loads
 *   - sendMessage flow that POSTs /chat, then orchestrates UI animation
 *     BEFORE typewriter-rendering the AI reply
 *   - Listen for `filter-chip-removed` CustomEvent dispatched by ProductGrid
 *     and POST /chat with `removed_filters` (and empty user_message)
 *   - Typewriter effect with click-to-skip
 *
 * Depends on:
 *   - API_BASE             (placeholders.js)
 *   - window.Cart          (cart.js)
 *   - window.ProductGrid   (product-grid.js, exposes init/applyUIAction/pulseSpoken)
 *
 * NOTE: ProductGrid dispatches `filter-chip-removed` (detail: {field, value})
 * when the user clicks a chip ×; chat.js does NOT add a chip-click handler.
 */

const MAX_HISTORY = 20;

// ── Session state ────────────────────────────────────────────────────────────

let sessionId = generateUUID();
let conversationHistory = []; // Array of {role, content} objects
let isSending = false;

function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ── DOM references ───────────────────────────────────────────────────────────

let messagesEl = null;
let inputEl = null;
let sendBtn = null;

// ── Pretty label map for the filter-removed system bubble ────────────────────

const PRETTY = {
  strain_type: "Strain",
  category: "Form",
  effects: "Effect",
  max_price: "Price cap",
};

// ── Bootstrap ────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
  messagesEl = document.getElementById("budtender-messages");
  inputEl = document.getElementById("budtender-input");
  sendBtn = document.getElementById("budtender-send");

  if (sendBtn) sendBtn.addEventListener("click", onSendClick);
  if (inputEl) {
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSendClick();
      }
    });
  }

  // Load the product grid before showing the welcome bubble so the
  // first thing the user sees is a populated page.
  if (window.ProductGrid && typeof window.ProductGrid.init === "function") {
    try {
      await window.ProductGrid.init();
    } catch (err) {
      console.warn("ProductGrid.init failed:", err);
    }
  }

  // Refresh cart badge from localStorage (no-op if Cart.render isn't exposed).
  if (window.Cart && typeof window.Cart.render === "function") {
    window.Cart.render();
  }

  appendMessage(
    "ai",
    "Hey there! 👋 Welcome! I'm your AI Budtender — here to help you find something that's just right. What brings you in?"
  );
});

// ── User-initiated send ──────────────────────────────────────────────────────

function onSendClick() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text || isSending) return;
  inputEl.value = "";
  sendMessage(text);
}

async function sendMessage(text) {
  appendMessage("user", text);
  setInputEnabled(false);
  const typingEl = showTypingIndicator();

  try {
    const data = await callChatAPI(text);
    typingEl.remove();

    if (data.ui_action) {
      await window.ProductGrid.applyUIAction(data.ui_action);
    }
    await typewriterAppend("ai", data.reply || "");
    schedulePulse(data.ui_action);

    addToHistory("user", text);
    addToHistory("assistant", data.reply || "");
  } catch (err) {
    typingEl.remove();
    appendMessage("ai", "Sorry, something went wrong. Please try again.");
    console.error("Chat error:", err);
  } finally {
    setInputEnabled(true);
  }
}

// ── Filter-chip × handler ────────────────────────────────────────────────────

window.addEventListener("filter-chip-removed", async (e) => {
  if (isSending) return; // ignore while another request is in flight
  const detail = (e && e.detail) || {};
  const { field, value } = detail;
  if (!field) return;

  // Visual-only system bubble; NOT pushed into conversationHistory.
  appendSystemBubble(
    `🔧 Filter removed: ${PRETTY[field] || field} = ${value}`
  );

  setInputEnabled(false);
  const typingEl = showTypingIndicator();

  try {
    const data = await callChatAPI("", {
      removed_filters: { [field]: value },
    });
    typingEl.remove();

    if (data.ui_action) {
      await window.ProductGrid.applyUIAction(data.ui_action);
    }
    await typewriterAppend("ai", data.reply || "");
    schedulePulse(data.ui_action);

    // Do NOT push the synthetic empty user_message into history.
    // DO push the assistant reply so future turns have context.
    addToHistory("assistant", data.reply || "");
  } catch (err) {
    typingEl.remove();
    appendMessage("ai", "Sorry, something went wrong.");
    console.error("Chip-removal chat error:", err);
  } finally {
    setInputEnabled(true);
  }
});

function schedulePulse(uiAction) {
  const ids =
    uiAction && Array.isArray(uiAction.spoken_product_ids)
      ? uiAction.spoken_product_ids
      : [];
  if (ids.length === 0) return;
  if (!window.ProductGrid || typeof window.ProductGrid.pulseSpoken !== "function") return;
  setTimeout(() => window.ProductGrid.pulseSpoken(ids), 100);
}

// ── History management ───────────────────────────────────────────────────────

function addToHistory(role, content) {
  conversationHistory.push({ role, content });
  while (conversationHistory.length > MAX_HISTORY) {
    conversationHistory.splice(0, 2);
  }
}

// ── API call ─────────────────────────────────────────────────────────────────

async function callChatAPI(userMessage, extras = {}) {
  const payload = {
    session_id: sessionId,
    messages: conversationHistory,
    is_beginner: false,
    user_message: userMessage,
    ...extras,
  };

  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return await response.json();
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
      setTimeout(step, 100); // ~40 char/s with batch of 4
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

// ── Public API for other modules (e.g. product detail modal) ─────────────────

window.Chat = {
  /**
   * Programmatically send a user message to the budtender.
   * Behaves identically to typing the text and pressing Send.
   */
  ask(text) {
    const t = String(text || "").trim();
    if (!t || isSending) return false;
    sendMessage(t);
    return true;
  },
};

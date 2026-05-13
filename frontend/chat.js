/**
 * AI Budtender Chat — Module 5 (minimal) version.
 *
 * Module 6 will refactor this file to consume ui_action and wire chip-×.
 * This version only:
 *   - reads new two-pane DOM IDs (chat is always visible in right pane)
 *   - keeps API call shape identical to pre-Module-5 behavior
 *   - drops the floating trigger / close button entirely
 *   - relies on API_BASE from placeholders.js (loaded earlier)
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

// ── DOM references (new two-pane IDs) ────────────────────────────────────────

let messagesEl = null;
let inputEl = null;
let sendBtn = null;

function bindDOM() {
  messagesEl = document.getElementById("budtender-messages");
  inputEl = document.getElementById("budtender-input");
  sendBtn = document.getElementById("budtender-send");

  if (sendBtn) sendBtn.addEventListener("click", sendMessage);
  if (inputEl) {
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  renderWelcome();
}

function renderWelcome() {
  if (!messagesEl) return;
  if (messagesEl.children.length > 0) return;
  appendMessage(
    "ai",
    "Hey there! 👋 Welcome! I'm your AI Budtender — here to help you find something that's just right for you today. What brings you in?"
  );
}

// ── Send message ─────────────────────────────────────────────────────────────

async function sendMessage() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text || isSending) return;

  appendMessage("user", text);
  inputEl.value = "";
  setInputEnabled(false);

  const typingEl = showTypingIndicator();

  try {
    const reply = await callChatAPI(text);
    typingEl.remove();

    appendMessage("ai", reply);
    addToHistory("user", text);
    addToHistory("assistant", reply);
  } catch (err) {
    typingEl.remove();
    appendMessage("ai", "Sorry, something went wrong. Please try again.");
    console.error("Chat error:", err);
  } finally {
    setInputEnabled(true);
  }
}

// ── History management ───────────────────────────────────────────────────────

function addToHistory(role, content) {
  conversationHistory.push({ role, content });
  while (conversationHistory.length > MAX_HISTORY) {
    conversationHistory.splice(0, 2);
  }
}

// ── API call ─────────────────────────────────────────────────────────────────

async function callChatAPI(userMessage) {
  const payload = {
    session_id: sessionId,
    messages: conversationHistory,
    is_beginner: false,
    user_message: userMessage,
  };

  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  const data = await response.json();
  return data.reply;
}

// ── DOM helpers ──────────────────────────────────────────────────────────────

function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function appendMessage(role, text) {
  if (!messagesEl) return;
  const el = document.createElement("div");
  el.className = `message ${role}`;
  if (role === "ai") {
    el.innerHTML = renderMarkdown(text);
  } else {
    el.textContent = text;
  }
  messagesEl.appendChild(el);
  scrollToBottom();
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

// ── Init ─────────────────────────────────────────────────────────────────────

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bindDOM);
} else {
  bindDOM();
}

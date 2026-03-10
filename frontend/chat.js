/**
 * AI Budtender Chat Widget
 * Manages session, conversation history, API calls, and UI rendering.
 */

const API_BASE = "http://localhost:8000";
const MAX_HISTORY = 20;

// ── Session state ─────────────────────────────────────────────────────────────

let sessionId = generateUUID();
let conversationHistory = [];  // Array of {role, content} objects
let isSending = false;

function generateUUID() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ── DOM references ────────────────────────────────────────────────────────────

const trigger = document.getElementById("budtender-trigger");
const container = document.getElementById("budtender-container");
const closeBtn = document.getElementById("budtender-close");
const messagesEl = document.getElementById("budtender-messages");
const inputEl = document.getElementById("budtender-input");
const sendBtn = document.getElementById("budtender-send");

// ── UI toggle ─────────────────────────────────────────────────────────────────

trigger.addEventListener("click", () => {
  container.classList.toggle("hidden");
  if (!container.classList.contains("hidden")) {
    inputEl.focus();
  }
});

closeBtn.addEventListener("click", () => {
  container.classList.add("hidden");
});

// ── Send message ──────────────────────────────────────────────────────────────

sendBtn.addEventListener("click", sendMessage);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function sendMessage() {
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

// ── History management ────────────────────────────────────────────────────────

function addToHistory(role, content) {
  conversationHistory.push({ role, content });

  // Keep within MAX_HISTORY by removing oldest pair when over limit
  while (conversationHistory.length > MAX_HISTORY) {
    conversationHistory.splice(0, 2);  // Remove oldest user+assistant pair
  }
}

// ── API call ──────────────────────────────────────────────────────────────────

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

// ── DOM helpers ───────────────────────────────────────────────────────────────

function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function appendMessage(role, text) {
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
  const el = document.createElement("div");
  el.className = "typing-indicator";
  el.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(el);
  scrollToBottom();
  return el;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setInputEnabled(enabled) {
  isSending = !enabled;
  inputEl.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) inputEl.focus();
}

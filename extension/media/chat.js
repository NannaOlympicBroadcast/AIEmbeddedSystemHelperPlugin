// @ts-check
(function () {
  const vscode = acquireVsCodeApi();

  const messagesEl = /** @type {HTMLElement} */ (document.getElementById("messages"));
  const inputEl = /** @type {HTMLTextAreaElement} */ (document.getElementById("input"));
  const sendBtn = /** @type {HTMLButtonElement} */ (document.getElementById("send-btn"));
  const clearBtn = /** @type {HTMLButtonElement} */ (document.getElementById("clear-btn"));
  const reloadBtn = /** @type {HTMLButtonElement} */ (document.getElementById("reload-btn"));

  /** @type {HTMLElement|null} - created lazily on first text chunk */
  let currentAssistantBubble = null;

  // ─── Minimal Markdown renderer ───────────────────────────────────────────
  /**
   * Convert a markdown string to safe HTML.
   * Handles: headings, bold, italic, inline code, code blocks, links, lists, hr.
   * @param {string} md
   * @returns {string}
   */
  function renderMarkdown(md) {
    // Escape HTML entities first
    let html = md
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Fenced code blocks ```lang\n...\n```
    html = html.replace(
      /```([^\n]*)\n([\s\S]*?)```/g,
      (_, lang, code) =>
        `<pre><code class="lang-${lang.trim()}">${code}</code></pre>`
    );

    // Process line by line for block-level elements
    const lines = html.split("\n");
    const out = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i];

      // Headings
      const hMatch = line.match(/^(#{1,4})\s+(.*)/);
      if (hMatch) {
        if (inList) { out.push("</ul>"); inList = false; }
        const level = hMatch[1].length;
        out.push(`<h${level}>${applyInline(hMatch[2])}</h${level}>`);
        continue;
      }

      // Horizontal rule
      if (/^---+$/.test(line.trim())) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<hr>");
        continue;
      }

      // Unordered list items
      const liMatch = line.match(/^[-*+]\s+(.*)/);
      if (liMatch) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${applyInline(liMatch[1])}</li>`);
        continue;
      }

      // End list on blank line
      if (line.trim() === "") {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<br>");
        continue;
      }

      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<p>${applyInline(line)}</p>`);
    }

    if (inList) out.push("</ul>");
    return out.join("");
  }

  /** Apply inline markdown spans (bold, italic, code, links). */
  function applyInline(text) {
    return text
      // Inline code `...`
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // Bold **...** or __...__
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      // Italic *...* or _..._
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/_([^_]+)_/g, "<em>$1</em>")
      // Links [text](url)
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
      );
  }

  // ─── Tool Icons ──────────────────────────────────────────────────────────
  const TOOL_ICONS = {
    tavily_search: "🔍",
    get_project_memory: "🧠",
    save_project_memory: "💾",
    list_projects: "📋",
    update_project_docs: "📎",
    add_status_note: "📝",
    list_project_files: "📁",
    read_project_file: "📄",
    list_boards: "🔌",
    get_board_info: "ℹ️",
    init_project: "🚀",
    build_project: "🔨",
    upload_firmware: "⬆️",
    search_libraries: "📚",
    install_library: "📦",
    electerm_list_tabs: "🖥️",
    electerm_send_command: "⌨️",
    _default: "⚙️",
  };

  /** @param {string} name */
  function getToolIcon(name) { return TOOL_ICONS[name] || TOOL_ICONS._default; }

  /** @param {string} name */
  function getToolLabel(name) {
    return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // ─── DOM helpers ─────────────────────────────────────────────────────────

  /**
   * Append a user or error message bubble.
   * @param {"user"|"error"} role
   * @param {string} text
   */
  function appendUserBubble(role, text) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  /**
   * Lazily create the assistant bubble on the first text chunk.
   * Tool cards that fired before any text will appear ABOVE the bubble.
   * @returns {HTMLElement}
   */
  function getOrCreateAssistantBubble() {
    if (!currentAssistantBubble) {
      currentAssistantBubble = document.createElement("div");
      currentAssistantBubble.className = "msg assistant";
      messagesEl.appendChild(currentAssistantBubble);
    }
    return currentAssistantBubble;
  }

  /** Accumulated raw markdown text for the current assistant turn. */
  let _assistantRawText = "";

  /**
   * Append a chunk of text to the current assistant bubble, re-rendering markdown.
   * @param {string} chunk
   */
  function appendAssistantChunk(chunk) {
    _assistantRawText += chunk;
    const el = getOrCreateAssistantBubble();
    el.innerHTML = renderMarkdown(_assistantRawText);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  /**
   * Create a running tool card and append it to the message flow.
   * @param {string} name
   * @param {string} agent
   * @param {object} args
   * @returns {HTMLElement}
   */
  function appendToolCard(name, agent, args) {
    const card = document.createElement("div");
    card.className = "tool-card running";
    card.dataset.toolName = name;

    const icon = getToolIcon(name);
    const label = getToolLabel(name);
    const agentLabel = agent ? ` <span class="tool-agent">(${agent})</span>` : "";

    let argsPreview = "";
    if (args && typeof args === "object") {
      const keys = Object.keys(args).slice(0, 2);
      if (keys.length > 0) {
        argsPreview = keys
          .map((k) => {
            let v = String(args[k]);
            if (v.length > 50) v = v.substring(0, 50) + "…";
            return `<span class="arg-key">${k}:</span> ${v}`;
          })
          .join("  ");
      }
    }

    card.innerHTML = `
      <div class="tool-header">
        <span class="tool-icon">${icon}</span>
        <span class="tool-name">${label}${agentLabel}</span>
        <span class="tool-spinner"></span>
      </div>
      ${argsPreview ? `<div class="tool-args">${argsPreview}</div>` : ""}
      <div class="tool-status">Running…</div>
    `;

    messagesEl.appendChild(card);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return card;
  }

  /**
   * Find the last running card with the given tool name and mark it done.
   * @param {string} name
   * @param {string} result
   */
  function completeToolCard(name, result) {
    const cards = messagesEl.querySelectorAll(
      `.tool-card.running[data-tool-name="${name}"]`
    );
    const card = cards[cards.length - 1];
    if (!card) return;

    card.classList.remove("running");
    card.classList.add("done");
    card.querySelector(".tool-spinner")?.remove();

    const statusEl = card.querySelector(".tool-status");
    if (statusEl) {
      let preview = result || "Done";
      if (preview.length > 120) preview = preview.substring(0, 120) + "…";
      statusEl.textContent = "✓ " + preview;
    }
  }

  // ─── Send / receive ──────────────────────────────────────────────────────

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    appendUserBubble("user", text);
    inputEl.value = "";
    sendBtn.disabled = true;
    inputEl.disabled = true;
    _assistantRawText = "";
    currentAssistantBubble = null;   // will be created on first chunk

    vscode.postMessage({ type: "userMessage", text });
  }

  sendBtn.addEventListener("click", sendMessage);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  clearBtn.addEventListener("click", () => {
    messagesEl.innerHTML = "";
    currentAssistantBubble = null;
    _assistantRawText = "";
    vscode.postMessage({ type: "clearHistory" });
  });

  reloadBtn.addEventListener("click", () => {
    reloadBtn.disabled = true;
    reloadBtn.textContent = "🔄 Reloading…";
    vscode.postMessage({ type: "reloadAgent" });
  });

  // ─── Message handler ─────────────────────────────────────────────────────

  window.addEventListener("message", (event) => {
    const msg = event.data;

    switch (msg.type) {
      case "assistantChunk":
        appendAssistantChunk(msg.text);
        break;

      case "assistantDone":
        currentAssistantBubble = null;
        _assistantRawText = "";
        sendBtn.disabled = false;
        inputEl.disabled = false;
        inputEl.focus();
        break;

      case "toolStart":
        appendToolCard(msg.name, msg.agent, msg.args);
        break;

      case "toolResult":
        completeToolCard(msg.name, msg.result);
        break;

      case "agentReloaded":
        reloadBtn.disabled = false;
        reloadBtn.textContent = "🔄 Reload Agent";
        appendUserBubble("error", "✅ Agent reloaded — Electerm MCP tools now active if Electerm is running.");
        break;

      case "error":
        if (currentAssistantBubble) {
          currentAssistantBubble.className = "msg error";
          currentAssistantBubble.textContent = "Error: " + msg.text;
          currentAssistantBubble = null;
        } else {
          appendUserBubble("error", "Error: " + msg.text);
        }
        sendBtn.disabled = false;
        inputEl.disabled = false;
        inputEl.focus();
        break;
    }
  });
})();

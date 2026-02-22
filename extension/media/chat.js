// @ts-check
(function () {
  // @ts-ignore: Injected by VS Code Webview
  const vscode = acquireVsCodeApi();

  const messagesEl = /** @type {HTMLElement} */ (document.getElementById("messages"));
  const inputEl = /** @type {HTMLTextAreaElement} */ (document.getElementById("input"));
  const sendBtn = /** @type {HTMLButtonElement} */ (document.getElementById("send-btn"));
  const clearBtn = /** @type {HTMLButtonElement} */ (document.getElementById("clear-btn"));
  const stopBtn = /** @type {HTMLButtonElement} */ (document.getElementById("stop-btn"));

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

  /**
   * Apply inline markdown spans (bold, italic, code, links).
   * @param {string} text
   */
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
  /** @type {Record<string, string>} */
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
   * @param {Record<string, any>} args
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

  // ─── User Form Cards ─────────────────────────────────────────────────────

  /**
   * Render an interactive form card in the chat flow.
   * When the user submits (button click or field submit), send a chat message
   * back through the normal userMessage channel so the agent continues.
   * @param {{ form_id: string, title?: string, description?: string, buttons?: any[], fields?: any[] }} formDef
   */
  function appendFormCard(formDef) {
    const { form_id, title, description, buttons = [], fields = [] } = formDef;

    const card = document.createElement("div");
    card.className = "form-card";
    card.dataset.formId = form_id;

    // ── Build inner HTML ──────────────────────────────────────────────────
    let fieldsHtml = "";
    for (const f of fields) {
      fieldsHtml += `
        <div class="form-field">
          <label class="form-label">${f.label || f.name}</label>
          <input class="form-input" type="text" name="${f.name}"
                 placeholder="${f.placeholder || ""}" />
        </div>`;
    }

    let buttonsHtml = "";
    for (const b of buttons) {
      buttonsHtml += `
        <button class="form-btn" data-value="${b.value}">${b.label}</button>`;
    }

    card.innerHTML = `
      <div class="form-header">📋 <strong>${title}</strong></div>
      ${description ? `<div class="form-desc">${description}</div>` : ""}
      ${fieldsHtml ? `<div class="form-fields">${fieldsHtml}</div>` : ""}
      <div class="form-buttons">${buttonsHtml}</div>
    `;

    // ── Wire up submission ────────────────────────────────────────────────
    /**
     * @param {string} buttonLabel
     * @param {string} buttonValue
     */
    function submitForm(buttonLabel, buttonValue) {
      // Collect field values
      const inputs = /** @type {NodeListOf<HTMLInputElement>} */ (card.querySelectorAll(".form-input"));
      /** @type {string[]} */
      const fieldLines = [];
      inputs.forEach((inp) => {
        if (inp.value.trim()) {
          fieldLines.push(`${inp.name}: ${inp.value.trim()}`);
        }
      });

      // Build the message the agent will receive
      const lines = [
        `[用户表单响应 form_id=${form_id}]`,
        `按钮: ${buttonLabel}`,
        `值: ${buttonValue}`,
      ];
      if (fieldLines.length) {
        lines.push("字段:");
        lines.push(...fieldLines.map((l) => "  " + l));
      }
      const msg = lines.join("\n");

      // Disable the form and show a done state
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
      card.querySelectorAll("input").forEach((i) => (i.disabled = true));
      card.classList.add("form-submitted");
      const doneEl = document.createElement("div");
      doneEl.className = "form-done";
      doneEl.textContent = `✓ 已提交：${buttonLabel}`;
      card.appendChild(doneEl);

      // Send as a new chat message
      vscode.postMessage({ type: "userMessage", text: msg });
    }

    /** @type {NodeListOf<HTMLButtonElement>} */ (card.querySelectorAll(".form-btn")).forEach((btn) => {
      btn.addEventListener("click", () => {
        submitForm(btn.textContent || "", btn.dataset.value || "");
      });
    });

    // Allow pressing Enter in text fields to trigger first button
    /** @type {NodeListOf<HTMLInputElement>} */ (card.querySelectorAll(".form-input")).forEach((inp) => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const firstBtn = /** @type {HTMLButtonElement|null} */ (card.querySelector(".form-btn"));
          if (firstBtn) firstBtn.click();
        }
      });
    });

    messagesEl.appendChild(card);
    messagesEl.scrollTop = messagesEl.scrollHeight;
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

  stopBtn.addEventListener("click", () => {
    stopBtn.disabled = true;
    vscode.postMessage({ type: "stopStream" });
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
        stopBtn.disabled = true;
        inputEl.focus();
        break;

      case "streamStarted":
        stopBtn.disabled = false;
        break;

      case "toolStart":
        // Seal current text bubble so post-tool text goes into a NEW bubble
        // placed AFTER the tool card, not prepended to the bubble above it.
        currentAssistantBubble = null;
        _assistantRawText = "";
        appendToolCard(msg.name, msg.agent, msg.args);
        break;

      case "toolResult":
        completeToolCard(msg.name, msg.result);
        break;

      case "form":
        // Seal current text bubble so the form appears inline after agent text.
        currentAssistantBubble = null;
        _assistantRawText = "";
        appendFormCard(msg);
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
        stopBtn.disabled = true;
        inputEl.focus();
        break;

      case "streamStopped": {
        // Shown after seal endpoint responds — context preserved or reset
        currentAssistantBubble = null;
        _assistantRawText = "";
        const noteEl = document.createElement("div");
        noteEl.className = "msg system-note";
        noteEl.textContent = msg.preserved
          ? "⏹ 任务已停止 · 上下文已保留，可继续对话"
          : "⏹ 任务已停止 · 上下文已重置（新对话将从头开始）";
        messagesEl.appendChild(noteEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        sendBtn.disabled = false;
        inputEl.disabled = false;
        stopBtn.disabled = true;
        inputEl.focus();
        break;
      }
    }
  });
})();

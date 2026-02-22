// @ts-check
(function () {
  const vscode = acquireVsCodeApi();

  const messagesEl = /** @type {HTMLElement} */ (document.getElementById("messages"));
  const inputEl = /** @type {HTMLTextAreaElement} */ (document.getElementById("input"));
  const sendBtn = /** @type {HTMLButtonElement} */ (document.getElementById("send-btn"));
  const clearBtn = /** @type {HTMLButtonElement} */ (document.getElementById("clear-btn"));

  /** @type {HTMLElement|null} */
  let currentAssistantBubble = null;

  function appendMessage(role, text) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    appendMessage("user", text);
    inputEl.value = "";
    sendBtn.disabled = true;
    inputEl.disabled = true;

    // Create an empty assistant bubble to stream into
    currentAssistantBubble = appendMessage("assistant", "");

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
    vscode.postMessage({ type: "clearHistory" });
  });

  window.addEventListener("message", (event) => {
    const msg = event.data;

    if (msg.type === "assistantChunk") {
      if (currentAssistantBubble) {
        currentAssistantBubble.textContent += msg.text;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    } else if (msg.type === "assistantDone") {
      currentAssistantBubble = null;
      sendBtn.disabled = false;
      inputEl.disabled = false;
      inputEl.focus();
    } else if (msg.type === "error") {
      if (currentAssistantBubble) {
        currentAssistantBubble.className = "msg error";
        currentAssistantBubble.textContent = "Error: " + msg.text;
        currentAssistantBubble = null;
      } else {
        appendMessage("error", "Error: " + msg.text);
      }
      sendBtn.disabled = false;
      inputEl.disabled = false;
      inputEl.focus();
    }
  });
})();

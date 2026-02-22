# Dream River

**AI assistant for embedded systems development** — chat with an LLM that understands your board, can operate your terminal, and knows community-written best practices.

> Built with Google ADK · Works with any OpenAI-compatible API · Zero-dependency install (bundled backend)

---

## Features

| | |
|---|---|
| 💬 **Streaming Chat** | SSE-based real-time responses with inline tool-call cards |
| 🧠 **Project Memory** | Board model, OS, skill level, and doc links remembered across sessions |
| 📚 **Best Practices Guide** | Community-editable `best_practices.md` — agent consults it before file transfer, WiFi setup, apt installs, and more |
| 🖥️ **Electerm Integration** | Agent operates SSH/serial terminals on remote boards via Electerm MCP |
| 🔧 **PlatformIO Integration** | Board discovery, project init, build, upload, and library management |
| 🔍 **Web Search** | Tavily-powered search with priority on official datasheets and tutorials |
| ⏹ **Force Stop** | Interrupt generation mid-stream without corrupting the session |
| 😴 **Sleep Tool** | Agent can wait during long `apt install` / `docker build` without polling |
| 📋 **User Forms** | Agent can present inline forms for structured input or pause/resume flows |

---

## Prerequisites

Dream River requires at least one of the following MCP backends depending on your hardware:

### For Single-Board Computers (Raspberry Pi, Radxa, Jetson…)

Install **[Electerm](https://electerm.html5beta.com/)** — a cross-platform SSH/serial terminal with built-in MCP support.

1. Download and install Electerm from the official site.
2. Open Electerm → **Settings → MCP** → enable **MCP server** (default port `30837`).
3. In VS Code Settings, set:
   ```
   Dream River: Electerm MCP URL = http://127.0.0.1:30837/mcp
   ```

### For Microcontrollers (Arduino, ESP32, STM32…)

Install the **PlatformIO MCP server** (when available) or use PlatformIO CLI directly. The agent can run `pio` commands through Electerm if the CLI is installed.

### LLM API

You need access to any **OpenAI-compatible** API endpoint, for example:

| Provider | API Base | Example Model |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `openai/gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek/deepseek-chat` |
| Ollama (local) | `http://localhost:11434/v1` | `openai/qwen2.5-coder:7b` |
| Azure OpenAI | `https://<your>.openai.azure.com/` | `azure/<deployment>` |

---

## Installation

Install from the [Open VSX Marketplace](https://open-vsx.org/extension/OpenOtter/ai-embedded-system-helper) or search **"Dream River"** in the VS Code Extensions panel.

No Python or pip required — the backend executable is bundled inside the extension.

---

## Configuration

Open VS Code Settings (`Ctrl+,`) and search **"Dream River"**:

| Setting | Description | Default |
|---|---|---|
| `aiEmbeddedHelper.apiKey` | API key for your LLM provider | *(required)* |
| `aiEmbeddedHelper.apiBase` | OpenAI-compatible base URL | `https://api.openai.com/v1` |
| `aiEmbeddedHelper.model` | Model name (LiteLLM format) | `openai/gpt-4o` |
| `aiEmbeddedHelper.tavilyApiKey` | Tavily API key for web search | *(optional)* |
| `aiEmbeddedHelper.electermMcpUrl` | Electerm MCP server URL | `http://127.0.0.1:30837/mcp` |
| `aiEmbeddedHelper.streamingEnabled` | Enable SSE streaming | `true` |
| `aiEmbeddedHelper.useExternalBackend` | Use your own backend process | `false` |
| `aiEmbeddedHelper.backendUrl` | URL of external backend | `http://127.0.0.1:8000` |

Settings changes trigger an automatic backend restart — no manual reload needed.

---

## Data Storage

Dream River stores project memory and conversation logs inside your opened workspace:

```
<your_project>/
└── .dream-river/
    └── data/
        ├── projects/   ← remembered board configs, doc URLs, notes
        └── logs/       ← per-session JSONL conversation logs
```

Each VS Code workspace has **its own independent data directory**. If no workspace is open, data is saved to the VS Code global storage location.

> `.dream-river/` is automatically added to `.gitignore` by the extension.

---

## Best Practices Guide

The file `backend/best_practices.md` is a **contributor-editable** knowledge base. The agent reads it before performing common tasks. Add your own team's practices:

```bash
git clone <repo>
# Edit backend/best_practices.md
# Add a new ## Section and send a PR
```

You can view and edit it at `<your_extension_dir>/resources/best_practices.md` after installation.

---

## Usage

1. Open the **Dream River** panel from the sidebar (river icon).
2. Type a question or task description in the chat box.
3. The agent will use tools (terminal, memory, search) as needed and show inline status cards.
4. Long operations: the agent will wait using `sleep_tool` instead of polling.
5. To stop mid-generation: click the **⏹ Stop** button in the toolbar.

### Example Prompts

```
Set up a Raspberry Pi 5 project — board is running Raspberry Pi OS Lite, IP is 192.168.1.42
```
```
Install Docker on the board and verify it runs hello-world
```
```
Transfer build/firmware.bin to the board and flash it
```
```
Connect the board to WiFi "MyNetwork" and verify internet access
```
```
Initialize an ESP32 PlatformIO project with the Arduino framework
```

---

## Architecture

```
VS Code Extension (TypeScript)
  ├── Sidebar WebView (chat.js / chat.css)   ← UI, SSE consumer
  ├── SidebarProvider (sidebarProvider.ts)   ← bridge: webview ↔ backend
  ├── BackendManager (backendManager.ts)     ← spawns/kills Python backend
  └── AgentClient (agentClient.ts)           ← HTTP/SSE requests to backend

Bundled Python Backend (FastAPI + Google ADK)
  ├── main.py                                ← FastAPI app, SSE endpoint
  ├── agent.py                               ← ADK agent, tools registry
  ├── memory.py                              ← project memory persistence
  ├── interaction_tools.py                   ← sleep_tool, request_user_form
  └── best_practices_tool.py                 ← read_best_practices()
```

---

## Development

```bash
# Clone
git clone https://github.com/OpenOtter/dream-river
cd dream-river

# Backend (Python 3.11+)
cd backend
pip install -e ".[dev]"
cp .env.example .env   # fill in API keys
python main.py

# Extension (Node 18+)
cd extension
npm install
# Press F5 in VS Code to launch Extension Development Host
```

Enable hot-reload:
```
DEV_RELOAD=1  # in backend/.env
```

---

## License

MIT © [OpenOtter](https://github.com/OpenOtter)

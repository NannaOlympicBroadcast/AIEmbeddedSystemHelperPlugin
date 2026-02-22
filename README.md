# AIEmbeddedSystemHelperPlugin

A VSCode extension development framework for an AI-powered embedded systems assistant.  
The architecture uses **Google ADK** (Agent Development Kit) as the backend AI agent engine and **OpenVSX** as the extension marketplace target.

```
┌─────────────────────────┐        HTTP / SSE        ┌───────────────────────────────┐
│   VSCode Extension      │ ◄──────────────────────► │   FastAPI + Google ADK        │
│   (TypeScript / OpenVSX)│                           │   (Python backend)            │
│                         │                           │                               │
│  • Chat WebView panel   │                           │  • ADK Runner                 │
│  • agentClient.ts       │                           │  • LiteLLM model adapter      │
│  • panel.ts             │                           │  • OpenAI-compatible API      │
└─────────────────────────┘                           └───────────────────────────────┘
```

---

## Repository layout

```
AIEmbeddedSystemHelperPlugin/
├── backend/                        # Python – Google ADK agent server
│   ├── requirements.txt
│   ├── .env.example                # Copy to .env and fill in your keys
│   ├── config.py                   # Reads environment variables
│   ├── main.py                     # FastAPI entry-point (POST /chat, GET /chat/stream)
│   └── embedded_system_helper/
│       ├── __init__.py
│       └── agent.py                # ADK Agent with LiteLlm model
└── extension/                      # TypeScript – VSCode extension
    ├── package.json                # Extension manifest (OpenVSX-ready)
    ├── tsconfig.json
    ├── .vscodeignore
    ├── src/
    │   ├── extension.ts            # Activation entry-point
    │   ├── panel.ts                # WebviewPanel (chat UI host)
    │   └── agentClient.ts          # HTTP client for the ADK backend
    └── media/
        ├── chat.css                # Webview styles
        └── chat.js                 # Webview script
```

---

## Backend setup

### Prerequisites

- Python ≥ 3.11
- An **OpenAI-compatible** API endpoint (OpenAI, Azure OpenAI, local Ollama, vLLM, LM Studio …)

### Install

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env:
#   OPENAI_API_BASE=https://api.openai.com/v1   ← or your local endpoint
#   OPENAI_API_KEY=sk-...
#   LITELLM_MODEL=openai/gpt-4o                 ← LiteLLM model string
```

LiteLLM model string examples:

| Provider | `LITELLM_MODEL` value |
|---|---|
| OpenAI | `openai/gpt-4o` |
| Azure OpenAI | `azure/my-deployment` |
| Ollama (local) | `ollama/llama3` |
| vLLM | `openai/meta-llama/Llama-3-8b` |

### Run

```bash
python main.py
# Server starts at http://127.0.0.1:8000
```

API endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Single-turn chat, returns full JSON response |
| `GET`  | `/chat/stream` | Server-Sent Events streaming response |
| `GET`  | `/health` | Liveness probe |

---

## Extension setup

### Prerequisites

- Node.js ≥ 18
- `npm`

### Install & build

```bash
cd extension
npm install
npm run compile
```

### Run in VSCode (development)

1. Open the `extension/` folder in VSCode.
2. Press **F5** to launch the Extension Development Host.
3. Run command **"AI Embedded Helper: Open Chat"** from the Command Palette.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `aiEmbeddedHelper.backendUrl` | `http://127.0.0.1:8000` | Backend server URL |
| `aiEmbeddedHelper.streamingEnabled` | `true` | Use SSE streaming responses |

### Package (`.vsix`)

```bash
cd extension
npm run package        # creates ai-embedded-system-helper-*.vsix
```

### Publish to OpenVSX

```bash
# Set your OpenVSX token
export OVSX_PAT=<your-token>
npm run publish:ovsx
```

---

## Technology stack

| Layer | Technology |
|-------|-----------|
| AI agent framework | [Google ADK](https://google.github.io/adk-docs/) |
| LLM abstraction | [LiteLLM](https://docs.litellm.ai/) (OpenAI-compatible API) |
| Backend HTTP server | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| Extension runtime | [VSCode Extension API](https://code.visualstudio.com/api) |
| Extension marketplace | [OpenVSX](https://open-vsx.org/) |

---

## License

MIT
"""FastAPI server that wraps the Google ADK agent and exposes a REST + SSE API
consumed by the VSCode extension frontend.

Endpoints
---------
POST /chat        – single-turn chat, returns full JSON response
GET  /chat/stream – streaming SSE endpoint (chunked text/event-stream)
GET  /health      – liveness probe
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from embedded_system_helper.agent import build_agent
from embedded_system_helper import root_agent as _initial_root_agent

# ---------------------------------------------------------------------------
# Conversation logger
# ---------------------------------------------------------------------------
_LOG_DIR = Path(config.PROJECT_MEMORY_DIR) / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("conversation")
_logger.setLevel(logging.DEBUG)


def _log_entry(session_id: str, role: str, content: str) -> None:
    """Append a JSONL entry to the session log file."""
    log_file = _LOG_DIR / f"{session_id}.jsonl"
    entry = json.dumps(
        {"ts": datetime.utcnow().isoformat(), "role": role, "content": content},
        ensure_ascii=False,
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


# ---------------------------------------------------------------------------
# Google ADK runner  (module-level; can be reloaded via /reload)
# ---------------------------------------------------------------------------
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

_session_service = InMemorySessionService()
_runner = Runner(
    agent=_initial_root_agent,
    app_name="embedded_system_helper",
    session_service=_session_service,
)

# Track last-known Electerm reachability so we only rebuild when it changes.
_electerm_was_reachable: bool = False


def _check_electerm_reachable() -> bool:
    """Quick TCP-level probe of the Electerm MCP URL (non-blocking)."""
    url = getattr(config, "ELECTERM_MCP_URL", "") or ""
    if not url:
        return False
    try:
        import urllib.request  # stdlib only, no extra deps
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=0.8):
            return True
    except Exception:
        return False


def _rebuild_runner() -> None:
    """Rebuild the runner using a fresh agent from build_agent().

    Preserves the existing session service so conversation history survives.
    """
    global _runner, _electerm_was_reachable
    new_agent = build_agent()
    # Keep same session_service to preserve conversation history
    _runner = Runner(
        agent=new_agent,
        app_name="embedded_system_helper",
        session_service=_session_service,
    )
    _electerm_was_reachable = _check_electerm_reachable()


def _maybe_rebuild_for_mcp() -> None:
    """Rebuild the runner only if Electerm MCP connectivity has changed.

    Called before every chat request so new Electerm connections are picked
    up automatically without the user clicking Reload Agent.
    """
    global _electerm_was_reachable
    now_reachable = _check_electerm_reachable()
    if now_reachable != _electerm_was_reachable:
        _rebuild_runner()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AIEmbeddedSystemHelper",
    description="Google ADK backend for the VSCode embedded-system helper extension",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _run_agent(message: str, session_id: str) -> str:
    """Run the ADK agent for one turn and return the final text reply."""
    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=message)],
    )

    reply_parts: list[str] = []
    async for event in _runner.run_async(
        user_id="vscode-user",
        session_id=session_id,
        new_message=user_content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    reply_parts.append(part.text)

    return "".join(reply_parts)


async def _stream_agent(message: str, session_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted chunks from the ADK agent.

    Event types sent to the client:
      - ``{"type":"text",  "chunk":"...", "done":false}``  — streamed text
      - ``{"type":"tool_start", "name":"...", "agent":"...", "args":{}}``
      - ``{"type":"tool_result","name":"...", "agent":"...", "result":"..."}``
      - ``{"type":"text",  "chunk":"",  "done":true}``   — stream end
    """
    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=message)],
    )

    assistant_text_parts: list[str] = []

    async for event in _runner.run_async(
        user_id="vscode-user",
        session_id=session_id,
        new_message=user_content,
    ):
        agent_name = getattr(event, "author", "") or ""

        # --- tool function calls (agent → tool) ---
        if event.content and event.content.parts:
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                if fc:
                    args_dict = dict(fc.args) if fc.args else {}
                    _log_entry(session_id, "tool_call", json.dumps(
                        {"agent": agent_name, "tool": fc.name, "args": args_dict},
                        ensure_ascii=False,
                    ))
                    data = json.dumps({
                        "type": "tool_start",
                        "name": fc.name,
                        "agent": agent_name,
                        "args": args_dict,
                    })
                    yield f"data: {data}\n\n"
                    await asyncio.sleep(0)  # flush immediately

                fr = getattr(part, "function_response", None)
                if fr:
                    result_str = json.dumps(fr.response, default=str, ensure_ascii=False)
                    _log_entry(session_id, "tool_result", json.dumps(
                        {"tool": fr.name, "result": result_str[:2000]},
                        ensure_ascii=False,
                    ))
                    if len(result_str) > 500:
                        result_str = result_str[:500] + "\u2026"
                    data = json.dumps({
                        "type": "tool_result",
                        "name": fr.name,
                        "agent": agent_name,
                        "result": result_str,
                    })
                    yield f"data: {data}\n\n"
                    await asyncio.sleep(0)  # flush immediately

                if part.text:
                    assistant_text_parts.append(part.text)
                    data = json.dumps({"type": "text", "chunk": part.text, "done": False})
                    yield f"data: {data}\n\n"
                    await asyncio.sleep(0)  # flush immediately
    # Log the full assistant turn
    if assistant_text_parts:
        _log_entry(session_id, "assistant", "".join(assistant_text_parts))

    done_data = json.dumps({"type": "text", "chunk": "", "done": True})
    yield f"data: {done_data}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/reload")
async def reload_agent() -> dict:
    """Rebuild the ADK runner — picks up Electerm MCP if it became available."""
    try:
        _rebuild_runner()
        return {"status": "reloaded"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())

    # Ensure session exists
    existing = await _session_service.get_session(
        app_name="embedded_system_helper",
        user_id="vscode-user",
        session_id=session_id,
    )
    if existing is None:
        await _session_service.create_session(
            app_name="embedded_system_helper",
            user_id="vscode-user",
            session_id=session_id,
        )

    try:
        reply = await _run_agent(req.message, session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(session_id=session_id, reply=reply)


@app.get("/chat/stream")
async def chat_stream(message: str, session_id: Optional[str] = None) -> StreamingResponse:
    # Auto-rebuild agent if Electerm MCP connectivity changed since last call
    _maybe_rebuild_for_mcp()

    sid = session_id or str(uuid.uuid4())

    existing = await _session_service.get_session(
        app_name="embedded_system_helper",
        user_id="vscode-user",
        session_id=sid,
    )
    if existing is None:
        await _session_service.create_session(
            app_name="embedded_system_helper",
            user_id="vscode-user",
            session_id=sid,
        )

    # Log the user turn
    _log_entry(sid, "user", message)

    return StreamingResponse(
        _stream_agent(message, sid),
        media_type="text/event-stream",
        headers={
            "X-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    dev_reload = getattr(config, "DEV_RELOAD", False)
    uvicorn.run(
        # Must be a string import path when reload=True
        "main:app" if dev_reload else app,  # type: ignore[arg-type]
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=dev_reload,
        reload_dirs=[str(__file__.replace("main.py", ""))] if dev_reload else None,
    )

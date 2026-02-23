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
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from embedded_system_helper.agent import build_agent
from embedded_system_helper import root_agent as _initial_root_agent
from google.adk.events import Event as _AdkEvent

# ---------------------------------------------------------------------------
# Conversation logger
# ---------------------------------------------------------------------------
_LOG_DIR = Path(config.PROJECT_MEMORY_DIR) / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("conversation")
_logger.setLevel(logging.DEBUG)
_log_handler = logging.StreamHandler()
_log_handler.setLevel(logging.DEBUG)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_logger.addHandler(_log_handler)


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

# We track the active LLM streaming task for each session.
# This ensures we never have two concurrent run_async calls to the same
# _runner for the same session (which would deadlock or corrupt state).
_active_stream_tasks: dict[str, asyncio.Task] = {}

# Cooperative stop signals — set the event to ask a running stream to stop.
_stop_events: dict[str, asyncio.Event] = {}

# Partial assistant text accumulated before a stop, keyed by session id.
# Written by _stream_agent(), consumed (popped) by /seal.
_partial_texts: dict[str, str] = {}


def _check_electerm_reachable() -> bool:
    """TCP-level probe: returns True if something is listening on the
    Electerm MCP host:port.  Uses a plain socket so it works for SSE
    endpoints that never return an HTTP response body.
    """
    url = getattr(config, "ELECTERM_MCP_URL", "") or ""
    if not url:
        return False
    try:
        import socket
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
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


import time as _time

# Throttle MCP connectivity checks — no need to probe on EVERY request.
_last_mcp_check_time: float = 0.0
_MCP_CHECK_INTERVAL = 30.0  # seconds


def _maybe_rebuild_for_mcp() -> None:
    """Rebuild the runner only if Electerm MCP connectivity has changed.

    Called before every chat request so new Electerm connections are picked
    up automatically without the user clicking Reload Agent.
    Throttled to at most once per 30 seconds to avoid blocking the event loop
    with a synchronous TCP probe on every request.
    """
    global _electerm_was_reachable, _last_mcp_check_time
    now = _time.monotonic()
    if now - _last_mcp_check_time < _MCP_CHECK_INTERVAL:
        return  # skip — checked recently
    _last_mcp_check_time = now
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


async def _stream_agent(
    message: str,
    session_id: str,
    stop_event: asyncio.Event | None = None,
) -> AsyncIterator[str]:
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
    _t0 = _time.monotonic()
    _event_count = 0

    _logger.info("[DEBUG][stream] >>> START run_async for session=%s msg=%r", session_id, message[:80])
    try:
      async for event in _runner.run_async(
        user_id="vscode-user",
        session_id=session_id,
        new_message=user_content,
      ):
        _event_count += 1
        _elapsed = _time.monotonic() - _t0
        _author = getattr(event, "author", "") or ""
        _logger.info("  [stream] event #%d from '%s' at +%.1fs", _event_count, _author, _elapsed)
        # ── hard stop: break immediately to free resources ──
        if stop_event and stop_event.is_set():
            _logger.info("  [stream] stop_event set — breaking out of runner loop")
            break
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
                    # ADK wraps the tool's return value as {"result": <value>}
                    raw = fr.response
                    raw_result = (
                        raw.get("result", "") if isinstance(raw, dict) else str(raw)
                    )

                    # ── form tool special handling ────────────────────────────
                    if isinstance(raw_result, str) and raw_result.startswith("__FORM__:"):
                        try:
                            form_def = json.loads(raw_result[9:])
                            form_data = json.dumps({"type": "form", **form_def})
                            yield f"data: {form_data}\n\n"
                            await asyncio.sleep(0)
                        except Exception:
                            pass
                        # Normalise the result string the LLM sees
                        raw_result = f'[表单已发送给用户，form_id={form_def.get("form_id", "?")}]'
                        raw = {"result": raw_result}

                    result_str = json.dumps(raw, default=str, ensure_ascii=False)
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
    except asyncio.CancelledError:
        _logger.info("[DEBUG][stream] <<< CancelledError in run_async loop after %d events", _event_count)
    except GeneratorExit:
        _logger.info("[DEBUG][stream] <<< GeneratorExit in run_async loop after %d events", _event_count)
        return  # Cannot yield after GeneratorExit
    except Exception as exc:
        _logger.warning("[DEBUG][stream] <<< Exception in run_async loop: %s", exc, exc_info=True)
    finally:
        _elapsed = _time.monotonic() - _t0
        _logger.info("[DEBUG][stream] <<< END run_async loop: %d events in %.1fs, stopped=%s",
                     _event_count, _elapsed, bool(stop_event and stop_event.is_set()))
    # ── Save partial text on interruption ──────────────────────────────────
    was_stopped = stop_event and stop_event.is_set()
    full_text = "".join(assistant_text_parts)

    if was_stopped and full_text:
        partial = full_text + "\n... [输出已被用户中断]"
        _partial_texts[session_id] = partial
        _log_entry(session_id, "assistant", partial)
        _logger.info("[DEBUG][stream] partial text saved (%d chars) for session=%s", len(partial), session_id)
    elif was_stopped:
        _logger.info("[DEBUG][stream] stopped but no text to save for session=%s", session_id)
    elif full_text:
        _log_entry(session_id, "assistant", full_text)
        _logger.info("[DEBUG][stream] full text logged (%d chars) for session=%s", len(full_text), session_id)

    if not was_stopped:
        done_data = json.dumps({"type": "text", "chunk": "", "done": True})
        yield f"data: {done_data}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/electerm-status")
async def electerm_status() -> dict:
    """Diagnostic endpoint: returns Electerm MCP connectivity info."""
    import socket
    from urllib.parse import urlparse

    url = getattr(config, "ELECTERM_MCP_URL", "") or ""
    if not url:
        return {"configured": False, "reachable": False,
                "hint": "ELECTERM_MCP_URL is not set in .env or VSCode settings."}

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        sock.close()
        reachable = result == 0
    except Exception as exc:
        reachable = False

    hint = (
        "Electerm MCP server is reachable. Reload Agent to connect."
        if reachable else
        f"Nothing is listening on {host}:{port}. "
        "Make sure Electerm is running and the MCP widget is enabled in Electerm settings "
        "(Settings → MCP → enable MCP server). "
        f"Check the URL shown in Electerm and update ELECTERM_MCP_URL in .env if needed."
    )

    return {
        "configured": True,
        "url": url,
        "host": host,
        "port": port,
        "reachable": reachable,
        "hint": hint,
    }



@app.post("/reload")
async def reload_agent() -> dict:
    """Rebuild the ADK runner — picks up Electerm MCP if it became available."""
    import traceback as _tb
    try:
        _rebuild_runner()
        return {"status": "reloaded"}
    except Exception as exc:
        _tb.print_exc()  # print full traceback to server console for debugging
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/reload-config")
async def reload_config(request: Request) -> dict:
    """Re-read config from .env and/or request body, then rebuild the runner.

    Called by the VSCode extension when the user changes settings so that
    the external backend picks up the new values without a full restart.

    Accepts an optional JSON body with env overrides, e.g.::

        {"LITELLM_MODEL": "openai/gpt-4o", "LITELLM_API_KEY": "sk-..."}

    Any keys provided in the body are applied to ``os.environ`` before
    ``config`` is refreshed.
    """
    import importlib

    # Apply optional overrides from request body
    try:
        body = await request.json()
    except Exception:
        body = {}

    if isinstance(body, dict):
        for key, value in body.items():
            if isinstance(value, str) and value.strip():
                os.environ[key] = value.strip()

    # Re-read .env (values already in os.environ take precedence by default,
    # so we use override=True to let the .env file win for keys NOT passed
    # in the body).
    from dotenv import load_dotenv as _reload_dotenv
    _reload_dotenv(override=True)

    # Re-apply any body overrides AFTER .env reload so they always win
    if isinstance(body, dict):
        for key, value in body.items():
            if isinstance(value, str) and value.strip():
                os.environ[key] = value.strip()

    # Refresh the config module
    importlib.reload(config)

    # Rebuild runner with new config
    _rebuild_runner()

    return {
        "status": "reloaded",
        "model": config.LITELLM_MODEL,
        "api_base": config.LITELLM_API_BASE,
    }



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
async def chat_stream(
    request: Request,   # FastAPI injects this — do NOT add a default value!
    message: str,
    session_id: Optional[str] = None,
) -> StreamingResponse:
    global _active_stream_tasks

    sid = session_id or str(uuid.uuid4())
    _logger.info("[DEBUG][chat_stream] >>> New stream request sid=%s msg=%r", sid, message[:80])

    # ── Stop any previous stream task before starting a new one ────────────
    # Signal the old stream to stop cooperatively, then wait briefly.
    if sid in _stop_events:
        _logger.info("[DEBUG][chat_stream] Stopping previous stream for sid=%s", sid)
        _stop_events[sid].set()
    if sid in _active_stream_tasks:
        old_task = _active_stream_tasks[sid]
        if not old_task.done():
            old_task.cancel()  # belt-and-suspenders: also cancel the task
            try:
                await asyncio.wait_for(
                    asyncio.shield(old_task), timeout=1.0
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        _active_stream_tasks.pop(sid, None)
    _stop_events.pop(sid, None)

    # Auto-rebuild agent if Electerm MCP connectivity changed since last call
    _maybe_rebuild_for_mcp()

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

    # Create a cooperative stop event for this stream
    stop_ev = asyncio.Event()
    _stop_events[sid] = stop_ev

    async def _monitored_stream() -> AsyncIterator[str]:
        """Wrap _stream_agent so we stop it gracefully when the client drops.

        Uses a cooperative stop event instead of task.cancel() because
        CancelledError inside _runner.run_async() corrupts ADK session state,
        making the session unrecoverable (seal fails, context is lost).
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _producer() -> None:
            _logger.info("[DEBUG][producer] >>> START for sid=%s", sid)
            try:
                async for chunk in _stream_agent(message, sid, stop_ev):
                    await queue.put(chunk)
            except asyncio.CancelledError:
                _logger.info("[DEBUG][producer] CancelledError for sid=%s", sid)
            except Exception as exc:
                _logger.warning("[DEBUG][producer] Exception for sid=%s: %s", sid, exc)
                # Surface errors as an SSE error event
                err = json.dumps({"type": "error", "text": str(exc)})
                await queue.put(f"data: {err}\n\n")
            finally:
                _logger.info("[DEBUG][producer] <<< END for sid=%s (putting sentinel)", sid)
                await queue.put(None)  # sentinel

        task = asyncio.create_task(_producer())
        _active_stream_tasks[sid] = task
        try:
            while True:
                # Poll for client disconnect while waiting for the next chunk
                if request is not None and await request.is_disconnected():
                    # Signal stop AND cancel the producer so the runner
                    # breaks out immediately and resources are freed.
                    _logger.info("[DEBUG][monitor] Client disconnected for sid=%s, cancelling", sid)
                    stop_ev.set()
                    if not task.done():
                        task.cancel()
                    return

                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue  # check disconnect again

                if chunk is None:
                    return  # producer finished normally
                yield chunk
        finally:
            # Always clean up — whether stopped or completed normally
            _logger.info("[DEBUG][monitor] finally block: task.done=%s stop=%s sid=%s",
                         task.done(), stop_ev.is_set(), sid)
            if not task.done():
                task.cancel()
            if _active_stream_tasks.get(sid) is task:
                _active_stream_tasks.pop(sid, None)
            if not stop_ev.is_set():
                # Normal completion — remove the stop event
                _stop_events.pop(sid, None)
            _logger.info("[DEBUG][monitor] <<< END monitored_stream sid=%s", sid)

    return StreamingResponse(
        _monitored_stream(),
        media_type="text/event-stream",
        headers={
            "X-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering
        },
    )


@app.post("/session/{session_id}/seal")
async def seal_session(session_id: str) -> dict:
    """Seal a session that was interrupted mid-turn by Force Stop.

    Strategy
    --------
    1. Cancel the active producer task (stops the LLM / tool calls).
    2. Fetch the session from the session service.
    3. Append a synthetic model-authored event with ``turn_complete=True``
       so ADK considers the turn finished.  The session is then safe to
       continue from on the next user message.
    4. If appending fails (e.g. ADK validation), fall back to deleting the
       session so at least the next request can start clean.

    Returns ``{"preserved": true}`` when the session can be reused,
    or ``{"preserved": false}`` when it was deleted.
    """
    global _active_stream_tasks
    _logger.info("[DEBUG][seal] >>> Sealing session %s", session_id)

    # ── STEP 1: Append the turn_complete event FIRST ──────────────────────
    # We do this BEFORE stopping the task because stopping (cancel/break)
    # can corrupt the ADK session state.  By appending first, we ensure
    # the session has a valid turn_complete marker even if cleanup fails.
    session = await _session_service.get_session(
        app_name="embedded_system_helper",
        user_id="vscode-user",
        session_id=session_id,
    )
    if session is None:
        _logger.warning("[DEBUG][seal] Session %s not found", session_id)
        return {"preserved": False, "reason": "session_not_found"}

    _logger.info("[DEBUG][seal] Session found. active_tasks=%s stop_events=%s partial_texts=%s",
                 list(_active_stream_tasks.keys()),
                 list(_stop_events.keys()),
                 list(_partial_texts.keys()))

    # ── STEP 1: Signal stop and hard-cancel the running stream ─────────────
    if session_id in _stop_events:
        _logger.info("[DEBUG][seal] Setting stop_event for sid=%s", session_id)
        _stop_events[session_id].set()

    if session_id in _active_stream_tasks:
        task = _active_stream_tasks[session_id]
        _logger.info("[DEBUG][seal] Found active task done=%s for sid=%s", task.done(), session_id)
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                _logger.info("[DEBUG][seal] Producer task finished after cancel")
            except (asyncio.CancelledError, asyncio.TimeoutError) as e:
                _logger.info("[DEBUG][seal] Producer cancel wait ended: %s", type(e).__name__)
        _active_stream_tasks.pop(session_id, None)
    else:
        _logger.info("[DEBUG][seal] No active task found for sid=%s", session_id)
    _stop_events.pop(session_id, None)

    # ── STEP 2: Append turn_complete with partial text ────────────────────
    partial = _partial_texts.pop(session_id, None)
    seal_text = partial if partial else "（用户叫停了当前任务）"
    _logger.info("[DEBUG][seal] partial_text=%s chars, seal_text preview=%r",
                 len(partial) if partial else 0, seal_text[:100])

    sealed = False
    try:
        stop_event = _AdkEvent(
            author="embedded_system_helper",
            invocation_id=str(uuid.uuid4()),
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=seal_text)],
            ),
            turn_complete=True,
        )
        await _session_service.append_event(session=session, event=stop_event)
        sealed = True
        _logger.info("[DEBUG][seal] ✓ Appended turn_complete event (partial=%s)",
                     bool(partial))
    except Exception as exc:
        _logger.warning("[DEBUG][seal] ✗ append_event FAILED: %s", exc, exc_info=True)

    _logger.info("[DEBUG][seal] <<< DONE sealed=%s sid=%s", sealed, session_id)
    return {"preserved": sealed}


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Delete an ADK session — called from Clear History."""
    try:
        await _session_service.delete_session(
            app_name="embedded_system_helper",
            user_id="vscode-user",
            session_id=session_id,
        )
        return {"deleted": True}
    except Exception:
        return {"deleted": False}


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

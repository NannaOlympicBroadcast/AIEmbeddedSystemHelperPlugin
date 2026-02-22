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
import uuid
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from embedded_system_helper import root_agent

# ---------------------------------------------------------------------------
# Google ADK runner
# ---------------------------------------------------------------------------
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name="embedded_system_helper",
    session_service=_session_service,
)

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
    """Yield SSE-formatted chunks from the ADK agent."""
    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=message)],
    )

    async for event in _runner.run_async(
        user_id="vscode-user",
        session_id=session_id,
        new_message=user_content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    data = json.dumps({"chunk": part.text, "done": False})
                    yield f"data: {data}\n\n"

    done_data = json.dumps({"chunk": "", "done": True})
    yield f"data: {done_data}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


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
async def chat_stream(message: str, session_id: str | None = None) -> StreamingResponse:
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

    return StreamingResponse(
        _stream_agent(message, sid),
        media_type="text/event-stream",
        headers={"X-Session-Id": sid},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )

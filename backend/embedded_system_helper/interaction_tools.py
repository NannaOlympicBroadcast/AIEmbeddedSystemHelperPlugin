"""Interaction utilities for the AI Embedded System Helper agent.

Provides two tools:
  - ``sleep_tool``         — pause without polling, saving tokens during long ops
  - ``request_user_form``  — render an interactive form in the chat UI
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# Sleep tool
# ---------------------------------------------------------------------------

async def sleep_tool(seconds: float) -> str:
    """Wait for the specified number of seconds without polling.

    Use this instead of repeatedly calling terminal-output tools while a long
    operation runs (e.g. ``apt install``, ``docker build``, ``pip install``).
    After the sleep, call the terminal-output tool once to check the result.

    Args:
        seconds: How many seconds to wait.  Clamped to [1, 300].

    Returns:
        Confirmation message with the actual sleep duration.
    """
    clamped = max(1.0, min(float(seconds), 300.0))
    await asyncio.sleep(clamped)
    return f"Slept {clamped:.1f}s."


# ---------------------------------------------------------------------------
# User-form tool
# ---------------------------------------------------------------------------

def request_user_form(
    title: str,
    description: str,
    buttons: list,
    fields: Optional[list],
) -> str:
    """Display an interactive form to the user inside the chat panel.

    Two main use-cases:

    **1. Pause / resume** — launch a long-running task (``apt install``,
    ``docker build`` …), then immediately call this tool to show the user
    a status panel.  They click a button when the task finishes (or errors)
    and that click wakes the agent with the result.

    **2. Collect info** — use text-input fields to gather structured data
    (paths, credentials, choices) more precisely than asking in free text.

    Args:
        title: Short heading shown in the form card (e.g. ``"安装进度"``)。
        description: One-line explanation of what the user should do.
        buttons: List of button dicts, each with ``"label"`` (display text)
            and ``"value"`` (returned to the agent).
            Example::

                [
                    {"label": "✓ 安装成功", "value": "success"},
                    {"label": "⚠ 出现错误", "value": "error"},
                ]

        fields: Optional list of text-input field dicts, each with
            ``"name"`` (key returned to agent) and ``"label"`` (prompt text).
            Example::

                [{"name": "ip", "label": "IP 地址（可选）"}]

    Returns:
        A special ``__FORM__:`` marker string that the backend SSE handler
        converts into a ``form`` event for the chat UI.  The agent should
        treat the return value as confirmation that the form was sent.
    """
    form_id = str(uuid.uuid4())[:8]
    form_def = {
        "form_id": form_id,
        "title": title,
        "description": description,
        "buttons": buttons,
        "fields": fields or [],
    }
    return f"__FORM__:{json.dumps(form_def, ensure_ascii=False)}"

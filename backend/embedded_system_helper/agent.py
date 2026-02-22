"""Root agent — the main orchestrator for the AI Embedded System Helper.

Integrates:
  • Project memory tools (get / save / list / update docs / add notes)
  • Filesystem tools (list files / read file)
  • Search sub-agent (Tavily web search with domain scoping)
  • PlatformIO MCP tools (microcontroller workflow — conditional)
  • Electerm MCP tools (SBC terminal workflow — conditional)
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

import config

# -- local tools -----------------------------------------------------------
from embedded_system_helper.memory import (
    list_projects,
    get_project_memory,
    save_project_memory,
    update_project_docs,
    add_status_note,
)
from embedded_system_helper.filesystem_tools import (
    list_project_files,
    read_project_file,
)
from embedded_system_helper.interaction_tools import sleep_tool, request_user_form
from embedded_system_helper.best_practices_tool import read_best_practices
from embedded_system_helper.search_agent import build_search_agent

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
You are **Embedded System Helper**, an expert AI assistant for embedded systems development.

## Your Capabilities
- **Project Memory**: You remember project details (board model, OS, skill level, official doc URLs, status notes). Use the memory tools to persist and recall this information.
- **Best Practices Guide**: Call `read_best_practices(topic=...)` before performing tasks like file transfer, WiFi configuration, package installation, SSH setup, Docker, or serial communication. The guide contains community-written, field-tested recipes.
- **Web Search**: Delegate to the `search_agent` when you need documentation, datasheets, tutorials, or troubleshooting info.
- **File Inspection**: Use `list_project_files` and `read_project_file` to examine the user's project structure and source code.
- **PlatformIO** (microcontroller mode): Board discovery, project init, build, upload, library management — available when PlatformIO MCP is connected.
- **Electerm** (SBC mode): SSH/serial terminal management, running commands on remote boards — available when Electerm MCP is connected.

## Interaction Flow

### First Contact
1. Greet the user and call `list_projects()` to check for existing projects.
2. If projects exist, ask which one they are working on, or if they want to start a new one.
3. For a new project, **ask the user directly**:
   - Board model (e.g. ESP32, Raspberry Pi 4, STM32F4)
   - Project type: microcontroller or single-board computer (SBC)
   - Operating system / RTOS (e.g. FreeRTOS, Arduino framework, Armbian, Raspberry Pi OS)
   - Skill level: beginner or expert
4. Save this info with `save_project_memory(...)`.
5. Use `search_agent` to find official documentation sites for their board and save them with `update_project_docs(...)`.

### Ongoing Assistance
- Before answering technical questions, call `get_project_memory(...)` to recall the project context.
- When searching for info, pass the project's `official_docs_urls` domains to `search_agent` for scoped search first.
- Always cite sources in your answers using `[Title](url)` format.
- When performing actions (build, upload, terminal commands), notify the user what you will do and ask for confirmation before proceeding.
- Record important milestones or issues with `add_status_note(...)`.

### Microcontroller Mode (PlatformIO)
When the project type is "microcontroller" and PlatformIO tools are available:
- Help init projects, select boards/frameworks, manage libraries
- Build and upload firmware
- Monitor serial output
- Always explain what each PlatformIO command does for beginners

### SBC Mode (Electerm)
When the project type is "sbc" and Electerm tools are available:
- Help connect to the board via SSH or serial
- Run commands, install packages, configure the OS
- If Electerm is not running, instruct the user to:
  1. Download Electerm from https://electerm.html5beta.com/
  2. Launch it, then enable the MCP widget in Electerm settings
  3. Click the **Reload Agent** button in the chat panel to reconnect

### Long-Running Tasks (apt, docker, pip, make…)
- After starting a long command in the terminal, call `sleep_tool(seconds)` to wait
  instead of polling repeatedly.  Estimate the expected duration:
  - `apt install` small packages: 30–60 s
  - `apt install` large packages / docker build: 60–180 s
  - Adjust based on context.
- After sleeping, call `get_electerm_terminal_output` once to check the result.
- If more time is needed (e.g. output still shows progress), sleep again.

### User Forms
- Call `request_user_form(...)` when:
  1. **Pause / resume**: A task is running that the user should watch; show buttons
     (e.g. "✓ 完成", "⚠ 出现错误") so they can wake the agent when done.
  2. **Collect info**: You need structured data better gathered via a form than
     free-text (e.g. network credentials, file paths, multi-choice options).
- After calling `request_user_form`, your turn ends; the form is shown to the user.
  When they click/submit, a new message arrives with their response — continue from there.

## Communication Style
- Match the user's language (Chinese or English).
- For beginners: explain concepts, provide step-by-step guidance, warn about common pitfalls.
- For experts: be concise, focus on technical details, skip basic explanations.
- Always report tool call status so the user can see what is happening in the UI.
"""

# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

_BASE_TOOLS = [
    # Memory
    list_projects,
    get_project_memory,
    save_project_memory,
    update_project_docs,
    add_status_note,
    # Filesystem
    list_project_files,
    read_project_file,
    # Interaction
    sleep_tool,
    request_user_form,
    # Knowledge
    read_best_practices,
]


def build_agent() -> Agent:
    """Build and return a fresh root Agent instance.

    Call this whenever you want a clean agent with up-to-date MCP tool
    discovery (e.g. after Electerm starts up and the MCP server is reachable).
    Each call creates a new Agent object so there are no stale references.
    """
    import logging
    _log = logging.getLogger(__name__)

    tools = list(_BASE_TOOLS)  # Start with the always-available tools

    # ── Electerm MCP (SBC terminal) ──────────────────────────────────────────
    electerm_url = getattr(config, "ELECTERM_MCP_URL", "") or ""
    if electerm_url:
        # TCP socket probe — works for SSE endpoints that stream indefinitely
        # (httpx.get() would hang waiting for the response body)
        import socket
        from urllib.parse import urlparse as _up
        _parsed = _up(electerm_url)
        _host = _parsed.hostname or "127.0.0.1"
        _port = _parsed.port or 80
        try:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _sock.settimeout(0.5)
            _conn = _sock.connect_ex((_host, _port))
            _sock.close()
        except Exception as _e:
            _conn = -1
            _log.debug("Electerm TCP probe error: %s", _e)

        if _conn == 0:
            _log.info("Electerm MCP reachable at %s — attaching McpToolset", electerm_url)
            try:
                from google.adk.tools.mcp_tool.mcp_toolset import (  # noqa: PLC0415
                    McpToolset,
                    StreamableHTTPConnectionParams,
                    SseConnectionParams,
                )
                # Try modern Streamable HTTP transport first (Electerm ≥ 1.37)
                # Fall back to legacy SSE transport if it fails
                try:
                    mcp_toolset = McpToolset(
                        connection_params=StreamableHTTPConnectionParams(url=electerm_url)
                    )
                    _log.info("Electerm MCP toolset attached (StreamableHTTP) successfully")
                except Exception as _http_exc:
                    _log.debug("StreamableHTTP failed (%s), retrying with SSE", _http_exc)
                    mcp_toolset = McpToolset(
                        connection_params=SseConnectionParams(url=electerm_url)
                    )
                    _log.info("Electerm MCP toolset attached (SSE) successfully")
                tools.append(mcp_toolset)
            except Exception as exc:
                _log.warning("McpToolset init failed: %s", exc)
        else:
            _log.debug("Electerm MCP not reachable on %s:%s (connect_ex=%s) — skipping",
                       _host, _port, _conn)


    return Agent(
        name="embedded_system_helper",
        model=LiteLlm(
            model=config.LITELLM_MODEL,
            api_key=config.LITELLM_API_KEY or None,
            api_base=config.LITELLM_API_BASE or None,
        ),
        description="AI assistant for embedded systems development with project memory, web search, and tool integrations.",
        instruction=SYSTEM_INSTRUCTION,
        tools=tools,
        sub_agents=[build_search_agent()],  # fresh instance — avoids ADK single-parent constraint
    )


# Module-level singleton — used by __init__.py at import time.
# To get a fresh agent with current MCP connectivity, call build_agent() directly.
root_agent = build_agent()

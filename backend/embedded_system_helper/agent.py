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
from embedded_system_helper.search_agent import search_agent

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
You are **Embedded System Helper**, an expert AI assistant for embedded systems development.

## Your Capabilities
- **Project Memory**: You remember project details (board model, OS, skill level, official doc URLs, status notes). Use the memory tools to persist and recall this information.
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
        try:
            import httpx  # lightweight; falls back gracefully if missing
            resp = httpx.get(f"{electerm_url.rstrip('/')}", timeout=1.0)
            if resp.status_code < 500:
                from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, SseServerParams  # noqa: PLC0415
                mcp_toolset = McpToolset(
                    connection_params=SseServerParams(url=electerm_url)
                )
                tools.append(mcp_toolset)
                _log.info("Electerm MCP connected at %s", electerm_url)
        except Exception as exc:
            _log.debug("Electerm MCP not reachable (%s) — skipping", exc)

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
        sub_agents=[search_agent],
    )


# Module-level singleton — used by __init__.py at import time.
# To get a fresh agent with current MCP connectivity, call build_agent() directly.
root_agent = build_agent()

"""Centralised configuration — all values sourced from environment variables.

Environment variables can be set via a ``.env`` file, the OS, or passed
through from VSCode extension settings → child-process env.
"""

from __future__ import annotations

import os

# Patch litellm BEFORE it is imported anywhere — prevents network call for model cost map
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")

from dotenv import load_dotenv

load_dotenv()


# -- LLM / API settings ---------------------------------------------------
LITELLM_API_BASE: str = os.getenv("LITELLM_API_BASE", "https://api.openai.com/v1")
LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "")
LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "openai/gpt-4o")

# -- Server settings -------------------------------------------------------
SERVER_HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

# -- Tavily search ---------------------------------------------------------
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

# -- Memory persistence ----------------------------------------------------
PROJECT_MEMORY_DIR: str = os.getenv("PROJECT_MEMORY_DIR", "./data")

# -- Electerm MCP ----------------------------------------------------------
ELECTERM_MCP_URL: str = os.getenv("ELECTERM_MCP_URL", "http://127.0.0.1:30837/mcp")

# -- Dev mode ---------------------------------------------------------------
# Set DEV_RELOAD=1 to enable uvicorn hot-reload (backend auto-restarts on file change)
DEV_RELOAD: bool = os.getenv("DEV_RELOAD", "0").strip() == "1"


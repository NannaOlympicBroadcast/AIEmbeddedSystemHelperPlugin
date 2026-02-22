"""Configuration for the AIEmbeddedSystemHelper backend."""

import os
from dotenv import load_dotenv

load_dotenv()

# LiteLLM / OpenAI-compatible endpoint
OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# Model identifier passed to LiteLLM (e.g. "openai/gpt-4o", "ollama/llama3")
LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "openai/gpt-4o")

# HTTP server
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))

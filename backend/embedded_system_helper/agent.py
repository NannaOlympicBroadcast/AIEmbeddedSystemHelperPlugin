"""ADK agent definition for the Embedded System Helper."""

import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

import config

# Expose the ADK base_url / api_key via environment so LiteLLM picks them up.
os.environ.setdefault("OPENAI_API_BASE", config.OPENAI_API_BASE)
os.environ.setdefault("OPENAI_API_KEY", config.OPENAI_API_KEY)

_SYSTEM_PROMPT = """You are an expert AI assistant specialized in embedded systems development.
You help engineers with:
- Writing, reviewing and debugging firmware in C/C++, Rust, MicroPython, etc.
- Understanding datasheets, register maps and hardware interfaces (UART, SPI, I2C, CAN …).
- Analysing RTOS concepts, memory layouts, linker scripts and build systems (CMake, Make, Bazel).
- Interpreting compiler warnings/errors and static-analysis reports.
- Suggesting best practices for power management, safety-critical design and testing.

Always provide concise, accurate answers with working code examples where relevant.
When referencing hardware specifics, ask the user to confirm the target MCU/SoC if unclear."""

root_agent = Agent(
    name="embedded_system_helper",
    model=LiteLlm(model=config.LITELLM_MODEL),
    description="AI assistant for embedded systems development",
    instruction=_SYSTEM_PROMPT,
)

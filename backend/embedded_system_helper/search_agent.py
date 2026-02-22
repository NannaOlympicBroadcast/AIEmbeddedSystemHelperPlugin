"""Search sub-agent — uses Tavily API for domain-specific and general web search.

The search agent is used as a sub-agent of the root agent.  It provides a
`tavily_search` tool that:
  • accepts an optional list of domains to scope the search
  • falls back to a general web search when domains are empty
  • returns structured results with title, URL, and content snippet
"""

from __future__ import annotations

from typing import Any, List, Optional

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

import config

# ---------------------------------------------------------------------------
# Tavily search tool
# ---------------------------------------------------------------------------

def tavily_search(
    query: str,
    domains: Optional[List[str]] = None,
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    """Search the web using Tavily API.

    When *domains* is provided the search is scoped to those websites first
    (e.g. the board's official documentation site).  When *domains* is empty
    or ``None`` the search covers the entire web.

    Args:
        query:       The search query text.
        domains:     Optional list of domain names to restrict the search to,
                     e.g. ``["docs.espressif.com", "wiki.seeedstudio.com"]``.
        max_results: Maximum number of results to return (default 5).

    Returns:
        A dict with ``results`` (list of dicts with title, url, content)
        and a ``source`` field indicating whether the search was scoped.
    """
    api_key = config.TAVILY_API_KEY
    if not api_key:
        return {
            "error": (
                "Tavily API key is not configured. "
                "Please set TAVILY_API_KEY in your .env or VSCode settings."
            )
        }

    try:
        from tavily import TavilyClient  # lazy import
    except ImportError:
        return {"error": "tavily-python package is not installed. Run: pip install tavily-python"}

    client = TavilyClient(api_key=api_key)

    kwargs: dict[str, Any] = {
        "query": query,
        "max_results": max_results if max_results is not None else 5,
        "search_depth": "advanced",
    }

    source_label = "general_web"
    if domains:
        kwargs["include_domains"] = domains
        source_label = f"scoped:{','.join(domains)}"

    try:
        raw = client.search(**kwargs)
    except Exception as exc:
        return {"error": f"Tavily search failed: {exc}"}

    results = []
    for item in raw.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        })

    return {"source": source_label, "results": results}


# ---------------------------------------------------------------------------
# Search sub-agent definition
# ---------------------------------------------------------------------------

search_agent = Agent(
    name="search_agent",
    model=LiteLlm(
        model=config.LITELLM_MODEL,
        api_key=config.LITELLM_API_KEY or None,
        api_base=config.LITELLM_API_BASE or None,
    ),
    description=(
        "A web search specialist agent. Delegates here when you need to look up "
        "documentation, datasheets, tutorials, or any online information about "
        "embedded development boards, operating systems, or tools."
    ),
    instruction="""\
You are a web search assistant for embedded systems development.

**Search strategy (follow this order):**
1. Check the conversation context for the current project's `official_docs_urls`.
2. If URLs are available, first call `tavily_search` with those domains.
3. If the scoped search returns insufficient results, call `tavily_search`
   again WITHOUT domains to do a general web search.
4. If no official docs URLs exist, search the general web directly.

**Response rules:**
- Always include the source URL for every piece of information.
- Format citations like: `[Title](url)`
- Summarise the relevant parts; do not dump raw search results.
- If multiple sources agree, mention that for credibility.
- If results are contradictory, present both sides.
""",
    tools=[tavily_search],
)

"""Project memory system — JSON-based persistent storage for project metadata.

Each project record stores board model, OS, user level, official doc URLs,
and status notes so the agent can provide context-aware assistance across
conversations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import config

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
_MEMORY_DIR = Path(config.PROJECT_MEMORY_DIR)
_MEMORY_FILE = _MEMORY_DIR / "projects.json"


def _ensure_dir() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _load_all() -> Dict[str, Dict[str, Any]]:
    """Load all project records from disk."""
    _ensure_dir()
    if not _MEMORY_FILE.exists():
        return {}
    with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_all(data: Dict[str, Dict[str, Any]]) -> None:
    """Persist all project records to disk."""
    _ensure_dir()
    with open(_MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# ADK FunctionTool implementations
# ---------------------------------------------------------------------------

def list_projects() -> dict[str, Any]:
    """List all saved projects and their basic info.

    Returns a dictionary with project names as keys and a brief summary
    (project_type, board_model) as values.
    """
    projects = _load_all()
    if not projects:
        return {"message": "No projects saved yet.", "projects": []}
    summary = {}
    for name, info in projects.items():
        summary[name] = {
            "project_type": info.get("project_type", "unknown"),
            "board_model": info.get("board_model", "unknown"),
            "os_info": info.get("os_info", ""),
        }
    return {"projects": summary}


def get_project_memory(project_name: str) -> dict[str, Any]:
    """Retrieve full memory for a specific project.

    Args:
        project_name: The name of the project to look up.

    Returns:
        The project record, or an error message if not found.
    """
    projects = _load_all()
    if project_name not in projects:
        return {"error": f"Project '{project_name}' not found.", "available": list(projects.keys())}
    return projects[project_name]


def save_project_memory(
    project_name: str,
    project_type: str,
    board_model: str,
    os_info: Optional[str] = None,
    user_level: Optional[str] = None,
    official_docs_urls: Optional[List[str]] = None,
) -> dict[str, Any]:
    """Create or fully update a project record.

    Args:
        project_name:  A short recognisable name for the project.
        project_type:  Either "microcontroller" or "sbc" (single-board computer).
        board_model:   Board model, e.g. "ESP32-S3", "Raspberry Pi 4".
        os_info:       Operating system / RTOS, e.g. "FreeRTOS", "Armbian".
        user_level:    "beginner" or "expert".
        official_docs_urls: A list of official documentation / reference URLs.

    Returns:
        Confirmation message.
    """
    projects = _load_all()
    projects[project_name] = {
        "project_name": project_name,
        "project_type": project_type,
        "board_model": board_model,
        "os_info": os_info or "",
        "user_level": user_level or "beginner",
        "official_docs_urls": official_docs_urls or [],
        "status_notes": projects.get(project_name, {}).get("status_notes", []),
    }
    _save_all(projects)
    return {"message": f"Project '{project_name}' saved successfully."}


def update_project_docs(
    project_name: str,
    urls: List[str],
) -> dict[str, Any]:
    """Add one or more official documentation URLs to a project.

    Args:
        project_name: Target project.
        urls: List of documentation URLs to add.

    Returns:
        Updated list of URLs for the project.
    """
    projects = _load_all()
    if project_name not in projects:
        return {"error": f"Project '{project_name}' not found."}
    existing: List[str] = projects[project_name].get("official_docs_urls", [])
    for u in urls:
        if u not in existing:
            existing.append(u)
    projects[project_name]["official_docs_urls"] = existing
    _save_all(projects)
    return {"message": "URLs updated.", "official_docs_urls": existing}


def add_status_note(project_name: str, note: str) -> dict[str, Any]:
    """Append a status note to a project's history.

    Use this to record key milestones, issues, or configuration changes
    (e.g. "WiFi configured", "OTG driver missing on Windows host").

    Args:
        project_name: Target project.
        note: Free-text status note.

    Returns:
        Confirmation and the updated list of notes.
    """
    projects = _load_all()
    if project_name not in projects:
        return {"error": f"Project '{project_name}' not found."}
    notes: List[str] = projects[project_name].get("status_notes", [])
    notes.append(note)
    projects[project_name]["status_notes"] = notes
    _save_all(projects)
    return {"message": "Note added.", "status_notes": notes}

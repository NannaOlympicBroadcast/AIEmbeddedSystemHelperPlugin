"""Filesystem tools — let the agent inspect project files on the host machine.

Provides two ADK FunctionTools:
  • list_project_files  – recursive directory listing
  • read_project_file   – read a single file (with size guard)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


MAX_FILE_SIZE = 256 * 1024  # 256 KB safety limit


def list_project_files(
    directory: str,
    max_depth: Optional[int],
) -> dict[str, Any]:
    """List files and subdirectories under *directory* up to *max_depth* levels.

    Args:
        directory: Absolute or relative path to the directory to scan.
        max_depth: Maximum recursion depth (default 3 when omitted).

    Returns:
        A nested dict representing the directory tree, or an error message.
    """
    depth = max_depth if max_depth is not None else 3
    target = Path(directory).resolve()
    if not target.exists():
        return {"error": f"Directory does not exist: {target}"}
    if not target.is_dir():
        return {"error": f"Path is not a directory: {target}"}

    def _walk(p: Path, current: int) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        try:
            for child in sorted(p.iterdir()):
                # skip hidden dirs/files and common heavy dirs
                if child.name.startswith(".") or child.name in {
                    "node_modules", "__pycache__", ".git", ".venv", "venv",
                    "build", "dist", ".pio",
                }:
                    continue
                if child.is_dir():
                    entry: dict[str, Any] = {"name": child.name, "type": "dir"}
                    if current < depth:
                        entry["children"] = _walk(child, current + 1)
                    entries.append(entry)
                else:
                    entries.append({
                        "name": child.name,
                        "type": "file",
                        "size": child.stat().st_size,
                    })
        except PermissionError:
            entries.append({"name": "(permission denied)", "type": "error"})
        return entries

    tree = _walk(target, 1)
    return {"directory": str(target), "tree": tree}


def read_project_file(file_path: str) -> dict[str, Any]:
    """Read the content of a single file.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        A dict with ``content`` (the file text) or ``error``.
    """
    target = Path(file_path).resolve()
    if not target.exists():
        return {"error": f"File does not exist: {target}"}
    if not target.is_file():
        return {"error": f"Path is not a file: {target}"}

    size = target.stat().st_size
    if size > MAX_FILE_SIZE:
        return {
            "error": f"File too large ({size:,} bytes). Max allowed: {MAX_FILE_SIZE:,} bytes.",
            "suggestion": "Try reading a specific section or a smaller file.",
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"error": f"Could not read file: {exc}"}

    return {
        "file": str(target),
        "size": size,
        "content": content,
    }

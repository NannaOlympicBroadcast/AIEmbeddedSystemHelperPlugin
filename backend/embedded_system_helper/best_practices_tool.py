"""Tool for reading the contributors' embedded-systems best-practices guide.

The guide lives at  <project_root>/data/best_practices.md
and can be edited by any repository contributor.  The agent calls this tool
to consult community-written knowledge before executing complex tasks such as
file transfer, networking, or long installations.
"""

from __future__ import annotations

import sys
from pathlib import Path

def _find_doc_path() -> Path:
    """Resolve the path to best_practices.md.

    - **PyInstaller bundle**: PyInstaller extracts ``--add-data`` files to
      ``sys._MEIPASS``.  The build spec bundles ``backend/best_practices.md``
      as ``best_practices.md`` in the root of ``_MEIPASS``.
    - **Dev mode**: the file lives at ``backend/best_practices.md``, which is
      two directories above this module
      (``backend/embedded_system_helper/best_practices_tool.py``).
    """
    if getattr(sys, "frozen", False):
        # Running inside a PyInstaller one-file executable
        return Path(sys._MEIPASS) / "best_practices.md"  # type: ignore[attr-defined]
    # Dev / editable install
    return Path(__file__).parents[1] / "best_practices.md"

_DOC_PATH = _find_doc_path()


def read_best_practices(topic: str) -> str:
    """Read the contributors' embedded-systems best-practices guide.

    Consult this tool **before** performing tasks like:
    - Transferring files to/from a board
    - Configuring WiFi or Ethernet
    - Installing packages with apt / pip / docker
    - Setting up SSH

    Args:
        topic: Optional keyword to narrow results (e.g. ``"file transfer"``,
               ``"wifi"``, ``"apt"``, ``"docker"``, ``"ssh"``, ``"serial"``).
               Leave empty to retrieve the full guide.

    Returns:
        Matching section(s) from the best-practices document, or the entire
        document if no topic is specified.
    """
    if not _DOC_PATH.exists():
        return (
            f"Best practices document not found at {_DOC_PATH}. "
            "Please create data/best_practices.md in the project root."
        )

    content = _DOC_PATH.read_text(encoding="utf-8")

    if not topic:
        return content

    # Split on level-2 headings so we return whole sections
    raw_sections = content.split("\n## ")
    sections: list[str] = []
    for i, sec in enumerate(raw_sections):
        # Re-attach the heading marker (except the preamble before first ##)
        sections.append(sec if i == 0 else "## " + sec)

    kw = topic.lower()
    matching = [s for s in sections if kw in s.lower()]

    if matching:
        return "\n\n".join(matching)
    return (
        f"No sections matching '{topic}' found in the best-practices guide. "
        "Here is the full document:\n\n" + content
    )

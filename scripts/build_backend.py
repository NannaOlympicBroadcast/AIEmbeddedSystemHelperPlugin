"""Build the Python backend into a standalone executable using PyInstaller.

Usage
-----
    cd backend
    python ../scripts/build_backend.py

The resulting binary is placed at:
    extension/resources/bin/backend-{platform}.{ext}
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
BACKEND_DIR = ROOT_DIR / "backend"
OUTPUT_DIR = ROOT_DIR / "extension" / "resources" / "bin"

# Platform-specific output name
PLAT = platform.system().lower()
if PLAT == "windows":
    EXE_NAME = "backend-win.exe"
elif PLAT == "darwin":
    EXE_NAME = "backend-darwin"
else:
    EXE_NAME = "backend-linux"


def main() -> None:
    print(f"[build] Platform: {PLAT}")
    print(f"[build] Backend dir: {BACKEND_DIR}")
    print(f"[build] Output: {OUTPUT_DIR / EXE_NAME}")

    # Ensure output dir exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build with PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name", EXE_NAME.replace(".exe", ""),
        "--distpath", str(OUTPUT_DIR),
        "--workpath", str(BACKEND_DIR / "build"),
        "--specpath", str(BACKEND_DIR),
        # Hidden imports that PyInstaller may miss
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "google.adk",
        "--hidden-import", "litellm",
        # Collect litellm data files (model_prices JSON, etc.)
        "--collect-data", "litellm",
        "--hidden-import", "embedded_system_helper",
        "--hidden-import", "embedded_system_helper.agent",
        "--hidden-import", "embedded_system_helper.memory",
        "--hidden-import", "embedded_system_helper.search_agent",
        "--hidden-import", "embedded_system_helper.filesystem_tools",
        # Include the embedded_system_helper package as data
        "--add-data", f"{BACKEND_DIR / 'embedded_system_helper'}{';' if PLAT == 'windows' else ':'}embedded_system_helper",
        # Clean build
        "--clean",
        "-y",
        # Entry point
        str(BACKEND_DIR / "main.py"),
    ]

    print(f"[build] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(BACKEND_DIR))

    if result.returncode != 0:
        print(f"[build] ERROR: PyInstaller exited with code {result.returncode}")
        sys.exit(1)

    output_path = OUTPUT_DIR / EXE_NAME
    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"[build] SUCCESS: {output_path} ({size_mb:.1f} MB)")
    else:
        print(f"[build] ERROR: Expected output not found at {output_path}")
        sys.exit(1)

    # Clean up build artifacts
    build_dir = BACKEND_DIR / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("[build] Cleaned up build directory")


if __name__ == "__main__":
    main()

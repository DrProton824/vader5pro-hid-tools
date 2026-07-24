"""
Build both executables with PyInstaller.

Run from the repo root:
    python build/build.py

Outputs land in  dist/VaderMapper/
  VaderService.exe   – no console window, no UAC elevation
  VaderConfig.exe    – windowed GUI
  config.json        – default config copied next to executables
  assets/            – SVG and any other runtime assets
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
DIST   = ROOT / "dist" / "VaderMapper"
ASSETS = ROOT / "assets"
CONFIG = ROOT / "config.json"


def _base_args(name: str, entry: Path) -> list[str]:
    """PyInstaller flags shared by both executables."""
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "work" / name),
        "--specpath", str(ROOT / "build"),
        "--collect-all", "hid",
    ]

    args.append(str(entry))
    return args


def run(cmd: list[str]) -> None:
    print("\n>", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_service() -> None:
    run(_base_args(
        "VaderService",
        ROOT / "src" / "service" / "main.py",
    ))


def build_config_gui() -> None:
    run(_base_args(
        "VaderConfig",
        ROOT / "src" / "config_gui" / "main.py",
    ))


def copy_runtime_files() -> None:
    DIST.mkdir(parents=True, exist_ok=True)

    # Only copy default config if the user does not already have one
    dest_config = DIST / "config.json"
    if not dest_config.exists():
        shutil.copy2(CONFIG, dest_config)

    # Always refresh assets
    dest_assets = DIST / "assets"
    if ASSETS.exists():
        if dest_assets.exists():
            shutil.rmtree(dest_assets)
        shutil.copytree(ASSETS, dest_assets)


def main() -> None:
    build_service()
    build_config_gui()
    copy_runtime_files()
    print(f"\n✓ Build complete → {DIST}")


if __name__ == "__main__":
    main()

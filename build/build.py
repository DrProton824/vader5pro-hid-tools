"""
Build both executables with PyInstaller.

Run from the repo root:
    python build/build.py

If assets/icons/*.ico don't exist yet, generate them first:
    pip install pillow
    python tools/generate_icons.py

Outputs land in  dist/VaderMapper/
  VaderService.exe   – no console window, no UAC elevation, custom icon
  VaderConfig.exe    – windowed GUI, custom icon
  config.json        – default config copied next to executables
  assets/            – SVG, icons, and any other runtime assets
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

SERVICE_ICON = ASSETS / "icons" / "service.ico"
CONFIG_ICON  = ASSETS / "icons" / "config.ico"
CONTROLLER_SVG = ASSETS / "controller.svg"
CONTROLLER_PNG = ASSETS / "controller.png"
HIT_ZONES_JSON = ASSETS / "hit_zones.json"


def _base_args(name: str, entry: Path, icon: Path | None = None) -> list[str]:
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

    if icon and icon.exists():
        args += ["--icon", str(icon)]
    else:
        print(f"  (icon not found at {icon} - run tools/generate_icons.py first "
              f"for a custom icon; building with the default one for now)")

    args.append(str(entry))
    return args


def run(cmd: list[str]) -> None:
    print("\n>", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def ensure_icons() -> None:
    """Generate the .ico files on the fly if they're missing."""
    if SERVICE_ICON.exists() and CONFIG_ICON.exists():
        return
    print("Icons missing - generating them now...")
    run([sys.executable, str(ROOT / "tools" / "generate_icons.py")])


def ensure_controller_png() -> None:
    """Re-render controller.svg -> controller.png if the SVG changed."""
    if not CONTROLLER_SVG.exists():
        return
    if CONTROLLER_PNG.exists() and CONTROLLER_PNG.stat().st_mtime >= CONTROLLER_SVG.stat().st_mtime:
        return
    print("controller.svg changed - re-rendering controller.png...")
    run([sys.executable, str(ROOT / "tools" / "render_controller_png.py")])


def ensure_hit_zones() -> None:
    """Re-derive assets/hit_zones.json if the SVG changed."""
    if not CONTROLLER_SVG.exists():
        return
    if HIT_ZONES_JSON.exists() and HIT_ZONES_JSON.stat().st_mtime >= CONTROLLER_SVG.stat().st_mtime:
        return
    print("controller.svg changed - re-deriving hit_zones.json...")
    run([sys.executable, str(ROOT / "tools" / "generate_hit_zones.py")])


def build_service() -> None:
    run(_base_args(
        "VaderService",
        ROOT / "src" / "service" / "main.py",
        SERVICE_ICON,
    ))


def build_config_gui() -> None:
    run(_base_args(
        "VaderConfig",
        ROOT / "src" / "config_gui" / "main.py",
        CONFIG_ICON,
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
    ensure_icons()
    ensure_controller_png()
    ensure_hit_zones()
    build_service()
    build_config_gui()
    copy_runtime_files()
    print(f"\nBuild complete -> {DIST}")


if __name__ == "__main__":
    main()

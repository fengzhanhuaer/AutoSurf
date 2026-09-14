"""Start the native supervisor with the installation's persisted environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys


def load_env(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"AutoSurf configuration is missing: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch AutoSurf without a console window")
    parser.add_argument("--root", type=Path, default=Path(r"C:\Tools\AutoSurf"))
    args = parser.parse_args()

    root = args.root.resolve()
    load_env(root / ".env")
    supervisor = root / "program" / "scripts" / "autosurf-supervisor.py"
    if not supervisor.is_file():
        raise RuntimeError(f"AutoSurf supervisor is missing: {supervisor}")

    sys.argv = [str(supervisor), "--root", str(root)]
    runpy.run_path(str(supervisor), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

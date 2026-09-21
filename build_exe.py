"""Build the canonical Windows onedir release from the checked-in spec."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def build() -> int:
    root = Path(__file__).resolve().parent
    for target in (root / "build", root / "dist"):
        if target.exists():
            shutil.rmtree(target)
    completed = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(root / "BetclicFullOddsExtractor.spec")],
        cwd=root,
        check=False,
    )
    executable = root / "dist" / "APEX_Context_Engine" / "APEX_Context_Engine.exe"
    if completed.returncode != 0 or not executable.is_file():
        raise SystemExit(completed.returncode or 1)
    print(f"BUILD_OK={executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())

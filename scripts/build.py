"""Build on the target OS: python scripts/build.py"""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
args = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "Human Typer",
    "--paths",
    str(root),
    "--collect-all",
    "human_typer",
]
if sys.platform == "darwin":
    args += ["--osx-bundle-identifier", "com.humantyper.desktop"]
elif sys.platform == "win32":
    args += ["--onefile"]
else:
    raise SystemExit("Build on macOS or Windows.")
subprocess.run([*args, str(root / "scripts" / "entrypoint.py")], cwd=root, check=True)

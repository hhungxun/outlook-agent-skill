#!/usr/bin/env python3
"""One-time optional Graph OAuth runtime setup, without system Python modifications."""
import subprocess
import sys
import venv
from outlooklib.storage import state_dir

runtime = state_dir() / "runtime"
venv.EnvBuilder(with_pip=True).create(runtime)
python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "msal>=1.31,<2"], check=True)
print("OAuth runtime ready. Use scripts/run.py for login and normal commands.")

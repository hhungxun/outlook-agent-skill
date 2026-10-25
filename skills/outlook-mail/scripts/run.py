#!/usr/bin/env python3
"""Use an optional private OAuth runtime automatically, otherwise the current Python."""
import subprocess
import sys
from pathlib import Path
from outlooklib.storage import state_dir

runtime = state_dir() / "runtime"
python = runtime / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if not python.is_file():
    python = Path(sys.executable)
raise SystemExit(subprocess.call([str(python), str(Path(__file__).with_name("outlook_mail.py")), *sys.argv[1:]]))

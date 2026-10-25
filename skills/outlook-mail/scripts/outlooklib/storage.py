"""Private local state; never write credentials or mailbox data into the skill."""
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def state_dir():
    override = os.environ.get("OUTLOOK_MAIL_HOME")
    if override:
        path = Path(override).expanduser().absolute()
    elif os.name == "nt":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "outlook-mail"
    elif sys.platform == "darwin":
        path = Path.home() / "Library/Application Support/outlook-mail"
    else:
        path = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "outlook-mail"
    private_dir(path)
    return path


def private_dir(path, tighten=True):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Private state directory cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if tighten and os.name == "posix":
        path.chmod(0o700)
    return path


def write_text_private(path, text):
    path = Path(path)
    private_dir(path.parent, tighten=False)
    if path.is_symlink():
        raise ValueError("Refusing to overwrite a symlink")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    write_text_private(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("State file exceeds 8 MiB limit")
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def mutation_lock():
    path = state_dir() / "mutation.lock"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Another mutation is active or interrupted: inspect mutation.lock; remove it only after confirming no process is running")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)

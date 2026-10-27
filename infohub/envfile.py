"""Settings from a `.env` file, for hosting without Docker (e.g. cPanel's „Setup Python App“).

Docker Compose reads `.env` itself. On shared hosting the web app (`passenger_wsgi.py`), the
commands in the terminal and the cron job (`manage.py`) read the same file, so the secrets live in
one place outside public_html. Variables already set in the environment win.
"""

import os
from pathlib import Path


def load(path):
    """Put the KEY=VALUE lines of `path` into os.environ; a missing file is fine."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)

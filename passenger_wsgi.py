"""Entry point for cPanel's „Setup Python App“ (Phusion Passenger). Docker uses gunicorn instead."""

from pathlib import Path

from infohub.envfile import load

load(Path(__file__).resolve().parent / ".env")

from infohub.wsgi import application  # noqa: E402  (after the settings are in the environment)

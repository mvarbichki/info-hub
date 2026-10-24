import os

from .base import *

DEBUG = False

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Comma-separated, e.g. "info.company.local,10.0.0.15"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

# Comma-separated full origins, e.g. "http://info.company.local,http://10.0.0.15"
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# The site is reached over HTTPS: the login cookies only travel encrypted.
# DJANGO_HTTPS=0 for plain HTTP (e.g. the VPN-only variant without a certificate).
if os.environ.get("DJANGO_HTTPS", "1") == "1":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# A web server (nginx/Apache) sits in front of the app.
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ManifestStaticFilesStorage is recommended in production, to prevent
# outdated JavaScript / CSS assets being served from cache
# (e.g. after a Wagtail upgrade).
# See https://docs.djangoproject.com/en/6.1/ref/contrib/staticfiles/#manifeststaticfilesstorage
STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"}}

# Uploaded files must stay readable by the nginx container.
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

# Server errors (with the full traceback of the failed page) and security warnings (e.g. an
# expired form) go to the console, which Docker keeps (`docker compose logs web`), and with
# INFOHUB_LOG_FILE also to that file, rotated at 5 MB (shared hosting: a path outside
# public_html, read in cPanel's File Manager). "Not found" pages are not logged: bots cause many.
INFOHUB_LOG_FILE = os.environ.get("INFOHUB_LOG_FILE", "")
LOG_HANDLERS = {"console": {"class": "logging.StreamHandler", "formatter": "plain"}}
if INFOHUB_LOG_FILE:
    LOG_HANDLERS["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": INFOHUB_LOG_FILE,
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 5,
        "encoding": "utf-8",
        "formatter": "plain",
    }
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": LOG_HANDLERS,
    "root": {"handlers": list(LOG_HANDLERS), "level": "WARNING"},
    "loggers": {"django.request": {"level": "ERROR"}},
}

try:
    from .local import *
except ImportError:
    pass

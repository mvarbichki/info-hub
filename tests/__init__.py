"""The project's tests: `python manage.py test` (see tests/README.md)."""

import logging

# The tests open forbidden and missing pages on purpose; Django would log each one.
for name in ("django.request", "django.security.csrf"):
    logging.getLogger(name).setLevel(logging.CRITICAL)

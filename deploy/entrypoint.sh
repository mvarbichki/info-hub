#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear --verbosity 0

# Long timeout so large video uploads are not cut off.
exec gunicorn infohub.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 300 \
    --access-logfile -

FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=infohub.settings.production

RUN useradd --create-home wagtail

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=wagtail:wagtail . .

# Mount points for the shared volumes (nginx reads static files and uploads from them).
RUN mkdir -p /app/static /app/media && chown wagtail:wagtail /app/static /app/media

USER wagtail
EXPOSE 8000

CMD ["sh", "deploy/entrypoint.sh"]

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && \
    playwright install --with-deps chromium

COPY app ./app
COPY models.yaml ./

# Bind to the platform-provided $PORT (Render/Fly/etc.); default 8000 locally.
# Shell form so ${PORT} expands at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

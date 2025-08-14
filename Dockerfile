FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml .
COPY . .
COPY README.md .

RUN uv sync

ENV PYTHONPATH=/app

EXPOSE $PORT

CMD uv run gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b [::]:$PORT main:app
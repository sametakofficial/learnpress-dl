FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "yt-dlp[default,curl-cffi]"

WORKDIR /app

COPY learnpress_dl /app/learnpress_dl
COPY .env.example /app/.env.example
COPY README.md /app/README.md

ENTRYPOINT ["python", "-m", "learnpress_dl"]

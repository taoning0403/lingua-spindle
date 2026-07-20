FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="LinguaSpindle" \
      org.opencontainers.image.version="0.2.0" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/taoning0403/lingua-spindle"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_CONSTRAINT=/app/constraints-v020.txt \
    LINGUASPINDLE_DATA_DIR=/data

WORKDIR /app

RUN groupadd --gid 10001 linguaspindle \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent linguaspindle

COPY pyproject.toml constraints-v020.txt README.md LICENSE ./
COPY src ./src

RUN python -m pip install . \
    && mkdir -p /data \
    && chown 10001:10001 /data

USER 10001:10001

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2).read()"]

# Container networking requires an all-interface bind inside the isolated network. Compose maps
# the host side to 127.0.0.1 by default; changing that mapping is an explicit trust-boundary choice.
CMD ["linguaspindle", "serve", "--host", "0.0.0.0", "--port", "8765"]

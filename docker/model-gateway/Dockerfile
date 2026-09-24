# HAL Model Gateway - production-minded one-click image
# Build via: docker compose -f docker/model-gateway/docker-compose.yml up --build
# Multi-arch friendly: amd64 + arm64 (Oracle Ampere A1)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HAL_ROOT=/app \
    HAL_CLOUD_FIRST=1 \
    HAL_OPENCODE_CONFIG=/app/opencode_config.json \
    HAL_GATEWAY_TOKEN_FILE=/run/secrets/hal_gateway_token \
    HAL_PEERS_CONFIG=/app/config/peers.json \
    HAL_GATEWAY_IMAGE_DIR=/app/data/gateway_images \
    PORT=8766

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY hal_model_gateway /app/hal_model_gateway
COPY opencode_config.json /app/opencode_config.json
COPY config /app/config
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN chmod +x /app/docker-entrypoint.sh \
 && mkdir -p /app/data/gateway_images /app/data /app/assets/voices/piper \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin hal \
 && chown -R hal:hal /app

USER hal
EXPOSE 8766

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8766/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

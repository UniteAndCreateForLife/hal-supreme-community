#!/bin/sh
set -eu
export HAL_ROOT="${HAL_ROOT:-/app}"
export HAL_CLOUD_FIRST="${HAL_CLOUD_FIRST:-1}"
export PORT="${PORT:-8766}"
export HAL_HOST="${HAL_HOST:-0.0.0.0}"

if [ -z "${HAL_GATEWAY_TOKEN:-}" ]; then
  if [ -n "${HAL_GATEWAY_TOKEN_FILE:-}" ] && [ -f "$HAL_GATEWAY_TOKEN_FILE" ]; then
    HAL_GATEWAY_TOKEN="$(tr -d '\r\n' < "$HAL_GATEWAY_TOKEN_FILE")"
    export HAL_GATEWAY_TOKEN
  fi
fi

mkdir -p "${HAL_GATEWAY_IMAGE_DIR:-/app/data/gateway_images}" \
         /app/data /app/config

cd /app
exec python -m uvicorn hal_model_gateway.server:app \
  --host "$HAL_HOST" \
  --port "$PORT" \
  --log-level "${HAL_LOG_LEVEL:-info}"

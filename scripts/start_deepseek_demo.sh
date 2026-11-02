#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${MODEL_API_KEY:-}" ]]; then
  echo "请先设置 MODEL_API_KEY，例如：export MODEL_API_KEY='你的 DeepSeek API Key'" >&2
  exit 1
fi

export MODEL_BASE_URL="${MODEL_BASE_URL:-https://api.deepseek.com}"
export MODEL_NAME="${MODEL_NAME:-deepseek-chat}"
export MODEL_MAX_TOKENS="${MODEL_MAX_TOKENS:-512}"
export MODEL_REQUEST_TIMEOUT="${MODEL_REQUEST_TIMEOUT:-120}"
export AGENT_DATA_DIR="${AGENT_DATA_DIR:-data/public_demo}"
export WEBAPP_HOST="${WEBAPP_HOST:-0.0.0.0}"
export WEBAPP_PORT="${WEBAPP_PORT:-8765}"

echo "DeepSeek Demo: ${MODEL_BASE_URL} / ${MODEL_NAME}"
exec python webapp.py

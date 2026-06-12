#!/usr/bin/env bash
# Gateway dev 啟動：LiveKit token + NATS→WS 事件橋（:8800，LAN 可達）
set -euo pipefail
cd "$(dirname "$0")/../.."
exec .venv/bin/python -m uvicorn services.gateway.app:app --host 0.0.0.0 --port 8800

#!/usr/bin/env bash
# 啟動翻譯用 vLLM 服務（dev 環境，主機 ~/.local 既有 vllm 0.22.1，零升級）。
#
# 模型：Breeze-7B W4A16（繁中特化）
#   registry 原本: /nas-data/allen-speakin/models/breeze-7b-w4a16-awq
#   熱快取（實際載入）: ~/speakin-data/model-cache/breeze-7b-w4a16-awq
#   同步指令: cp -r /nas-data/allen-speakin/models/breeze-7b-w4a16-awq ~/speakin-data/model-cache/
#
# CPATH：主機無 sudo 裝 python3-dev，標頭由 deb 解壓至 ~/.local/pyhdrs（Triton JIT 編譯需要）。
# 若日後系統裝了 python3-dev，CPATH 與 VLLM_USE_FLASHINFER_SAMPLER/--enforce-eager 皆可移除以取得最佳效能。
set -euo pipefail

MODEL="${HOME}/speakin-data/model-cache/breeze-7b-w4a16-awq"
export CPATH="${HOME}/.local/pyhdrs/usr/include/python3.12:${HOME}/.local/pyhdrs/usr/include"
export VLLM_USE_FLASHINFER_SAMPLER=0

exec "${HOME}/.local/bin/vllm" serve "${MODEL}" \
  --served-model-name breeze-7b-mt \
  --port 8001 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.45 \
  --enforce-eager

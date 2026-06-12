# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案是什麼

SpeakIn：多對多即時串流語音翻譯管線（STT → MT → TTS）。完整架構、事件 schema 不變量、
PoC 各 Phase 進度與量測數字都在 **《結構及技術棧.md》** — 它是唯一真相來源，
完成任何 Phase 項目或改動架構決策後必須同步更新該文件。

## 常用指令

venv 在本機 NVMe（`/home/a0935951152/speakin-venv`），repo 內 `.venv` 是指向它的 symlink：

```bash
.venv/bin/ruff check .                 # lint（CI 同款）
.venv/bin/python -m pytest tests/unit  # 單元測試（無 GPU/外部依賴，CI 會跑）
.venv/bin/python -m pytest tests/unit/test_events.py -k roundtrip  # 跑單一測試

# 重播測試需要 GPU + NATS + vLLM 都在線（CI 不跑）
.venv/bin/python -m pytest tests/replay

# 啟動依賴
docker start speakin-nats              # NATS JetStream（含 -m 8222 監控埠）
bash deploy/dev/vllm_mt.sh             # vLLM 起 breeze-7b-mt 於 :8001（見下方環境約束）
curl -s localhost:8001/v1/models       # 確認 vLLM 就緒

# 跑管線（dev 重播模式）：--set 可覆寫 pipeline YAML 任一節點參數
.venv/bin/python -m services.runner --pipeline pipelines/default.yaml --session dev \
  --set stt.source=tests/replay/golden/zh_demo.wav --set stt.language=zh
.venv/bin/python -m services.viewer --session dev   # 終端訂閱者，看字幕流
```

## 架構（讀多個檔案才看得出來的部分)

核心原理：**stage 之間只透過 NATS topic 溝通、只依賴事件 schema**，因此管線拓撲就是
一份 YAML（`pipelines/*.yaml`），插入/替換 stage 不動核心碼。

- `schemas/events.py` — 事件 schema v1.0（`SegmentEvent` 等，`extra="forbid"`，擴充欄位走
  `meta`）。topic 命名一律用此處的 helper（`stt_topic`/`text_topic`/`tts_topic`），不要手拼字串。
- `core/bus/` — NATS 封裝；`nats-py` 只准出現在這個模組。
- `core/stage/` — `Stage` ABC（`setup`/`run`/`teardown`）與 `load_stage("name@ver")`，
  從 `stages/` 與 `plugins/` 找目錄（`manifest.yaml` + `stage.py` 的 `STAGE_CLASS`）。
- `services/runner/` — 讀 pipeline YAML、注入 config、併發跑各節點；`route_by` 語法已保留
  但未實作（Phase 3）。

事件流不變量（破壞它們會讓下游全錯）：

- 每段語音有遞增 `rev` 的 `partial` 事件，最後一個 `final` 收尾；下游以
  `(speaker_id, segment_id)` upsert，舊 `rev` 與 final 後事件須拒收。
- `segment_id` 貫穿 stt→mt→tts；每個 stage 在 `trace` 追加自己的耗時。
- TTS 只消費 `final`。翻譯每段每目標語言只做一次，與訂閱人數無關。
- mt_vllm 有輸出語言護欄（`lang_guard_ok`）：擋模型對破碎 partial 原文照抄；改 prompt
  或換模型後要重跑 `tests/unit/test_mt_guard.py` 與 zh→en 重播確認。

## 環境約束（違反會弄壞別人的東西）

- **`~/.local` 是 MISA 專案在用的環境：嚴禁升級任何套件**，壞了只能同版本重裝
  （`pip install --force-reinstall --no-deps --break-system-packages pkg==同版本`）。
  SpeakIn 一律用獨立 venv。
- vLLM 用主機既有 0.22.1（MISA 的），不裝進 venv；無 sudo 環境的 Python 標頭、
  `CPATH`、`VLLM_USE_FLASHINFER_SAMPLER=0` 等解法已固化在 `deploy/dev/vllm_mt.sh`，
  不要繞過該腳本手起。
- 儲存原則：NAS（本 repo 所在）寫入僅 ~63MB/s，是倉庫——模型 registry 在
  `/nas-data/allen-speakin/models`（git 忽略）、黃金音檔入庫以小檔為限；本機 NVMe 是熱路徑
  ——venv、模型熱快取（`~/speakin-data/model-cache`）、NATS 資料都放本機。
- `/nas-data/allen` 以外的 NAS 目錄是別人的，不能動。

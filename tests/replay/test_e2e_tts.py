"""端到端回放：STT → MT → TTS（Phase 3 退出條件）。

需要：NATS 運行中、GPU、vLLM 翻譯服務（deploy/dev/vllm_mt.sh）。
量測定義：講完一句到「聽到」譯文語音 = 首塊音訊就緒（串流合成，trace 的
first_audio_ms）對齊到該 segment 音訊（t_end_ms）到達 wall time 的差。
退出條件 P50 < 4s；整句合成完成時間另列參考。

執行：.venv/bin/python -m tests.replay.test_e2e_tts
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from pathlib import Path

import httpx
import pytest

from core.bus import Bus
from core.stage import load_stage
from schemas.events import SegmentEvent, SegmentState, TtsMetaEvent

GOLDEN = "tests/replay/golden/zh_demo.wav"
API_BASE = "http://127.0.0.1:8001/v1"
TARGETS = ["en", "ja"]
P50_BUDGET_S = 4.0


def _vllm_up() -> bool:
    try:
        return httpx.get(f"{API_BASE}/models", timeout=3).status_code == 200
    except Exception:
        return False


async def run_e2e():
    session = f"ses_tts_{uuid.uuid4().hex[:6]}"
    bus = Bus()
    await bus.connect()
    seg_end_ms: dict[str, int] = {}          # segment_id → 音訊軸上的結束時間
    tts_events: list[tuple[float, TtsMetaEvent]] = []

    async def on_stt(subject: str, ev) -> None:
        if isinstance(ev, SegmentEvent) and ev.state is SegmentState.FINAL:
            seg_end_ms[ev.segment_id] = ev.t_end_ms

    async def on_tts(subject: str, ev) -> None:
        tts_events.append((time.monotonic(), ev))

    await bus.subscribe(f"speakin.{session}.stt.>", on_stt)
    await bus.subscribe(f"speakin.{session}.tts.>", on_tts)

    mt_cls, _ = load_stage("mt_vllm@0.1")
    mt = mt_cls(bus=bus, session_id=session, config={
        "api_base": API_BASE, "model": "breeze-7b-mt", "target_langs": TARGETS,
    })
    await mt.setup()
    mt_task = asyncio.create_task(mt.run())

    tts_cls, _ = load_stage("tts_cosyvoice2@0.1")
    tts = tts_cls(bus=bus, session_id=session, config={"langs": TARGETS})
    await tts.setup()
    tts_task = asyncio.create_task(tts.run())

    stt_cls, _ = load_stage("stt_whisperlive@0.1")
    stt = stt_cls(bus=bus, session_id=session, config={
        "source": GOLDEN, "speaker_id": "spk_test", "language": "zh", "pace": 1.0,
    })
    await stt.setup()
    t0 = time.monotonic()
    await stt.run()
    await asyncio.sleep(12.0)  # 等最後的翻譯+合成完成

    mt_task.cancel()
    tts_task.cancel()
    await mt.teardown()
    await bus.close()
    return t0, seg_end_ms, tts_events


def analyze(t0, seg_end_ms, tts_events) -> dict:
    assert tts_events, "沒有收到任何 segment.tts 事件"
    langs = {e.lang for _, e in tts_events}
    assert langs == set(TARGETS), f"目標語言不齊: {langs}"
    for _, e in tts_events:
        assert e.event_type == "segment.tts" and e.duration_ms > 0
        assert e.trace[-1].stage.startswith("tts_cosyvoice2"), "trace 未追加 tts stage"
        assert Path(e.meta["path"]).exists(), f"音檔不存在: {e.meta['path']}"

    done_lats, first_lats = [], []
    for t, e in tts_events:
        done = t - (t0 + seg_end_ms[e.segment_id] / 1000)
        tr = e.trace[-1]
        first_lats.append(done - (tr.ms - tr.first_audio_ms) / 1000)
        done_lats.append(done)
    return {
        "events": len(tts_events),
        "p50_s": round(statistics.median(first_lats), 3),
        "max_s": round(max(first_lats), 3),
        "done_p50_s": round(statistics.median(done_lats), 3),
        "samples": {e.lang: e.meta["path"] for _, e in tts_events},
    }


@pytest.mark.skipif(not _vllm_up(), reason="vLLM 翻譯服務未啟動")
def test_e2e_tts() -> None:
    t0, ends, evs = asyncio.run(run_e2e())
    m = analyze(t0, ends, evs)
    print(f"\n[e2e-tts] segment.tts×{m['events']} | 首塊音訊 e2e P50={m['p50_s']}s "
          f"max={m['max_s']}s（整句合成完 P50={m['done_p50_s']}s）")
    for lang, path in m["samples"].items():
        print(f"[e2e-tts] {lang}: {path}")
    assert m["p50_s"] < P50_BUDGET_S, f"P50 {m['p50_s']}s 超出預算 {P50_BUDGET_S}s"


if __name__ == "__main__":
    test_e2e_tts()
    print("[e2e-tts] PASS")

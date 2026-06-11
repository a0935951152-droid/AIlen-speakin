"""端到端回放：STT → MT（Phase 2 退出條件）。

需要：NATS 運行中、GPU、vLLM 翻譯服務（deploy/dev/vllm_mt.sh）。
量測定義：e2e final 延遲 = 翻譯 final 事件到達 wall time −
該 segment 音訊（t_end_ms）到達 wall time。退出條件 P50 < 2.5s。

執行：.venv/bin/python -m tests.replay.test_e2e_stt_mt
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid

import httpx
import pytest

from core.bus import Bus
from core.stage import load_stage
from schemas.events import SegmentEvent, SegmentState

GOLDEN = "tests/replay/golden/jfk.wav"
API_BASE = "http://127.0.0.1:8001/v1"
TARGETS = ["zh", "ja"]
P50_BUDGET_S = 2.5


def _vllm_up() -> bool:
    try:
        return httpx.get(f"{API_BASE}/models", timeout=3).status_code == 200
    except Exception:
        return False


async def run_e2e():
    session = f"ses_e2e_{uuid.uuid4().hex[:6]}"
    bus = Bus()
    await bus.connect()
    mt_events: list[tuple[float, SegmentEvent]] = []

    async def on_text(subject: str, ev) -> None:
        mt_events.append((time.monotonic(), ev))

    await bus.subscribe(f"speakin.{session}.text.>", on_text)

    mt_cls, _ = load_stage("mt_vllm@0.1")
    mt = mt_cls(bus=bus, session_id=session, config={
        "api_base": API_BASE, "model": "breeze-7b-mt", "target_langs": TARGETS,
    })
    await mt.setup()
    mt_task = asyncio.create_task(mt.run())

    stt_cls, _ = load_stage("stt_whisperlive@0.1")
    stt = stt_cls(bus=bus, session_id=session, config={
        "source": GOLDEN, "speaker_id": "spk_test", "language": "en", "pace": 1.0,
    })
    await stt.setup()
    t0 = time.monotonic()
    await stt.run()
    await asyncio.sleep(3.0)  # 等最後的翻譯完成

    mt_task.cancel()
    await mt.teardown()
    await bus.close()
    return t0, mt_events


def analyze(t0: float, mt_events: list[tuple[float, SegmentEvent]]) -> dict:
    finals = [(t, e) for t, e in mt_events if e.state is SegmentState.FINAL]
    assert finals, "沒有收到任何翻譯 final"
    langs = {e.lang for _, e in finals}
    assert langs == set(TARGETS), f"目標語言不齊: {langs}"
    for _, e in finals:
        assert e.event_type == "segment.mt" and e.text.strip()
        assert e.trace[-1].stage.startswith("mt_vllm"), "trace 未追加 mt stage"

    lats = [t - (t0 + e.t_end_ms / 1000) for t, e in finals]
    return {
        "finals": len(finals),
        "p50_s": round(statistics.median(lats), 3),
        "max_s": round(max(lats), 3),
        "samples": {e.lang: e.text for _, e in finals},
    }


@pytest.mark.skipif(not _vllm_up(), reason="vLLM 翻譯服務未啟動")
def test_e2e_stt_mt() -> None:
    t0, evs = asyncio.run(run_e2e())
    m = analyze(t0, evs)
    print(f"\n[e2e] final×{m['finals']} | e2e延遲 P50={m['p50_s']}s max={m['max_s']}s")
    for lang, text in m["samples"].items():
        print(f"[e2e] {lang}: {text}")
    assert m["p50_s"] < P50_BUDGET_S, f"P50 {m['p50_s']}s 超出預算 {P50_BUDGET_S}s"


if __name__ == "__main__":
    test_e2e_stt_mt()
    print("[e2e] PASS")

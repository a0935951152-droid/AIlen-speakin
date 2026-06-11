"""黃金音檔回放測試：STT stage 事件序列與延遲斷言（Phase 1 退出條件）。

執行（需 NATS 運行中、GPU 可用）：
    .venv/bin/python -m tests.replay.test_stt_replay      # 直接跑
    .venv/bin/python -m pytest tests/replay -s            # pytest

量測定義：partial 延遲 = 事件到達 wall time − 該事件涵蓋音訊（t_end_ms）的到達 wall time，
即「音講到這裡之後多久字幕跟上」。退出條件 P50 < 1.5s。
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid

from core.bus import Bus
from core.stage import load_stage
from schemas.events import SegmentEvent, SegmentState

GOLDEN = "tests/replay/golden/jfk.wav"
EXPECT_SUBSTR = "country"          # JFK 名句必含詞
P50_BUDGET_S = 1.5


async def run_replay(pace: float = 1.0):
    session = f"ses_replay_{uuid.uuid4().hex[:6]}"
    bus = Bus()
    await bus.connect()
    received: list[tuple[float, SegmentEvent]] = []

    async def on_event(subject: str, ev) -> None:
        received.append((time.monotonic(), ev))

    await bus.subscribe(f"speakin.{session}.stt.>", on_event)

    cls, _ = load_stage("stt_whisperlive@0.1")
    stage = cls(bus=bus, session_id=session, config={
        "source": GOLDEN, "speaker_id": "spk_test", "language": "en", "pace": pace,
    })
    await stage.setup()           # 模型載入與暖機不計入延遲
    t0 = time.monotonic()         # 回放起點 = session 音訊軸 0ms
    await stage.run()
    await asyncio.sleep(0.3)      # 等最後的事件送達
    await bus.close()
    return t0, received


def analyze(t0: float, received: list[tuple[float, SegmentEvent]]) -> dict:
    partials = [(t, e) for t, e in received if e.state is SegmentState.PARTIAL]
    finals = [(t, e) for t, e in received if e.state is SegmentState.FINAL]
    assert partials, "沒有收到任何 partial"
    assert finals, "沒有收到任何 final"

    # rev 單調遞增、final 為每個 segment 的最後事件（§1.5）
    by_seg: dict[str, list[SegmentEvent]] = {}
    for _, e in received:
        by_seg.setdefault(e.segment_id, []).append(e)
    for seg_id, evs in by_seg.items():
        revs = [e.rev for e in evs]
        assert revs == sorted(revs), f"{seg_id} rev 非單調: {revs}"
        assert all(e.state is not SegmentState.FINAL for e in evs[:-1]), \
            f"{seg_id} final 之後還有事件"

    full_text = " ".join(e.text for _, e in finals).lower()
    assert EXPECT_SUBSTR in full_text, f"轉寫內容異常: {full_text!r}"

    # partial 延遲（pace=1.0 時 t_end_ms 的音訊在 t0 + t_end/1000 到達）
    lats = [t - (t0 + e.t_end_ms / 1000) for t, e in partials]
    p50 = statistics.median(lats)
    return {
        "partials": len(partials), "finals": len(finals),
        "p50_s": round(p50, 3), "max_s": round(max(lats), 3),
        "final_text": " ".join(e.text for _, e in finals),
    }


def test_stt_replay() -> None:
    t0, received = asyncio.run(run_replay(pace=1.0))
    m = analyze(t0, received)
    print(f"\n[replay] partial×{m['partials']} final×{m['finals']} "
          f"| partial延遲 P50={m['p50_s']}s max={m['max_s']}s")
    print(f"[replay] final: {m['final_text']}")
    assert m["p50_s"] < P50_BUDGET_S, f"P50 {m['p50_s']}s 超出預算 {P50_BUDGET_S}s"


if __name__ == "__main__":
    test_stt_replay()
    print("[replay] PASS")

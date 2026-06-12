"""終端字幕 viewer：訂閱 segment 事件並以 upsert 語意顯示（Phase 1 驗證用）。

partial 以「…」標示、同一 segment 的新 rev 覆蓋舊內容；final 以「✔」定稿。
用法：
    .venv/bin/python -m services.viewer --session ses_dev [--kind stt|text]
"""

from __future__ import annotations

import argparse
import asyncio

from core.bus import Bus
from schemas.events import SegmentEvent, SegmentState


async def amain() -> None:
    p = argparse.ArgumentParser(prog="services.viewer")
    p.add_argument("--session", required=True)
    p.add_argument("--kind", default="stt", choices=["stt", "text"])
    p.add_argument("--nats", default="nats://127.0.0.1:4222")
    args = p.parse_args()

    # key 含 lang：同一 segment 的多語言翻譯共用 segment_id（§1.5-4 對齊），
    # 只用 (speaker, segment) 會讓不同語言互相覆寫/被先到的 final 擋掉
    latest: dict[tuple[str, str, str], SegmentEvent] = {}

    async def on_event(subject: str, ev) -> None:
        if not isinstance(ev, SegmentEvent):
            return
        key = (ev.speaker_id, ev.segment_id, ev.lang)
        prev = latest.get(key)
        if prev and (prev.state is SegmentState.FINAL or prev.rev >= ev.rev):
            return  # upsert 規則：final 不可變、rev 只往前
        latest[key] = ev
        mark = "✔" if ev.state is SegmentState.FINAL else "…"
        stt_ms = ev.trace[-1].ms if ev.trace else "-"
        print(f"[{ev.segment_id} r{ev.rev} {mark} {ev.lang} {stt_ms}ms] {ev.text}")

    bus = Bus(args.nats)
    await bus.connect()
    await bus.subscribe(f"speakin.{args.session}.{args.kind}.>", on_event)
    print(f"[viewer] 訂閱 speakin.{args.session}.{args.kind}.> 中，Ctrl-C 結束")
    try:
        await asyncio.Event().wait()
    finally:
        await bus.close()


if __name__ == "__main__":
    asyncio.run(amain())

"""TTS worker 發軌驗證（Phase 4）：segment.mt final → 串流合成 → LiveKit 虛擬參與者音軌。

需要：NATS、GPU、LiveKit（deploy/dev/livekit.sh）；不需 vLLM（直接餵 final 翻譯事件）。
驗證：聽端參與者訂到 `tts.{speaker}.{lang}` 音軌、收到的音訊時長與 TtsMetaEvent
吻合、track_id 對得上、首框延遲（講端 final 到聽端聽到）入帳。

執行：.venv/bin/python -m tests.replay.test_livekit_tts
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx
import pytest

from core.bus import Bus
from core.stage import load_stage
from schemas.events import SegmentEvent, SegmentState, TtsMetaEvent, text_topic

LK_WS, LK_HTTP = "ws://127.0.0.1:7880", "http://127.0.0.1:7880"
TEXT = "Hello everyone, this is a streaming synthesis test over LiveKit."


def _lk_up() -> bool:
    try:
        return httpx.get(LK_HTTP, timeout=3).status_code == 200
    except Exception:
        return False


async def run_flow():
    from livekit import api, rtc  # 測試聽端直接用 SDK；產品碼一律走 core/rtc

    session = f"ses_lk_{uuid.uuid4().hex[:6]}"
    bus = Bus()
    await bus.connect()
    metas: list[TtsMetaEvent] = []

    async def on_tts(subject: str, ev) -> None:
        if isinstance(ev, TtsMetaEvent):
            metas.append(ev)

    await bus.subscribe(f"speakin.{session}.tts.>", on_tts)

    # 聽端先進房（auto_subscribe：新發布的音軌會自動訂上）。
    # SFU 在無資料時填靜音框，所以延遲與時長都只認「非靜音」樣本。
    import numpy as np

    sub = {"name": None, "sid": None, "speech_samples": 0, "sr": 0, "t_first": None}
    listener = rtc.Room()

    @listener.on("track_subscribed")
    def _on_track(track, pub, participant):
        sub["name"], sub["sid"] = pub.name, pub.sid

        async def drain():
            async for fev in rtc.AudioStream(track):
                sub["sr"] = fev.frame.sample_rate
                pcm = np.frombuffer(fev.frame.data, dtype=np.int16)
                if np.abs(pcm).max() > 250:  # 非靜音
                    if sub["t_first"] is None:
                        sub["t_first"] = time.monotonic()
                    sub["speech_samples"] += fev.frame.samples_per_channel

        asyncio.create_task(drain())

    token = (api.AccessToken("devkey", "secret").with_identity("listener")
             .with_grants(api.VideoGrants(room_join=True, room=session)).to_jwt())
    await listener.connect(LK_WS, token)

    tts_cls, _ = load_stage("tts_cosyvoice2@0.1")
    tts = tts_cls(bus=bus, session_id=session, config={
        "langs": ["en"],
        "livekit": {"url": LK_WS, "api_key": "devkey", "api_secret": "secret"},
    })
    await tts.setup()
    task = asyncio.create_task(tts.run())
    await asyncio.sleep(1.0)  # 等 run() 的訂閱在 NATS 生效，再發事件

    t_final = time.monotonic()
    await bus.publish(text_topic(session, "en"), SegmentEvent(
        event_type="segment.mt", session_id=session, speaker_id="spk_a",
        segment_id="spk_a-000000", rev=0, state=SegmentState.FINAL,
        t_start_ms=0, t_end_ms=3000, src_lang="zh", lang="en", text=TEXT,
    ))
    for _ in range(60):  # 合成+傳輸最多等 30s
        if metas and sub["speech_samples"] > 0:
            await asyncio.sleep(2.0)  # 讓尾端音框送完
            break
        await asyncio.sleep(0.5)

    task.cancel()
    await tts.teardown()
    await listener.disconnect()
    await bus.close()
    return t_final, metas, sub


def test_livekit_tts() -> None:
    t_final, metas, sub = asyncio.run(run_flow())
    assert metas, "沒收到 TtsMetaEvent"
    m = metas[0]
    assert sub["name"] == "tts.spk_a.en", f"音軌名不對: {sub['name']}"
    assert m.track_id == sub["sid"], f"meta track_id {m.track_id} ≠ 訂閱音軌 {sub['sid']}"
    assert m.audio_t0_ms == 0  # 該軌第一段
    heard_ms = sub["speech_samples"] / sub["sr"] * 1000
    assert heard_ms > m.duration_ms * 0.5, f"有聲僅 {heard_ms:.0f}ms，合成 {m.duration_ms}ms"
    first_s = sub["t_first"] - t_final
    print(f"\n[lk-tts] 軌 {sub['name']} | final→聽端首聲 {first_s:.2f}s | "
          f"合成 {m.duration_ms}ms / 有聲 {heard_ms:.0f}ms @ {sub['sr']}Hz")


pytestmark = pytest.mark.skipif(not _lk_up(), reason="LiveKit 未啟動")

if __name__ == "__main__":
    test_livekit_tts()
    print("[lk-tts] PASS")

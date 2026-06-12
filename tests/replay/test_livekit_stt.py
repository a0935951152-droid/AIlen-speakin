"""LiveKit mic → STT ingress 驗證（Phase 4）：講者音軌 → 訂閱 → VAD/STT → segment.stt。

需要：NATS、GPU、LiveKit（deploy/dev/livekit.sh）；不需 vLLM。
驗證：① 虛擬講者以麥克風音軌實時推黃金音檔，STT stage 從房內訂軌轉寫，
事件 speaker_id = 參與者 identity、partial/final 序列符合 §1.5；
② 另一參與者發布 `tts.*` 譯音軌（同樣的可轉寫音訊），必須被過濾——
若回灌會形成 stt→mt→tts→stt 翻譯迴圈。

執行：.venv/bin/python -m tests.replay.test_livekit_stt
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid

import httpx
import numpy as np
import pytest

from core.bus import Bus
from core.stage import load_stage
from schemas.events import SegmentEvent, SegmentState

LK_WS, LK_HTTP = "ws://127.0.0.1:7880", "http://127.0.0.1:7880"
GOLDEN = "tests/replay/golden/jfk.wav"
EXPECT_SUBSTR = "country"


def _lk_up() -> bool:
    try:
        return httpx.get(LK_HTTP, timeout=3).status_code == 200
    except Exception:
        return False


async def _publish_wav(session: str, identity: str, track_name: str,
                       audio: np.ndarray, sr: int = 16000):
    """以虛擬參與者把音檔當即時音軌推進房（測試端直接用 SDK；產品碼一律走 core/rtc）。
    回傳 (room, 推流 task)。"""
    from livekit import api, rtc

    token = (api.AccessToken("devkey", "secret").with_identity(identity)
             .with_grants(api.VideoGrants(room_join=True, room=session)).to_jwt())
    room = rtc.Room()
    await room.connect(LK_WS, token)
    source = rtc.AudioSource(sr, 1)
    track = rtc.LocalAudioTrack.create_audio_track(track_name, source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    i16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    step = sr // 10  # 100ms 框，sleep 控實時節奏

    async def pump() -> None:
        for i in range(0, len(i16), step):
            chunk = i16[i : i + step]
            await source.capture_frame(rtc.AudioFrame(
                data=chunk.tobytes(), sample_rate=sr,
                num_channels=1, samples_per_channel=len(chunk)))
            await asyncio.sleep(len(chunk) / sr)

    return room, asyncio.create_task(pump())


async def run_flow():
    from faster_whisper.audio import decode_audio

    session = f"ses_lkstt_{uuid.uuid4().hex[:6]}"
    bus = Bus()
    await bus.connect()
    received: list[tuple[float, SegmentEvent]] = []

    async def on_event(subject: str, ev) -> None:
        received.append((time.monotonic(), ev))

    await bus.subscribe(f"speakin.{session}.stt.>", on_event)

    cls, _ = load_stage("stt_whisperlive@0.1")
    stage = cls(bus=bus, session_id=session, config={
        "language": "en",
        "livekit": {"url": LK_WS, "api_key": "devkey", "api_secret": "secret"},
    })
    await stage.setup()  # 模型載入與暖機不計入延遲
    run_task = asyncio.create_task(stage.run())
    await asyncio.sleep(1.0)  # 等 ingress 連房完成

    audio = decode_audio(GOLDEN, sampling_rate=16000)
    # 干擾軌先進房：名稱 tts.* = 本系統譯音軌，內容同樣可轉寫，必須被忽略
    decoy_room, decoy_pump = await _publish_wav(session, "tts-decoy",
                                                "tts.spk_x.en", audio)
    spk_room, spk_pump = await _publish_wav(session, "spk_pub", "mic", audio)
    t0 = time.monotonic()  # 推流起點 = 講者音訊軸 0ms

    dur = len(audio) / 16000
    for _ in range(int((dur + 25) * 2)):  # 音檔時長 + 轉寫/收尾餘裕
        finals = [e for _, e in received
                  if e.state is SegmentState.FINAL and e.speaker_id == "spk_pub"]
        if finals and EXPECT_SUBSTR in " ".join(e.text for e in finals).lower():
            await asyncio.sleep(1.0)  # 收殘餘事件
            break
        await asyncio.sleep(0.5)

    for t in (decoy_pump, spk_pump, run_task):
        t.cancel()
    await asyncio.gather(decoy_pump, spk_pump, run_task, return_exceptions=True)
    await decoy_room.disconnect()
    await spk_room.disconnect()
    await bus.close()
    return t0, received


def test_livekit_stt() -> None:
    t0, received = asyncio.run(run_flow())
    assert received, "沒收到任何 segment.stt 事件"

    speakers = {e.speaker_id for _, e in received}
    assert "tts-decoy" not in speakers, "tts.* 譯音軌被回灌進 STT（翻譯迴圈風險）"
    assert speakers == {"spk_pub"}, f"speaker_id 異常: {speakers}"

    finals = [(t, e) for t, e in received if e.state is SegmentState.FINAL]
    partials = [(t, e) for t, e in received if e.state is SegmentState.PARTIAL]
    assert finals, "沒有收到任何 final"
    full_text = " ".join(e.text for _, e in finals).lower()
    assert EXPECT_SUBSTR in full_text, f"轉寫內容異常: {full_text!r}"

    by_seg: dict[str, list[SegmentEvent]] = {}
    for _, e in received:
        by_seg.setdefault(e.segment_id, []).append(e)
    for seg_id, evs in by_seg.items():
        revs = [e.rev for e in evs]
        assert revs == sorted(revs), f"{seg_id} rev 非單調: {revs}"
        assert all(e.state is not SegmentState.FINAL for e in evs[:-1]), \
            f"{seg_id} final 之後還有事件"

    # partial 延遲：推流實時，t_end_ms 的音訊在 t0 + t_end/1000 才存在
    lats = [t - (t0 + e.t_end_ms / 1000) for t, e in partials]
    p50 = round(statistics.median(lats), 3) if lats else None
    print(f"\n[lk-stt] partial×{len(partials)} final×{len(finals)} "
          f"| partial延遲 P50={p50}s")
    print(f"[lk-stt] final: {' '.join(e.text for _, e in finals)}")


pytestmark = pytest.mark.skipif(not _lk_up(), reason="LiveKit 未啟動")

if __name__ == "__main__":
    test_livekit_stt()
    print("[lk-stt] PASS")

"""空 final tombstone（§1.5-1）單元測試。

背景：partial 發布後若 final 轉寫為空（VAD 截掉幻覺假設），原本不發 final
也不遞增 seq → segment_id 被下一句重用且 rev 歸零，下游依「rev 只往前」
拒收整句。修法：仍發空 final 收尾；mt 原樣轉發、tts 跳過。
"""

from __future__ import annotations

import asyncio

from schemas.events import SegmentEvent, SegmentState
from stages.mt_vllm.stage import MtVllm
from stages.stt_whisperlive.stage import SttWhisperLive


def _stt() -> SttWhisperLive:
    st = SttWhisperLive(bus=None, session_id="ses_t", config={})
    st.speaker, st.lang = "spk", "zh"
    return st


def test_empty_final_after_partials_emits_tombstone():
    ev = _stt()._event([], None, buf_off=0, buf_len=16000, seq=3, rev=2,
                       state=SegmentState.FINAL, ms=1.0)
    assert ev is not None and ev.state is SegmentState.FINAL
    assert ev.text == "" and ev.segment_id == "spk-000003"


def test_empty_final_without_partials_stays_silent():
    ev = _stt()._event([], None, buf_off=0, buf_len=16000, seq=0, rev=0,
                       state=SegmentState.FINAL, ms=1.0)
    assert ev is None


def test_empty_partial_never_published():
    ev = _stt()._event([], None, buf_off=0, buf_len=16000, seq=0, rev=5,
                       state=SegmentState.PARTIAL, ms=1.0)
    assert ev is None


class _FakeBus:
    def __init__(self):
        self.published: list[tuple[str, SegmentEvent]] = []

    async def publish(self, topic, event):
        self.published.append((topic, event))


def test_mt_forwards_tombstone_without_translating():
    bus = _FakeBus()
    mt = MtVllm(bus=bus, session_id="ses_t", config={})
    mt.targets, mt._seen = ["en", "ja"], {}
    src = SegmentEvent(
        event_type="segment.stt", session_id="ses_t", speaker_id="spk",
        segment_id="spk-000003", rev=2, state=SegmentState.FINAL,
        t_start_ms=0, t_end_ms=1000, src_lang="zh", lang="zh", text="",
    )
    asyncio.run(mt._on_stt("subj", src))  # 沒有 HTTP client：若嘗試翻譯會直接炸
    assert {e.lang for _, e in bus.published} == {"en", "ja"}
    for _, e in bus.published:
        assert e.event_type == "segment.mt" and e.text == ""
        assert e.state is SegmentState.FINAL and e.segment_id == "spk-000003"

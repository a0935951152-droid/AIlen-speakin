"""事件 schema 單元測試（CI 無 GPU 也能跑）。"""

import pytest
from pydantic import ValidationError

from core.bus import parse_event
from schemas.events import (
    ControlEvent,
    SegmentEvent,
    SegmentState,
    TtsMetaEvent,
    custom_topic,
    stt_topic,
    text_topic,
    tts_topic,
)


def _seg(**kw) -> SegmentEvent:
    base = dict(
        event_type="segment.stt", session_id="ses_t", speaker_id="spk_a",
        segment_id="spk_a-000001", rev=0, state=SegmentState.PARTIAL,
        t_start_ms=0, t_end_ms=500, src_lang="zh", lang="zh", text="哈囉",
    )
    base.update(kw)
    return SegmentEvent(**base)


def test_topic_naming():
    assert stt_topic("s1", "spk_a") == "speakin.s1.stt.spk_a"
    assert text_topic("s1", "en") == "speakin.s1.text.en"
    assert tts_topic("s1", "spk_a", "ja") == "speakin.s1.tts.spk_a.ja"
    assert custom_topic("s1", "glossary") == "speakin.s1.x.glossary"


def test_extra_fields_forbidden():
    """§1.5-8：客製資料只准進 meta，核心欄位不准外加。"""
    with pytest.raises(ValidationError):
        _seg(my_custom_field="x")
    ev = _seg(meta={"my_custom_field": "x"})
    assert ev.meta["my_custom_field"] == "x"


def test_parse_event_dispatch():
    seg = _seg()
    assert isinstance(parse_event(seg.model_dump_json().encode()), SegmentEvent)

    tts = TtsMetaEvent(session_id="s", speaker_id="a", segment_id="a-1",
                       lang="en", track_id="t", audio_t0_ms=0, duration_ms=10)
    assert isinstance(parse_event(tts.model_dump_json().encode()), TtsMetaEvent)

    ctl = ControlEvent(event_type="control.floor", session_id="s")
    assert isinstance(parse_event(ctl.model_dump_json().encode()), ControlEvent)


def test_roundtrip_preserves_fields():
    ev = _seg(rev=3, conf=0.91)
    back = parse_event(ev.model_dump_json().encode())
    assert (back.rev, back.conf, back.state) == (3, 0.91, SegmentState.PARTIAL)

"""SpeakIn 事件 Schema v1.0 — 全系統唯一合約。

定義見《結構及技術棧.md》§1。所有 stage / 前端 SDK / 外部應用只依賴本檔案，
不互相依賴。演進規則（§1.5）：只准加欄位（minor bump）；改/刪欄位 = major bump。

產出 JSON Schema（供前端 TS 型別與外部 SDK 生成）：
    python -m schemas.events  →  schemas/events.schema.json
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VER = "1.0"


# ── Topic 命名（§1.1）─────────────────────────────────────────────


def stt_topic(session_id: str, speaker_id: str) -> str:
    return f"speakin.{session_id}.stt.{speaker_id}"


def text_topic(session_id: str, lang: str) -> str:
    return f"speakin.{session_id}.text.{lang}"


def tts_topic(session_id: str, speaker_id: str, lang: str) -> str:
    return f"speakin.{session_id}.tts.{speaker_id}.{lang}"


def control_topic(session_id: str) -> str:
    return f"speakin.{session_id}.control"


def custom_topic(session_id: str, stage_id: str, suffix: str = "") -> str:
    """客製 stage 的中間 topic（§6 插拔用）。"""
    base = f"speakin.{session_id}.x.{stage_id}"
    return f"{base}.{suffix}" if suffix else base


# ── 共用元件 ──────────────────────────────────────────────────────


class SegmentState(str, Enum):
    PARTIAL = "partial"  # 可被更高 rev 覆寫
    FINAL = "final"      # 不可變（§1.5-1）


class Word(BaseModel):
    """詞級時間戳，供字幕逐字上屏與跨模態對齊。"""

    w: str
    t0: int = Field(description="相對 session 起點的開始時間 (ms)")
    t1: int = Field(description="相對 session 起點的結束時間 (ms)")


class TraceEntry(BaseModel):
    """延遲遙測：事件流經的每個 stage 追加一筆。"""

    model_config = ConfigDict(extra="allow")  # stage 可加自訂量測欄位

    stage: str = Field(description="stage 識別與版本，如 'stt_whisperlive@1.3.0'")
    ms: float | None = Field(default=None, description="本 stage 處理耗時 (ms)")


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 客製資料一律進 meta（§1.5-8）

    schema_ver: str = SCHEMA_VER
    session_id: str
    wall_ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── SegmentEvent（§1.2：stt / mt 共用）────────────────────────────


class SegmentEvent(_EventBase):
    event_type: Literal["segment.stt", "segment.mt"]
    speaker_id: str
    segment_id: str = Field(description="{speaker_id}-{單調遞增序號}，貫穿 stt→mt→tts")
    rev: int = Field(default=0, ge=0, description="partial 修訂號，單調遞增；final 後不再變")
    state: SegmentState
    t_start_ms: int = Field(ge=0)
    t_end_ms: int = Field(ge=0)
    src_lang: str = Field(description="講者原始語言 (BCP-47, 如 'zh')")
    lang: str = Field(description="本事件 text 的語言；stt 事件 = src_lang")
    text: str
    words: list[Word] = Field(default_factory=list)
    conf: float | None = Field(default=None, ge=0.0, le=1.0)
    trace: list[TraceEntry] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict, description="客製 stage 擴充欄位")


# ── TtsMetaEvent(§1.3：音訊本體走 LiveKit 音軌，匯流排只走中繼資料)──


class TtsMetaEvent(_EventBase):
    event_type: Literal["segment.tts"] = "segment.tts"
    speaker_id: str
    segment_id: str = Field(description="與來源 segment 同 ID，跨模態對齊的關鍵")
    lang: str
    track_id: str = Field(description="對應的 LiveKit 音軌 ID")
    audio_t0_ms: int = Field(ge=0, description="此段音訊在該音軌上的起點")
    duration_ms: int = Field(ge=0)
    trace: list[TraceEntry] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# ── ControlEvent（§1.4）──────────────────────────────────────────


class FloorPayload(BaseModel):
    floor_speaker: str | None = Field(default=None, description="當前主發言者，耳機預設跟隨")
    active_speakers: list[str] = Field(default_factory=list)


class SubsPayload(BaseModel):
    lang_subscribers: dict[str, int] = Field(
        default_factory=dict, description="TTS 惰性啟動依據：0 訂閱者不合成（§1.5-6）"
    )


class ControlEvent(_EventBase):
    event_type: Literal["control.floor", "control.presence", "control.subs"]
    payload: dict[str, Any] = Field(default_factory=dict)


AnyEvent = SegmentEvent | TtsMetaEvent | ControlEvent


# ── JSON Schema 匯出 ─────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from pathlib import Path

    from pydantic import TypeAdapter

    schema = TypeAdapter(AnyEvent).json_schema()
    schema["$comment"] = f"SpeakIn event schema v{SCHEMA_VER}; generated from schemas/events.py"
    out = Path(__file__).parent / "events.schema.json"
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out}")

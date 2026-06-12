/* 由 schemas/events.schema.json 生成（npm run gen:types），勿手改 */

export type EventsSchema = SegmentEvent | TtsMetaEvent | ControlEvent;
export type SchemaVer = string;
export type SessionId = string;
export type WallTs = string;
export type EventType = "segment.stt" | "segment.mt";
export type SpeakerId = string;
/**
 * {speaker_id}-{單調遞增序號}，貫穿 stt→mt→tts
 */
export type SegmentId = string;
/**
 * partial 修訂號，單調遞增；final 後不再變
 */
export type Rev = number;
export type SegmentState = "partial" | "final";
export type TStartMs = number;
export type TEndMs = number;
/**
 * 講者原始語言 (BCP-47, 如 'zh')
 */
export type SrcLang = string;
/**
 * 本事件 text 的語言；stt 事件 = src_lang
 */
export type Lang = string;
export type Text = string;
export type W = string;
/**
 * 相對 session 起點的開始時間 (ms)
 */
export type T0 = number;
/**
 * 相對 session 起點的結束時間 (ms)
 */
export type T1 = number;
export type Words = Word[];
export type Conf = number | null;
/**
 * stage 識別與版本，如 'stt_whisperlive@1.3.0'
 */
export type Stage = string;
/**
 * 本 stage 處理耗時 (ms)
 */
export type Ms = number | null;
export type Trace = TraceEntry[];
export type SchemaVer1 = string;
export type SessionId1 = string;
export type WallTs1 = string;
export type EventType1 = "segment.tts";
export type SpeakerId1 = string;
/**
 * 與來源 segment 同 ID，跨模態對齊的關鍵
 */
export type SegmentId1 = string;
export type Lang1 = string;
/**
 * 對應的 LiveKit 音軌 ID
 */
export type TrackId = string;
/**
 * 此段音訊在該音軌上的起點
 */
export type AudioT0Ms = number;
export type DurationMs = number;
export type Trace1 = TraceEntry[];
export type SchemaVer2 = string;
export type SessionId2 = string;
export type WallTs2 = string;
export type EventType2 = "control.floor" | "control.presence" | "control.subs";

export interface SegmentEvent {
  schema_ver?: SchemaVer;
  session_id: SessionId;
  wall_ts?: WallTs;
  event_type: EventType;
  speaker_id: SpeakerId;
  segment_id: SegmentId;
  rev?: Rev;
  state: SegmentState;
  t_start_ms: TStartMs;
  t_end_ms: TEndMs;
  src_lang: SrcLang;
  lang: Lang;
  text: Text;
  words?: Words;
  conf?: Conf;
  trace?: Trace;
  meta?: Meta;
}
/**
 * 詞級時間戳，供字幕逐字上屏與跨模態對齊。
 */
export interface Word {
  w: W;
  t0: T0;
  t1: T1;
  [k: string]: unknown;
}
/**
 * 延遲遙測：事件流經的每個 stage 追加一筆。
 */
export interface TraceEntry {
  stage: Stage;
  ms?: Ms;
  [k: string]: unknown;
}
/**
 * 客製 stage 擴充欄位
 */
export interface Meta {
  [k: string]: unknown;
}
export interface TtsMetaEvent {
  schema_ver?: SchemaVer1;
  session_id: SessionId1;
  wall_ts?: WallTs1;
  event_type?: EventType1;
  speaker_id: SpeakerId1;
  segment_id: SegmentId1;
  lang: Lang1;
  track_id: TrackId;
  audio_t0_ms: AudioT0Ms;
  duration_ms: DurationMs;
  trace?: Trace1;
  meta?: Meta1;
}
export interface Meta1 {
  [k: string]: unknown;
}
export interface ControlEvent {
  schema_ver?: SchemaVer2;
  session_id: SessionId2;
  wall_ts?: WallTs2;
  event_type: EventType2;
  payload?: Payload;
}
export interface Payload {
  [k: string]: unknown;
}

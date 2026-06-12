/**
 * 滾動修正字幕的狀態機（與框架無關的核心 + React hook）。
 * 不變量（《結構及技術棧.md》§1.5）：以 (speaker_id, segment_id, lang) upsert，
 * 舊 rev 與 final 後到的事件拒收；空 final = tombstone，清掉該段 partial。
 */

import type { SegmentEvent, SpeakInClient } from "@speakin/sdk";
import { useEffect, useMemo, useReducer } from "react";

export interface CaptionSegment {
  speaker: string;
  segmentId: string;
  lang: string;
  text: string;
  final: boolean;
  rev: number;
  tEndMs: number;
  /** final 事件帶的 stage 延遲鏈，餵延遲儀表 */
  trace: { stage: string; ms?: number | null }[];
  receivedAt: number;
}

export interface SpeakerCaptions {
  speaker: string;
  finals: CaptionSegment[];
  partial: CaptionSegment | null;
}

type State = Map<string, CaptionSegment>; // key: speaker|segment|lang

export function captionKey(ev: SegmentEvent): string {
  return `${ev.speaker_id}|${ev.segment_id}|${ev.lang}`;
}

/** upsert 一筆事件；違反不變量的事件回傳原 state（不重繪）。 */
export function applySegment(state: State, ev: SegmentEvent): State {
  const key = captionKey(ev);
  const rev = ev.rev ?? 0;
  const prev = state.get(key);
  if (prev && (prev.final || rev < prev.rev)) return state;
  const next = new Map(state);
  if (ev.state === "final" && !ev.text) {
    next.delete(key); // tombstone：撤掉幻覺假設
    return next;
  }
  next.set(key, {
    speaker: ev.speaker_id,
    segmentId: ev.segment_id,
    lang: ev.lang,
    text: ev.text,
    final: ev.state === "final",
    rev,
    tEndMs: ev.t_end_ms,
    trace: ev.trace ?? [],
    receivedAt: Date.now(),
  });
  return next;
}

/** 訂閱 client 的 segment 事件，回傳指定語言、按講者分組的字幕。 */
export function useCaptions(client: SpeakInClient | null, lang: string): SpeakerCaptions[] {
  const [state, dispatch] = useReducer(applySegment, new Map() as State);

  useEffect(() => {
    if (!client) return;
    return client.onSegment((ev) => {
      if (ev.lang === lang) dispatch(ev);
    });
  }, [client, lang]);

  return useMemo(() => {
    const bySpeaker = new Map<string, SpeakerCaptions>();
    const segs = [...state.values()]
      .filter((s) => s.lang === lang)
      .sort((a, b) => a.segmentId.localeCompare(b.segmentId));
    for (const s of segs) {
      let g = bySpeaker.get(s.speaker);
      if (!g) {
        g = { speaker: s.speaker, finals: [], partial: null };
        bySpeaker.set(s.speaker, g);
      }
      if (s.final) g.finals.push(s);
      else g.partial = s; // segmentId 已排序，最後一個 partial 即當前句
    }
    return [...bySpeaker.values()].sort((a, b) => a.speaker.localeCompare(b.speaker));
  }, [state, lang]);
}

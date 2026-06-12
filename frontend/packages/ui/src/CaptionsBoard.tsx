/** 字幕牆：一講者一欄，final 實色、partial 半透明（滾動修正）。 */

import type { SpeakerCaptions } from "./captions";
import { useEffect, useRef } from "react";

export function CaptionsBoard({ speakers, selfId }: {
  speakers: SpeakerCaptions[];
  /** 自己的 speaker_id，標示「（你）」 */
  selfId?: string;
}) {
  if (!speakers.length) {
    return <div className="captions-empty">等待講者開口…</div>;
  }
  return (
    <div className="captions-board">
      {speakers.map((s) => (
        <SpeakerColumn key={s.speaker} data={s} self={s.speaker === selfId} />
      ))}
    </div>
  );
}

function SpeakerColumn({ data, self }: { data: SpeakerCaptions; self: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [data.finals.length, data.partial?.text]);

  return (
    <section className="speaker-col">
      <h3>
        {data.speaker}
        {self && <span className="self-tag">（你）</span>}
      </h3>
      <div className="speaker-scroll">
        {data.finals.map((f) => (
          <p key={f.segmentId} className="cap-final">{f.text}</p>
        ))}
        {data.partial && (
          <p key={data.partial.segmentId} className="cap-partial">{data.partial.text}</p>
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}

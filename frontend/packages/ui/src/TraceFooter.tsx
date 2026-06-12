/** 延遲儀表（最小版）：顯示最近一句 final 的 stage 延遲鏈。 */

import type { CaptionSegment } from "./captions";

export function TraceFooter({ speakers }: {
  speakers: { finals: CaptionSegment[] }[];
}) {
  const finals = speakers.flatMap((s) => s.finals);
  if (!finals.length) return null;
  const last = finals.reduce((a, b) => (a.receivedAt > b.receivedAt ? a : b));
  const total = last.trace.reduce((sum, t) => sum + (t.ms ?? 0), 0);
  return (
    <footer className="trace-footer">
      {last.trace.map((t) => `${t.stage} ${Math.round(t.ms ?? 0)}ms`).join(" → ")}
      {total > 0 && <strong>（Σ {Math.round(total)}ms）</strong>}
    </footer>
  );
}

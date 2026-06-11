"""翻譯 stage（Phase 2）：訂閱 segment.stt → vLLM(OpenAI 相容 API) → 發布 text.{lang}。

partial 防抖（§5 Phase 2）：同一 segment 的 partial 需間隔 ≥ partial_min_gap_ms
且文字增長 ≥ partial_min_grow_chars 才重翻；final 一律全段重翻。
每段每目標語言只翻一次，與訂閱人數無關（§1.5-5）。
"""

from __future__ import annotations

import asyncio
import time

import httpx

from core.stage import Stage
from schemas.events import SegmentEvent, SegmentState, TraceEntry, text_topic

_LANG_NAMES = {
    "zh": "Traditional Chinese", "en": "English", "ja": "Japanese",
    "ko": "Korean", "fr": "French", "de": "German", "es": "Spanish",
}

_SYSTEM = (
    "You are a professional simultaneous interpreter. "
    "Translate the user's text from {src} into {tgt}. "
    "Output ONLY the translation, with no explanations or quotes."
)


class MtVllm(Stage):
    async def setup(self) -> None:
        c = self.config
        self.api_base: str = c.get("api_base", "http://127.0.0.1:8001/v1")
        self.model: str = c.get("model", "Qwen/Qwen2.5-7B-Instruct-AWQ")
        self.targets: list[str] = list(c["target_langs"])
        self.min_gap = int(c.get("partial_min_gap_ms", 1000)) / 1000
        self.min_grow = int(c.get("partial_min_grow_chars", 6))
        self.max_tokens = int(c.get("max_tokens", 256))
        self._http = httpx.AsyncClient(base_url=self.api_base, timeout=30.0)
        # 防抖狀態：segment_id → (上次翻譯的原文長度, 上次翻譯時間)
        self._seen: dict[str, tuple[int, float]] = {}

    async def _translate(self, text: str, src: str, tgt: str) -> str:
        r = await self._http.post("/chat/completions", json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM.format(
                    src=_LANG_NAMES.get(src, src), tgt=_LANG_NAMES.get(tgt, tgt))},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        })
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def _should_translate(self, ev: SegmentEvent) -> bool:
        if ev.state is SegmentState.FINAL:
            self._seen.pop(ev.segment_id, None)
            return True
        last_len, last_t = self._seen.get(ev.segment_id, (0, 0.0))
        now = time.monotonic()
        if now - last_t < self.min_gap or len(ev.text) - last_len < self.min_grow:
            return False
        self._seen[ev.segment_id] = (len(ev.text), now)
        return True

    async def _on_stt(self, subject: str, ev) -> None:
        if not isinstance(ev, SegmentEvent) or not self._should_translate(ev):
            return
        targets = [t for t in self.targets if t != ev.src_lang]

        async def one(tgt: str) -> None:
            t0 = time.perf_counter()
            try:
                out = await self._translate(ev.text, ev.src_lang, tgt)
            except Exception as e:  # 單語言失敗不拖垮其他語言
                print(f"[mt] {ev.segment_id}→{tgt} 失敗: {e}")
                return
            ms = (time.perf_counter() - t0) * 1000
            mt_ev = ev.model_copy(update={
                "event_type": "segment.mt",
                "lang": tgt,
                "text": out,
                "words": [],
                "conf": None,
                "trace": [*ev.trace, TraceEntry(stage=self.stage_tag, ms=round(ms, 1))],
            })
            await self.bus.publish(text_topic(self.session_id, tgt), mt_ev)

        await asyncio.gather(*(one(t) for t in targets))

    async def run(self) -> None:
        await self.bus.subscribe(f"speakin.{self.session_id}.stt.>", self._on_stt)
        await asyncio.Event().wait()  # 常駐消費

    async def teardown(self) -> None:
        await self._http.aclose()


STAGE_CLASS = MtVllm

"""串流 STT stage（Phase 1）。

策略：音訊按 chunk_ms 餵入滾動緩衝（pace=1.0 模擬即時到達）；
說話中每 partial_interval_ms 重轉寫整段緩衝發 partial（rev 遞增）；
尾端靜音 ≥ silence_ms 視為句末 → 帶詞級時間戳轉寫發 final，緩衝推進、序號 +1。
VAD 先用能量式（乾淨音源夠用），Phase 4 接 LiveKit 後換 Silero。
"""

from __future__ import annotations

import asyncio
import math
import time

import numpy as np

from core.stage import Stage
from schemas.events import SegmentEvent, SegmentState, TraceEntry, Word, stt_topic

SR = 16000
_FRAME = SR // 50  # 20ms
_RMS_THRESH = 0.005


def trailing_silence_ms(buf: np.ndarray) -> float:
    """能量式尾端靜音長度。"""
    n = 0
    for end in range(len(buf), 0, -_FRAME):
        seg = buf[max(0, end - _FRAME) : end]
        if seg.size and float(np.sqrt(np.mean(seg * seg))) > _RMS_THRESH:
            break
        n += 1
    return n * 20.0


class SttWhisperLive(Stage):
    async def setup(self) -> None:
        from faster_whisper import WhisperModel

        c = self.config
        self.speaker: str = c.get("speaker_id", "spk_dev")
        self.lang: str | None = c.get("language")
        self.pace = float(c.get("pace", 1.0))
        self.chunk = SR * int(c.get("chunk_ms", 500)) // 1000
        self.partial_every = int(c.get("partial_interval_ms", 1000)) / 1000
        self.silence_ms = int(c.get("silence_ms", 600))
        self.max_utt = float(c.get("max_utterance_s", 20)) * SR
        self._model = WhisperModel(
            c.get("model", "large-v3-turbo"),
            device=c.get("device", "cuda"),
            compute_type=c.get("compute_type", "int8_float16"),
        )
        # 暖機：cudnn/cublas 首次初始化不能算進首字延遲
        self._transcribe(np.zeros(SR // 2, dtype=np.float32), words=False)

    def _transcribe(self, audio: np.ndarray, words: bool):
        t0 = time.perf_counter()
        segs, info = self._model.transcribe(
            audio,
            language=self.lang,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=words,
            vad_filter=False,
        )
        segs = list(segs)
        return segs, info, (time.perf_counter() - t0) * 1000

    def _event(self, segs, info, buf_off: int, buf_len: int, seq: int, rev: int,
               state: SegmentState, ms: float) -> SegmentEvent | None:
        text = "".join(s.text for s in segs).strip()
        if not text:
            return None
        base_ms = buf_off / SR * 1000
        words: list[Word] = []
        conf = None
        if state is SegmentState.FINAL:
            for s in segs:
                for w in s.words or []:
                    words.append(Word(w=w.word, t0=int(base_ms + w.start * 1000),
                                      t1=int(base_ms + w.end * 1000)))
            lps = [s.avg_logprob for s in segs if s.avg_logprob is not None]
            if lps:
                conf = round(min(1.0, math.exp(sum(lps) / len(lps))), 3)
        lang = self.lang or info.language
        return SegmentEvent(
            event_type="segment.stt",
            session_id=self.session_id,
            speaker_id=self.speaker,
            segment_id=f"{self.speaker}-{seq:06d}",
            rev=rev,
            state=state,
            t_start_ms=int(base_ms),
            t_end_ms=int(base_ms + buf_len / SR * 1000),
            src_lang=lang,
            lang=lang,
            text=text,
            words=words,
            conf=conf,
            trace=[TraceEntry(stage=self.stage_tag, ms=round(ms, 1))],
        )

    async def run(self) -> None:
        from faster_whisper.audio import decode_audio

        audio = decode_audio(self.config["source"], sampling_rate=SR)
        topic = stt_topic(self.session_id, self.speaker)
        buf = np.empty(0, np.float32)
        buf_off = 0          # 緩衝起點在 session 音訊軸上的樣本位置
        seq, rev = 0, 0
        last_partial = 0.0
        last_text = ""

        for i in range(0, len(audio), self.chunk):
            if self.pace > 0:
                await asyncio.sleep(self.chunk / SR * self.pace)
            buf = np.concatenate([buf, audio[i : i + self.chunk]])
            sil = trailing_silence_ms(buf)
            speech_ms = len(buf) / SR * 1000 - sil
            is_last = i + self.chunk >= len(audio)

            if speech_ms < 200 and not is_last:
                # 尚無人聲：緩衝只留最後 1 秒，避免無限增長
                if len(buf) > SR:
                    buf_off += len(buf) - SR
                    buf = buf[-SR:]
                continue

            if sil >= self.silence_ms or len(buf) >= self.max_utt or is_last:
                segs, info, ms = await asyncio.to_thread(self._transcribe, buf, True)
                ev = self._event(segs, info, buf_off, len(buf), seq, rev,
                                 SegmentState.FINAL, ms)
                if ev:
                    await self.bus.publish(topic, ev)
                    seq += 1
                rev, last_text = 0, ""
                buf_off += len(buf)
                buf = np.empty(0, np.float32)
            elif time.monotonic() - last_partial >= self.partial_every:
                segs, info, ms = await asyncio.to_thread(self._transcribe, buf, False)
                ev = self._event(segs, info, buf_off, len(buf), seq, rev,
                                 SegmentState.PARTIAL, ms)
                if ev and ev.text != last_text:
                    await self.bus.publish(topic, ev)
                    rev += 1
                    last_text = ev.text
                last_partial = time.monotonic()


STAGE_CLASS = SttWhisperLive

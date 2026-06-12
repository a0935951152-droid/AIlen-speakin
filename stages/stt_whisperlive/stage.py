"""串流 STT stage（Phase 1 檔案回放；Phase 4 加 LiveKit mic ingress）。

策略：音訊按 chunk_ms 餵入滾動緩衝；說話中每 partial_interval_ms 重轉寫整段
緩衝發 partial（rev 遞增）；尾端靜音 ≥ silence_ms 視為句末 → 帶詞級時間戳轉寫
發 final，緩衝推進、序號 +1。VAD 用能量式偵測句末 + final 時 Silero vad_filter。

音訊來源二擇一（`source` 優先，重播測試 --set stt.source=... 即可切回）：
- source:  音檔實時回放（pace 控速），單講者 = config speaker_id
- livekit: 訂閱 room=session_id 的講者音軌，一軌一講者（speaker_id = 參與者
  identity），跨講者並行轉寫；音軌名 `tts.` 開頭的譯音軌一律跳過（回灌會
  形成 stt→mt→tts→stt 翻譯迴圈）
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import AsyncIterator

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
        # 跨講者轉寫並行上限（ctranslate2 執行緒安全；防多軌同時 final 擠爆 GPU）
        self._gpu = asyncio.Semaphore(int(c.get("gpu_concurrency", 2)))
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
            # final（words=True）啟用 Silero VAD：截掉緩衝尾端靜音，防止 Whisper 對
            # 無語音段產生幻覺文字；partial 為求延遲不開
            vad_filter=words,
        )
        segs = list(segs)
        return segs, info, (time.perf_counter() - t0) * 1000

    async def _transcribe_async(self, audio: np.ndarray, words: bool):
        async with self._gpu:
            return await asyncio.to_thread(self._transcribe, audio, words)

    def _event(self, segs, info, speaker: str, buf_off: int, buf_len: int,
               seq: int, rev: int, state: SegmentState, ms: float) -> SegmentEvent | None:
        text = "".join(s.text for s in segs).strip()
        # 空文字但已發過 partial（多半是 VAD 截掉的幻覺假設）：仍要發空 final tombstone
        # 收尾，否則 segment_id 會被下一句重用且 rev 歸零，下游依「rev 只往前」拒收整句
        if not text and not (state is SegmentState.FINAL and rev > 0):
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
            speaker_id=speaker,
            segment_id=f"{speaker}-{seq:06d}",
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

    async def _stream_stt(self, speaker: str, chunks: AsyncIterator[np.ndarray]) -> None:
        """單一講者的分段轉寫主迴圈；chunks 須以實時節奏到達（回放有 pace 控速）。"""
        topic = stt_topic(self.session_id, speaker)
        buf = np.empty(0, np.float32)
        buf_off = 0          # 緩衝起點在該講者音訊軸上的樣本位置
        seq, rev = 0, 0
        last_partial = 0.0
        last_text = ""

        async def emit_final() -> None:
            nonlocal seq, rev, last_text, buf, buf_off
            segs, info, ms = await self._transcribe_async(buf, True)
            ev = self._event(segs, info, speaker, buf_off, len(buf), seq, rev,
                             SegmentState.FINAL, ms)
            if ev:
                await self.bus.publish(topic, ev)
                seq += 1
            rev, last_text = 0, ""
            buf_off += len(buf)
            buf = np.empty(0, np.float32)

        async for chunk in chunks:
            buf = np.concatenate([buf, chunk])
            sil = trailing_silence_ms(buf)
            speech_ms = len(buf) / SR * 1000 - sil

            if speech_ms < 200:
                # 尚無人聲：緩衝只留最後 1 秒，避免無限增長
                if len(buf) > SR:
                    buf_off += len(buf) - SR
                    buf = buf[-SR:]
                continue

            if sil >= self.silence_ms or len(buf) >= self.max_utt:
                await emit_final()
            elif time.monotonic() - last_partial >= self.partial_every:
                segs, info, ms = await self._transcribe_async(buf, False)
                ev = self._event(segs, info, speaker, buf_off, len(buf), seq, rev,
                                 SegmentState.PARTIAL, ms)
                if ev and ev.text != last_text:
                    await self.bus.publish(topic, ev)
                    rev += 1
                    last_text = ev.text
                last_partial = time.monotonic()

        # 串流結束（檔案放完 / 講者離房）：殘餘語音、或已發過 partial 的段落
        # （tombstone 義務，§1.5-1）都要以 final 收尾
        sil = trailing_silence_ms(buf)
        if (len(buf) / SR * 1000 - sil) >= 200 or rev > 0:
            await emit_final()

    async def _run_replay(self) -> None:
        from faster_whisper.audio import decode_audio

        audio = decode_audio(self.config["source"], sampling_rate=SR)

        async def chunks() -> AsyncIterator[np.ndarray]:
            for i in range(0, len(audio), self.chunk):
                if self.pace > 0:
                    await asyncio.sleep(self.chunk / SR * self.pace)
                yield audio[i : i + self.chunk]

        await self._stream_stt(self.speaker, chunks())

    async def _chunked(self, stream) -> AsyncIterator[np.ndarray]:
        """遠端音框聚成 chunk；斷流超過 2 個 chunk 時補靜音，
        讓講者停止送框（靜音抑制/暫時離線）時句末 final 仍會觸發。"""
        frames = stream.frames(SR).__aiter__()
        pending = np.empty(0, np.float32)
        while True:
            try:
                frame = await asyncio.wait_for(anext(frames),
                                               timeout=self.chunk / SR * 2)
            except StopAsyncIteration:
                if pending.size:
                    yield pending
                return
            except asyncio.TimeoutError:
                yield np.zeros(self.chunk, np.float32)
                continue
            pending = np.concatenate([pending, frame])
            while len(pending) >= self.chunk:
                yield pending[: self.chunk]
                pending = pending[self.chunk:]

    async def _run_livekit(self, lk: dict) -> None:
        from core.rtc import RtcRoom

        room = RtcRoom(url=lk["url"], api_key=lk.get("api_key", "devkey"),
                       api_secret=lk.get("api_secret", "secret"),
                       room=self.session_id, identity="stt-ingress",
                       subscribe_audio=True)
        await room.connect()
        tasks: set[asyncio.Task] = set()
        try:
            async for stream in room.incoming_audio():
                if stream.name.startswith("tts."):
                    continue  # 本系統譯音軌，回灌會形成翻譯迴圈
                # identity 直接作 speaker_id；NATS subject token 不容許 . 等字元
                speaker = re.sub(r"[^\w-]", "-", stream.identity)
                t = asyncio.create_task(self._stream_stt(speaker, self._chunked(stream)))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await room.close()

    async def run(self) -> None:
        if self.config.get("source"):
            await self._run_replay()
        elif self.config.get("livekit"):
            await self._run_livekit(self.config["livekit"])
        else:
            raise ValueError("stt_whisperlive 需設 source（檔案回放）或 livekit（mic ingress）")


STAGE_CLASS = SttWhisperLive

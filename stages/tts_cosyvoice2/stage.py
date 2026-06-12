"""TTS stage（Phase 3）：訂閱 text.{lang} 的 final → CosyVoice2 合成 → 發布 segment.tts。

只消費 final（§1.5-4）；cross-lingual 模式用 prompt 音色合成目標語言，
音色特徵在 setup 抽一次（spk2info 快取），之後每句直接引用。

設定 `livekit:` 時即 Phase 4 完整形態：以虛擬參與者連入 room=session_id，
合成串流逐塊推 `tts.{speaker}.{lang}` 音軌（首塊即開播，體感延遲=首塊延遲），
匯流排上只走 TtsMetaEvent 中繼資料（§1.3）。未設定則退回 Phase 3 行為
（整句落地 out_dir，track_id 為 local:path）；wav 兩種模式都落地供驗證。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from core.stage import Stage
from schemas.events import SegmentEvent, SegmentState, TraceEntry, TtsMetaEvent, text_topic, tts_topic

_SPK_ID = "speakin_prompt"


class TtsCosyVoice2(Stage):
    async def setup(self) -> None:
        c = self.config
        repo = Path(c.get("repo_dir", "~/speakin-data/CosyVoice")).expanduser()
        for p in (str(repo), str(repo / "third_party" / "Matcha-TTS")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from cosyvoice.cli.cosyvoice import CosyVoice2

        self.langs: list[str] | str = c.get("langs", "*")
        self.exclude: set[str] = set(c.get("langs_exclude") or [])
        self.out_dir = Path(c.get("out_dir", "~/speakin-data/tts-out")).expanduser() / self.session_id
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # 併發上限：CosyVoice model.tts 以 uuid+lock 支援多請求並行（官方 server 同款用法），
        # 但無上限併發會把 GPU 擠爆，留 2 路（同段多語言可並行）
        self._gpu = asyncio.Semaphore(2)

        self._rtc = None
        self._tracks: dict[tuple[str, str], object] = {}  # (speaker, lang) → AudioTrackHandle
        lk = c.get("livekit")
        if lk:
            from core.rtc import RtcRoom

            ident = "tts:" + ("+".join(self.langs) if isinstance(self.langs, list) else "*")
            self._rtc = RtcRoom(url=lk["url"], api_key=lk.get("api_key", "devkey"),
                                api_secret=lk.get("api_secret", "secret"),
                                room=self.session_id, identity=ident)
            await self._rtc.connect()

        import opencc

        # CosyVoice2 中文語料以簡體為主，繁體輸入發音會壞掉；合成前 t2s（字幕不受影響）
        self._t2s = opencc.OpenCC("t2s")

        model_dir = str(Path(c.get("model_dir", "~/speakin-data/model-cache/cosyvoice2-0.5b")).expanduser())
        self._cv = CosyVoice2(model_dir, fp16=bool(c.get("fp16", True)))
        self.sr: int = self._cv.sample_rate
        prompt = str(Path(c.get("prompt_wav", "tests/replay/golden/zh_demo.wav")).expanduser())
        self._cv.add_zero_shot_spk("", prompt, _SPK_ID)
        self._synth("你好。")  # 暖機：CUDA/onnxruntime 首次初始化不算進延遲

    def _synth(self, text: str, lang: str = "zh", on_chunk=None):
        """串流合成；回傳 (完整音訊, 首塊音訊就緒的 perf_counter 時刻)。

        聽眾「聽到語音」的時點是首塊就緒，不是整句合成完——on_chunk 在每塊
        就緒時被呼叫（推 LiveKit 音軌），首塊延遲就是體感延遲。
        """
        import torch

        if lang == "zh":
            text = self._t2s.convert(text)
        chunks, t_first = [], None
        for out in self._cv.inference_cross_lingual(
                text, "", zero_shot_spk_id=_SPK_ID, stream=True):
            if t_first is None:
                t_first = time.perf_counter()
            if on_chunk is not None:
                on_chunk(out["tts_speech"])
            chunks.append(out["tts_speech"])
        return torch.cat(chunks, dim=1), t_first

    async def _track(self, speaker_id: str, lang: str):
        """惰性建立並發布 (speaker, lang) 音軌；同 lang 事件序列消費，無競態。"""
        key = (speaker_id, lang)
        if key not in self._tracks:
            from core.rtc import tts_track_name

            self._tracks[key] = await self._rtc.publish_audio_track(
                tts_track_name(speaker_id, lang), self.sr)
        return self._tracks[key]

    async def _on_text(self, subject: str, ev) -> None:
        if not isinstance(ev, SegmentEvent) or ev.event_type != "segment.mt":
            return
        if ev.state is not SegmentState.FINAL:
            return
        if self.langs != "*" and ev.lang not in self.langs:
            return
        if ev.lang in self.exclude:
            return
        if not ev.text:
            return  # 空 final tombstone 只用於字幕收尾，無聲可合成
        import torchaudio

        handle = await self._track(ev.speaker_id, ev.lang) if self._rtc else None
        audio_t0_ms = int(handle.pushed_ms) if handle else 0
        on_chunk = None
        if handle:
            loop = asyncio.get_running_loop()

            def on_chunk(chunk, _h=handle, _loop=loop):  # 合成執行緒 → 事件圈推軌
                fut = asyncio.run_coroutine_threadsafe(
                    _h.push(chunk.squeeze(0).numpy()), _loop)
                fut.result()  # 等推完才合成下一塊，對 GPU 形成自然背壓

        t0 = time.perf_counter()
        async with self._gpu:
            try:
                audio, t_first = await asyncio.to_thread(self._synth, ev.text, ev.lang, on_chunk)
            except Exception as e:  # 單段失敗不拖垮常駐消費
                print(f"[tts] {ev.segment_id}.{ev.lang} 合成失敗: {e}")
                return
        ms = (time.perf_counter() - t0) * 1000
        first_audio_ms = (t_first - t0) * 1000  # 含排隊等待，首塊音訊就緒延遲
        path = self.out_dir / f"{ev.segment_id}.{ev.lang}.wav"
        torchaudio.save(str(path), audio, self.sr)
        await self.bus.publish(
            tts_topic(self.session_id, ev.speaker_id, ev.lang),
            TtsMetaEvent(
                session_id=self.session_id,
                speaker_id=ev.speaker_id,
                segment_id=ev.segment_id,
                lang=ev.lang,
                track_id=handle.sid if handle else f"local:{path}",
                audio_t0_ms=audio_t0_ms,
                duration_ms=int(audio.shape[1] / self.sr * 1000),
                trace=[*ev.trace, TraceEntry(stage=self.stage_tag, ms=round(ms, 1),
                                             first_audio_ms=round(first_audio_ms, 1))],
                meta={"path": str(path), "text": ev.text},
            ),
        )

    async def run(self) -> None:
        if self.langs == "*":
            await self.bus.subscribe(f"speakin.{self.session_id}.text.>", self._on_text)
        else:
            for lang in self.langs:
                await self.bus.subscribe(text_topic(self.session_id, lang), self._on_text)
        await asyncio.Event().wait()  # 常駐消費

    async def teardown(self) -> None:
        if self._rtc:
            await self._rtc.close()


STAGE_CLASS = TtsCosyVoice2

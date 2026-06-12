"""TTS stage（Phase 3）：訂閱 text.{lang} 的 final → CosyVoice2 合成 → 發布 segment.tts。

只消費 final（§1.5-4）；cross-lingual 模式用 prompt 音色合成目標語言，
音色特徵在 setup 抽一次（spk2info 快取），之後每句直接引用。
Phase 3 音訊本體落地 out_dir 供本地驗證；Phase 4 改推 LiveKit 音軌，
匯流排上只走 TtsMetaEvent 中繼資料（§1.3）。
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

        import opencc

        # CosyVoice2 中文語料以簡體為主，繁體輸入發音會壞掉；合成前 t2s（字幕不受影響）
        self._t2s = opencc.OpenCC("t2s")

        model_dir = str(Path(c.get("model_dir", "~/speakin-data/model-cache/cosyvoice2-0.5b")).expanduser())
        self._cv = CosyVoice2(model_dir, fp16=bool(c.get("fp16", True)))
        self.sr: int = self._cv.sample_rate
        prompt = str(Path(c.get("prompt_wav", "tests/replay/golden/zh_demo.wav")).expanduser())
        self._cv.add_zero_shot_spk("", prompt, _SPK_ID)
        self._synth("你好。")  # 暖機：CUDA/onnxruntime 首次初始化不算進延遲

    def _synth(self, text: str, lang: str = "zh"):
        """串流合成；回傳 (完整音訊, 首塊音訊就緒的 perf_counter 時刻)。

        聽眾「聽到語音」的時點是首塊就緒，不是整句合成完——Phase 4 接 LiveKit
        後逐塊推音軌，首塊延遲就是體感延遲。Phase 3 仍整句落地驗證。
        """
        import torch

        if lang == "zh":
            text = self._t2s.convert(text)
        chunks, t_first = [], None
        for out in self._cv.inference_cross_lingual(
                text, "", zero_shot_spk_id=_SPK_ID, stream=True):
            if t_first is None:
                t_first = time.perf_counter()
            chunks.append(out["tts_speech"])
        return torch.cat(chunks, dim=1), t_first

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

        t0 = time.perf_counter()
        async with self._gpu:
            try:
                audio, t_first = await asyncio.to_thread(self._synth, ev.text, ev.lang)
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
                track_id=f"local:{path}",  # Phase 4 換成 LiveKit 音軌 ID
                audio_t0_ms=0,
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


STAGE_CLASS = TtsCosyVoice2

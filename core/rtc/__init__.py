"""LiveKit 封裝：所有 stage / services 只透過這層收發即時音訊。

廠商 SDK（livekit / livekit-api）只准在本模組出現（《結構及技術棧.md》§8.4），
日後換 SFU 實作時 stages / services / frontend 不需改動。
房間即會話：room 名稱一律用 session_id。
"""

from __future__ import annotations

import asyncio

import numpy as np
from livekit import api, rtc


def tts_track_name(speaker_id: str, lang: str) -> str:
    """譯音音軌命名（§2 分發平面：audio track {speaker×lang}），聽端按名選軌。"""
    return f"tts.{speaker_id}.{lang}"


class AudioTrackHandle:
    """單一已發布音軌。push() 逐塊餵 PCM 即時開播；pushed_ms 是軌上時間軸的游標，
    也就是下一段音訊的 audio_t0_ms（TtsMetaEvent §1.3）。"""

    def __init__(self, source: rtc.AudioSource, sid: str, sample_rate: int):
        self._source = source
        self.sid = sid
        self.sample_rate = sample_rate
        self.pushed_ms = 0.0

    async def push(self, pcm: np.ndarray) -> None:
        """pcm: float32 mono [-1, 1]，任意長度（SFU 端自行切 10ms 框）。"""
        i16 = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
        await self._source.capture_frame(rtc.AudioFrame(
            data=i16.tobytes(), sample_rate=self.sample_rate,
            num_channels=1, samples_per_channel=len(i16)))
        self.pushed_ms += len(i16) / self.sample_rate * 1000


class RemoteAudioStream:
    """訂閱到的單一遠端音軌（講者即音軌：identity 即 speaker_id 來源）。"""

    def __init__(self, track: rtc.RemoteTrack, identity: str, name: str):
        self._track = track
        self.identity = identity   # 發布者 participant identity
        self.name = name           # 音軌名；`tts.` 開頭為本系統譯音軌

    async def frames(self, sample_rate: int = 16000):
        """逐框產出 float32 mono [-1,1]（SDK 端重採樣）；軌結束時迭代自然結束。"""
        async for fev in rtc.AudioStream(self._track, sample_rate=sample_rate,
                                         num_channels=1):
            i16 = np.frombuffer(fev.frame.data, dtype=np.int16)
            yield i16.astype(np.float32) / 32768.0


class RtcRoom:
    """以單一參與者身分連入房間；可發布音軌（TTS worker = 虛擬參與者），
    或以 subscribe_audio=True 訂閱房內音軌（STT ingress）。"""

    def __init__(self, url: str, api_key: str, api_secret: str,
                 room: str, identity: str, subscribe_audio: bool = False):
        self._url, self._key, self._secret = url, api_key, api_secret
        self._room_name, self._identity = room, identity
        self._room: rtc.Room | None = None
        self._audio_q: asyncio.Queue[RemoteAudioStream | None] | None = (
            asyncio.Queue() if subscribe_audio else None)

    async def connect(self) -> None:
        token = (api.AccessToken(self._key, self._secret)
                 .with_identity(self._identity)
                 .with_grants(api.VideoGrants(room_join=True, room=self._room_name))
                 .to_jwt())
        self._room = rtc.Room()
        if self._audio_q is not None:
            @self._room.on("track_subscribed")
            def _on_track(track, pub, participant) -> None:
                if track.kind == rtc.TrackKind.KIND_AUDIO:
                    self._audio_q.put_nowait(RemoteAudioStream(
                        track, participant.identity, pub.name))
        await self._room.connect(self._url, token,
                                 options=rtc.RoomOptions(
                                     auto_subscribe=self._audio_q is not None))

    async def incoming_audio(self):
        """房內每有音軌訂上就產出一個 RemoteAudioStream；close() 後結束。"""
        assert self._audio_q is not None, "需以 subscribe_audio=True 建立"
        while True:
            stream = await self._audio_q.get()
            if stream is None:
                return
            yield stream

    async def publish_audio_track(self, name: str, sample_rate: int) -> AudioTrackHandle:
        assert self._room, "RtcRoom 未連線"
        source = rtc.AudioSource(sample_rate, 1)
        track = rtc.LocalAudioTrack.create_audio_track(name, source)
        pub = await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        return AudioTrackHandle(source, pub.sid, sample_rate)

    async def close(self) -> None:
        if self._audio_q is not None:
            self._audio_q.put_nowait(None)
        if self._room:
            await self._room.disconnect()
            self._room = None

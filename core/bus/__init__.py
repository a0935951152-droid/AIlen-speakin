"""NATS 匯流排封裝：所有 stage 與消費端只透過這層收發 schemas.events 事件。

廠商 SDK（nats-py）只准在本模組出現（《結構及技術棧.md》§8.3），
日後換匯流排實作時 stages / services / frontend 不需改動。
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import nats
from pydantic import BaseModel

from schemas.events import ControlEvent, SegmentEvent, TtsMetaEvent

AnyEvent = SegmentEvent | TtsMetaEvent | ControlEvent
EventHandler = Callable[[str, AnyEvent], Awaitable[None]]


def parse_event(data: bytes) -> AnyEvent:
    obj: dict[str, Any] = json.loads(data)
    et: str = obj.get("event_type", "")
    if et == "segment.tts":
        return TtsMetaEvent.model_validate(obj)
    if et.startswith("control."):
        return ControlEvent.model_validate(obj)
    return SegmentEvent.model_validate(obj)


class Bus:
    def __init__(self, url: str = "nats://127.0.0.1:4222"):
        self._url = url
        self._nc: nats.NATS | None = None

    async def connect(self) -> None:
        self._nc = await nats.connect(self._url)

    async def close(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None

    async def publish(self, topic: str, event: BaseModel) -> None:
        assert self._nc, "Bus 未連線"
        await self._nc.publish(topic, event.model_dump_json().encode())

    async def subscribe(self, subject: str, handler: EventHandler):
        """訂閱 subject（可用 NATS 萬用字元 * / >），事件解析後交給 handler。"""
        assert self._nc, "Bus 未連線"

        async def _cb(msg):
            await handler(msg.subject, parse_event(msg.data))

        return await self._nc.subscribe(subject, cb=_cb)

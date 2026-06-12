"""Gateway（Phase 4 最小落地）：前端的唯一後端入口。

- GET /api/token：簽發 LiveKit 入房 token（room=session_id）；secret 不出後端
- WS  /ws/{session_id}：把該 session 的 NATS 事件橋接成 JSON 推送
  （?topics=text,control 過濾 topic 第一段；預設 text,control，字幕夠用）

Phase 5 再加：REST 收外部文字 → 虛擬講者進 TTS 房。
執行：bash deploy/dev/gateway.sh（uvicorn :8800）
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.bus import Bus
from core.rtc import create_access_token

LK_KEY = os.environ.get("SPEAKIN_LIVEKIT_KEY", "devkey")
LK_SECRET = os.environ.get("SPEAKIN_LIVEKIT_SECRET", "secret")
# 回給瀏覽器的 LiveKit 位址；未設則按請求的 host 推導（LAN 裝置直接可用）
LK_PUBLIC_URL = os.environ.get("SPEAKIN_LIVEKIT_URL", "")
NATS_URL = os.environ.get("SPEAKIN_NATS_URL", "nats://127.0.0.1:4222")

app = FastAPI(title="speakin-gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"],  # dev：viewer 在 vite :5173
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/token")
async def token(request: Request, session: str, identity: str) -> dict:
    lk_url = LK_PUBLIC_URL or f"ws://{request.url.hostname}:7880"
    return {
        "token": create_access_token(LK_KEY, LK_SECRET, room=session, identity=identity),
        "livekit_url": lk_url,
        "session": session,
        "identity": identity,
    }


@app.websocket("/ws/{session}")
async def events_ws(ws: WebSocket, session: str,
                    topics: str = Query("text,control")) -> None:
    """事件下行：subject 第一段（stt/text/tts/control）在 topics 內的才推。"""
    await ws.accept()
    wanted = {t.strip() for t in topics.split(",") if t.strip()}
    bus = Bus(NATS_URL)
    await bus.connect()
    closed = False

    async def forward(subject: str, ev) -> None:
        # subject: speakin.{session}.{kind}...
        kind = subject.split(".")[2] if subject.count(".") >= 2 else ""
        if closed or kind not in wanted:
            return
        try:
            await ws.send_text(f'{{"subject":"{subject}","event":{ev.model_dump_json()}}}')
        except Exception:
            pass  # 客端正在斷線；主迴圈會收尾

    sub = await bus.subscribe(f"speakin.{session}.>", forward)
    try:
        while True:  # 收瀏覽器 ping / 等斷線
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        closed = True
        await sub.unsubscribe()
        await bus.close()


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}

/**
 * SpeakIn 前端 SDK：apps 只透過這層連 gateway / LiveKit。
 * 廠商 SDK（livekit-client）只准在本套件出現（《結構及技術棧.md》§8.3）。
 *
 * - 上行：publishMic() 把麥克風發成 LiveKit 音軌（一人一軌，identity 即 speaker_id）
 * - 下行字幕：gateway WS 橋（/ws/{session}）推 segment/control 事件
 * - 下行譯音：訂閱 `tts.{speaker}.{lang}` 音軌，onTtsTrack 通知 UI 選軌播放
 */

import {
  createLocalAudioTrack,
  LocalAudioTrack,
  RemoteTrack,
  Room,
  RoomEvent,
} from "livekit-client";
import type { ControlEvent, SegmentEvent, TtsMetaEvent } from "./events.gen";

export type AnyEvent = SegmentEvent | TtsMetaEvent | ControlEvent;
export interface BusMessage {
  subject: string;
  event: AnyEvent;
}

/** 一條已訂上的譯音軌；attach 回傳可直接掛進 DOM 的 <audio>。 */
export interface TtsTrack {
  speaker: string;
  lang: string;
  name: string;
  sid: string;
  attach(): HTMLMediaElement;
  detach(): void;
}

export interface ConnectOptions {
  /** gateway HTTP 位址，如 http://192.168.x.x:8800；同源代理時傳 location.origin */
  gateway: string;
  session: string;
  identity: string;
  /** WS 橋要的 topic 類別，預設 stt,text,control（字幕含原文） */
  topics?: string[];
  /** 覆寫 LiveKit 信令位址（如同源代理 wss://host/lk）；未設用 gateway 回的 */
  livekitUrl?: string;
}

type SegmentHandler = (ev: SegmentEvent, subject: string) => void;
type ControlHandler = (ev: ControlEvent) => void;
type TtsTrackHandler = (track: TtsTrack, active: boolean) => void;

export class SpeakInClient {
  private room: Room | null = null;
  private ws: WebSocket | null = null;
  private mic: LocalAudioTrack | null = null;
  private opts: ConnectOptions | null = null;
  private segmentHandlers = new Set<SegmentHandler>();
  private controlHandlers = new Set<ControlHandler>();
  private ttsHandlers = new Set<TtsTrackHandler>();
  private tracks = new Map<string, TtsTrack>();
  private closed = false;

  get identity(): string {
    return this.opts?.identity ?? "";
  }

  /** 目前房內所有譯音軌（onTtsTrack 之外的查詢入口）。 */
  get ttsTracks(): TtsTrack[] {
    return [...this.tracks.values()];
  }

  async connect(opts: ConnectOptions): Promise<void> {
    this.opts = opts;
    this.closed = false;
    const res = await fetch(
      `${opts.gateway}/api/token?session=${encodeURIComponent(opts.session)}` +
        `&identity=${encodeURIComponent(opts.identity)}`,
    );
    if (!res.ok) throw new Error(`gateway token 失敗: ${res.status}`);
    const { token, livekit_url } = (await res.json()) as {
      token: string;
      livekit_url: string;
    };

    this.room = new Room();
    this.room.on(RoomEvent.TrackSubscribed, (track, pub) => {
      if (track.kind !== "audio" || !pub.trackName.startsWith("tts.")) return;
      const [, speaker, lang] = pub.trackName.split(".");
      const t = makeTtsTrack(track, pub.trackName, pub.trackSid, speaker, lang);
      this.tracks.set(pub.trackSid, t);
      this.ttsHandlers.forEach((h) => h(t, true));
    });
    this.room.on(RoomEvent.TrackUnsubscribed, (_track, pub) => {
      const t = this.tracks.get(pub.trackSid);
      if (!t) return;
      this.tracks.delete(pub.trackSid);
      this.ttsHandlers.forEach((h) => h(t, false));
    });
    await this.room.connect(opts.livekitUrl ?? livekit_url, token);

    this.openEventsWs();
  }

  /** gateway WS 橋；斷線自動重連（2s 退避）。 */
  private openEventsWs(): void {
    if (!this.opts || this.closed) return;
    const { gateway, session, topics } = this.opts;
    const wsBase = gateway.replace(/^http/, "ws");
    const q = (topics ?? ["stt", "text", "control"]).join(",");
    const ws = new WebSocket(`${wsBase}/ws/${encodeURIComponent(session)}?topics=${q}`);
    ws.onmessage = (m) => {
      const { subject, event } = JSON.parse(m.data as string) as BusMessage;
      const et = (event as { event_type: string }).event_type;
      if (et.startsWith("control.")) {
        this.controlHandlers.forEach((h) => h(event as ControlEvent));
      } else if (et === "segment.stt" || et === "segment.mt") {
        this.segmentHandlers.forEach((h) => h(event as SegmentEvent, subject));
      }
    };
    ws.onclose = () => {
      this.ws = null;
      if (!this.closed) setTimeout(() => this.openEventsWs(), 2000);
    };
    this.ws = ws;
  }

  /** 發布麥克風（回音消除/降噪開），回傳實際生效與否。 */
  async publishMic(): Promise<boolean> {
    if (!this.room) return false;
    if (this.mic) return true;
    this.mic = await createLocalAudioTrack({
      echoCancellation: true,
      noiseSuppression: true,
    });
    await this.room.localParticipant.publishTrack(this.mic, { name: "mic" });
    return true;
  }

  async unpublishMic(): Promise<void> {
    if (!this.room || !this.mic) return;
    await this.room.localParticipant.unpublishTrack(this.mic);
    this.mic.stop();
    this.mic = null;
  }

  get micOn(): boolean {
    return this.mic !== null;
  }

  onSegment(h: SegmentHandler): () => void {
    this.segmentHandlers.add(h);
    return () => this.segmentHandlers.delete(h);
  }

  onControl(h: ControlHandler): () => void {
    this.controlHandlers.add(h);
    return () => this.controlHandlers.delete(h);
  }

  /** 譯音軌增減通知（active=false 表示軌已移除）；註冊時補發既有軌。 */
  onTtsTrack(h: TtsTrackHandler): () => void {
    this.ttsHandlers.add(h);
    this.tracks.forEach((t) => h(t, true));
    return () => this.ttsHandlers.delete(h);
  }

  async disconnect(): Promise<void> {
    this.closed = true;
    this.ws?.close();
    this.ws = null;
    await this.unpublishMic();
    await this.room?.disconnect();
    this.room = null;
    this.tracks.clear();
  }
}

function makeTtsTrack(
  track: RemoteTrack,
  name: string,
  sid: string,
  speaker: string,
  lang: string,
): TtsTrack {
  return {
    speaker,
    lang,
    name,
    sid,
    attach: () => track.attach() as HTMLMediaElement,
    detach: () => {
      track.detach().forEach((el) => el.remove());
    },
  };
}

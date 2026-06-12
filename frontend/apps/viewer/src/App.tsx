/**
 * Viewer（Phase 4 閉環主力）：發布麥克風、選語言、字幕牆、譯音播放、延遲儀表。
 * 一人一軌：identity 即 speaker_id（gateway/STT ingress 端會做字元消毒）。
 */

import { SpeakInClient } from "@speakin/sdk";
import { CaptionsBoard, LanguagePicker, TraceFooter, useCaptions } from "@speakin/ui";
import { useEffect, useMemo, useRef, useState } from "react";

const LANGS = ["zh", "en", "ja"]; // 與 pipelines/default.yaml target_langs 對齊

/** 與 stt ingress 相同的 speaker_id 消毒規則（NATS subject token 限制） */
const sanitize = (s: string) => s.replace(/[^\w-]/g, "-");

export default function App() {
  const [client, setClient] = useState<SpeakInClient | null>(null);
  const [error, setError] = useState("");
  const [lang, setLang] = useState(LANGS[0]);
  const [micOn, setMicOn] = useState(false);
  const [listen, setListen] = useState(true);

  // 預設同源（vite 代理 /api、/ws、/lk）；直連 gateway 時自行改成 http://host:8800
  const [gateway, setGateway] = useState(location.origin);
  const [session, setSession] = useState("ses_dev");
  const [identity, setIdentity] = useState(`spk_${Math.random().toString(36).slice(2, 6)}`);

  const join = async () => {
    setError("");
    const c = new SpeakInClient();
    try {
      // gateway 同源時 LiveKit 信令也走同源代理 /lk；媒體流仍是 WebRTC 直連
      const livekitUrl = gateway === location.origin
        ? `${location.origin.replace(/^http/, "ws")}/lk`
        : undefined;
      await c.connect({ gateway, session, identity, livekitUrl });
      setClient(c);
    } catch (e) {
      setError(String(e));
    }
  };

  const leave = async () => {
    await client?.disconnect();
    setClient(null);
    setMicOn(false);
  };

  const toggleMic = async () => {
    if (!client) return;
    if (client.micOn) {
      await client.unpublishMic();
      setMicOn(false);
    } else {
      try {
        await client.publishMic();
        setMicOn(true);
      } catch (e) {
        setError(`麥克風失敗: ${e}`);
      }
    }
  };

  if (!client) {
    return (
      <main className="join">
        <h1>SpeakIn Viewer</h1>
        <label>Gateway <input value={gateway} onChange={(e) => setGateway(e.target.value)} /></label>
        <label>Session <input value={session} onChange={(e) => setSession(e.target.value)} /></label>
        <label>你的名字 <input value={identity} onChange={(e) => setIdentity(e.target.value)} /></label>
        <label>語言 <LanguagePicker langs={LANGS} value={lang} onChange={setLang} /></label>
        <button onClick={join}>加入</button>
        {error && <p className="error">{error}</p>}
      </main>
    );
  }

  return (
    <main className="room">
      <header className="bar">
        <strong>{session}</strong>
        <span>{identity}</span>
        <LanguagePicker langs={LANGS} value={lang} onChange={setLang} />
        <button className={micOn ? "mic on" : "mic"} onClick={toggleMic}>
          {micOn ? "🎙 麥克風開" : "🎙 麥克風關"}
        </button>
        <label className="listen">
          <input type="checkbox" checked={listen} onChange={(e) => setListen(e.target.checked)} />
          聽譯音
        </label>
        <button onClick={leave}>離開</button>
        {error && <span className="error">{error}</span>}
      </header>
      <Captions client={client} lang={lang} selfId={sanitize(identity)} />
      {listen && <TtsAudio client={client} lang={lang} selfId={sanitize(identity)} />}
    </main>
  );
}

function Captions({ client, lang, selfId }: {
  client: SpeakInClient; lang: string; selfId: string;
}) {
  const speakers = useCaptions(client, lang);
  return (
    <>
      <CaptionsBoard speakers={speakers} selfId={selfId} />
      <TraceFooter speakers={speakers} />
    </>
  );
}

/** 譯音播放：掛上所選語言、且非自己的 tts 軌。
 * floor control（耳機單軌跟隨 active speaker）是下一個 P0 項，目前全播。 */
function TtsAudio({ client, lang, selfId }: {
  client: SpeakInClient; lang: string; selfId: string;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [, bump] = useState(0);

  useEffect(() => client.onTtsTrack(() => bump((n) => n + 1)), [client]);

  const active = useMemo(
    () => client.ttsTracks.filter((t) => t.lang === lang && t.speaker !== selfId),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client.ttsTracks.length, lang, selfId],
  );

  useEffect(() => {
    const els = active.map((t) => {
      const el = t.attach();
      holder.current?.appendChild(el);
      return { t, el };
    });
    return () => els.forEach(({ t }) => t.detach());
  }, [active]);

  return (
    <div className="tts-audio" ref={holder}>
      <small>譯音軌 ×{active.length}</small>
    </div>
  );
}

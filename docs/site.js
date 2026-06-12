const nodes = {
  overview: {
    zh: {
      title: "總覽",
      role: "整體架構",
      upstream: "講者音訊、外部文字輸入、訂閱端控制訊號。",
      downstream: "字幕、譯音、逐字稿、投影幕、VR overlay、外部 webhook。",
      principle: "音訊本體與語意事件分離：LiveKit 負責即時媒體，NATS / JetStream 負責語意狀態。所有 stage 只依賴事件 schema。",
      status: "Phase 4 已完成 TTS 發軌；下一步是 LiveKit mic ingress、viewer 完整閉環與 control plane。"
    },
    en: {
      title: "Overview",
      role: "System architecture",
      upstream: "Speaker audio, external text input, and subscriber control signals.",
      downstream: "Captions, translated audio, transcripts, stage display, VR overlay, and external webhooks.",
      principle: "Media and semantic state are separated: LiveKit handles real-time audio, while NATS / JetStream handles event state. Stages depend only on the event schema.",
      status: "Phase 4 has TTS track publishing. Next: LiveKit microphone ingress, viewer loop, and control plane."
    }
  },
  "speaker-devices": {
    zh: {
      title: "Speaker Devices",
      role: "講者端裝置，負責擷取麥克風並加入 LiveKit room。",
      upstream: "真實講者、瀏覽器麥克風、手機或專用收音設備。",
      downstream: "LiveKit Room 的一人一軌 WebRTC 音訊。",
      principle: "每位講者對應穩定 participant identity 與 speaker_id，避免後續字幕、譯音和 trace 無法對齊。",
      status: "Phase 4 待做：viewer 發布麥克風。"
    },
    en: {
      title: "Speaker Devices",
      role: "Capture microphone audio and join the LiveKit room.",
      upstream: "Real speakers, browser microphones, phones, or dedicated microphones.",
      downstream: "One WebRTC audio track per speaker in LiveKit.",
      principle: "Each speaker should map to a stable participant identity and speaker_id so captions, audio, and traces stay aligned.",
      status: "Phase 4 pending: viewer microphone publishing."
    }
  },
  "livekit-room": {
    zh: {
      title: "LiveKit Room",
      role: "即時媒體交換機，承載講者原音與 TTS 譯音音軌。",
      upstream: "Speaker Devices 的 WebRTC 音軌、TTS Worker 的虛擬參與者音軌。",
      downstream: "RTC Ingress、Viewer、Audience App、VR Overlay。",
      principle: "LiveKit 只處理低延遲音訊傳輸與扇出，不承擔語意狀態。語意狀態由 event bus 管理。",
      status: "已自建 dev LiveKit；TTS 發軌已完成。"
    },
    en: {
      title: "LiveKit Room",
      role: "Real-time media switch for original speaker audio and translated TTS tracks.",
      upstream: "WebRTC tracks from speaker devices and virtual participant tracks from TTS workers.",
      downstream: "RTC ingress, viewer, audience app, and VR overlay.",
      principle: "LiveKit handles low-latency audio transport and fan-out only; semantic state lives in the event bus.",
      status: "Self-hosted dev LiveKit exists; TTS publishing is implemented."
    }
  },
  "rtc-ingress": {
    zh: {
      title: "RTC Ingress",
      role: "把 LiveKit 音軌轉成 STT worker 可消費的 PCM frame。",
      upstream: "LiveKit Room 中的講者音軌。",
      downstream: "VAD 與 STT Worker。",
      principle: "這層隔離 LiveKit SDK，讓 STT stage 不直接依賴 WebRTC 細節。也可在此做音訊格式、採樣率與緩衝控制。",
      status: "Phase 4 關鍵待辦：補上真實 mic → STT 路徑。"
    },
    en: {
      title: "RTC Ingress",
      role: "Convert LiveKit audio tracks into PCM frames consumable by STT workers.",
      upstream: "Speaker tracks in the LiveKit room.",
      downstream: "VAD and STT worker.",
      principle: "This layer isolates the LiveKit SDK from STT stages and owns audio format, sample rate, and buffering concerns.",
      status: "Critical Phase 4 task: implement real microphone-to-STT ingress."
    }
  },
  vad: {
    zh: {
      title: "VAD",
      role: "語音活動偵測，決定哪些音訊片段送進 STT。",
      upstream: "RTC Ingress 或音檔 replay 的 PCM frame。",
      downstream: "STT Worker。",
      principle: "靜音不推論可降低成本，也能減少結尾靜音造成的 STT 幻覺文字。VAD 也定義 segment 邊界。",
      status: "音檔 replay 已使用 VAD；LiveKit ingress 後需套用同樣策略。"
    },
    en: {
      title: "VAD",
      role: "Voice activity detection before STT.",
      upstream: "PCM frames from RTC ingress or replay files.",
      downstream: "STT worker.",
      principle: "Skipping silence reduces cost and prevents trailing-silence hallucinations. VAD also helps define segment boundaries.",
      status: "Used in replay; should be applied to LiveKit ingress as well."
    }
  },
  "stt-worker": {
    zh: {
      title: "STT Worker",
      role: "把講者原音轉成 `segment.stt` partial/final 事件。",
      upstream: "VAD 後的語音片段。",
      downstream: "`speakin.{session}.stt.{speaker}` topic，後續由 MT 或插件消費。",
      principle: "partial 可回改，final 不可變。segment_id 由此產生並貫穿 MT/TTS，這是跨模態對齊的根。",
      status: "音檔 replay 已完成；LiveKit 即時 ingress 待接。"
    },
    en: {
      title: "STT Worker",
      role: "Convert speaker audio into `segment.stt` partial and final events.",
      upstream: "Speech chunks after VAD.",
      downstream: "`speakin.{session}.stt.{speaker}` topic consumed by MT or plugins.",
      principle: "Partials can be revised, finals are immutable. segment_id is created here and preserved through MT and TTS.",
      status: "Replay path is working; LiveKit real-time ingress is pending."
    }
  },
  "sa-asr": {
    zh: {
      title: "SA-ASR",
      role: "共用麥克風場景的 speaker-attributed ASR。",
      upstream: "多人混在同一支麥克風的音訊。",
      downstream: "帶 speaker attribution 的 `segment.stt`。",
      principle: "一人一軌是主路徑；共用麥是例外，需要模型同時做分離、辨識與講者歸屬。",
      status: "Phase 6+。"
    },
    en: {
      title: "SA-ASR",
      role: "Speaker-attributed ASR for shared microphone scenarios.",
      upstream: "Mixed audio from multiple speakers on one microphone.",
      downstream: "`segment.stt` with speaker attribution.",
      principle: "One-track-per-speaker is the main path; shared microphones require separation, recognition, and attribution.",
      status: "Phase 6+."
    }
  },
  "event-bus": {
    zh: {
      title: "NATS / JetStream Event Bus",
      role: "全系統唯一語意事件匯流排。",
      upstream: "STT、MT、TTS、Session Manager、Gateway、插件 stage。",
      downstream: "所有 stage、viewer、audience app、gateway、observability。",
      principle: "所有元件透過 schema v1.0 溝通。partial 可 best-effort；final、control、tts meta 建議 durable。",
      status: "目前 bus wrapper 是普通 NATS；JetStream durable 是 P1 補強項。"
    },
    en: {
      title: "NATS / JetStream Event Bus",
      role: "The single semantic event bus for the system.",
      upstream: "STT, MT, TTS, session manager, gateway, and plugin stages.",
      downstream: "All stages, viewer, audience app, gateway, and observability.",
      principle: "Components communicate through schema v1.0. Partials may be best-effort; finals, control, and TTS metadata should be durable.",
      status: "The current wrapper uses plain NATS; JetStream durable streams are a P1 hardening task."
    }
  },
  "stt-topic": {
    zh: {
      title: "STT Topic",
      role: "`speakin.{session}.stt.{speaker}` 承載原文 STT 事件。",
      upstream: "STT Worker。",
      downstream: "MT Worker、glossary plugin、shadow eval、viewer debug。",
      principle: "以 speaker 維度分 topic，方便 per-speaker 保序與跨 speaker 並行。",
      status: "已使用。"
    },
    en: {
      title: "STT Topic",
      role: "`speakin.{session}.stt.{speaker}` carries source-language STT events.",
      upstream: "STT worker.",
      downstream: "MT worker, glossary plugin, shadow eval, and viewer debug tools.",
      principle: "Speaker-scoped topics make per-speaker ordering and cross-speaker concurrency natural.",
      status: "Implemented."
    }
  },
  "text-control-topics": {
    zh: {
      title: "Text / Control Topics",
      role: "`text.{lang}` 承載翻譯文字；`control` 承載 presence、floor、subs。",
      upstream: "MT Worker、Session Manager。",
      downstream: "TTS Worker、字幕端、講稿端、耳機選軌策略。",
      principle: "文字與控制分流，避免 UI 狀態污染 segment schema。TTS 惰性啟動依賴 control.subs。",
      status: "text topic 已用；control plane 待落地。"
    },
    en: {
      title: "Text / Control Topics",
      role: "`text.{lang}` carries translated text; `control` carries presence, floor, and subscription state.",
      upstream: "MT worker and session manager.",
      downstream: "TTS worker, caption clients, transcript clients, and headset track selection.",
      principle: "Text and control are separate so UI state does not pollute segment schema. Lazy TTS depends on control.subs.",
      status: "Text topics are used; control plane is pending."
    }
  },
  "mt-worker": {
    zh: {
      title: "MT Worker",
      role: "把 `segment.stt` 翻成各目標語言的 `segment.mt`。",
      upstream: "STT topic 或 glossary stage 輸出。",
      downstream: "`text.{lang}` topic、TTS Worker、字幕端。",
      principle: "每個 segment × 目標語言只翻一次。partial 做防抖，final 一律完整翻譯，語言護欄避免照抄原文。",
      status: "Phase 2 已完成；多講者併發派工待補。"
    },
    en: {
      title: "MT Worker",
      role: "Translate `segment.stt` into `segment.mt` events for target languages.",
      upstream: "STT topics or glossary stage output.",
      downstream: "`text.{lang}` topics, TTS worker, and caption clients.",
      principle: "Each segment × target language is translated once. Partials are debounced; finals are always translated with language guards.",
      status: "Phase 2 implemented; multi-speaker dispatch concurrency is pending."
    }
  },
  "glossary-stage": {
    zh: {
      title: "Glossary Stage",
      role: "領域術語校正或敏感詞處理的插件 stage。",
      upstream: "STT Worker 或其他前置 stage。",
      downstream: "MT Worker。",
      principle: "插件只讀寫事件，不改 core。runner 需實作 `after:` topic 改寫，才能真正只靠 YAML 插入。",
      status: "Phase 5 插拔實證。"
    },
    en: {
      title: "Glossary Stage",
      role: "Plugin stage for terminology correction or content filtering.",
      upstream: "STT worker or earlier stages.",
      downstream: "MT worker.",
      principle: "Plugins read and write events without changing core code. The runner must implement `after:` topic rewriting for true YAML-only insertion.",
      status: "Phase 5 plug-in validation."
    }
  },
  "tts-worker": {
    zh: {
      title: "TTS Worker",
      role: "把 final 翻譯文字合成語音，並以虛擬參與者發布 LiveKit 音軌。",
      upstream: "`text.{lang}` final event、control.subs。",
      downstream: "LiveKit TTS audio track、`segment.tts` metadata event。",
      principle: "TTS 只消費 final，避免 partial 回改導致音訊不可撤回。音訊本體走 LiveKit，event bus 只發 metadata。",
      status: "CosyVoice2 串流合成與 LiveKit 發軌已完成；惰性啟動待補。"
    },
    en: {
      title: "TTS Worker",
      role: "Synthesize final translated text and publish translated audio as a LiveKit virtual participant.",
      upstream: "`text.{lang}` final events and control.subs.",
      downstream: "LiveKit TTS audio tracks and `segment.tts` metadata events.",
      principle: "TTS consumes finals only because audio cannot be revised like text. Media goes through LiveKit; the bus carries metadata.",
      status: "CosyVoice2 streaming and LiveKit publishing are implemented; lazy activation is pending."
    }
  },
  "route-table": {
    zh: {
      title: "Route Table",
      role: "依 lang 或其他欄位把事件路由到不同 stage 實作。",
      upstream: "runner pipeline YAML。",
      downstream: "CosyVoice2、Kokoro、MMS 或其他 MT/TTS engine。",
      principle: "語言數是設定，不是結構。擴語言應改 route table，不應改 core framework。",
      status: "TTS route_by 已實作；runner 拓撲接線仍待補強。"
    },
    en: {
      title: "Route Table",
      role: "Route events to different stage implementations by lang or other fields.",
      upstream: "Runner pipeline YAML.",
      downstream: "CosyVoice2, Kokoro, MMS, or other MT/TTS engines.",
      principle: "Language count is configuration, not architecture. Adding languages should update routing, not core code.",
      status: "TTS route_by exists; runner topology wiring still needs hardening."
    }
  },
  "shadow-eval": {
    zh: {
      title: "Shadow Eval",
      role: "新模型或新 stage 上線前的旁路比對。",
      upstream: "主線事件的 tap。",
      downstream: "離線評測、BLEU/WER/延遲報告、canary 決策。",
      principle: "旁路訂閱不影響主線輸出，用真實流量評估品質與延遲，降低替換模型風險。",
      status: "文件設計完成，尚未實作。"
    },
    en: {
      title: "Shadow Eval",
      role: "Side-path evaluation before deploying a new model or stage.",
      upstream: "Taps from production events.",
      downstream: "Offline metrics, BLEU/WER/latency reports, and canary decisions.",
      principle: "Shadow stages do not affect primary output and evaluate new versions on real traffic.",
      status: "Designed in the document; not implemented yet."
    }
  },
  runner: {
    zh: {
      title: "Runner",
      role: "讀 pipeline YAML，載入 stage，建立管線拓撲。",
      upstream: "`pipelines/*.yaml`、stage manifest、CLI overrides。",
      downstream: "執行中的 stage instances。",
      principle: "runner 應負責拓撲，不讓 stage hardcode 全域 topic。這是插拔架構能否成立的關鍵。",
      status: "目前可載入 stage 與 route_by；`after:`/`taps:` 接線待實作。"
    },
    en: {
      title: "Runner",
      role: "Read pipeline YAML, load stages, and construct the topology.",
      upstream: "`pipelines/*.yaml`, stage manifests, and CLI overrides.",
      downstream: "Running stage instances.",
      principle: "The runner should own topology so stages do not hardcode global topics. This is required for real plugability.",
      status: "Stage loading and route_by exist; `after:` and `taps:` wiring are pending."
    }
  },
  viewer: {
    zh: {
      title: "Viewer",
      role: "開發主力 UI：發布麥克風、顯示字幕、播放譯音、展示 trace。",
      upstream: "使用者操作、麥克風、event bus、LiveKit TTS tracks。",
      downstream: "LiveKit speaker track、語言訂閱控制、debug/trace 視圖。",
      principle: "viewer 不碰模型，只透過 LiveKit 與 event bus 互動。字幕 key 使用 `(speaker_id, segment_id, lang)` upsert。",
      status: "Phase 4 待做：完整 browser loop。"
    },
    en: {
      title: "Viewer",
      role: "Primary development UI for microphone publishing, captions, translated audio, and trace display.",
      upstream: "User actions, microphone input, event bus, and LiveKit TTS tracks.",
      downstream: "LiveKit speaker track, language subscription control, and debug/trace views.",
      principle: "The viewer never talks to models directly. Caption state is upserted by `(speaker_id, segment_id, lang)`.",
      status: "Phase 4 pending: complete browser loop."
    }
  },
  "audience-app": {
    zh: {
      title: "Audience App",
      role: "聽眾端 PWA，負責選語言、聽譯音、看講稿。",
      upstream: "event bus、LiveKit TTS tracks、使用者語言選擇。",
      downstream: "control.subs、耳機播放、講稿視圖。",
      principle: "語言訂閱狀態會回饋給 session_manager，進一步控制 TTS 是否惰性啟動。",
      status: "Phase 5。"
    },
    en: {
      title: "Audience App",
      role: "Audience PWA for language selection, translated audio, and transcripts.",
      upstream: "Event bus, LiveKit TTS tracks, and user language selection.",
      downstream: "control.subs, headset playback, and transcript views.",
      principle: "Language subscription state feeds back to the session manager, which controls lazy TTS activation.",
      status: "Phase 5."
    }
  },
  "stage-display": {
    zh: {
      title: "Stage Display",
      role: "投影幕或大屏字幕端。",
      upstream: "`text.{lang}` partial/final。",
      downstream: "現場大屏顯示。",
      principle: "只消費文字事件，不訂閱 TTS 音軌。可使用 partial 提升即時性，再由 final 固化。",
      status: "Phase 5。"
    },
    en: {
      title: "Stage Display",
      role: "Projection or large-screen caption display.",
      upstream: "`text.{lang}` partial/final events.",
      downstream: "On-stage display.",
      principle: "Consumes text only, not TTS tracks. Partials provide immediacy; finals stabilize the transcript.",
      status: "Phase 5."
    }
  },
  "vr-overlay": {
    zh: {
      title: "VR Overlay",
      role: "VR / WebXR 字幕與可能的空間音訊端。",
      upstream: "LiveKit 音軌、`text.{lang}`、control.floor。",
      downstream: "VR 視野中的字幕 overlay。",
      principle: "VR 端對延遲和遮擋更敏感，應只消費已整理好的事件，不放模型邏輯。",
      status: "Phase 6+。"
    },
    en: {
      title: "VR Overlay",
      role: "VR / WebXR captions and possible spatial audio client.",
      upstream: "LiveKit tracks, `text.{lang}`, and control.floor.",
      downstream: "Caption overlay in the VR view.",
      principle: "VR is sensitive to latency and occlusion, so it should consume prepared events only and avoid model logic.",
      status: "Phase 6+."
    }
  },
  gateway: {
    zh: {
      title: "Gateway",
      role: "外部 REST/WS/Webhook 入口與房間 token 服務。",
      upstream: "外部應用、前端 token 請求、event bus。",
      downstream: "WS 逐字稿、REST 外部文字進 TTS、LiveKit token。",
      principle: "Gateway 是外部系統邊界，負責認證、權限、協議轉換，不把外部 API 直接接進 stage。",
      status: "Phase 5。"
    },
    en: {
      title: "Gateway",
      role: "External REST/WS/Webhook entry point and room-token service.",
      upstream: "External apps, frontend token requests, and the event bus.",
      downstream: "Transcript WebSocket, external text-to-TTS path, and LiveKit tokens.",
      principle: "The gateway is the system boundary for auth, permissions, and protocol translation. External APIs should not call stages directly.",
      status: "Phase 5."
    }
  },
  "session-manager": {
    zh: {
      title: "Session Manager",
      role: "場次生命週期、presence、floor control、訂閱統計。",
      upstream: "LiveKit participant 狀態、viewer/audience 選語言、active speaker 偵測。",
      downstream: "`control.floor`、`control.presence`、`control.subs`。",
      principle: "耳機通常只跟隨一位 floor speaker；字幕可以多人並行。TTS 惰性啟動依賴 lang_subscribers。",
      status: "P1 最小落地項。"
    },
    en: {
      title: "Session Manager",
      role: "Session lifecycle, presence, floor control, and subscription statistics.",
      upstream: "LiveKit participant state, viewer/audience language choices, and active speaker detection.",
      downstream: "`control.floor`, `control.presence`, and `control.subs`.",
      principle: "Headsets usually follow a single floor speaker, while captions can show multiple speakers. Lazy TTS depends on lang_subscribers.",
      status: "P1 minimum implementation task."
    }
  },
  observability: {
    zh: {
      title: "Observability",
      role: "Prometheus / Grafana / Loki 與事件 trace 彙整。",
      upstream: "各 stage trace、runner health、LiveKit/NATS 指標。",
      downstream: "延遲儀表、SLO 告警、回放迴歸報告。",
      principle: "trace 附在事件上，能把一段話的 STT、MT、TTS 延遲串起來，定位首字與首音長尾來源。",
      status: "文件設計完成；Phase 4 退出條件要求可見。"
    },
    en: {
      title: "Observability",
      role: "Prometheus / Grafana / Loki plus event trace aggregation.",
      upstream: "Stage traces, runner health, and LiveKit/NATS metrics.",
      downstream: "Latency dashboard, SLO alerts, and replay regression reports.",
      principle: "Trace travels with events, allowing STT, MT, and TTS latency to be connected for each segment.",
      status: "Designed; Phase 4 exit criteria require visibility."
    }
  }
};

const detail = document.querySelector("[data-detail]");
const langButtons = [...document.querySelectorAll("[data-lang]")];
const nodeButtons = [...document.querySelectorAll("[data-node-button]")];
const viewport = document.querySelector("[data-diagram-viewport]");
const diagram = document.querySelector("[data-diagram]");

const hotspotCoords = {
  "speaker-devices": [78, 184, 170, 66],
  "livekit-room": [315, 184, 190, 66],
  "rtc-ingress": [572, 184, 168, 66],
  vad: [805, 184, 150, 66],
  "stt-worker": [1020, 184, 210, 66],
  "sa-asr": [1295, 184, 175, 66],
  "event-bus": [500, 374, 600, 100],
  "stt-topic": [94, 390, 238, 82],
  "text-control-topics": [1268, 390, 238, 82],
  "mt-worker": [92, 630, 190, 74],
  "glossary-stage": [332, 630, 190, 74],
  "tts-worker": [572, 630, 210, 74],
  "route-table": [832, 630, 210, 74],
  "shadow-eval": [1092, 630, 190, 74],
  runner: [1332, 630, 170, 74],
  viewer: [82, 868, 184, 64],
  "audience-app": [310, 868, 184, 64],
  "stage-display": [538, 868, 184, 64],
  "vr-overlay": [766, 868, 184, 64],
  gateway: [994, 868, 184, 64],
  "session-manager": [1222, 852, 140, 92],
  observability: [1406, 852, 112, 92]
};

let activeNode = "overview";
let activeLang = "zh";
let scale = 1;
let offsetX = 0;
let offsetY = 0;
let dragging = false;
let moved = false;
let dragStart = { x: 0, y: 0, ox: 0, oy: 0 };

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function renderDetail() {
  const entry = nodes[activeNode][activeLang];
  detail.innerHTML = `
    <h4>${escapeHtml(entry.title)}</h4>
    <dl>
      <dt>${activeLang === "zh" ? "功能" : "Function"}</dt>
      <dd>${escapeHtml(entry.role)}</dd>
      <dt>${activeLang === "zh" ? "上游" : "Upstream"}</dt>
      <dd>${escapeHtml(entry.upstream)}</dd>
      <dt>${activeLang === "zh" ? "下游" : "Downstream"}</dt>
      <dd>${escapeHtml(entry.downstream)}</dd>
      <dt>${activeLang === "zh" ? "原理" : "Principle"}</dt>
      <dd>${escapeHtml(entry.principle)}</dd>
      <dt>${activeLang === "zh" ? "目前狀態" : "Current status"}</dt>
      <dd>${escapeHtml(entry.status)}</dd>
    </dl>
  `;
}

function setActiveNode(next) {
  activeNode = nodes[next] ? next : "overview";
  nodeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.nodeButton === activeNode);
  });
  diagram.querySelectorAll("[data-node]").forEach((node) => {
    node.classList.toggle("active", node.dataset.node === activeNode);
  });
  renderDetail();
}

function setLang(next) {
  activeLang = next;
  langButtons.forEach((button) => button.classList.toggle("active", button.dataset.lang === next));
  renderDetail();
}

function applyTransform() {
  diagram.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
}

function zoomBy(delta) {
  scale = Math.min(2.4, Math.max(0.72, scale + delta));
  applyTransform();
}

function resetView() {
  scale = 1;
  offsetX = 0;
  offsetY = 0;
  applyTransform();
}

function createHotspots() {
  Object.entries(hotspotCoords).forEach(([id, [x, y, width, height]]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nodeHotspot";
    button.dataset.node = id;
    button.setAttribute("aria-label", nodes[id].en.title);
    Object.assign(button.style, {
      left: `${x}px`,
      top: `${y}px`,
      width: `${width}px`,
      height: `${height}px`
    });
    button.addEventListener("click", (event) => {
      if (moved) return;
      event.stopPropagation();
      setActiveNode(id);
    });
    diagram.appendChild(button);
  });
}

nodeButtons.forEach((button) => {
  button.addEventListener("click", () => setActiveNode(button.dataset.nodeButton));
});

langButtons.forEach((button) => {
  button.addEventListener("click", () => setLang(button.dataset.lang));
});

document.querySelector("[data-zoom='in']").addEventListener("click", () => zoomBy(0.16));
document.querySelector("[data-zoom='out']").addEventListener("click", () => zoomBy(-0.16));
document.querySelector("[data-reset]").addEventListener("click", resetView);

viewport.addEventListener("pointerdown", (event) => {
  dragging = true;
  moved = false;
  viewport.setPointerCapture(event.pointerId);
  dragStart = { x: event.clientX, y: event.clientY, ox: offsetX, oy: offsetY };
});

viewport.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const dx = event.clientX - dragStart.x;
  const dy = event.clientY - dragStart.y;
  if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
  offsetX = dragStart.ox + dx;
  offsetY = dragStart.oy + dy;
  applyTransform();
});

viewport.addEventListener("pointerup", () => {
  dragging = false;
  setTimeout(() => {
    moved = false;
  }, 0);
});

viewport.addEventListener("pointercancel", () => {
  dragging = false;
});

viewport.addEventListener("wheel", (event) => {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  zoomBy(event.deltaY > 0 ? -0.12 : 0.12);
}, { passive: false });

renderDetail();
applyTransform();
createHotspots();

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 同源代理：viewer 經 tunnel/https 開出去時，gateway 與 LiveKit 信令
// 都走同一個 origin，避免 mixed content（媒體流是 WebRTC/UDP，不經此處）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: true, // dev tunnel 域名不固定
    proxy: {
      "/api": "http://127.0.0.1:8800",
      "/ws": { target: "ws://127.0.0.1:8800", ws: true },
      "/lk": {
        target: "ws://127.0.0.1:7880",
        ws: true,
        rewrite: (p) => p.replace(/^\/lk/, ""),
      },
    },
  },
});

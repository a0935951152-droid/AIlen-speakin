#!/usr/bin/env bash
# 啟動 LiveKit SFU（dev 環境，docker，與 speakin-nats 同模式）。
#
# --dev 內建測試金鑰 devkey/secret（僅限內網開發，prod 走 §7 K8s + 正式金鑰）。
# host network：UDP/RTC 不經 docker NAT，LAN 上兩台裝置可直連；
# node-ip 自動偵測為主機 LAN IP。埠位：7880 ws/http、7881 rtc-tcp、7882/udp rtc-udp。
set -euo pipefail

docker rm -f speakin-livekit 2>/dev/null || true
exec docker run -d --name speakin-livekit \
  --network host \
  --restart unless-stopped \
  livekit/livekit-server:latest \
  --dev --bind 0.0.0.0

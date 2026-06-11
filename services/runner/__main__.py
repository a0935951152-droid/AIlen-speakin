"""管線執行器：讀 pipelines/*.yaml 拉起 stage（《結構及技術棧.md》§6.2）。

用法：
    .venv/bin/python -m services.runner --pipeline pipelines/default.yaml \
        --session ses_dev --nodes stt \
        --set stt.source=tests/replay/golden/jfk.wav
"""

from __future__ import annotations

import argparse
import asyncio

import yaml

from core.bus import Bus
from core.stage import load_stage


def parse_args():
    p = argparse.ArgumentParser(prog="services.runner")
    p.add_argument("--pipeline", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--nats", default="nats://127.0.0.1:4222")
    p.add_argument("--nodes", default="", help="逗號分隔，只啟動這些 node（預設全部）")
    p.add_argument("--set", action="append", default=[], metavar="NODE.KEY=VAL",
                   help="覆寫 node config，如 stt.source=foo.wav")
    return p.parse_args()


def apply_overrides(nodes: list[dict], overrides: list[str]) -> None:
    for item in overrides:
        target, _, val = item.partition("=")
        node_id, _, key = target.partition(".")
        for node in nodes:
            if node["id"] == node_id:
                node.setdefault("config", {})[key] = val
                break
        else:
            raise SystemExit(f"--set 指定的 node '{node_id}' 不在管線中")


async def amain() -> None:
    args = parse_args()
    spec = yaml.safe_load(open(args.pipeline))
    nodes: list[dict] = spec["nodes"]
    only = {n for n in args.nodes.split(",") if n}
    apply_overrides(nodes, args.set)

    bus = Bus(args.nats)
    await bus.connect()
    insts = []
    try:
        for node in nodes:
            if only and node["id"] not in only:
                continue
            if "route_by" in node:
                # §6.3 路由語法已保留；Phase 3 TTS 接入時實作
                raise NotImplementedError(
                    f"node '{node['id']}' 使用 route_by：Phase 3 實作")
            cls, mf = load_stage(node["use"])
            st = cls(bus=bus, session_id=args.session,
                     config=dict(node.get("config") or {}))
            await st.setup()
            insts.append(st)
            print(f"[runner] node '{node['id']}' ← {mf.id}@{mf.version} 就緒")
        if not insts:
            raise SystemExit("沒有任何 node 被啟動（檢查 --nodes）")
        await asyncio.gather(*(s.run() for s in insts))
    finally:
        for s in insts:
            await s.teardown()
        await bus.close()


if __name__ == "__main__":
    asyncio.run(amain())

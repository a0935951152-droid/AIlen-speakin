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


def expand_routes(node: dict) -> list[dict]:
    """§6.3 route_by：把路由節點展開成多個普通節點，每路一個 stage 實例。

    routes 鍵是 YAML 清單字面值（"[zh, ja]"）或 "*" 兜底。展開節點繼承共用
    config 並注入 langs；兜底路由拿 langs="*" + langs_exclude=已被明示路由
    接走的語言，因此不需要預知全語言集合——語言數始終是設定值，不是結構。
    """
    if node["route_by"] != "lang":
        raise SystemExit(f"node '{node['id']}'：route_by 目前僅支援 lang")
    base = dict(node.get("config") or {})
    out: list[dict] = []
    explicit: list[str] = []
    wildcard_use = None
    for key, use in node["routes"].items():
        if key == "*":
            wildcard_use = use
            continue
        langs = yaml.safe_load(key)
        if not isinstance(langs, list):
            raise SystemExit(f"node '{node['id']}' 路由鍵 '{key}'：須為 \"[lang, ...]\" 或 \"*\"")
        explicit += langs
        out.append({"id": f"{node['id']}:{'+'.join(langs)}", "use": use,
                    "config": {**base, "langs": langs}})
    if wildcard_use:
        out.append({"id": f"{node['id']}:*", "use": wildcard_use,
                    "config": {**base, "langs": "*", "langs_exclude": explicit}})
    return out


def apply_overrides(nodes: list[dict], overrides: list[str]) -> None:
    for item in overrides:
        target, _, val = item.partition("=")
        node_id, _, key = target.partition(".")
        for node in nodes:
            if node["id"] == node_id:
                # YAML 解析值：讓 pace=0.5 / fp16=false / target_langs=[zh,en]
                # 拿到 float/bool/list，而不是字串（字串照舊不受影響）
                node.setdefault("config", {})[key] = yaml.safe_load(val)
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
            for sub in expand_routes(node) if "route_by" in node else [node]:
                cls, mf = load_stage(sub["use"])
                st = cls(bus=bus, session_id=args.session,
                         config=dict(sub.get("config") or {}))
                await st.setup()
                insts.append(st)
                print(f"[runner] node '{sub['id']}' ← {mf.id}@{mf.version} 就緒")
        if not insts:
            raise SystemExit("沒有任何 node 被啟動（檢查 --nodes）")
        await asyncio.gather(*(s.run() for s in insts))
    finally:
        for s in insts:
            await s.teardown()
        await bus.close()


if __name__ == "__main__":
    asyncio.run(amain())

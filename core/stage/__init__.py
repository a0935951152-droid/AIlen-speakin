"""Stage 基底類別與載入器（《結構及技術棧.md》§6.1）。

每個 stage = 一個目錄（stages/ 或 plugins/ 下），含 manifest.yaml + stage.py，
stage.py 需匯出 STAGE_CLASS。stage 之間只透過匯流排 topic 溝通。
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from core.bus import Bus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEARCH_BASES = ("stages", "plugins")


class StageManifest:
    def __init__(self, raw: dict[str, Any]):
        self.id: str = raw["id"]
        self.version: str = str(raw["version"])
        self.consumes: Any = raw.get("consumes")  # None = 源頭 stage（音訊直入）
        self.emits: Any = raw.get("emits")
        self.config_schema: dict[str, Any] = raw.get("config_schema", {})


class Stage(ABC):
    manifest: StageManifest | None = None

    def __init__(self, bus: Bus, session_id: str, config: dict[str, Any] | None = None):
        self.bus = bus
        self.session_id = session_id
        self.config = config or {}

    @property
    def stage_tag(self) -> str:
        """trace 用識別，如 'stt_whisperlive@0.1.0'。"""
        m = type(self).manifest
        return f"{m.id}@{m.version}" if m else type(self).__name__

    async def setup(self) -> None:  # noqa: B027
        pass

    @abstractmethod
    async def run(self) -> None:
        """源頭 stage 在此產生事件；消費型 stage 在此訂閱並常駐。"""

    async def teardown(self) -> None:  # noqa: B027
        pass


def load_stage(use: str) -> tuple[type[Stage], StageManifest]:
    """解析 'stt_whisperlive@0.1' 或 'plugins/glossary_corrector@0.2'。"""
    name, _, want_ver = use.partition("@")
    name = name.split("/")[-1]
    for base in SEARCH_BASES:
        mpath = PROJECT_ROOT / base / name / "manifest.yaml"
        if not mpath.exists():
            continue
        manifest = StageManifest(yaml.safe_load(mpath.read_text()))
        if want_ver and not manifest.version.startswith(want_ver):
            print(f"[stage] 警告: {name} 釘選 @{want_ver}，實際安裝 {manifest.version}")
        mod = importlib.import_module(f"{base}.{name}.stage")
        cls: type[Stage] = mod.STAGE_CLASS
        cls.manifest = manifest
        return cls, manifest
    raise FileNotFoundError(f"找不到 stage '{name}'（搜尋路徑: {SEARCH_BASES}）")

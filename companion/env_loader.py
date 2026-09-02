from __future__ import annotations

import os
from pathlib import Path


def load_env_files(*paths: str | Path) -> list[str]:
    """从 .env 文件加载 KEY=VALUE，不覆盖已有环境变量。返回成功加载的文件路径。"""
    loaded: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key] = value
        loaded.append(str(path))
    return loaded


def bootstrap_plugin_env(plugin_root: str) -> list[str]:
    root = Path(plugin_root)
    candidates = [
        root / ".env",
        root.parent / ".env",
        root.parent.parent / ".env",
    ]
    return load_env_files(*candidates)

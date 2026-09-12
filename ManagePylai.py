#!/usr/bin/env python3
"""ManagePylai 开发入口。Release 中此文件会被构建为兼容自更新的单文件启动器。"""
from __future__ import annotations

__version__ = "0.1.25"

from managepylai_core import __version__ as _runtime_version
from managepylai_cli import main

if _runtime_version != __version__:
    raise RuntimeError(
        f"ManagePylai 版本不一致: entry={__version__}, core={_runtime_version}"
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。", flush=True)

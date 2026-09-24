#!/usr/bin/env python3
"""ManagePylai 源码入口。发布时由 Manager/build.py 打包为单文件 ManagePylai.pyz（zipapp）。

开发期直接运行：``python3 Manager/__main__.py``。

``__version__`` 是**兼容声明**：v0.1.25 及更早的自更新器会在 zipapp 内按
``managepylai_core.py / ManagePylai.py / __main__.py`` 顺序查找顶层版本号，模块
重命名后只有 ``__main__.py`` 可见，故保留该字面量并在启动时与 ``core`` 强校验。
"""
from __future__ import annotations

__version__ = "0.1.32"

from core import __version__ as _runtime_version
from cli import main

if _runtime_version != __version__:
    raise RuntimeError(
        f"ManagePylai 版本不一致: entry={__version__}, core={_runtime_version}"
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。", flush=True)

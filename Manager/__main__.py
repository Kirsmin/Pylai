#!/usr/bin/env python3
"""ManagePylai 源码入口。发布时由 Manager/build.py 打包为单文件 ManagePylai.pyz（zipapp）。

开发期直接运行：``python3 Manager/__main__.py``。

``__version__`` 是**兼容声明**：v0.1.25 及更早的自更新器会在 zipapp 内按
``managepylai_core.py / ManagePylai.py / __main__.py`` 顺序查找顶层版本号，模块
重命名后只有 ``__main__.py`` 可见，故保留该字面量并在启动时与 ``core`` 强校验。
"""
from __future__ import annotations

import sys

__version__ = "0.1.41"

# 版本守卫必须放在 import core 之前：源码使用 PEP 695（type X = ...）等 3.12+ 语法，
# 旧解释器只会在 import 阶段抛裸 SyntaxError，用户完全看不出是 Python 版本问题。
MIN_PYTHON = (3, 12)
if sys.version_info < MIN_PYTHON:
    _current = ".".join(str(part) for part in sys.version_info[:3])
    _required = ".".join(str(part) for part in MIN_PYTHON)
    sys.exit(
        f"ManagePylai 需要 Python {_required}+（当前 {_current}，解释器 {sys.executable}）。\n"
        f"请改用较新的解释器运行，例如：python3.13 ManagePylai.pyz ...\n"
        "Ubuntu 22.04 自带 python3.10 过旧，可用 pyenv/venv 安装 3.12+ 后运行。"
    )

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

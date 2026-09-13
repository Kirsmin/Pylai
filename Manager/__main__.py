#!/usr/bin/env python3
"""ManagePylai 源码入口。发布时由 Manager/build.py 打包为单文件 ManagePylai.pyz（zipapp）。

开发期直接运行：``python3 Manager/__main__.py``。
"""
from __future__ import annotations

from cli import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。", flush=True)

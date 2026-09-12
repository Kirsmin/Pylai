#!/usr/bin/env python3
"""同步 ConfigEditor/ 权威源码到 managepylai_editor.py。

源码拆分后，配置编辑器不再内嵌于 ManagePylai.py 入口；发布构建器会把
managepylai_editor.py 一并打入 zipapp。同步算法保持与旧版一致：
server_code.py 覆盖 ``def find_free_port`` 到 ``CONFIG_EDITOR_HTML`` 之前，
index.html 覆盖 raw triple-quoted HTML 内容。
"""
from __future__ import annotations

import argparse
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "managepylai_editor.py"
SERVER_SRC = ROOT / "ConfigEditor" / "server_code.py"
HTML_SRC = ROOT / "ConfigEditor" / "index.html"

SERVER_START_MARK = "def find_free_port() -> int:"
HTML_START_MARK = 'CONFIG_EDITOR_HTML = r"""'


def build_updated(target_text: str, server_text: str, html_text: str) -> str:
    """按稳定标记重建 managepylai_editor.py 的内嵌区。"""
    if SERVER_START_MARK not in target_text:
        raise SystemExit(
            f"错误：managepylai_editor.py 中未找到 server 起始标记 {SERVER_START_MARK!r}"
        )
    if HTML_START_MARK not in target_text:
        raise SystemExit(
            f"错误：managepylai_editor.py 中未找到 HTML 起始标记 {HTML_START_MARK!r}"
        )

    server_start = target_text.index(SERVER_START_MARK)
    html_start = target_text.index(HTML_START_MARK)
    html_end = target_text.index('\n"""', html_start)
    html_closer_end = html_end + len('\n"""')

    # ConfigEditor/server_code.py 允许保留文件头注释；嵌入模块只保留实际代码。
    server_lines = server_text.splitlines()
    while server_lines and (
        not server_lines[0].strip() or server_lines[0].lstrip().startswith("#")
    ):
        server_lines.pop(0)
    server_body = "\n".join(server_lines).rstrip() + "\n\n"

    return (
        target_text[:server_start]
        + server_body
        + target_text[html_start : html_start + len(HTML_START_MARK)]
        + html_text
        + target_text[html_end:html_closer_end]
        + target_text[html_closer_end:]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查 ConfigEditor/ 与 managepylai_editor.py 是否一致，不一致时 exit 1",
    )
    args = parser.parse_args()

    target_text = TARGET.read_text(encoding="utf-8")
    server_text = SERVER_SRC.read_text(encoding="utf-8")
    html_text = HTML_SRC.read_text(encoding="utf-8")
    updated = build_updated(target_text, server_text, html_text)

    if updated == target_text:
        print("同步检查通过：ConfigEditor/ 与 managepylai_editor.py 一致。")
        return 0

    if args.check:
        print(
            "同步检查失败：请运行 python3 scripts/sync_config_editor.py 更新 managepylai_editor.py",
            file=sys.stderr,
        )
        return 1

    TARGET.write_text(updated, encoding="utf-8")
    print(f"已同步 ConfigEditor/ 到 {TARGET.name}（{len(updated)} 字节）。")
    py_compile.compile(str(TARGET), doraise=True)
    print(f"{TARGET.name} 语法检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

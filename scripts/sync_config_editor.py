#!/usr/bin/env python3
"""同步 ConfigEditor/ 源文件到 ManagePylai.py 内嵌区域。

ConfigEditor/server_code.py 与 ConfigEditor/index.html 是配置编辑器的唯一
权威源码；ManagePylai.py 中内嵌了一份副本（发布时单文件分发，不能依赖
ConfigEditor/ 目录存在）。本脚本按标记替换内嵌区，保证两处永远一致。

用法：
    python3 scripts/sync_config_editor.py            # 同步写入
    python3 scripts/sync_config_editor.py --check    # 仅检查是否漂移（CI 用）

替换范围：
    server 块：def find_free_port  →  CONFIG_EDITOR_HTML 赋值前
    HTML 块：  CONFIG_EDITOR_HTML = r''' ... ''' 的内容
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANAGE = ROOT / "ManagePylai.py"
SERVER_SRC = ROOT / "ConfigEditor" / "server_code.py"
HTML_SRC = ROOT / "ConfigEditor" / "index.html"

SERVER_START_MARK = "def find_free_port() -> int:"
HTML_START_MARK = 'CONFIG_EDITOR_HTML = r"""'


def build_updated(manage_text: str, server_text: str, html_text: str) -> str:
    """按标记重建 ManagePylai.py 文本。"""
    if SERVER_START_MARK not in manage_text:
        raise SystemExit(f"错误：ManagePylai.py 中未找到 server 起始标记 {SERVER_START_MARK!r}")
    if HTML_START_MARK not in manage_text:
        raise SystemExit(f"错误：ManagePylai.py 中未找到 HTML 起始标记 {HTML_START_MARK!r}")

    server_start = manage_text.index(SERVER_START_MARK)
    html_start = manage_text.index(HTML_START_MARK)

    # HTML 原始字符串以换行 + 三引号结尾
    html_end = manage_text.index('\n"""', html_start)
    html_closer_end = html_end + len('\n"""')

    # 清理 server 源码头注释，只保留函数/类体（ManagePylai 内嵌处自带分节注释）
    server_lines = server_text.splitlines()
    while server_lines and (not server_lines[0].strip() or server_lines[0].lstrip().startswith("#")):
        server_lines.pop(0)
    server_body = "\n".join(server_lines).rstrip() + "\n\n"

    return (
        manage_text[:server_start]
        + server_body
        + manage_text[html_start : html_start + len(HTML_START_MARK)]
        + html_text
        + manage_text[html_end : html_closer_end]
        + manage_text[html_closer_end:]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查 ConfigEditor/ 与 ManagePylai.py 内嵌区是否一致，不一致时 exit 1",
    )
    args = parser.parse_args()

    manage_text = MANAGE.read_text(encoding="utf-8")
    server_text = SERVER_SRC.read_text(encoding="utf-8")
    html_text = HTML_SRC.read_text(encoding="utf-8")

    updated = build_updated(manage_text, server_text, html_text)

    if updated == manage_text:
        print("同步检查通过：ConfigEditor/ 与 ManagePylai.py 内嵌区一致。")
        return 0

    if args.check:
        print("同步检查失败：ConfigEditor/ 与 ManagePylai.py 内嵌区不一致，请运行 python3 scripts/sync_config_editor.py", file=sys.stderr)
        return 1

    MANAGE.write_text(updated, encoding="utf-8")
    print(f"已同步 ConfigEditor/ 到 {MANAGE.name}（{len(updated)} 字节）。")

    import py_compile

    py_compile.compile(str(MANAGE), doraise=True)
    print(f"{MANAGE.name} 语法检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
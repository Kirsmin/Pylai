#!/usr/bin/env python3
"""统一版本对齐校验：源码 / 后端 / 镜像 / 两个前端必须声明同一版本。

CI 与 release 发布门禁均调用本脚本；Release Tag 版本经 ``--version`` 传入时
一并比对，任何一处不一致立即 exit 1（Fail Closed）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FORMAT_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?$")


def normalize(raw: str) -> str:
    return raw.strip().removeprefix("v").removeprefix("V")


def read_version(source: str) -> str:
    path, pattern = SOURCES[source]
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit(f"无法从 {path} 解析版本声明")
    return normalize(match.group(1))


SOURCES: dict[str, tuple[str, str]] = {
    "Manager/core.py": ("Manager/core.py", r'^__version__\s*=\s*["\']([^"\']+)["\']'),
    "OS/Pylaios.csproj": ("OS/Pylaios.csproj", r"<Version>([^<]+)</Version>"),
    "Dockerfile": ("Dockerfile", r"^ARG\s+PYLAI_VERSION=([^\s]+)"),
    "UI/package.json": ("UI/package.json", r'"version"\s*:\s*"([^"]+)"'),
    "AdminUI/package.json": ("AdminUI/package.json", r'"version"\s*:\s*"([^"]+)"'),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Release Tag 版本（可带 v 前缀），一并比对")
    args = parser.parse_args()

    versions = {name: read_version(name) for name in SOURCES}
    width = max(len(name) for name in versions)
    for name, version in versions.items():
        print(f"  {name.ljust(width)}  {version}")

    values = set(versions.values())
    if len(values) != 1:
        print("\n版本不一致：", file=sys.stderr)
        for name, version in versions.items():
            print(f"  {name}: {version}", file=sys.stderr)
        return 1

    source_version = values.pop()
    if not VERSION_FORMAT_RE.fullmatch(source_version):
        print(f"非法版本号: {source_version}", file=sys.stderr)
        return 1

    if args.version:
        expected = normalize(args.version)
        if expected != source_version:
            print(
                f"Release Tag 版本 {expected} 与源码版本 {source_version} 不一致",
                file=sys.stderr,
            )
            return 1

    print(f"\n版本对齐通过: {source_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

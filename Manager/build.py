#!/usr/bin/env python3
"""从 Manager/ 源码构建 ManagePylai 发布物。

输出：
  - ManagePylai.pyz：标准 zipapp（``__main__.py`` + core/install/editor/services/cli）。
  - ManagePylai.pyz.sha256：校验文件。

发布物只保留 .pyz 一种形态；不再生成兼容用的 ManagePylai.py 文本启动器。
"""
from __future__ import annotations

import argparse
import hashlib
import py_compile
import re
import tempfile
import zipfile
from pathlib import Path

SOURCE_FILES = (
    "core.py",
    "install.py",
    "editor.py",
    "services.py",
    "cli.py",
)
ENTRY_FILE = "__main__.py"
VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
VERSION_VALUE_RE = re.compile(
    r'(^__version__\s*=\s*)["\'][^"\']+["\']', re.MULTILINE
)
VERSION_FORMAT_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?$")
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def read_declared_version(path: Path) -> str:
    match = VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"missing __version__ in {path}")
    return match.group(1)


def replace_version(source: str, version: str) -> str:
    updated, count = VERSION_VALUE_RE.subn(
        lambda m: f'{m.group(1)}"{version}"', source, count=1
    )
    if count != 1:
        raise SystemExit("Manager/core.py must contain exactly one top-level __version__")
    return updated


def compile_sources(root: Path) -> None:
    files = [root / ENTRY_FILE, *sorted(root.glob("*.py"))]
    for path in dict.fromkeys(files):
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")
        py_compile.compile(str(path), doraise=True)


def check_versions(root: Path) -> str:
    return read_declared_version(root / "core.py")


def zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def build_pyz(root: Path, output: Path, version: str) -> bytes:
    entry = (root / ENTRY_FILE).read_text(encoding="utf-8")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr(zip_info(ENTRY_FILE), entry.encode("utf-8"))
            for name in SOURCE_FILES:
                source = (root / name).read_text(encoding="utf-8")
                if name == "core.py":
                    source = replace_version(source, version)
                zf.writestr(zip_info(name), source.encode("utf-8"))
        zip_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"#!/usr/bin/env python3\n" + zip_bytes)
    output.chmod(0o755)
    return output.read_bytes()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sha256(path: Path) -> Path:
    digest = sha256_file(path)
    target = path.with_name(path.name + ".sha256")
    target.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return target


def verify_artifacts(output_dir: Path, version: str) -> None:
    with zipfile.ZipFile(output_dir / "ManagePylai.pyz") as zf:
        names = set(zf.namelist())
        required = {ENTRY_FILE, *SOURCE_FILES}
        missing = required - names
        if missing:
            raise SystemExit(f"zipapp missing files: {sorted(missing)}")
        core = zf.read("core.py").decode("utf-8")
        match = VERSION_RE.search(core)
        if not match or match.group(1) != version:
            raise SystemExit("zipapp runtime version declaration is incorrect")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the ManagePylai.pyz release artifact")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--version", help="release version; defaults to source __version__")
    parser.add_argument("--check", action="store_true", help="only validate source layout and versions")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    compile_sources(root)
    source_version = check_versions(root)
    if args.check:
        if args.version:
            expected = args.version.removeprefix("v").removeprefix("V")
            if source_version != expected:
                raise SystemExit(
                    f"source/release version mismatch: source={source_version}, release={expected}"
                )
        print(f"ManagePylai sources OK ({source_version})")
        return

    version = (args.version or source_version).removeprefix("v").removeprefix("V")
    if not VERSION_FORMAT_RE.fullmatch(version):
        raise SystemExit(f"invalid version: {version}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pyz_path = output_dir / "ManagePylai.pyz"
    build_pyz(root, pyz_path, version)
    pyz_sha = write_sha256(pyz_path)
    verify_artifacts(output_dir, version)

    print(f"built {pyz_path} ({pyz_path.stat().st_size} bytes)")
    print(f"sha256 {pyz_sha.name}")


if __name__ == "__main__":
    main()

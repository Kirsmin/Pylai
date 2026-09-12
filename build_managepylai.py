#!/usr/bin/env python3
"""Build ManagePylai release artifacts from the flat source modules.

Outputs:
  - ManagePylai.pyz: a regular zipapp.
  - ManagePylai.py: UTF-8 compatibility launcher embedding the same pyz payload.

The text launcher is intentional: ManagePylai v0.1.24 reads the next
ManagePylai.py as UTF-8 and extracts a top-level ``__version__`` before
replacing itself. Shipping a raw zipapp under that filename would break the
existing self-update chain.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import py_compile
import re
import tempfile
import zipfile
from pathlib import Path

SOURCE_FILES = (
    "managepylai_core.py",
    "managepylai_install.py",
    "managepylai_editor.py",
    "managepylai_services.py",
    "managepylai_cli.py",
)
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
        raise SystemExit("managepylai_core.py must contain exactly one top-level __version__")
    return updated


def compile_sources(root: Path) -> None:
    files = [root / "ManagePylai.py", root / "build_managepylai.py"]
    files.extend(root / name for name in SOURCE_FILES)
    for path in files:
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")
        py_compile.compile(str(path), doraise=True)


def check_versions(root: Path) -> str:
    entry_version = read_declared_version(root / "ManagePylai.py")
    core_version = read_declared_version(root / "managepylai_core.py")
    if entry_version != core_version:
        raise SystemExit(
            f"source version mismatch: ManagePylai.py={entry_version}, "
            f"managepylai_core.py={core_version}"
        )
    return entry_version


def zip_info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def build_pyz(root: Path, output: Path, version: str) -> bytes:
    main = f'''#!/usr/bin/env python3
from managepylai_core import __version__ as _runtime_version
from managepylai_cli import main

if _runtime_version != {version!r}:
    raise RuntimeError(
        f"ManagePylai version mismatch: runtime={{_runtime_version}}, artifact={version}"
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n已退出。", flush=True)
'''

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr(zip_info("__main__.py"), main.encode("utf-8"))
            for name in SOURCE_FILES:
                source = (root / name).read_text(encoding="utf-8")
                if name == "managepylai_core.py":
                    source = replace_version(source, version)
                zf.writestr(zip_info(name), source.encode("utf-8"))
        zip_bytes = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"#!/usr/bin/env python3\n" + zip_bytes)
    output.chmod(0o755)
    return output.read_bytes()


def launcher_text(version: str, pyz_bytes: bytes) -> str:
    encoded = base64.b85encode(pyz_bytes)
    payload_literal = repr(encoded)
    return f'''#!/usr/bin/env python3
from __future__ import annotations

# Keep this top-level text declaration for ManagePylai v0.1.24 self-update.
__version__ = {version!r}

import base64
import importlib.abc
import importlib.util
import io
import sys
import zipfile

_PYZ = base64.b85decode({payload_literal})

with zipfile.ZipFile(io.BytesIO(_PYZ)) as _archive:
    _SOURCES = {{
        name[:-3]: _archive.read(name).decode("utf-8")
        for name in _archive.namelist()
        if name.endswith(".py") and name != "__main__.py"
    }}


class _EmbeddedFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in _SOURCES:
            return importlib.util.spec_from_loader(
                fullname,
                self,
                origin=f"{{sys.argv[0]}}!/{{fullname}}.py",
            )
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = _SOURCES[module.__name__]
        filename = f"{{sys.argv[0]}}!/{{module.__name__}}.py"
        module.__file__ = filename
        exec(compile(source, filename, "exec"), module.__dict__)


sys.meta_path.insert(0, _EmbeddedFinder())

from managepylai_core import __version__ as _runtime_version
from managepylai_cli import main

if _runtime_version != __version__:
    raise RuntimeError(
        f"ManagePylai version mismatch: launcher={{__version__}}, runtime={{_runtime_version}}"
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n已退出。", flush=True)
'''


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sha256(path: Path) -> Path:
    digest = sha256_file(path)
    target = path.with_name(path.name + ".sha256")
    target.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return target


def verify_artifacts(output_dir: Path, version: str) -> None:
    text = (output_dir / "ManagePylai.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match or match.group(1) != version:
        raise SystemExit("compat launcher version declaration is missing or incorrect")

    with zipfile.ZipFile(output_dir / "ManagePylai.pyz") as zf:
        names = set(zf.namelist())
        required = {"__main__.py", *SOURCE_FILES}
        missing = required - names
        if missing:
            raise SystemExit(f"zipapp missing files: {sorted(missing)}")
        core = zf.read("managepylai_core.py").decode("utf-8")
        match = VERSION_RE.search(core)
        if not match or match.group(1) != version:
            raise SystemExit("zipapp runtime version declaration is incorrect")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ManagePylai single-file release artifacts")
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
    pyz_bytes = build_pyz(root, pyz_path, version)

    launcher_path = output_dir / "ManagePylai.py"
    launcher_path.write_text(launcher_text(version, pyz_bytes), encoding="utf-8")
    launcher_path.chmod(0o755)

    py_sha = write_sha256(launcher_path)
    pyz_sha = write_sha256(pyz_path)
    verify_artifacts(output_dir, version)

    print(f"built {launcher_path} ({launcher_path.stat().st_size} bytes)")
    print(f"built {pyz_path} ({pyz_path.stat().st_size} bytes)")
    print(f"sha256 {py_sha.name}, {pyz_sha.name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
MANAGE_PY = ROOT / "ManagePylai.py"
MIGRATIONS_DIR = ROOT / "OS" / "Features" / "Database" / "Migrations"

TARGETS = {
    "linux-amd64": {"platform": "linux/amd64", "os": "Linux", "arch": "AMD64"},
    "linux-arm64": {"platform": "linux/arm64", "os": "Linux", "arch": "ARM64"},
}


def run(command: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, text=True)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"缺少构建工具: {name}")


def normalize_version(raw: str) -> str:
    version = raw.strip()
    if version.startswith(("v", "V")):
        version = version[1:]
    if not version or any(c in version for c in r'\/:*?"<>| '):
        raise SystemExit(f"非法版本号: {raw!r}")
    return version


def read_db_schema_version() -> str:
    names = sorted(
        p.name for p in MIGRATIONS_DIR.glob("*.cs")
        if not p.name.endswith(".Designer.cs") and "Snapshot" not in p.name
    )
    if not names:
        raise SystemExit("未找到 EF 迁移文件")
    return names[-1].replace(".cs", "")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_target(version: str, target_name: str, target: dict[str, str]) -> Path:
    package_name = f"Pylai-{version}-Linux-{target['arch']}"
    tar_path = DIST_DIR / f"{package_name}.tar"
    if tar_path.exists():
        tar_path.unlink()

    require_tool("docker")
    if shutil.which("buildx") is None and run(["docker", "buildx", "version"], check=False).returncode != 0:
        raise SystemExit("缺少 docker buildx")

    print(f"==> 构建 Docker 镜像: {package_name}")
    schema = read_db_schema_version()
    run(
        [
            "docker", "buildx", "build",
            "--platform", target["platform"],
            "--build-arg", f"PYLAI_VERSION={version}",
            "--build-arg", f"PYLAI_DB_SCHEMA={schema}",
            "-t", f"pylaios:{version}-{target['arch']}",
            "--provenance=false",
            "--output", f"type=docker,dest={tar_path}",
            ".",
        ],
        cwd=ROOT,
    )

    if not tar_path.is_file() or tar_path.stat().st_size == 0:
        raise SystemExit(f"镜像导出失败: {tar_path}")

    checksum = sha256_file(tar_path)
    checksum_path = DIST_DIR / f"{tar_path.name}.sha256"
    checksum_path.write_text(f"{checksum}  {tar_path.name}\n", encoding="utf-8")

    print(f"==> 完成: {tar_path}")
    print(f"    SHA256: {checksum}")
    return tar_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 Pylai Docker 部署镜像并生成 Release tar")
    parser.add_argument("--version", required=True, help="版本号，例如 0.0.1 或 v0.0.1")
    parser.add_argument("--target", default="all", choices=["all", *TARGETS.keys()],
                        help="目标平台，默认 all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = normalize_version(args.version)

    if not (ROOT / "Dockerfile").is_file():
        raise SystemExit("找不到 Dockerfile")
    if not MANAGE_PY.is_file():
        raise SystemExit("找不到 ManagePylai.py，请先创建管理工具")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    selected = TARGETS.items() if args.target == "all" else [(args.target, TARGETS[args.target])]

    outputs = [build_target(version, name, target) for name, target in selected]

    manage_dst = DIST_DIR / "ManagePylai.py"
    shutil.copy2(MANAGE_PY, manage_dst)
    manage_checksum = sha256_file(manage_dst)
    (DIST_DIR / "ManagePylai.py.sha256").write_text(
        f"{manage_checksum}  ManagePylai.py\n", encoding="utf-8")

    manifest = {
        "name": "Pylai",
        "version": version,
        "deployment": "docker",
        "targets": [
            {
                "name": f"Pylai-{version}-Linux-{target['arch']}",
                "tar": f"Pylai-{version}-Linux-{target['arch']}.tar",
                "sha256": f"Pylai-{version}-Linux-{target['arch']}.tar.sha256",
                "os": target["os"],
                "architecture": target["arch"],
                "platform": target["platform"],
            }
            for _, target in selected
        ],
        "manager": "ManagePylai.py",
        "dbSchemaVersion": read_db_schema_version(),
        "builtAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (DIST_DIR / "release.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\nRelease 产物:")
    for output in outputs:
        print(f"  - {output.name}")
        print(f"  - {output.name}.sha256")
    print(f"  - ManagePylai.py")
    print(f"  - ManagePylai.py.sha256")
    print(f"  - release.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\n构建命令失败，退出码: {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)

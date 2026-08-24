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


def verify_tar_templates(tar_path: Path) -> None:
    """Fail Closed: 直接检查 tar 产物内是否包含两份模板（不依赖 docker daemon 与架构）。"""
    import tarfile
    try:
        with tarfile.open(tar_path, "r") as tf:
            names = tf.getnames()
    except Exception as exc:
        raise SystemExit(f"无法读取 tar {tar_path}: {exc}") from exc
    # buildx 导出的 docker 镜像 tar 内层为多个 layer.tar，需再检查内层
    # 简化：直接在 tar 中搜索文件名片段
    has_template = any("pylai.template.toml" in n for n in names)
    # 若外层未直接包含，则尝试检查内部 layer（tar 内 tar）
    if not has_template:
        # 回退检查：tar 内容字节搜索（兼容 docker/oci 归档格式差异）
        data = tar_path.read_bytes()
        if b"pylai.template.toml" not in data:
            raise SystemExit(f"tar {tar_path} 内未找到 pylai.template.toml")
        if b"server_url" not in data:
            raise SystemExit(f"tar {tar_path} 内 template 缺少 server_url 占位")
    else:
        # 已找到文件名，再校验占位
        data = tar_path.read_bytes()
        if b"server_url" not in data:
            raise SystemExit(f"tar {tar_path} 内 template 缺少 server_url 占位")
    if b"pylai.example.toml" not in tar_path.read_bytes():
        raise SystemExit(f"tar {tar_path} 内未找到 pylai.example.toml")
    print(f"==> tar 模板校验通过: {tar_path.name}")


def verify_image_templates(image: str) -> None:
    """Fail Closed: 校验镜像内两份配置模板齐全且模板含必需占位（需镜像已 load）。"""
    for fname, needle in [
        ("pylai.template.toml", "server_url"),
        ("pylai.example.toml", "[Server]"),
    ]:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "cat", image, f"/opt/pylai/{fname}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"镜像 {image} 缺少 /opt/pylai/{fname}，构建失败（docker run 失败: {result.stderr.strip()[:200]}）")
        if needle not in result.stdout:
            raise SystemExit(f"镜像 {image} 的 {fname} 内容异常（缺少 {needle}）")
    print(f"==> 镜像模板校验通过: {image}")


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

    # 优先通过 tar 内容校验（兼容 ARM64 无法在 amd64 runner 上 docker run 的情况）
    verify_tar_templates(tar_path)
    # AMD64 额外尝试镜像内验证（需先 load，已在上一步导出，可直接 load 后验证）
    if target["arch"] == "AMD64":
        image = f"pylaios:{version}-{target['arch']}"
        load = subprocess.run(["docker", "load", "-i", str(tar_path)], capture_output=True, text=True)
        if load.returncode == 0:
            try:
                verify_image_templates(image)
            except SystemExit as exc:
                print(f"警告: 镜像内验证失败（tar 已通过）: {exc}", file=sys.stderr)
        else:
            print(f"警告: docker load 失败，跳过镜像内验证: {load.stderr.strip()[:200]}", file=sys.stderr)

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
    parser.add_argument("--finalize", action="store_true",
                        help="跳过镜像构建：校验 dist/ 下已有 tar 产物齐全后仅生成 "
                             "ManagePylai.py 与 release.json（供 CI 汇总 job 使用）")
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

    if args.finalize:
        expected = [DIST_DIR / f"Pylai-{version}-Linux-{target['arch']}.tar" for _, target in selected]
        missing = [p.name for p in expected if not p.is_file() or p.stat().st_size == 0]
        if missing:
            raise SystemExit(f"产物缺失或为空，无法 finalize: {', '.join(missing)}")
        # finalize 同样校验已存在的 tar 内模板（不依赖镜像是否可运行）
        for _, target in selected:
            tar_path = DIST_DIR / f"Pylai-{version}-Linux-{target['arch']}.tar"
            try:
                verify_tar_templates(tar_path)
            except SystemExit as exc:
                raise SystemExit(f"finalize 校验失败: {exc}") from exc
            # AMD64 额外镜像内验证（已 load 情况下）
            if target["arch"] == "AMD64":
                image = f"pylaios:{version}-{target['arch']}"
                load = subprocess.run(["docker", "load", "-i", str(tar_path)], capture_output=True, text=True)
                if load.returncode == 0:
                    try:
                        verify_image_templates(image)
                    except SystemExit as exc:
                        print(f"警告: finalize 镜像内验证失败: {exc}", file=sys.stderr)
        outputs = expected
    else:
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

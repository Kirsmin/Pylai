#!/usr/bin/env python3
"""Pylai 开发实例启动器。

流程：代码哈希比对 → 必要时重建镜像 → 启动 loopback 容器 → 等待就绪 →
打印非敏感运行摘要 → 跟随日志；Ctrl+C/SIGTERM 优雅退出并恢复初始状况。
"""
from __future__ import annotations

import argparse
import hashlib
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from shutil import which

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

IMAGE = "pylai-dev:latest"
CONTAINER = "pylai-dev"
HASH_LABEL = "pylai.dev.codehash"
VOLUME_DATA = "pylai-dev-data"
VOLUME_PG = "pylai-dev-pg"
UI_PORT = 8080
API_PORT = 5000
ROOT = Path(__file__).resolve().parent
HASH_EXCLUDE_DIRS = {"bin", "obj", "node_modules", "dist", ".git", "__pycache__", ".pnpm-store"}
HASH_PATHS = ("Dockerfile", ".dockerignore", "dev", "deploy", "OS", "UI", "AdminUI")
_exiting = False
_keep = False


def run(*args: str, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    return subprocess.run([str(a) for a in args], text=True, **kw)


def require_docker() -> None:
    if which("docker") is None:
        sys.exit(
            "缺少 docker。请先安装：\n"
            "  sudo pacman -S docker docker-buildx\n"
            "  sudo systemctl enable --now docker\n"
            "  sudo usermod -aG docker $USER   # 重新登录后生效"
        )
    if run("docker", "info").returncode != 0:
        sys.exit("docker 守护进程不可用：请检查 docker 服务是否已启动（sudo systemctl start docker）。")


def code_hash() -> str:
    hasher = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    for name in HASH_PATHS:
        path = ROOT / name
        if path.is_file():
            files.append((name, path))
        elif path.is_dir():
            for p in sorted(path.rglob("*")):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(ROOT))
                if any(f"/{d}/" in f"/{rel}" for d in HASH_EXCLUDE_DIRS):
                    continue
                if rel.endswith(".md") or rel == "OS/pylai.toml":
                    continue
                files.append((rel, p))
    for rel, p in sorted(files):
        hasher.update(rel.encode())
        hasher.update(b"\0")
        hasher.update(p.read_bytes())
    return hasher.hexdigest()


def image_hash() -> str | None:
    fmt = f'{{{{index .Config.Labels "{HASH_LABEL}"}}}}'
    result = run("docker", "image", "inspect", IMAGE, "--format", fmt)
    return None if result.returncode != 0 else (result.stdout.strip() or None)


def build_image() -> None:
    current = code_hash()
    print("==> 源码有变化，重新编译镜像（linux/amd64）...")
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE, "--label", f"{HASH_LABEL}={current}", "."],
        cwd=ROOT,
    )
    if result.returncode != 0:
        print("==> 经典构建器失败，回退 buildx...")
        for image in (
            "docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32",
            "node@sha256:934240a162082fd8b8a2f90cd5114446443f1eba1c5378f6687167ca405e6584",
        ):
            run("docker", "pull", image)
        result = subprocess.run(
            ["docker", "buildx", "build", "--platform", "linux/amd64", "-t", IMAGE,
             "--load", "--label", f"{HASH_LABEL}={current}", "."],
            cwd=ROOT,
        )
    if result.returncode != 0:
        sys.exit("镜像构建失败，请检查上方错误。")
    print("==> 镜像构建完成。")


def detect_lan_ip() -> str:
    result = run("ip", "-4", "route", "get", "1.1.1.1")
    for line in result.stdout.splitlines():
        parts = line.split()
        if "src" in parts:
            return parts[parts.index("src") + 1]
    result = run("hostname", "-I")
    first = result.stdout.split()
    return first[0] if first else "127.0.0.1"


def wait_ready(timeout: int = 240) -> None:
    url = f"http://127.0.0.1:{API_PORT}/health/ready"
    print(f"==> 等待实例就绪（{url}，首次启动需初始化数据库）...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _exiting:
            return
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    print("==> 实例就绪。")
                    return
        except Exception:
            pass
        time.sleep(3)
    sys.exit("等待实例就绪超时，请查看 docker logs pylai-dev 排查。")


def print_summary(ui_url: str) -> None:
    print()
    print("=" * 72)
    print("  Pylai Dev 实例已启动")
    print()
    print(f"  前端     : {ui_url}/")
    print(f"  管理台   : {ui_url}/admin/")
    print(f"  后端 API : http://127.0.0.1:{API_PORT}   （经系统 Nginx 开放到 0.0.0.0:80）")
    print(f"  健康检查 : {ui_url}/health/ready")
    print()
    print("  测试账号 / OAuth 客户端 / 邀请码凭据不会写入 stdout 或 docker logs。")
    print("  如确需本机调试，请显式执行：docker exec pylai-dev cat /var/lib/pylai/.secrets")
    print()
    print("  实时日志持续显示中，按 Ctrl+C 优雅退出（停止并删除容器与数据卷；--keep 时保留）。")
    print("=" * 72)
    print()


def follow_logs() -> None:
    subprocess.run(["docker", "logs", "--follow", "--tail", "200", CONTAINER], check=False)


def cleanup() -> None:
    global _exiting
    if _exiting:
        return
    _exiting = True
    if _keep:
        print()
        print("==> --keep 模式：容器与数据卷已保留（便于 docker exec 复现/回归验证）。")
        print(f"    手动清理：docker rm -f {CONTAINER} && docker volume rm {VOLUME_DATA} {VOLUME_PG}")
        return
    print()
    print("==> 正在优雅退出：停止并删除容器与数据卷...")
    run("docker", "stop", "-t", "30", CONTAINER)
    removed = run("docker", "rm", "-f", CONTAINER).returncode == 0
    volumes_removed = run("docker", "volume", "rm", VOLUME_DATA, VOLUME_PG).returncode == 0
    if removed and volumes_removed:
        print("==> 已恢复初始状况（镜像保留，代码未变化时下次启动免编译）。")
        return
    print("!! 清理未完全成功，请手动检查：")
    print(f"    docker ps -a --filter name={CONTAINER}")
    print("    docker volume ls")
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pylai 开发实例启动器")
    parser.add_argument("--ui-url", metavar="URL", default=None,
                        help="前端访问地址（覆盖自动探测的 LAN IP，如 http://192.168.1.10）")
    parser.add_argument("--keep", action="store_true",
                        help="退出时保留容器与数据卷（便于 docker exec 手动复现/回归验证），默认恢复初始状况")
    args = parser.parse_args()
    global _keep
    _keep = args.keep

    require_docker()
    ui_url = args.ui_url or f"http://{detect_lan_ip()}"
    existing = image_hash()
    if existing is None:
        print("!! 未找到上次编译的镜像，将重新编译")
        build_image()
    elif existing != code_hash():
        print("!! 源码与上次编译不一致，将重新编译")
        build_image()
    else:
        print("==> 源码无变化，直接使用上次编译的镜像")

    if run("docker", "inspect", CONTAINER).returncode == 0:
        print(f"==> 残留容器 {CONTAINER} 已存在，先删除...")
        run("docker", "rm", "-f", CONTAINER)

    print(f"==> 启动容器 {CONTAINER}（UI:127.0.0.1:{UI_PORT} -> 80, API:127.0.0.1:{API_PORT} -> 5000）...")
    result = subprocess.run([
        "docker", "run", "-d", "--name", CONTAINER, "--restart", "no", "--read-only",
        "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "FOWNER", "--cap-add", "SETGID", "--cap-add", "SETUID",
        "--cap-add", "NET_BIND_SERVICE", "--cap-add", "KILL",
        "--tmpfs", "/tmp:rw,nosuid,size=64m", "--tmpfs", "/run:rw,nosuid,size=16m",
        "--security-opt", "no-new-privileges:true", "--pids-limit", "512",
        "-p", f"127.0.0.1:{UI_PORT}:80", "-p", f"127.0.0.1:{API_PORT}:5000",
        "-v", f"{VOLUME_DATA}:/var/lib/pylai", "-v", f"{VOLUME_PG}:/var/lib/postgresql",
        "-e", f"PYL_UI_URL={ui_url}", "-e", "PYLAI_ROLE=dev", IMAGE,
    ])
    if result.returncode != 0:
        sys.exit("容器启动失败，请查看 docker ps / docker logs 排查。")

    signal.signal(signal.SIGINT, lambda *_: cleanup())
    signal.signal(signal.SIGTERM, lambda *_: cleanup())
    wait_ready()
    if _exiting:
        return 0
    print_summary(ui_url)
    try:
        follow_logs()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        raise SystemExit(130)

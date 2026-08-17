#!/usr/bin/env python3
"""Pylai 开发实例启动器。

流程：代码哈希比对（镜像 label）→ 需要则 buildx 重建 → 启动容器（仅绑定 127.0.0.1）
→ 等待就绪 → 打印凭据总览 → 实时日志；Ctrl+C/SIGTERM 优雅退出并恢复初始状况
（停止并删除容器 + 数据卷，镜像保留以便下次免编译）。
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
UI_PORT = 8080  # 容器 nginx 80 → 宿主机 127.0.0.1:8080
API_PORT = 5000  # 后端 5000 → 宿主机 127.0.0.1:5000

ROOT = Path(__file__).resolve().parent

# 参与镜像哈希的输入（排除构建产物目录）
HASH_EXCLUDE_DIRS = {"bin", "obj", "node_modules", "dist", ".git", "__pycache__", ".pnpm-store"}
HASH_PATHS = ("Dockerfile", ".dockerignore", "dev", "deploy", "OS", "UI", "AdminUI")

_exiting = False


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
    result = run("docker", "info")
    if result.returncode != 0:
        sys.exit("docker 守护进程不可用：请检查 docker 服务是否已启动（sudo systemctl start docker）。")


def code_hash() -> str:
    """对影响镜像内容的源码计算稳定哈希（相对路径 + 内容）。"""
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
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_image() -> None:
    current = code_hash()
    print(f"==> 源码有变化，使用 buildx 重新编译镜像（linux/amd64）...")
    # docker.io 可能被网络策略阻断：buildx 客户端进程不带代理时拉取会失败，
    # 先经 dockerd（带 daemon 代理）预拉取，buildkit 将直接使用本地镜像。
    for image in ("docker/dockerfile:1.14.2", "node:24.19.0-bookworm-slim"):
        run("docker", "pull", image)
    result = subprocess.run(
        ["docker", "buildx", "build",
         "--platform", "linux/amd64",
         "-t", IMAGE,
         "--load",
         "--label", f"{HASH_LABEL}={current}",
         "."],
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
    if first:
        return first[0]
    return "127.0.0.1"


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
    result = run("docker", "exec", CONTAINER, "cat", "/var/lib/pylai/.secrets")
    secrets: dict[str, str] = {}
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                secrets[k.strip()] = v.strip().strip("'")
    print()
    print("=" * 72)
    print("  Pylai Dev 实例已启动")
    print()
    print(f"  前端     : {ui_url}/")
    print(f"  管理台   : {ui_url}/admin/")
    print(f"  后端 API : http://127.0.0.1:{API_PORT}   （经系统 Nginx 开放到 0.0.0.0:80）")
    print(f"  健康检查 : {ui_url}/health/ready")
    print()
    print(f"  Max 账号    : max@pylaios.local / {secrets.get('MAX_PASSWORD', '<未知>')}")
    print(f"  Admin 账号  : admin@pylaios.local / {secrets.get('ADMIN_PASSWORD', '<未知>')}")
    print(f"  Normal 账号 : user@pylaios.local / {secrets.get('USER_PASSWORD', '<未知>')}")
    print(f"  OAuth 客户端: pylai-console / {secrets.get('CLIENT_SECRET', '<未知>')}")
    print(f"  管理台    : Cookie BFF（不保存 OAuth token）")
    print(f"  OAuth 客户端: pylai-console（Confidential，授权码/client_credentials/refresh_token）")
    print()
    print(f"  Normal 邀请码: {secrets.get('INVITE_NORMAL_CODE', '<未知>')}（仅此一次）")
    print(f"  Admin 邀请码 : {secrets.get('INVITE_ADMIN_CODE', '<未知>')}（仅此一次）")
    print(f"  Max 邀请码   : {secrets.get('INVITE_MAX_CODE', '<未知>')}（仅此一次）")
    print()
    print("  实时日志持续显示中，按 Ctrl+C 优雅退出（停止并删除容器与数据卷）。")
    print("=" * 72)
    print()


def follow_logs() -> None:
    subprocess.run(["docker", "logs", "--follow", "--tail", "200", CONTAINER], check=False)


def cleanup() -> None:
    global _exiting
    if _exiting:
        return
    _exiting = True
    print()
    print("==> 正在优雅退出：停止并删除容器与数据卷...")
    # 先优雅停止（-t 30 给 PG/后端收尾时间），再 rm -f 兜底删除：若容器未在宽限期内
    # 退出（如 supervisord 收尾阻塞），普通 rm 会失败，遗留运行中的容器与占用中的数据卷，
    # 导致下次启动依赖残留状态（历史 bug：清理失败仍打印"已恢复初始状况"）。
    run("docker", "stop", "-t", "30", CONTAINER)
    removed = run("docker", "rm", "-f", CONTAINER).returncode == 0
    volumes_removed = run("docker", "volume", "rm", VOLUME_DATA, VOLUME_PG).returncode == 0
    if removed and volumes_removed:
        print("==> 已恢复初始状况（镜像保留，代码未变化时下次启动免编译）。")
        return
    print("!! 清理未完全成功，请手动检查：")
    print(f"    docker ps -a --filter name={CONTAINER}")
    print("    docker volume ls")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pylai 开发实例启动器")
    parser.add_argument(
        "--ui-url", metavar="URL", default=None,
        help="前端访问地址（覆盖自动探测的 LAN IP，如 http://192.168.1.10）",
    )
    args = parser.parse_args()

    require_docker()

    ui_url = args.ui_url or f"http://{detect_lan_ip()}"

    # 构建检测：镜像不存在 / 无哈希 label / 哈希不一致 → 重建
    existing = image_hash()
    if existing is None:
        print("!! 未找到上次编译的镜像，将使用 buildx 重新编译")
        build_image()
    elif existing != code_hash():
        print("!! 源码与上次编译不一致，将使用 buildx 重新编译")
        build_image()
    else:
        print("==> 源码无变化，直接使用上次编译的镜像")

    if run("docker", "inspect", CONTAINER).returncode == 0:
        print(f"==> 残留容器 {CONTAINER} 已存在，先删除...")
        run("docker", "rm", "-f", CONTAINER)

    print(f"==> 启动容器 {CONTAINER}（UI:127.0.0.1:{UI_PORT} -> 80, API:127.0.0.1:{API_PORT} -> 5000）...")
    result = subprocess.run(
        ["docker", "run", "-d", "--name", CONTAINER,
         "--restart", "no",
         "--read-only",
         "--cap-drop", "ALL",
         "--cap-add", "CHOWN",
         "--cap-add", "DAC_OVERRIDE",
         "--cap-add", "FOWNER",
         "--cap-add", "SETGID",
         "--cap-add", "SETUID",
         "--cap-add", "NET_BIND_SERVICE",
         "--cap-add", "KILL",
         "--tmpfs", "/tmp:rw,nosuid,size=64m",
         "--tmpfs", "/run:rw,nosuid,size=16m",
         "--security-opt", "no-new-privileges:true",
         "--pids-limit", "512",
         "-p", f"127.0.0.1:{UI_PORT}:80",
         "-p", f"127.0.0.1:{API_PORT}:5000",
         "-v", f"{VOLUME_DATA}:/var/lib/pylai",
         "-v", f"{VOLUME_PG}:/var/lib/postgresql",
         "-e", f"PYL_UI_URL={ui_url}",
         "-e", "PYLAI_ROLE=dev",
         IMAGE],
    )
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

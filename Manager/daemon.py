#!/usr/bin/env python3
"""常驻更新守护进程：按固定间隔检查 Release，结果缓存到 state.json 供菜单标题
提示「有新版本」；``[Updates] AutoUpdate`` 开启时自动执行「管理工具 + Pylai 应用」
云端更新（等同 ``update --from-remote --yes --version <latest>``）。

生命周期：
  - 交互菜单启动时自动后台拉起（除非用户 ``daemon stop`` 显式停止）；
  - ``daemon run`` 前台运行（调试用），``daemon start/stop/status`` 手动管理；
  - 进程 pid 写入 ``~/.pylai/daemon.pid``，输出追加到 ``~/.pylai/daemon.log``。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from core import (
    HOME,
    AppContext,
    ManageError,
    ManagerConfig,
    ReleaseClient,
    SelfUpdater,
    State,
    __version__,
    manager_entry_path,
    out,
    utc_now_iso,
)
from install import UpdateService

PID_FILE = HOME / "daemon.pid"
LOG_FILE = HOME / "daemon.log"
LOG_MAX_BYTES = 5 * 1024 * 1024

_STOP = False


def _handle_signal(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """仅当 pid 属于本工具的 daemon run 进程时才视为存活（防 pid 复用误杀）。"""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return False
    return b"daemon" in cmdline and b"run" in cmdline


def is_running() -> bool:
    pid = _read_pid()
    return bool(pid and _pid_alive(pid))


def _log(message: str) -> None:
    """daemon 的 stdout 已被重定向到 LOG_FILE，统一时间戳前缀。"""
    out(f"[{utc_now_iso()}] {message}")


def check_once(ctx: AppContext) -> None:
    """单次检查：缓存最新版本；AutoUpdate 开启且有新版本时执行自动更新。"""
    # 每轮重读配置与状态：设置修改（间隔/开关/镜像源）无需重启常驻进程即生效。
    manager = ManagerConfig(ctx.manager.path)
    state = State()
    client = ReleaseClient(manager)

    latest = client.check_latest()
    if not latest:
        _log("检查失败：无法获取远端版本信息。")
        return

    version, _, _info = latest
    if state.installed:
        state.set("latest_version", version)
        state.set("latest_check_at", utc_now_iso())
        state.save()

    updater = SelfUpdater(client, manager, state)
    newer_manager = updater.version_gt(version, __version__)
    newer_app = state.installed and updater.version_gt(version, state.version)
    if not newer_manager and not newer_app:
        _log(f"已是最新（远端 v{version}）。")
        return

    _log(f"发现新版本 v{version}（当前管理工具 v{__version__}"
         + (f"，Pylai v{state.version}" if state.installed else "") + "）。")

    if manager.skip_version == version:
        _log(f"版本 {version} 已标记跳过，不自动更新。")
        return
    if not manager.auto_update:
        _log("AutoUpdate 未开启，仅提示。")
        return

    _log("AutoUpdate 已开启，开始自动更新（等同 update --from-remote --yes）。")
    try:
        UpdateService(ctx).update_cli(
            argparse.Namespace(
                check_only=False,
                from_remote=True,
                version=version,
                yes=True,
                dry_run=False,
                verbose=False,
                force_pg_upgrade=False,
                force=False,
            )
        )
        _log("自动更新流程结束。")
    except (SystemExit, KeyboardInterrupt):
        raise
    except ManageError as exc:
        _log(f"自动更新失败: {exc}")
    except Exception as exc:  # noqa: BLE001 - 常驻进程不能因为单次更新异常退出
        _log(f"自动更新未预期错误: {exc}")


def run(ctx: AppContext) -> None:
    """前台常驻循环：立即检查一次，之后每 CheckIntervalMinutes 检查一轮。"""
    pid = _read_pid()
    if pid and pid != os.getpid() and _pid_alive(pid):
        _log(f"常驻进程已在运行（pid {pid}），本次启动退出。")
        return

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    PID_FILE.write_text(f"{os.getpid()}\n", encoding="ascii")
    try:
        manager = ManagerConfig(ctx.manager.path)
        _log(
            f"常驻进程启动：检查间隔 {manager.check_interval_minutes} 分钟，"
            f"AutoUpdate = {str(manager.auto_update).lower()}。"
        )
        while not _STOP:
            try:
                check_once(ctx)
            except (SystemExit, KeyboardInterrupt):
                raise
            except Exception as exc:  # noqa: BLE001 - 单轮失败不打断常驻循环
                _log(f"检查异常: {exc}")

            deadline = time.monotonic() + ManagerConfig(
                ctx.manager.path
            ).check_interval_minutes * 60
            while not _STOP and time.monotonic() < deadline:
                time.sleep(min(5.0, deadline - time.monotonic()))
    finally:
        try:
            if _read_pid() == os.getpid():
                PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        _log("常驻进程已退出。")


def _spawn(ctx: AppContext) -> bool:
    """后台拉起 daemon run：完全脱离终端（新会话、stdin 关闭、输出进日志）。"""
    entry = manager_entry_path()
    if entry.suffix.lower() != ".pyz" and entry.name != "__main__.py":
        return False

    try:
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.write_text("", encoding="utf-8")
        log_fd = os.open(LOG_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    except OSError:
        return False

    try:
        proc = subprocess.Popen(  # noqa: S603 - 入口与参数均为本工具自身
            [
                sys.executable,
                str(entry),
                "--config",
                str(ctx.manager.path),
                "daemon",
                "run",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(HOME),
            close_fds=True,
        )
    except OSError:
        os.close(log_fd)
        return False

    os.close(log_fd)
    return proc.pid > 0


def ensure(ctx: AppContext) -> None:
    """交互菜单启动时调用：未显式停止且未运行时静默后台拉起常驻进程。"""
    if ctx.manager.daemon_stopped or is_running():
        return
    try:
        _spawn(ctx)
    except OSError:
        pass


def start(ctx: AppContext) -> None:
    ctx.manager.set_daemon_stopped(False)
    if is_running():
        out("常驻进程已在运行。")
        return
    if _spawn(ctx):
        out(f"常驻进程已后台启动（日志: {LOG_FILE}）。")
    else:
        raise ManageError("无法启动常驻进程：当前不是可执行的发布物（ManagePylai.pyz）？")


def stop(ctx: AppContext) -> None:
    ctx.manager.set_daemon_stopped(True)
    pid = _read_pid()
    if not pid or not _pid_alive(pid):
        out("常驻进程未在运行。")
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
    out("常驻进程已停止；菜单启动不再自动拉起，可用 daemon start 恢复。")


def status(ctx: AppContext) -> None:
    manager = ctx.manager
    state = State()

    pid = _read_pid()
    if pid and _pid_alive(pid):
        out(f"常驻进程：运行中（pid {pid}）")
    else:
        out("常驻进程：未运行")

    out(f"检查间隔：{manager.check_interval_minutes} 分钟")
    out(f"AutoUpdate：{str(manager.auto_update).lower()}（默认关闭，开启后自动更新管理工具 + Pylai 应用）")
    out(f"菜单自动拉起：{str(not manager.daemon_stopped).lower()}")

    latest = str(state.get("latest_version") or "")
    checked = str(state.get("latest_check_at") or "")
    if latest and checked:
        out(f"最近一次检查：{checked}，远端最新 v{latest}")
    elif latest:
        out(f"远端最新版本：v{latest}")
    else:
        out("尚无检查记录（常驻进程启动后立即检查第一轮）。")

    out(f"日志文件：{LOG_FILE}")

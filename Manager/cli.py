#!/usr/bin/env python3
"""ManagePylai 命令行入口与交互菜单。"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import platform as host_platform
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request

from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Any, Literal, Self, TypeVar
from urllib.parse import urlparse

from core import (
    AppContext,
    HOME,
    ManageError,
    ReleaseClient,
    SelfUpdater,
    __version__,
    ask_bool,
    confirm_danger,
    out,
    service_action,
    uninstall,
)
from install import InstallService, UpdateService
from services import (
    BackupService,
    ComponentService,
    ConfigService,
    SecurityService,
    SettingsService,
    UserService,
)

class InteractiveMenu:
    """轻量交互菜单。

    入口只展示六个领域，具体动作进入二级菜单；输出风格与安装向导一致，
    不使用大边框、emoji 或重复说明。
    """

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def _print_header(self) -> None:
        ctx = self.ctx
        out(f"\nPylai Manager {__version__}")
        if not ctx.state.installed:
            out("  未安装")
            return
        running = ctx.docker.service_running()
        status = "运行中" if running else "已停止"
        out(f"  Pylai v{ctx.state.version} · {status} · {ctx.state.public_url}")

    @staticmethod
    def _read_choice() -> str:
        try:
            return input("› ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("\n已退出。")
            raise SystemExit(0)

    @staticmethod
    def _pause() -> None:
        try:
            input("\n按 Enter 继续")
        except (EOFError, KeyboardInterrupt):
            out()

    def run_submenu(self, title: str, items: list[tuple[str, Callable[[], None]]]) -> None:
        while True:
            self._print_header()
            out(f"\n? {title}")
            for idx, (label, _) in enumerate(items, 1):
                out(f"  {idx}. {label}")
            out("  b. 返回")
            out("  q. 退出")

            choice = self._read_choice()
            if choice in {"b", "back"}:
                return
            if choice in {"q", "quit", "exit"}:
                raise SystemExit(0)

            try:
                index = int(choice) - 1
                if index < 0 or index >= len(items):
                    raise ValueError
                items[index][1]()
                self._pause()
            except (ValueError, IndexError):
                out("! 选择无效。")
            except ManageError as exc:
                out(f"! {exc}")
                self._pause()
            except SystemExit:
                raise
            except Exception as exc:
                out(f"! 未预期错误: {exc}")
                self._pause()

    def run(self) -> None:
        self.auto_check_notify()
        while True:
            self._print_header()
            out("\n? 选择操作")
            items = [
                ("安装与更新", self._install_update),
                ("服务", self._service),
                ("配置", self._config),
                ("用户", self._users),
                ("数据与安全", self._data_security),
                ("工具与设置", self._tools),
            ]
            for idx, (label, _) in enumerate(items, 1):
                out(f"  {idx}. {label}")
            out("  q. 退出")

            choice = self._read_choice()
            if choice in {"q", "quit", "exit", "0"}:
                return
            try:
                index = int(choice) - 1
                if index < 0 or index >= len(items):
                    raise ValueError
                items[index][1]()
            except (ValueError, IndexError):
                out("! 选择无效。")
            except ManageError as exc:
                out(f"! {exc}")
                self._pause()
            except SystemExit:
                raise
            except Exception as exc:
                out(f"! 未预期错误: {exc}")
                self._pause()

    def _install_update(self) -> None:
        items: list[tuple[str, Callable[[], None]]] = []
        if self.ctx.state.installed:
            items.extend([
                ("更新 Pylai", lambda: UpdateService(self.ctx).update_interactive()),
                ("检查更新", self._check_updates),
                ("卸载 Pylai", lambda: uninstall(self.ctx, yes=False, purge=False)),
            ])
        else:
            items.append(("安装 Pylai", lambda: InstallService(self.ctx).install_interactive()))
        self.run_submenu("安装与更新", items)

    def _check_updates(self) -> None:
        service = UpdateService(self.ctx)
        service.check_manager_update()
        service.check_app_update()

    def _service(self) -> None:
        items: list[tuple[str, Callable[[], None]]] = [
            ("查看状态", lambda: service_action(self.ctx, "status")),
        ]
        if self.ctx.state.installed:
            items.extend([
                ("启动", lambda: service_action(self.ctx, "start")),
                ("停止", lambda: service_action(self.ctx, "stop")),
                ("重启", lambda: service_action(self.ctx, "restart")),
                ("组件管理", lambda: ComponentService(self.ctx).manage()),
                ("查看最近日志", lambda: self.ctx.docker.view_logs(200)),
                ("实时日志", lambda: self.ctx.docker.view_logs(200, follow=True)),
            ])
        self.run_submenu("服务", items)

    def _config(self) -> None:
        service = ConfigService(self.ctx)
        items: list[tuple[str, Callable[[], None]]] = [
            ("查看配置（脱敏）", service.view),
            ("校验配置", service.validate),
        ]
        if self.ctx.state.installed:
            items.extend([
                ("网页编辑", service.edit_in_web),
                ("文本编辑", service.edit),
                ("修改公开地址", service.change_url),
                ("修改端口", service.change_ports),
                ("修改 SMTP", service.change_smtp),
                ("修改 MFA", service.change_mfa),
                ("生成主机 Nginx 配置", service.generate_nginx),
            ])
        self.run_submenu("配置", items)

    def _users(self) -> None:
        self.ctx.require_running()
        users = UserService(self.ctx)
        self.run_submenu(
            "用户",
            [
                ("用户列表", users.list_users),
                ("查看用户详情", users.show_user),
                ("创建用户", lambda: users.create_user(interactive=True)),
                ("删除用户", users.delete_user),
                ("修改用户密码", users.reset_password),
                ("移除 TOTP 认证器", users.remove_totp),
                ("设置用户组", lambda: users.set_group(interactive=True)),
                ("设置用户状态", lambda: users.set_status(interactive=True)),
                ("吊销用户全部会话", users.revoke_sessions),
            ],
        )

    def _data_security(self) -> None:
        self.ctx.require_installed()
        backup = BackupService(self.ctx)
        items: list[tuple[str, Callable[[], None]]] = [
            ("创建数据库备份", backup.export),
            ("恢复数据库备份", backup.restore_interactive),
            ("查看备份", backup.list_backups),
        ]
        if self.ctx.docker.service_running():
            security = SecurityService(self.ctx)
            items.extend([
                ("签名密钥状态", security.key_status),
                ("轮换签名密钥", security.key_rotate),
                ("数据库迁移状态", security.db_status),
                ("执行 db bootstrap", security.db_bootstrap),
            ])
        self.run_submenu("数据与安全", items)

    def _tools(self) -> None:
        settings = SettingsService(self.ctx)
        self.run_submenu(
            "工具与设置",
            [
                ("检查并更新管理工具", self._self_update),
                ("查看管理工具设置", settings.view),
                ("修改镜像源", settings.change_mirror),
                ("自动检查更新", settings.change_auto_check),
                ("包含预发布版本", settings.change_include_prerelease),
                ("下载缓存目录", settings.change_download_dir),
                ("更新前自动备份", settings.change_auto_backup),
            ],
        )

    def _self_update(self) -> None:
        client = ReleaseClient(self.ctx.manager)
        updater = SelfUpdater(client, self.ctx.manager, self.ctx.state)
        if result := updater.check():
            version, _ = result
            out(f"可更新到 ManagePylai {version}")
            if ask_bool("现在更新？", True):
                updater.update()
        else:
            out("当前已是最新版本，或暂时无法获取版本信息。")

    def auto_check_notify(self) -> None:
        """启动时按 AutoCheck 静默检查，只输出一行必要提示。"""
        ctx = self.ctx
        if not ctx.manager.auto_check:
            return
        try:
            client = ReleaseClient(ctx.manager)
            latest = client.check_latest()
        except Exception:
            return
        if not latest:
            return

        version, _, info = latest
        updater = SelfUpdater(client, ctx.manager, ctx.state)
        notices: list[str] = []
        if updater.version_gt(version, __version__) and ctx.manager.skip_version != version:
            notices.append(f"ManagePylai {version}")
        if ctx.state.installed and updater.version_gt(version, ctx.state.version):
            app = f"Pylai {version}"
            if info and "dbSchemaVersion" in info:
                app += f" (schema {info['dbSchemaVersion']})"
            notices.append(app)
        if notices:
            out("更新可用: " + "；".join(notices))


def cmd_install(ctx: AppContext, args: argparse.Namespace) -> None:
    if ctx.state.installed:
        raise ManageError("检测到已有安装。如需重新安装，请先卸载。")

    InstallService(ctx).install_cli(args)


def cmd_update(ctx: AppContext, args: argparse.Namespace) -> None:
    UpdateService(ctx).update_cli(args)


def cmd_self_update(ctx: AppContext, args: argparse.Namespace) -> None:
    client = ReleaseClient(ctx.manager)
    updater = SelfUpdater(client, ctx.manager, ctx.state)

    if args.check_only:
        if result := updater.check():
            version, _ = result
            out(f"最新版本: {version}")
        else:
            out("当前已是最新，或无法获取版本信息。")
    else:
        updater.update(force=args.force, dry_run=args.dry_run, skip_prompt=args.yes)


def cmd_logs(ctx: AppContext, args: argparse.Namespace) -> None:
    ctx.require_installed()

    tail = getattr(args, "tail", 200)
    if args.follow:
        ctx.docker.view_logs(tail=tail, follow=True, service=args.service, verbose=args.verbose)
    else:
        text = ctx.docker.logs_text(tail=tail, service=args.service)
        out(text.strip() or "（暂无日志输出）")


def cmd_config(ctx: AppContext, args: argparse.Namespace) -> None:
    service = ConfigService(ctx)

    match args.config_cmd:
        case "view":
            service.view()
        case "edit":
            service.edit()
        case "web-edit":
            service.edit_in_web()
        case "validate":
            service.validate()
        case "generate-nginx":
            service.generate_nginx()
        case _:
            raise ManageError("请指定 config 子命令: view / edit / web-edit / validate / generate-nginx")


def cmd_backup(ctx: AppContext, args: argparse.Namespace) -> None:
    service = BackupService(ctx)

    match args.backup_cmd:
        case "create":
            service.export()
        case "list":
            service.list_backups()
        case "restore":
            if not args.file:
                raise ManageError("请指定备份文件路径")

            file_path = Path(args.file).expanduser()

            if not args.yes and not confirm_danger(
                f"将用 {file_path.name} 全量覆盖当前数据库，且不可撤销。"
            ):
                out("已取消。")
                return

            service.restore_file(file_path)
        case _:
            raise ManageError("请指定 backup 子命令: create / list / restore <file>")


def cmd_uninstall(ctx: AppContext, args: argparse.Namespace) -> None:
    uninstall(ctx, yes=args.yes, purge=args.purge)


def cmd_rotate_keys(ctx: AppContext, args: argparse.Namespace) -> None:
    SecurityService(ctx).key_rotate()


def cmd_user(ctx: AppContext, args: argparse.Namespace) -> None:
    ctx.require_running()
    service = UserService(ctx)

    match args.user_cmd:
        case "list":
            service.list_users()
        case "show":
            service.show_user(args.target)
        case "create":
            service.create_user(
                email=args.email,
                name=args.name or "",
                group=args.group or "normal",
                interactive=False,
            )
        case "delete":
            service.delete_user(args.target, assume_yes=args.yes)
        case "set-group":
            service.set_group(args.target, args.group, interactive=False)
        case "set-status":
            service.set_status(args.target, args.status, interactive=False)
        case "revoke-sessions":
            service.revoke_sessions(args.target)
        case "reset-password":
            service.reset_password(args.target, args.password, privileged=False)
        case "remove-totp":
            service.remove_totp(args.target)
        case _:
            raise ManageError("请指定 user 子命令")


# ============================================================================
# 主入口
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ManagePylai.pyz",
        description="Pylai Docker Compose 部署管理工具",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="显示管理工具版本并退出",
    )
    parser.add_argument(
        "--config",
        dest="manager_config",
        default=str(HOME / "ManagerConfig.toml"),
        help="ManagerConfig.toml 路径（默认 ~/.pylai/ManagerConfig.toml）",
    )
    parser.add_argument("--yes", action="store_true", help="非交互模式，所有确认默认 Yes")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的操作")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    install_p = subparsers.add_parser("install", help="安装 Pylai")
    install_p.add_argument("--config-file", dest="pylai_config", help="从现有 pylai.toml 非交互安装")
    install_p.add_argument("--env-file", help="从 .env 文件非交互安装")
    install_p.add_argument(
        "--compat",
        action="store_true",
        help="兼容模式：镜像未提供 pylai.template.toml 时回退到 pylai.example.toml（不推荐）",
    )
    install_p.add_argument(
        "--from-remote",
        action="store_true",
        help="从云端 GitHub Release 下载安装包（不读本地 tar）",
    )
    install_p.add_argument(
        "--version",
        help="指定要安装的版本号（如 0.0.25；缺省取最新；仅与 --from-remote 搭配）",
    )
    install_p.add_argument(
        "--force",
        action="store_true",
        help="忽略下载缓存，强制重新下载",
    )

    update_p = subparsers.add_parser("update", help="更新 Pylai")
    update_p.add_argument("--check-only", action="store_true", help="只检查更新（管理工具 + Pylai 应用），不执行")
    update_p.add_argument("--force-pg-upgrade", action="store_true", help="跳过 PostgreSQL 大版本升级检查（数据可丢弃或已迁移时使用）")
    update_p.add_argument(
        "--from-remote",
        action="store_true",
        help="从云端 GitHub Release 下载并更新（不读本地 tar）",
    )
    update_p.add_argument(
        "--version",
        help="指定要更新到的版本号（如 0.0.25；缺省取最新；仅与 --from-remote 搭配）",
    )
    update_p.add_argument(
        "--force",
        action="store_true",
        help="忽略下载缓存，强制重新下载",
    )

    self_update_p = subparsers.add_parser("self-update", help="更新管理工具自身")
    self_update_p.add_argument("--check-only", action="store_true")
    self_update_p.add_argument("--force", action="store_true")

    for name, help_text in (
        ("start", "启动服务"),
        ("stop", "停止服务"),
        ("restart", "重启服务"),
        ("status", "查看状态"),
    ):
        subparsers.add_parser(name, help=help_text)

    logs_p = subparsers.add_parser("logs", help="查看日志")
    logs_p.add_argument(
        "service",
        nargs="?",
        default="all",
        choices=["backend", "nginx", "postgres", "redis", "all"],
        help="服务名",
    )
    logs_p.add_argument(
        "-f", "--follow",
        action="store_true",
        help="持续跟踪（实时流式输出，按 Ctrl+C 退出）",
    )
    logs_p.add_argument(
        "--tail",
        type=str,
        default="200",
        help="显示最后 N 行（默认 200，all 表示全部）",
    )

    config_p = subparsers.add_parser("config", help="配置管理")
    config_sub = config_p.add_subparsers(dest="config_cmd")
    config_sub.add_parser("view", help="查看当前配置（脱敏）")
    config_sub.add_parser("edit", help="编辑 pylai.toml")
    config_sub.add_parser("web-edit", help="在网页中编辑配置（临时密码验证）")
    config_sub.add_parser("validate", help="验证配置合法性")
    config_sub.add_parser("generate-nginx", help="生成主机 Nginx 配置模板")

    backup_p = subparsers.add_parser("backup", help="备份管理")
    backup_sub = backup_p.add_subparsers(dest="backup_cmd")
    backup_sub.add_parser("create", help="创建备份")
    backup_sub.add_parser("list", help="列出备份")

    restore_p = backup_sub.add_parser("restore", help="从备份恢复")
    restore_p.add_argument("file", nargs="?")

    uninstall_p = subparsers.add_parser("uninstall", help="卸载")
    uninstall_p.add_argument("--purge", action="store_true", help="完全卸载（删除所有数据）")

    subparsers.add_parser("rotate-keys", help="轮换签名密钥")

    user_p = subparsers.add_parser("user", help="用户管理")
    user_sub = user_p.add_subparsers(dest="user_cmd")

    user_sub.add_parser("list", help="用户列表")

    show_p = user_sub.add_parser("show", help="查看用户")
    show_p.add_argument("target", nargs="?")

    create_p = user_sub.add_parser("create", help="创建用户")
    create_p.add_argument("--email", help="邮箱")
    create_p.add_argument("--name", help="登录名")
    create_p.add_argument("--group", choices=["normal", "admin", "max"], help="用户组")

    delete_p = user_sub.add_parser("delete", help="删除用户")
    delete_p.add_argument("target", nargs="?")

    set_group_p = user_sub.add_parser("set-group", help="设置用户组")
    set_group_p.add_argument("target", nargs="?")
    set_group_p.add_argument("group", nargs="?")

    set_status_p = user_sub.add_parser("set-status", help="设置用户状态")
    set_status_p.add_argument("target", nargs="?")
    set_status_p.add_argument("status", nargs="?")

    revoke_p = user_sub.add_parser("revoke-sessions", help="吊销会话")
    revoke_p.add_argument("target", nargs="?")

    reset_password_p = user_sub.add_parser("reset-password", help="重置密码")
    reset_password_p.add_argument("target", nargs="?")
    reset_password_p.add_argument("--password", help="新密码")

    remove_totp_p = user_sub.add_parser("remove-totp", help="移除用户已绑定的 TOTP 认证器")
    remove_totp_p.add_argument("target", nargs="?")

    return parser


COMMANDS: dict[str, Callable[[AppContext, argparse.Namespace], None]] = {
    "install": cmd_install,
    "update": cmd_update,
    "self-update": cmd_self_update,
    "start": lambda ctx, _a: service_action(ctx, "start"),
    "stop": lambda ctx, _a: service_action(ctx, "stop"),
    "restart": lambda ctx, _a: service_action(ctx, "restart"),
    "status": lambda ctx, _a: service_action(ctx, "status"),
    "logs": cmd_logs,
    "config": cmd_config,
    "backup": cmd_backup,
    "uninstall": cmd_uninstall,
    "rotate-keys": cmd_rotate_keys,
    "user": cmd_user,
}


def main() -> None:
    args = build_parser().parse_args()
    ctx = AppContext.create(Path(args.manager_config) if args.manager_config else None)

    try:
        ctx.docker.ensure_docker()

        if args.command is None:
            InteractiveMenu(ctx).run()
        elif handler := COMMANDS.get(args.command):
            handler(ctx, args)
        else:
            out("未知命令。")
            raise SystemExit(1)

    except ManageError as exc:
        out(f"错误: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        out(f"未预期错误: {exc}")
        raise SystemExit(1)

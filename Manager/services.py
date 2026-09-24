#!/usr/bin/env python3
"""ManagePylai 业务服务：备份、用户、安全、配置与工具设置。"""

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
import select
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
    ADVANCED_COMPONENTS,
    AppContext,
    BACKUP_DIR,
    CONFIG_FILE,
    ComposeConfig,
    DEFAULT_DOWNLOAD_DIR,
    GROUP_OPTIONS,
    InstallAnswers,
    Json,
    ManageError,
    PYLAI_CONFIG_ARG,
    STATUS_OPTIONS,
    TomlText,
    UserGroup,
    ask,
    ask_bool,
    ask_int,
    atomic_write,
    choose,
    configure_smtp_interactive,
    confirm_danger,
    ensure_home,
    generate_host_nginx_template,
    is_valid_url,
    out,
    read_password_policy,
    toml_list,
    toml_str,
    validate_password_local,
)
from editor import (
    ConfigEditorServer,
    EDITOR_CTX,
    find_free_port,
    generate_editor_password,
)

class BackupService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def export(self) -> None:
        ctx = self.ctx
        ctx.require_running()
        ensure_home()

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"manage-export-{stamp}"

        ctx.docker.exec_pylaios(
            "backup",
            "create",
            name,
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=1200,
        )

        ctx.docker.compose(
            "cp",
            f"backend:/var/lib/pylai/backups/{name}.dump",
            BACKUP_DIR / f"{name}.dump",
            timeout=1200,
        )

        out(f"已导出: {BACKUP_DIR / (name + '.dump')}")

    def list_backups(self) -> None:
        backups = sorted(BACKUP_DIR.glob("*.dump"))
        if not backups:
            out("备份目录为空。")
            return

        for path in backups:
            out(f"{path.name}  {path.stat().st_size} bytes")

    def restore_interactive(self) -> None:
        backups = sorted(
            BACKUP_DIR.glob("*.dump"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not backups:
            out("没有可用备份。请先执行导出，或将 .dump 放入备份目录。")
            return

        name = choose([(p.name, p.name) for p in backups], "请选择要导入的备份")
        if not name:
            return

        if not confirm_danger(f"将用 {name} 全量覆盖当前数据库，且不可撤销。"):
            out("已取消。")
            return

        self.restore_file(BACKUP_DIR / name)

    def restore_file(self, path: Path) -> None:
        ctx = self.ctx
        ctx.require_installed()

        if not path.is_file():
            raise ManageError(f"备份文件不存在: {path}")

        if not ctx.docker.service_running():
            ctx.docker.compose("up", "-d", timeout=120)
            ctx.docker.wait_healthy(ctx.state.api_port)

        name = path.name

        ctx.docker.compose(
            "cp",
            path,
            f"backend:/var/lib/pylai/backups/{name}",
            timeout=1200,
        )

        # 拆分模式下 PostgreSQL 为独立服务，pg_restore --clean 支持活动连接，
        # 无需停止 backend（停止后 compose exec 无法执行，旧逻辑必然失败）
        ctx.docker.exec_pylaios(
            "backup",
            "restore",
            name,
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=1800,
        )

        if ctx.docker.wait_healthy(ctx.state.api_port):
            out("导入完成，服务已恢复。")
        else:
            out("导入命令已完成，但健康检查未通过，请查看日志。")


class UserService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def execute(self, *args: str, input_text: str | None = None) -> Json:
        result = self.ctx.docker.exec_pylaios(
            "user",
            *args,
            "--config",
            PYLAI_CONFIG_ARG,
            stdin=input_text,
            timeout=120,
            check=False,
        )

        with suppress(json.JSONDecodeError):
            return json.loads(result.stdout.strip())

        out(result.stdout.strip() or result.stderr.strip())
        return {"success": False}

    def list_users(self) -> None:
        data = self.execute("list")
        if not data.get("success"):
            out("获取用户列表失败。")
            return

        users = data.get("users", [])
        total = data.get("total", 0)

        out(f"共 {total} 位用户：")
        out(f"{'UID':<36} {'用户名':<20} {'显示名':<20} {'邮箱':<30} {'组':<8} {'状态':<8}")
        out("-" * 120)

        for user in users:
            out(
                f"{user.get('uid', ''):<36} "
                f"{user.get('name', ''):<20} "
                f"{user.get('displayName', '') or '-':<20} "
                f"{user.get('email', ''):<30} "
                f"{user.get('group', ''):<8} "
                f"{user.get('status', ''):<8}"
            )

    def show_user(self, target: str | None = None) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")
        data = self.execute("show", target)

        if not data.get("success"):
            out("用户不存在或查询失败。")
            return

        user = data.get("user", {})

        out(f"UID:         {user.get('uid')}")
        out(f"用户名:      {user.get('name')}")
        out(f"显示名:      {user.get('displayName')}")
        out(f"邮箱:        {user.get('email')}")
        out(f"组:          {user.get('group')}")
        out(f"状态:        {user.get('status')}")
        out(f"注册时间:    {user.get('registerTime')}")
        out(f"最后登录:    {user.get('lastLoginAt') or '从未登录'}")
        out(f"活跃会话数:  {user.get('activeSessions', 0)}")
        out(f"TOTP 认证器: {'已绑定' if user.get('totpEnabled') else '未绑定'}")
        out(f"Passkey:     {user.get('webAuthnCount', 0)} 个")

        if user.get("externalLogins"):
            out("外部登录绑定:")
            for login in user["externalLogins"]:
                out(f"  - {login['provider']} ({login['boundAt']})")

    def create_user(
        self,
        *,
        email: str | None = None,
        name: str = "",
        display_name: str = "",
        group: UserGroup = "normal",
        interactive: bool = False,
    ) -> None:
        email = email or ask("邮箱")

        if interactive:
            name = ask("登录名（留空使用邮箱前缀）", "", allow_blank=True)
            display_name = ask("显示名（留空使用登录名）", "", allow_blank=True)
            group = choose(GROUP_OPTIONS, "请选择用户组") or "normal"

        base_args = [
            "create",
            email,
            "--name",
            name or "",
            "--display-name",
            display_name or "",
            "--group",
            group,
        ]

        policy = read_password_policy()
        privileged = group in {"admin", "max"}

        if interactive and ask_bool("手动指定密码？（留空则自动生成）", False):
            while True:
                password = ask("密码", "", secret=True)
                errors = validate_password_local(password, policy, privileged=privileged)

                if not errors:
                    break

                out(f"密码不符合策略: {', '.join(errors)}")
                if not ask_bool("重新输入？"):
                    return

            data = self.execute(*base_args, "--password-stdin", input_text=password + "\n")
        else:
            data = self.execute(*base_args)

        if data.get("success"):
            out(f"创建成功: {data.get('message')}")

            if "generatedPassword" in data:
                out(f"自动生成的密码: {data['generatedPassword']}")
                out("请立即保存，该密码不会再次显示。")
        else:
            out(f"创建失败: {data.get('message', '未知错误')}")

    def delete_user(self, target: str | None = None, *, assume_yes: bool = False) -> None:
        target = target or ask("要删除的用户标识（uid/用户名/邮箱）")

        if not assume_yes and not confirm_danger(
            f"将软删除用户 {target}，其全部会话将被吊销，之后可重新启用。"
        ):
            out("已取消。")
            return

        data = self.execute("delete", target)
        out(data.get("message", "未知错误"))

    def hard_delete_user(self, target: str | None = None, *, assume_yes: bool = False) -> None:
        target = target or ask("要硬删除的用户标识（uid/用户名/邮箱）")

        if not assume_yes and not confirm_danger(
            f"将硬删除用户 {target}：物理删除全部数据且不可恢复，其用户名与邮箱将被释放，可被其他人注册。",
            required_word="HARD DELETE",
        ):
            out("已取消。")
            return

        data = self.execute("hard-delete", target)
        out(data.get("message", "未知错误"))

    def set_group(
        self,
        target: str | None = None,
        group: str | None = None,
        *,
        interactive: bool = False,
    ) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")

        if interactive:
            group = choose(GROUP_OPTIONS, "请选择新用户组") or "normal"
        else:
            group = group or ask("新用户组")

        data = self.execute("set-group", target, group)
        out(data.get("message", "未知错误"))

    def set_status(
        self,
        target: str | None = None,
        status: str | None = None,
        *,
        interactive: bool = False,
    ) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")

        if interactive:
            status = choose(STATUS_OPTIONS, "请选择新状态") or "active"
        else:
            status = status or ask("新状态")

        data = self.execute("set-status", target, status)
        out(data.get("message", "未知错误"))

    def revoke_sessions(self, target: str | None = None) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")
        data = self.execute("revoke-sessions", target)
        out(data.get("message", "未知错误"))

    def reset_password(
        self,
        target: str | None = None,
        password: str | None = None,
        *,
        privileged: bool = False,
    ) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")
        policy = read_password_policy()

        if password is None:
            while True:
                password = ask("新密码", "", secret=True)
                errors = validate_password_local(password, policy, privileged=privileged)

                if not errors:
                    break

                out(f"密码不符合策略: {', '.join(errors)}")
                if not ask_bool("重新输入？"):
                    return
        else:
            if errors := validate_password_local(password, policy, privileged=privileged):
                raise ManageError(f"密码不符合策略: {', '.join(errors)}")

        data = self.execute(
            "reset-password",
            target,
            "--password-stdin",
            input_text=password + "\n",
        )

        if data.get("success"):
            out(data.get("message", "密码已重置，该用户全部会话与 token 已吊销。"))
        else:
            out("密码重置失败。")

    def remove_totp(self, target: str | None = None) -> None:
        target = target or ask("用户标识（uid/用户名/邮箱）")

        data = self.execute("show", target)
        if not data.get("success"):
            out("用户不存在或查询失败。")
            return

        user = data.get("user", {})
        if not user.get("totpEnabled"):
            out(f"用户 {user.get('name', target)} 未绑定 TOTP 认证器，无需移除。")
            return

        passkeys = user.get("webAuthnCount", 0)

        if not confirm_danger(
            f"将移除用户 {user.get('name')} 已绑定的 TOTP 认证器（Passkey 不受影响），"
            f"并吊销其全部会话与 token；该账户当前 Passkey 数量为 {passkeys}。"
        ):
            out("已取消。")
            return

        data = self.execute("remove-totp", target)
        out(data.get("message", "未知错误"))


class SecurityService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def key_status(self) -> None:
        self.ctx.require_running()
        self.ctx.docker.exec_pylaios(
            "key",
            "status",
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=120,
        )

    def key_rotate(self) -> None:
        self.ctx.require_running()

        mfa_user = ask(
            "用于 MFA 验证的 Admin/Max 账户",
            self.ctx.state.get("max_email") or "max@pylai.local",
        )
        mfa_code = ask("该账户 TOTP 验证码", "", secret=True)

        if not mfa_code:
            raise ManageError("签名密钥轮换需要 MFA 验证码。")

        self.ctx.docker.exec_pylaios(
            "key",
            "rotate",
            "--mfa-user",
            mfa_user,
            "--mfa-code",
            mfa_code,
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=120,
        )

    def db_status(self) -> None:
        self.ctx.require_running()
        self.ctx.docker.exec_pylaios(
            "db",
            "status",
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=120,
        )

    def db_bootstrap(self) -> None:
        self.ctx.require_running()
        self.ctx.docker.exec_pylaios(
            "db",
            "bootstrap",
            "--config",
            PYLAI_CONFIG_ARG,
            timeout=120,
        )

class ConfigService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def view(self) -> None:
        if not CONFIG_FILE.is_file():
            out("配置文件不存在")
            return

        out(self.ctx.config.mask())

    def edit(self) -> None:
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(CONFIG_FILE)])

    def edit_in_web(self) -> None:
        if not CONFIG_FILE.is_file():
            out("配置文件不存在")
            return

        # 注入容器校验上下文：backend 容器运行时，保存后追加权威 config validate 兜底
        EDITOR_CTX.update(docker=self.ctx.docker)

        port = find_free_port()
        password = generate_editor_password()
        server = ConfigEditorServer(port, password)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        out(f"编辑器就绪，访问 http://127.0.0.1:{port} 编辑配置文件")
        out(f"临时密码 {password}")
        out("（按回车键关闭编辑器并返回上级菜单）")

        try:
            input()
        except (EOFError, KeyboardInterrupt):
            out()
        finally:
            server.shutdown()
            server.server_close()

        out("网页编辑器已关闭。")

    def validate(self) -> None:
        self.ctx.config.validate()
        out("配置校验通过。")

    def generate_nginx(self) -> None:
        self.ctx.require_installed()
        path = generate_host_nginx_template(self.ctx.state)
        out(f"模板已生成: {path}")
        out("请自行替换证书路径和 server_name，然后安装到 /etc/nginx/conf.d/ 并 reload。")

    def change_url(self) -> None:
        self.ctx.require_installed()

        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        new_url = ask("新公开地址", self.ctx.state.public_url)
        origin = new_url.rstrip("/")
        external_host = urlparse(new_url).hostname or "localhost"

        allowed_hosts = [external_host]
        if external_host not in {"localhost", "127.0.0.1", "::1"}:
            allowed_hosts.extend(("localhost", "127.0.0.1"))

        t = TomlText(CONFIG_FILE.read_text(encoding="utf-8"))
        t.set("[Frontend]", "Url", toml_str(new_url))
        t.set("[OpenIddict]", "Issuer", toml_str(origin))
        t.set("[OpenIddict]", "RequireHttps", "true" if origin.startswith("https://") else "false")
        t.set("[Server]", "AllowedHosts", toml_list(allowed_hosts))
        t.set("[Mfa]", "RelyingPartyId", toml_str(external_host))
        t.set("[Mfa]", "Origins", toml_list([origin]))
        t.set(
            "[Cookie]",
            "SecurePolicy",
            toml_str("Always" if origin.startswith("https://") else "SameAsRequest"),
        )

        atomic_write(CONFIG_FILE, str(t))

        self.ctx.state.set("public_url", new_url)
        self.ctx.state.save()

        out("配置已修改，注意：需要手动重启实例才能生效")

    def change_ports(self) -> None:
        self.ctx.require_installed()

        new_public = ask_int("新公开端口", self.ctx.state.public_port)
        new_api = ask_int("新本机 API 端口", self.ctx.state.api_port)

        self.ctx.state.set("public_port", new_public)
        self.ctx.state.set("api_port", new_api)

        env = self.ctx.docker.read_env()
        db_password = env.get("PYLAI_DB_PASSWORD", "")
        redis_password = env.get("PYLAI_REDIS_PASSWORD", "")

        if not db_password or not redis_password:
            self.ctx.state.save()
            out("无法读取现有环境变量，端口已记录，将在下次重建时生效。")
            return

        if ask_bool("端口映射需要重建服务才能生效，是否立即应用？", True):
            answers = InstallAnswers(
                public_url=self.ctx.state.public_url,
                public_port=new_public,
                api_port=new_api,
                db_user=env.get("PYLAI_DB_USER", "pylai"),
                db_name=env.get("PYLAI_DB_NAME", "pylai"),
                db_password=db_password,
                redis_password=redis_password,
            )

            self.ctx.docker.start(self.ctx.state.image, answers)

            if not self.ctx.docker.wait_healthy(new_api):
                self.ctx.docker.view_logs(60)
                raise ManageError("重建后健康检查未通过，请根据上方日志排查。")

            out("端口已更新并重建服务。")
        else:
            out("端口已记录，将在下次重建时生效。")

        self.ctx.state.save()

    def change_smtp(self) -> None:
        self.ctx.require_installed()

        if not CONFIG_FILE.is_file():
            out("配置文件不存在")
            return

        smtp = configure_smtp_interactive()
        if not smtp:
            out("已取消。")
            return

        t = TomlText(CONFIG_FILE.read_text(encoding="utf-8"))
        t.set("[Email]", "FromAddress", toml_str(smtp.sender))
        t.set_many("[Email.Smtp]", {
            "Host": toml_str(smtp.host),
            "Port": str(smtp.port),
            "Security": toml_str(smtp.security),
            "Username": toml_str(smtp.user),
            "Password": toml_str(smtp.password),
        })
        t.strip_line(r"(?m)^[ \t]*UseSsl[ \t]*=.*\n")
        atomic_write(CONFIG_FILE, str(t))

        out(f"SMTP 配置已更新：{smtp.host}:{smtp.port} / {smtp.security}")
        out("注意：需要手动重启实例才能生效")

    def change_mfa(self) -> None:
        self.ctx.require_installed()

        if not CONFIG_FILE.is_file():
            out("配置文件不存在")
            return

        text = CONFIG_FILE.read_text(encoding="utf-8")

        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            out(f"配置解析失败: {exc}")
            return

        mfa = parsed.get("Mfa", {})
        current_admin = bool(mfa.get("RequireForAdmin", False))
        current_max_webauthn = bool(mfa.get("RequireWebAuthnForMax", False))

        out("当前 MFA 配置：")
        out(f"  RequireForAdmin = {'true' if current_admin else 'false'}")
        out(f"  RequireWebAuthnForMax = {'true' if current_max_webauthn else 'false'}")

        new_admin = ask_bool("Admin 及以上角色登录时强制要求 MFA？", current_admin)
        new_max_webauthn = (
            ask_bool(
                "Max 角色强制使用 WebAuthn（需 HTTPS 环境，HTTP 内网部署请勿开启）？",
                current_max_webauthn,
            )
            if new_admin
            else False
        )

        t = TomlText(text)
        t.set_many("[Mfa]", {
            "RequireForAdmin": "true" if new_admin else "false",
            "RequireWebAuthnForMax": "true" if new_max_webauthn else "false",
        })
        atomic_write(CONFIG_FILE, str(t))
        out("MFA 配置已更新，注意：需要手动重启实例才能生效")

    def reset_password(self, kind: Literal["max", "admin"]) -> None:
        self.ctx.require_running()

        default_email = (
            self.ctx.state.get("max_email")
            if kind == "max"
            else self.ctx.state.get("admin_email")
        )

        email = ask("账号邮箱/登录名", default_email or f"{kind}@pylai.local")
        policy = read_password_policy()

        while True:
            password = ask("新密码", "", secret=True)
            errors = validate_password_local(password, policy, privileged=True)

            if not errors:
                break

            out(f"密码不符合策略: {', '.join(errors)}")
            if not ask_bool("重新输入？"):
                return

        UserService(self.ctx).reset_password(email, password, privileged=True)


# ============================================================================
# 管理工具设置（ManagerConfig.toml）
# ============================================================================
MIRROR_OPTIONS: list[tuple[str, str]] = [
    ("Github — GitHub 官方源", "Github"),
    ("ghproxy — GitHub 加速镜像", "ghproxy"),
    ("Custom — 自定义镜像源（需填 BaseUrl）", "Custom"),
]


class SettingsService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def view(self) -> None:
        manager = self.ctx.manager
        out("当前管理工具设置（~/.pylai/ManagerConfig.toml，可手动编辑）：")
        out(f"  [Manager.Source] Mirror      = {manager.mirror}")
        out(f"  [Manager.Source] BaseUrl     = {manager.custom_mirror_base or ''}")
        out(f"  [Updates]        AutoCheck       = {str(manager.auto_check).lower()}")
        out(f"  [Updates]        IncludePrerelease = {str(manager.include_prerelease).lower()}")
        out(f"  [Updates]        DownloadDir     = {manager.download_dir}")
        out(f"  [Security]       AutoBackupBeforeUpdate = {str(manager.auto_backup).lower()}")
        out(f"  [Logging]        Level           = {manager.logging_level}")

    def change_mirror(self) -> None:
        manager = self.ctx.manager
        chosen = choose(MIRROR_OPTIONS, "请选择更新/下载镜像源")
        if chosen is None:
            return

        if chosen == "Custom":
            base = ask(
                "自定义镜像源 BaseUrl（如 https://mirror.example.com，须能提供 releases/v<ver>/ 下载）",
                manager.custom_mirror_base or "",
            ).strip().rstrip("/")
            if not base or not is_valid_url(base):
                out("BaseUrl 必须是以 http(s) 开头的合法地址，已取消。")
                return
            manager.set_custom_mirror_base(base)
        else:
            manager.set_custom_mirror_base(None)

        manager.set_mirror(chosen)
        out(f"镜像源已设为 {chosen}。")

    def change_auto_check(self) -> None:
        manager = self.ctx.manager
        enabled = ask_bool("每次运行时自动检查更新并提示？", manager.auto_check)
        manager.set_auto_check(enabled)
        out(f"AutoCheck 已设为 {str(enabled).lower()}。")

    def change_include_prerelease(self) -> None:
        manager = self.ctx.manager
        enabled = ask_bool("版本列表是否包含预发布版本？", manager.include_prerelease)
        manager.set_include_prerelease(enabled)
        out(f"IncludePrerelease 已设为 {str(enabled).lower()}。")

    def change_download_dir(self) -> None:
        manager = self.ctx.manager
        current = manager.download_dir
        path = ask(f"下载缓存目录（留空恢复默认 {DEFAULT_DOWNLOAD_DIR}）", current).strip()
        manager.set_download_dir(path or str(DEFAULT_DOWNLOAD_DIR))
        out(f"DownloadDir 已设为 {manager.download_dir}。")

    def change_auto_backup(self) -> None:
        manager = self.ctx.manager
        enabled = ask_bool("更新前自动备份数据库？", manager.auto_backup)
        manager.set_auto_backup(enabled)
        out(f"AutoBackupBeforeUpdate 已设为 {str(enabled).lower()}。")


# ============================================================================
# 组件管理（单独开关 OS 后端 / 用户前端 / 管理面板）
# ============================================================================
COMPONENT_ITEMS: tuple[tuple[str, str], ...] = (
    ("backend", "Pylai OS 后端"),
    ("ui", "Pylai UI 用户前端"),
    ("adminui", "Admin UI 管理面板"),
)


def _component_lines(states: dict[str, bool], index: int) -> list[str]:
    lines: list[str] = []
    for idx, (key, label) in enumerate(COMPONENT_ITEMS):
        cursor = ">" if idx == index else " "
        box = "x" if states.get(key, True) else " "
        lines.append(f"  {cursor} [{box}] {label}")
    return lines


def _read_component_key() -> str:
    """原始模式下读一个按键，仅识别组件管理需要的键。"""
    fd = sys.stdin.fileno()

    def read_one(timeout: float | None = None) -> str:
        if timeout is not None:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                return ""
        return os.read(fd, 1).decode("utf-8", errors="ignore")

    ch = read_one()
    if ch == "\x1b":
        # 方向键为 ESC [ A/B；单独 ESC 取消（限时读取，避免阻塞等待后续字节）
        if read_one(0.05) == "[":
            return {"A": "up", "B": "down"}.get(read_one(0.05), "other")
        return "cancel"
    if ch in ("\r", "\n"):
        return "enter"
    if ch == " ":
        return "space"
    if ch in ("q", "Q", "\x03", "\x04"):
        return "cancel"
    return "other"


def _select_components_fallback(states: dict[str, bool]) -> dict[str, bool] | None:
    out("当前终端不支持键盘选择，改为逐个确认（直接回车保持当前值）。")
    result: dict[str, bool] = {}
    for key, label in COMPONENT_ITEMS:
        try:
            result[key] = ask_bool(f"{label} 启用？", states.get(key, True))
        except SystemExit:
            return None
    return result


def _select_components(current: dict[str, bool]) -> dict[str, bool] | None:
    """↑↓ 选择、Space 开关、Enter 确认、Esc/q 取消；非交互终端退化为逐个问答。"""
    states = {key: bool(current.get(key, True)) for key, _ in COMPONENT_ITEMS}

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _select_components_fallback(states)

    try:
        import termios
        import tty
    except ImportError:
        return _select_components_fallback(states)

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    index = 0
    printed = 0

    out("\n? 组件管理（↑↓ 选择 · Space 开关 · Enter 确认 · Esc 取消）")
    try:
        tty.setraw(fd)
        while True:
            body = _component_lines(states, index) + [""]
            if printed:
                sys.stdout.write(f"\x1b[{printed}A")
            for line in body:
                sys.stdout.write("\x1b[2K" + line + "\r\n")
            sys.stdout.flush()
            printed = len(body)

            key = _read_component_key()
            if key == "up":
                index = (index - 1) % len(COMPONENT_ITEMS)
            elif key == "down":
                index = (index + 1) % len(COMPONENT_ITEMS)
            elif key == "space":
                name = COMPONENT_ITEMS[index][0]
                states[name] = not states[name]
            elif key == "enter":
                return states
            elif key == "cancel":
                return None
    finally:
        # 丢弃选择期间残留的按键，避免其被后续确认问答误读（Fail Closed）
        with suppress(OSError, termios.error):
            termios.tcflush(fd, termios.TCIFLUSH)
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


class ComponentService:
    """组件管理：单独开关 OS 后端 / 用户前端 / 管理面板。

    OS 后端与用户前端属于高级操作（影响整体可用性，需二次确认）；Admin UI 是
    常规运维开关，可随时关闭或开启，不额外确认。
    """

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def manage(self) -> None:
        ctx = self.ctx
        ctx.require_installed()

        current = ctx.manager.components
        selected = _select_components(current)
        if selected is None:
            out("已取消。")
            return

        changed = {k: v for k, v in selected.items() if current.get(k, True) != v}
        if not changed:
            out("组件状态未变化。")
            return

        advanced = [key for key in changed if key in ADVANCED_COMPONENTS]
        if advanced:
            names = "、".join(label for key, label in COMPONENT_ITEMS if key in advanced)
            out(f"注意：{names} 的开关会影响整体可用性。")
            if not ask_bool("确认执行？", False):
                out("已取消。")
                return

        # 先在内存生效（供 Nginx 渲染读取），动作全部成功后再落盘，失败可重试
        ctx.manager.set_components(selected, save=False)

        if "ui" in changed or "adminui" in changed:
            ComposeConfig.write_nginx_conf(ctx.manager)
            self._reload_nginx()

        if "backend" in changed:
            if selected["backend"]:
                ctx.docker.compose("up", "-d", "backend", timeout=180)
            else:
                ctx.docker.compose("stop", "-t", "30", "backend", timeout=120)

        ctx.manager.save()

        for key, label in COMPONENT_ITEMS:
            if key in changed:
                out(f"  {'已启用' if selected[key] else '已关闭'} {label}")

    def _reload_nginx(self) -> None:
        docker = self.ctx.docker
        if not docker.service_running("nginx"):
            out("提示：Nginx 未运行，组件配置将在下次启动时生效。")
            return

        result = docker.compose(
            "exec", "-T", "nginx", "nginx", "-s", "reload",
            check=False, timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ManageError(f"Nginx 重载失败（配置已写入，可手动重启服务生效）: {detail}")
        out("Nginx 已重载，前端组件开关即时生效。")


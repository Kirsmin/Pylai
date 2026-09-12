#!/usr/bin/env python3
"""ManagePylai 安装、更新与安装向导。"""

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

from managepylai_core import (
    AppContext,
    CONFIG_DIR,
    CONFIG_FILE,
    CONTAINER_CERT_DIR,
    ComposeConfig,
    InstallAnswers,
    Json,
    ManageError,
    PYLAIOS_BIN,
    PYLAI_CONFIG_ARG,
    PylaiConfig,
    ReleaseClient,
    SeedAccount,
    SelfUpdater,
    __version__,
    as_int,
    ask,
    ask_bool,
    choose_install_source,
    configure_smtp_interactive,
    ensure_remote_tar,
    ensure_signing_kek,
    generate_encryption_pfx,
    host_arch,
    import_pfx,
    normalize_release_version,
    out,
    parse_env_file,
    parse_tar,
    resolve_remote_version,
    reveal_credentials,
    run,
    select_tar,
    split_csv,
    toml_str,
    utc_now_iso,
    validate_answers,
)


# ============================================================================
# 新增：帮助系统
# ============================================================================
class HelpSystem:
    """统一帮助系统，每个配置项都有说明。"""

    TOPICS: dict[str, str] = {
        "public_url": """
对外访问地址是用户浏览器访问 Pylai 的完整 URL。
  • 内网部署: http://192.168.1.100:8080
  • 公网部署: https://pylai.example.com
  • 本地测试: http://localhost:8080

注意：这会影响 OAuth 回调和邮件链接的正确性。
        """,
        "public_port": """
容器 80 端口映射到主机的端口。
用户将通过 http://<主机IP>:<此端口> 访问 Pylai。
如果主机已有 Nginx 反代，建议避免使用 80/443。
        """,
        "api_port": """
后端 API 服务映射到本机的端口（仅绑定 127.0.0.1）。
外部无法直接访问，仅供内部健康检查和必要时的直接调用。
        """,
        "db_password": """
PostgreSQL 数据库密码，将自动生成强密码。
通常无需手动修改，除非有特定安全策略要求。
        """,
        "redis_password": """
Redis 缓存密码，将自动生成强密码。
        """,
        "trusted_proxies": """
可信代理 IP 是反向代理服务器（如 Nginx）的地址。
Pylai 需要知道这些地址才能正确解析用户真实 IP。

默认值 127.0.0.1,::1 适用于本机 Nginx 反代场景。
        """,
        "trusted_networks": """
可信网络 CIDR，来自这些网段的请求会被视为内部请求。
默认 172.16.0.0/12 覆盖 Docker 默认网桥范围。
        """,
        "smtp": """
SMTP 配置用于发送邮件通知（密码重置、邀请等）。
不配置则无法发送邮件，但系统仍可正常使用。
        """,
        "encryption_cert": """
OpenIddict 加密证书用于保护令牌安全。
生产环境必须配置持久化证书，否则容器重启后所有会话将失效。
        """,
        "mfa": """
MFA（多因素认证）可保护高权限账户安全。
• Admin 强制 MFA：登录时必须提供 TOTP 验证码
• Max 强制 WebAuthn：需 HTTPS 环境，使用硬件密钥/指纹等
        """,
    }

    @classmethod
    def show(cls, topic: str) -> None:
        if text := cls.TOPICS.get(topic):
            out(f"\n帮助 · {topic}")
            for line in text.strip().split("\n"):
                out(f"  {line}")
            out()
        else:
            out(f"! 暂无 {topic} 的帮助信息。")

    @classmethod
    def print_hint(cls, topic: str) -> None:
        """打印一行说明，不打断问答流。"""
        if text := cls.TOPICS.get(topic):
            first_line = text.strip().split("\n")[0].strip()
            out(f"  {first_line}")


# ============================================================================
# 新增：操作流水线 - 带步骤追踪和回滚
# ============================================================================
@dataclass
class PipelineStep:
    name: str
    fn: Callable[[], Any]
    rollback: Callable[[], None] | None = None
    checkpoint: bool = False


class OperationPipeline:
    """统一操作流水线：顺序明确、失败回滚、输出保持紧凑。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.steps: list[PipelineStep] = []
        self.completed: list[PipelineStep] = []
        self._results: list[Any] = []

    def add(
        self,
        name: str,
        fn: Callable[[], Any],
        *,
        rollback: Callable[[], None] | None = None,
        checkpoint: bool = False,
    ) -> Self:
        self.steps.append(PipelineStep(name, fn, rollback, checkpoint))
        return self

    def run(self) -> list[Any]:
        out(f"\n{self.name}")
        total = len(self.steps)
        for idx, step in enumerate(self.steps, 1):
            out(f"  {idx}/{total} {step.name} ... ", end="")
            try:
                result = step.fn()
                self.completed.append(step)
                self._results.append(result)
                out("完成")
            except Exception as exc:
                out("失败")
                out(f"! {exc}")
                self._handle_failure()
                raise
        out(f"{self.name}完成")
        return self._results

    def _handle_failure(self) -> None:
        rollback_steps = [step for step in reversed(self.completed) if step.rollback]
        if not rollback_steps:
            return
        out("  回滚已完成步骤")
        for step in rollback_steps:
            try:
                assert step.rollback is not None
                step.rollback()
                out(f"    {step.name}: 已回滚")
            except Exception as exc:
                out(f"    {step.name}: 回滚失败 ({exc})")


# ============================================================================
# 新增：安装向导 - 分阶段 + 可回退
# ============================================================================
class WizardBackError(Exception):
    """用户要求返回上一步。"""


class WizardSkipError(Exception):
    """用户要求跳过当前阶段。"""


@dataclass
class WizardPhase:
    name: str
    fields: list[str]
    required: bool = True
    help_topic: str = ""


class InstallWizard:
    """分阶段安装向导，支持返回上一步和查看帮助。"""

    PHASES: list[WizardPhase] = [
        WizardPhase("基础配置", ["public_url", "public_port", "api_port"], help_topic="public_url"),
        WizardPhase("数据库", ["db_user", "db_name"], help_topic="db_password"),
        WizardPhase("初始账号", ["max_account", "admin_account", "user_account"]),
        WizardPhase("邮件服务", ["smtp"], required=False, help_topic="smtp"),
        WizardPhase("安全证书", ["encryption_cert"], help_topic="encryption_cert"),
        WizardPhase("网络与安全", ["trusted_proxies", "trusted_networks", "cors", "mfa"], help_topic="trusted_proxies"),
    ]

    def __init__(self) -> None:
        self.answers = InstallAnswers()
        self._history: list[int] = []
        self._phase_idx = 0

    def run(self) -> InstallAnswers:
        """运行向导，返回收集到的答案。"""
        out("\nPylai 安装")
        out("  输入 ? 查看当前阶段帮助，< 返回上一阶段，! 跳过当前阶段。")

        while self._phase_idx < len(self.PHASES):
            phase = self.PHASES[self._phase_idx]
            if not phase.required:
                while True:
                    raw = input(
                        f"? {self._phase_idx + 1}/{len(self.PHASES)} {phase.name}（可选），是否配置? (y/N) › "
                    ).strip().lower()
                    if raw in {"?", "h", "help"}:
                        HelpSystem.show(phase.help_topic or phase.fields[0])
                        continue
                    if raw not in {"y", "yes"}:
                        self._phase_idx += 1
                        break
                    try:
                        self._collect_phase(phase)
                        self._history.append(self._phase_idx)
                        self._phase_idx += 1
                    except WizardBackError:
                        self._phase_idx = self._history.pop() if self._history else 0
                    except WizardSkipError:
                        self._phase_idx += 1
                    break
                continue

            try:
                self._collect_phase(phase)
                self._history.append(self._phase_idx)
                self._phase_idx += 1
            except WizardBackError:
                if self._history:
                    self._phase_idx = self._history.pop()
                else:
                    out("! 已经是第一阶段。")
            except WizardSkipError:
                self._phase_idx += 1

        return self.answers

    def _collect_phase(self, phase: WizardPhase) -> None:
        out(f"\n{self._phase_idx + 1}/{len(self.PHASES)} {phase.name}")
        if phase.help_topic:
            HelpSystem.print_hint(phase.help_topic)
        for field in phase.fields:
            self._collect_field(field)

    def _collect_field(self, field: str) -> None:
        match field:
            case "public_url":
                self.answers.public_url = self._ask(
                    "对外访问地址", self._detect_public_url(), help_topic="public_url"
                )
            case "public_port":
                self.answers.public_port = self._ask_int(
                    "公开端口", 8080, help_topic="public_port"
                )
            case "api_port":
                self.answers.api_port = self._ask_int(
                    "本机 API 端口", 5000, help_topic="api_port"
                )
            case "db_user":
                self.answers.db_user = self._ask("PostgreSQL 用户名", "pylai")
            case "db_name":
                self.answers.db_name = self._ask("PostgreSQL 数据库名", "pylai")
            case "max_account":
                self._collect_max_account()
            case "admin_account":
                self._collect_admin_account()
            case "user_account":
                self._collect_user_account()
            case "smtp":
                self._collect_smtp()
            case "encryption_cert":
                self._collect_encryption_cert()
            case "trusted_proxies":
                value = self._ask("可信代理 IP（逗号分隔）", "127.0.0.1,::1", help_topic="trusted_proxies")
                self.answers.trusted_proxies = split_csv(value)
            case "trusted_networks":
                value = self._ask("可信代理 CIDR（逗号分隔）", "172.16.0.0/12", help_topic="trusted_networks")
                self.answers.trusted_networks = split_csv(value)
            case "cors":
                value = self._ask("额外 CORS Origin（逗号分隔）", "", allow_blank=True)
                self.answers.extra_cors_origins = split_csv(value)
            case "mfa":
                self._collect_mfa()

    def _ask(
        self,
        prompt: str,
        default: str = "",
        *,
        secret: bool = False,
        allow_blank: bool = False,
        help_topic: str = "",
    ) -> str:
        default_hint = f" ({default})" if default else ""
        while True:
            prompt_line = f"? {prompt}{default_hint} › "
            try:
                raw = getpass.getpass(prompt_line) if secret else input(prompt_line)
            except (EOFError, KeyboardInterrupt):
                out("\n已退出。")
                raise SystemExit(0)

            value = raw.strip()
            if value == "?" and help_topic:
                HelpSystem.show(help_topic)
                continue
            if value == "<":
                if self._history:
                    raise WizardBackError()
                out("! 已经是第一阶段。")
                continue
            if value == "!":
                raise WizardSkipError()
            if value:
                return value
            if default is not None:
                return default
            if allow_blank:
                return ""
            out("! 该项不能为空。")

    def _ask_int(
        self,
        prompt: str,
        default: int,
        *,
        minimum: int = 1,
        maximum: int = 65535,
        help_topic: str = "",
    ) -> int:
        while True:
            raw = self._ask(prompt, str(default), help_topic=help_topic)
            with suppress(ValueError):
                value = int(raw)
                if minimum <= value <= maximum:
                    return value
            out(f"! 请输入 {minimum}-{maximum} 之间的数字。")

    def _ask_bool(self, prompt: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            value = self._ask(f"{prompt} ({hint})", "", allow_blank=True).strip().lower()
            if not value:
                return default
            if value in {"y", "yes", "1"}:
                return True
            if value in {"n", "no", "0"}:
                return False
            out("! 请输入 y 或 n。")

    def _detect_public_url(self) -> str:
        """检测建议的 public_url。"""
        # 尝试获取本机 IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and ip not in ("127.0.0.1", "localhost"):
                return f"http://{ip}:8080"
        except Exception:
            pass
        return "http://localhost:8080"

    def _collect_max_account(self) -> None:
        out("  Max 账号（必须）")
        email = self._ask("Max 账号邮箱/登录名", "max@pylai.local")
        password = self._ask("Max 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
        self.answers.max_account = SeedAccount(
            role="max",
            email=email,
            password=password,
            display_name="Max User",
        )

    def _collect_admin_account(self) -> None:
        if self._ask_bool("创建初始 Admin 账号？", True):
            email = self._ask("Admin 账号邮箱/登录名", "admin@pylai.local")
            password = self._ask("Admin 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
            self.answers.admin_account = SeedAccount(
                role="admin",
                email=email,
                password=password,
                display_name="Administrator",
            )

    def _collect_user_account(self) -> None:
        if self._ask_bool("创建初始 Normal 测试账号？", False):
            email = self._ask("Normal 账号邮箱/登录名", "user@pylai.local")
            password = self._ask("Normal 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
            self.answers.user_account = SeedAccount(
                role="user",
                email=email,
                password=password,
                display_name="Test User",
            )

    def _collect_smtp(self) -> None:
        if self._ask_bool("配置 SMTP 邮件发送？", False):
            smtp = configure_smtp_interactive()
            if smtp:
                self.answers.smtp = smtp

    def _collect_encryption_cert(self) -> None:
        out("  加密证书")
        HelpSystem.print_hint("encryption_cert")

        if shutil.which("openssl") and self._ask_bool("自动生成加密证书？", True):
            self.answers.encryption_pfx, self.answers.encryption_pfx_password = generate_encryption_pfx()
            out("  已生成加密证书")
        else:
            path = self._ask("加密 PFX 文件路径（留空则跳过，但生产环境必需）", "", allow_blank=True)
            if path:
                password = self._ask("加密 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
                self.answers.encryption_pfx = import_pfx(Path(path).expanduser(), "encryption.pfx")
                self.answers.encryption_pfx_password = password

    def _collect_mfa(self) -> None:
        out("  高权限账户 MFA")
        HelpSystem.print_hint("mfa")

        self.answers.mfa_for_admin = self._ask_bool("Admin 及以上角色登录时强制要求 MFA？", False)
        if self.answers.mfa_for_admin:
            self.answers.mfa_webauthn_for_max = self._ask_bool(
                "Max 角色强制使用 WebAuthn（需 HTTPS 环境，HTTP 内网部署请勿开启）？",
                False,
            )

class InstallService:
    """安装服务 - 新流程：必选项 → Web编辑器 → 启动容器。"""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # ========================================================================
    # 公共入口
    # ========================================================================
    def install_cli(self, args: argparse.Namespace) -> None:
        """CLI 入口。"""
        tar_path = self._resolve_install_tar(args)
        image = self.ctx.docker.load_image_tar(tar_path)

        # 判断模式
        from_existing = bool(args.pylai_config)
        use_env = bool(args.env_file or args.yes)
        interactive = not (args.yes or args.pylai_config or args.env_file)
        allow_compat = bool(getattr(args, "compat", False))

        if getattr(args, "dry_run", False):
            self._dry_run(image, args, allow_compat)
            return

        if from_existing:
            # 从现有配置安装
            answers = self._answers_from_config(args)
            self._run_install_pipeline(tar_path, image, answers, from_existing=True, interactive=False)
        elif use_env:
            # 非交互模式
            answers = self._answers_from_env(args)
            self._run_install_pipeline(tar_path, image, answers, from_existing=False, interactive=False, yes_mode=args.yes)
        else:
            # 交互模式：新向导流程
            self._interactive_install(tar_path, image, allow_compat=allow_compat)

    def install_interactive(self) -> None:
        """交互菜单入口。"""
        source = choose_install_source("请选择安装包的来源")
        client = ReleaseClient(self.ctx.manager)

        if source == "remote":
            version = resolve_remote_version(client, self.ctx.manager, prompt="请选择要安装的版本")
            tar_path = ensure_remote_tar(client, self.ctx.manager, version)
        else:
            tar_path = select_tar(yes=False)

        image = self.ctx.docker.load_image_tar(tar_path)
        self._interactive_install(tar_path, image, allow_compat=False)

    # ========================================================================
    # 新交互安装流程：必选项 → Web编辑器 → 启动
    # ========================================================================
    def _interactive_install(self, tar_path: Path, image: str, *, allow_compat: bool = False) -> None:
        """交互安装：问答 → 基础配置 → 可选网页编辑 → 确认 → 启动。"""
        ctx = self.ctx
        wizard = InstallWizard()
        answers = wizard.run()

        if not answers.db_password:
            answers.db_password = secrets.token_hex(16)
        if not answers.redis_password:
            answers.redis_password = secrets.token_hex(16)
        if not answers.invite_pepper:
            answers.invite_pepper = secrets.token_hex(32)

        out("\n生成基础配置")
        validate_answers(answers)
        PylaiConfig.generate_from_template(image, answers, allow_compat=allow_compat)
        ctx.config.reload()
        self.fix_container_hosts()
        ctx.config.validate()
        ComposeConfig.generate(answers, ctx.manager, image)
        ctx.docker.validate_compose()
        ensure_signing_kek()
        self.ensure_signing_certificate(answers)
        self.ensure_encryption_certificate(answers, interactive=True)
        out("基础配置已生成")

        if ask_bool("打开网页配置编辑器调整高级配置？", True):
            try:
                self._run_web_editor()
            except Exception as exc:
                out(f"! 网页编辑器异常: {exc}")
                if not ask_bool("继续使用当前配置？", True):
                    raise ManageError("安装已取消。") from exc

        ctx.config.reload()
        out("\n确认配置")
        self._preview_config(answers)
        if not ask_bool("现在启动 Pylai？", True):
            out("已保存配置，未启动服务。")
            return

        self._run_install_pipeline(
            tar_path,
            image,
            answers,
            from_existing=False,
            interactive=True,
            yes_mode=False,
            skip_config=True,
        )

    def _run_web_editor(self) -> None:
        """启动网页编辑器并等待用户完成。"""
        from managepylai_editor import (
            ConfigEditorServer,
            EDITOR_CTX,
            find_free_port,
            generate_editor_password,
        )

        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        # 注入容器校验上下文
        EDITOR_CTX.update(docker=self.ctx.docker)

        port = find_free_port()
        password = generate_editor_password()
        server = ConfigEditorServer(port, password)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        out(f"\n网页编辑器: http://127.0.0.1:{port}")
        out(f"临时密码: {password}")
        out("保存后回到终端按 Enter 继续。")

        try:
            input()
        except (EOFError, KeyboardInterrupt):
            out()
        finally:
            server.shutdown()
            server.server_close()

        out("网页编辑器已关闭")

    def _preview_config(self, answers: InstallAnswers) -> None:
        """显示配置摘要。"""
        out(f"  地址      {answers.public_url}")
        out(f"  公开端口  {answers.public_port}")
        out(f"  API 端口  {answers.api_port}")
        out(f"  数据库    {answers.db_user}@{answers.db_name}")
        out(f"  Max 账号  {answers.max_account.email}")
        if answers.admin_account:
            out(f"  Admin 账号 {answers.admin_account.email}")
        if answers.smtp.enabled:
            out(f"  SMTP      {answers.smtp.host}:{answers.smtp.port}")
        out(f"  加密证书  {'已配置' if answers.encryption_pfx else '未配置'}")

    # ========================================================================
    # 流水线安装（CLI 和最终启动共用）
    # ========================================================================
    def _run_install_pipeline(
        self,
        tar_path: Path,
        image: str,
        answers: InstallAnswers,
        *,
        from_existing: bool,
        interactive: bool,
        allow_compat: bool = False,
        yes_mode: bool = False,
        skip_config: bool = False,
    ) -> None:
        """使用 OperationPipeline 执行安装。"""
        ctx = self.ctx

        pipeline = OperationPipeline("Pylai 安装")

        # 步骤 1: 校验
        pipeline.add("校验输入与弱密码预检", lambda: validate_answers(answers))

        # 步骤 2: 生成配置（如需要）
        if not skip_config:
            def step_config() -> None:
                if not from_existing:
                    PylaiConfig.generate_from_template(image, answers, allow_compat=allow_compat)
                    ctx.config.reload()
                self.fix_container_hosts()
                ctx.config.validate()
            pipeline.add("生成配置", step_config, checkpoint=True)

        # 步骤 3: 生成 Compose
        def step_compose() -> None:
            ComposeConfig.generate(answers, ctx.manager, image)
            ctx.docker.validate_compose()
        pipeline.add("生成 Compose", step_compose)

        # 步骤 4: 创建数据卷
        pipeline.add("创建数据卷", ComposeConfig.ensure_volumes)

        # 步骤 5: 准备证书
        def step_certs() -> None:
            ensure_signing_kek()
            self.ensure_signing_certificate(answers)
            self.ensure_encryption_certificate(answers, interactive=interactive)
        pipeline.add("准备证书与 KEK", step_certs)

        # 步骤 6: 启动容器
        def step_start() -> None:
            ctx.docker.ensure_docker()
            ctx.docker.start(image, answers)
        pipeline.add("启动容器", step_start)

        # 步骤 7: 健康检查
        def step_health() -> None:
            out(f"\n==> 等待健康检查 http://127.0.0.1:{answers.api_port}/health/ready ...")
            healthy = ctx.docker.wait_healthy(answers.api_port, timeout=None, warn_after=300)
            if not healthy:
                ctx.docker.dump_diagnostics(tail=200)
                if interactive and not yes_mode:
                    out("\n[提示] 安装失败，现场已保留以便排查。")
                    if ask_bool("是否清理本次创建的容器与数据卷？", False):
                        with suppress(Exception):
                            ctx.docker.compose("down", "-v", check=False)
                raise ManageError("服务启动失败，请根据上方诊断信息排查。")
        pipeline.add("健康检查", step_health)

        # 执行流水线
        pipeline.run()

        # 保存状态
        self.save_state(tar_path, image, answers)
        self.print_summary(answers)

    # ========================================================================
    # 辅助方法
    # ========================================================================
    def _resolve_install_tar(self, args: argparse.Namespace) -> Path:
        """解析安装包来源。"""
        from_remote = bool(getattr(args, "from_remote", False))
        if from_remote:
            client = ReleaseClient(self.ctx.manager)
            version = resolve_remote_version(
                client, self.ctx.manager,
                requested=getattr(args, "version", None),
                yes=bool(args.yes),
                prompt="请选择要安装的版本",
            )
            return ensure_remote_tar(client, self.ctx.manager, version, force=bool(getattr(args, "force", False)))
        return select_tar(yes=args.yes)

    def _answers_from_config(self, args: argparse.Namespace) -> InstallAnswers:
        """从现有配置提取答案。"""
        source = Path(args.pylai_config).expanduser()
        self.ctx.config = PylaiConfig.from_existing(source)
        answers = self.ctx.config.extract_answers()
        answers.public_port = as_int(os.environ.get("PYLAI_PUBLIC_PORT"), answers.public_port)
        answers.api_port = as_int(os.environ.get("PYLAI_API_PORT"), answers.api_port)
        if not answers.db_password or not answers.redis_password:
            raise ManageError("从现有配置无法提取数据库/Redis 密码，请检查 pylai.toml。")
        return answers

    def _answers_from_env(self, args: argparse.Namespace) -> InstallAnswers:
        """从环境变量提取答案。"""
        if args.env_file:
            return InstallAnswers.from_env(parse_env_file(Path(args.env_file).expanduser()))
        env = {k: v for k, v in os.environ.items() if k.startswith("PYLAI_")}
        return InstallAnswers.from_env(env)

    def _dry_run(self, image: str, args: argparse.Namespace, allow_compat: bool) -> None:
        """干运行模式。"""
        out("[dry-run] 预览安装配置（不实际启动）：")
        answers = self._answers_from_env(args) if args.env_file or args.yes else InstallAnswers.collect_interactive()
        validate_answers(answers)
        out(f"  public_url: {answers.public_url}")
        out(f"  public_port: {answers.public_port}  api_port: {answers.api_port}")
        out(f"  db: {answers.db_user}@{answers.db_name}  redis: ***")
        out(f"  image: {image}  compat: {allow_compat}")
        try:
            PylaiConfig.generate_from_template(image, answers, allow_compat=allow_compat)
            out("  配置模板渲染通过")
        except Exception as e:
            out(f"  配置生成失败: {e}")
        out("  Compose 预览: ~/.pylai/docker-compose.yml / ~/.pylai/.env")

    def fix_container_hosts(self) -> None:
        config = self.ctx.config

        connection_string = str(config.get_value("Database", "ConnectionString", ""))
        # 兼容 127.0.0.1 / localhost / 空主机 均修正为 postgres
        for old in ("Host=127.0.0.1", "Host=localhost"):
            if old in connection_string:
                connection_string = connection_string.replace(old, "Host=postgres")
                config.set_block_value(
                    "[Database]",
                    "ConnectionString",
                    toml_str(connection_string),
                )
                break

        redis_host = str(config.get_value("Redis", "Host", ""))
        if redis_host in {"127.0.0.1", "localhost"}:
            config.set_block_value("[Redis]", "Host", toml_str("redis"))
            config.set_block_value("[Redis]", "Port", "6379")

    def ensure_signing_certificate(self, answers: InstallAnswers) -> None:
        if answers.signing_pfx and not answers.signing_pfx.startswith(CONTAINER_CERT_DIR):
            answers.signing_pfx = import_pfx(
                Path(answers.signing_pfx).expanduser(),
                "signing.pfx",
            )

    def ensure_encryption_certificate(
        self,
        answers: InstallAnswers,
        *,
        interactive: bool,
    ) -> None:
        if answers.encryption_pfx and not answers.encryption_pfx.startswith(CONTAINER_CERT_DIR):
            answers.encryption_pfx = import_pfx(
                Path(answers.encryption_pfx).expanduser(),
                "encryption.pfx",
            )
        elif not answers.encryption_pfx:
            if shutil.which("openssl"):
                answers.encryption_pfx, answers.encryption_pfx_password = generate_encryption_pfx()
            elif interactive:
                raise ManageError("生产环境必须配置持久化 OpenIddict 加密证书。")
            else:
                out("警告：未找到 openssl，且未提供加密证书。")
                return

        if answers.encryption_pfx:
            self.ctx.config.reload()
            self.ctx.config.set_block_value(
                "[OpenIddict.Certificates.Encryption]",
                "Path",
                toml_str(answers.encryption_pfx),
            )
            self.ctx.config.set_block_value(
                "[OpenIddict.Certificates.Encryption]",
                "Password",
                toml_str(answers.encryption_pfx_password),
            )

    def save_state(self, tar_path: Path, image: str, answers: InstallAnswers) -> None:
        version, arch = parse_tar(tar_path) or (__version__, host_arch())
        state = self.ctx.state

        state.set("version", version)
        state.set("architecture", arch)
        state.set("image", image)
        state.set("public_url", answers.public_url)
        state.set("public_port", answers.public_port)
        state.set("api_port", answers.api_port)
        state.set("max_email", answers.max_account.email)
        state.set("admin_email", answers.admin_account.email if answers.admin_account else "")
        state.set("installed_at", utc_now_iso())
        state.set("mode", "compose")
        state.save()

    def print_summary(self, answers: InstallAnswers) -> None:
        out("\nPylai 安装完成")
        out(f"  用户端    {answers.public_url}/")
        out(f"  管理台    {answers.public_url}/admin/")
        out(f"  健康检查  http://127.0.0.1:{answers.api_port}/health/ready")

        reveal_credentials(answers.credentials)

        if auto := answers.auto_generated_accounts:
            out(
                f"  {', '.join(auto)} 的密码由后端按策略生成，"
                "可在容器日志的 [DbSeeder] 记录中查看。"
            )
        out("  可用 config generate-nginx 生成主机 Nginx 模板。")


class UpdateService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def _remote_reexec_args(
        self,
        target_version: str,
        *,
        yes: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        force_pg_upgrade: bool = False,
        force: bool = False,
    ) -> list[str]:
        """构造自更新后继续云端后端更新的等价命令行。"""
        argv = ["--config", str(self.ctx.manager.path)]
        if yes:
            argv.append("--yes")
        if dry_run:
            argv.append("--dry-run")
        if verbose:
            argv.append("--verbose")
        argv.extend(["update", "--from-remote", "--version", target_version])
        if force_pg_upgrade:
            argv.append("--force-pg-upgrade")
        if force:
            argv.append("--force")
        return argv

    def ensure_manager_for_remote_release(
        self,
        target_version: str,
        *,
        reexec_args: Sequence[str],
        yes: bool = False,
        dry_run: bool = False,
    ) -> None:
        """云端更新的强制前置步骤：先把 ManagePylai.py 更新到目标 Release。

        目标版本高于当前管理工具时，成功替换后会 os.execv 重新执行新版脚本，
        并携带同一后端更新参数继续执行；失败则 Fail Closed，不触碰后端。
        """
        target_version = normalize_release_version(target_version)
        if not SelfUpdater.version_gt(target_version, __version__):
            return

        out(
            f"==> 云端更新前置：目标 Pylai v{target_version} 高于管理工具 v{__version__}，"
            "先更新 ManagePylai.py。"
        )
        client = ReleaseClient(self.ctx.manager)
        updater = SelfUpdater(client, self.ctx.manager, self.ctx.state)
        updated = updater.update(
            target_version=target_version,
            skip_prompt=yes,
            dry_run=dry_run,
            reexec_args=reexec_args,
        )
        if dry_run and updated:
            return
        # 正常成功路径会在 updater.update 内 os.execv，不会走到这里。
        raise ManageError(
            "云端更新要求先更新 ManagePylai.py；管理工具未能更新，后端保持不变。"
        )

    def update_cli(self, args: argparse.Namespace) -> None:
        if args.check_only:
            self.check_manager_update()
            self.check_app_update()
            return

        from_remote = bool(getattr(args, "from_remote", False))
        if from_remote:
            client = ReleaseClient(self.ctx.manager)
            target_version = resolve_remote_version(
                client,
                self.ctx.manager,
                requested=getattr(args, "version", None),
                yes=args.yes,
                prompt="请选择要更新到的版本",
            )
            reexec_args = self._remote_reexec_args(
                target_version,
                yes=args.yes,
                dry_run=getattr(args, "dry_run", False),
                verbose=getattr(args, "verbose", False),
                force_pg_upgrade=args.force_pg_upgrade,
                force=getattr(args, "force", False),
            )
            self.ensure_manager_for_remote_release(
                target_version,
                reexec_args=reexec_args,
                yes=args.yes,
                dry_run=getattr(args, "dry_run", False),
            )
            self.update_app(
                yes=args.yes,
                force_pg_upgrade=args.force_pg_upgrade,
                source="remote",
                version=target_version,
                force=getattr(args, "force", False),
            )
            return

        # 本地 tar 更新保留原有“先检查管理工具最新版本”的行为。
        self.ensure_manager_up_to_date(args.yes)
        self.update_app(
            yes=args.yes,
            force_pg_upgrade=args.force_pg_upgrade,
            source="local",
            version=getattr(args, "version", None),
            force=getattr(args, "force", False),
        )

    def update_interactive(self) -> None:
        ctx = self.ctx
        client = ReleaseClient(ctx.manager)
        releases = client.list_releases(
            include_prerelease=ctx.manager.include_prerelease, limit=12)
        if not releases and not ctx.manager.include_prerelease:
            releases = client.list_releases(include_prerelease=True, limit=12)

        if not releases:
            source = choose_install_source("请选择更新包的来源") or "remote"
            if source == "local":
                self.ensure_manager_up_to_date(yes=False)
                self.update_app(yes=False, source="local", version=None)
                return

            target_version = resolve_remote_version(
                client, ctx.manager, requested=None, yes=False, prompt="请选择要更新到的版本")
            self.ensure_manager_for_remote_release(
                target_version,
                reexec_args=self._remote_reexec_args(target_version),
            )
            self.update_app(yes=False, source="remote", version=target_version)
            return

        out("云端可用的版本：")
        for index, release in enumerate(releases, 1):
            label = "预发布" if release["prerelease"] else "正式版"
            out(f"  [{index}] v{release['version']}（{label}）")
        out("（输入 + 可从本地磁盘安装 Pylai-<version>-Linux-<arch>.tar）")

        raw = ask("请选择要更新到的版本", default="1").strip()
        if raw == "+":
            self.ensure_manager_up_to_date(yes=False)
            self.update_app(yes=False, source="local", version=None)
            return

        try:
            chosen = normalize_release_version(releases[int(raw) - 1]["version"])
        except (ValueError, IndexError):
            raise ManageError("未选择版本。")

        self.ensure_manager_for_remote_release(
            chosen,
            reexec_args=self._remote_reexec_args(chosen),
        )
        self.update_app(yes=False, source="remote", version=chosen)

    def check_manager_update(self) -> None:
        client = ReleaseClient(self.ctx.manager)
        updater = SelfUpdater(client, self.ctx.manager, self.ctx.state)

        if result := updater.check():
            version, info = result
            out(f"最新 ManagePylai.py 版本: {version}")
            if "dbSchemaVersion" in info:
                out(f"  dbSchemaVersion: {info['dbSchemaVersion']}")
        else:
            out("当前已是最新，或无法获取版本信息。")

    def check_app_update(self) -> None:
        """报告云端最新 Pylai 应用版本（与已部署版本比较）。"""
        ctx = self.ctx
        if not ctx.state.installed:
            out("Pylai 未安装，无法比较版本。")
            return

        client = ReleaseClient(ctx.manager)
        latest = client.check_latest()
        if not latest:
            out("无法获取云端最新 Pylai 版本信息。")
            return

        version, _, info = latest
        updater = SelfUpdater(client, ctx.manager, ctx.state)
        if info and "dbSchemaVersion" in info:
            out(f"最新 Pylai 版本: v{version}（dbSchemaVersion: {info['dbSchemaVersion']}）")
        else:
            out(f"最新 Pylai 版本: v{version}")

        if updater.version_gt(version, ctx.state.version):
            out(f"> 当前已部署 v{ctx.state.version}，可执行 `update --from-remote --yes` 升级。")
        elif version == ctx.state.version:
            out(f"> 当前已是最新版本 v{ctx.state.version}。")
        else:
            out(f"> 当前部署 v{ctx.state.version} 高于云端最新 v{version}（已回滚/领先）。")

    def ensure_manager_up_to_date(self, yes: bool) -> None:
        client = ReleaseClient(self.ctx.manager)
        updater = SelfUpdater(client, self.ctx.manager, self.ctx.state)
        updater.ensure_up_to_date(yes=yes)

    def update_app(
        self,
        *,
        yes: bool,
        force_pg_upgrade: bool = False,
        source: str = "local",
        version: str | None = None,
        force: bool = False,
    ) -> None:
        ctx = self.ctx
        ctx.require_installed()

        self.check_pg_major_upgrade(force=force_pg_upgrade)

        if source == "remote":
            client = ReleaseClient(ctx.manager)
            target_version = resolve_remote_version(
                client,
                ctx.manager,
                requested=version,
                yes=yes,
                prompt="请选择要更新到的版本",
            )
            # 降级保护：目标版本低于当前部署版本时给出警告
            if yes:
                out(f"云端安装包版本: v{target_version}")
            if SelfUpdater.version_gt(ctx.state.version, target_version):
                if not yes and not ask_bool(
                    f"目标版本 v{target_version} 低于当前部署 v{ctx.state.version}（降级），仍要继续？",
                    False,
                ):
                    out("已取消。")
                    return
                out("[警告] 正在执行版本回退（降级），请确认数据兼容性。")
            tar_path = ensure_remote_tar(client, ctx.manager, target_version, force=force)
        else:
            tar_path = select_tar(yes=yes, prompt="请选择新版本安装包")

        version, arch = parse_tar(tar_path) or (
            ctx.state.version,
            ctx.state.architecture,
        )

        image = ctx.docker.load_image_tar(tar_path)

        if ctx.manager.auto_backup:
            if ctx.docker.service_running():
                out("==> 自动备份数据库...")
                try:
                    from managepylai_services import BackupService
                    BackupService(ctx).export()
                except ManageError as exc:
                    out(f"[警告] 自动备份失败，已跳过（{exc}）。建议更新完成后立即手动备份。")
            else:
                out("[警告] 后端未在运行（可能处于重启循环或已退出），已跳过自动备份。")

        self.preflight_config(image)

        # 按最新模板全量重渲染 compose（基础设施镜像随版本升级；.env 凭据保留）
        ComposeConfig.regenerate(image, ctx.manager)
        # 预检 compose 语法
        try:
            ctx.docker.validate_compose()
        except ManageError as e:
            raise ManageError(f"Compose 校验失败: {e}") from e
        ctx.docker.compose("up", "-d", "--remove-orphans", timeout=300)

        if not ctx.docker.wait_healthy(ctx.state.api_port, timeout=None, warn_after=300):
            ctx.docker.dump_diagnostics(tail=200)
            raise ManageError("更新后健康检查未通过，请查看上方诊断。")

        ctx.state.set("version", version)
        ctx.state.set("architecture", arch)
        ctx.state.set("image", image)
        ctx.state.save()

        out("更新完成。")

    def check_pg_major_upgrade(self, *, force: bool = False) -> None:
        """PostgreSQL 数据目录跨大版本不兼容，升级前 Fail Closed 拦截并给出迁移步骤。"""
        compose_file = ComposeConfig.COMPOSE_FILE
        if not compose_file.is_file():
            return
        text = compose_file.read_text(encoding="utf-8")
        old = re.search(r"^\s*image:\s*(postgres:[\w.-]+)\s*$", text, re.MULTILINE)
        if not old:
            return
        old_major = re.match(r"postgres:(\d+)", old.group(1))
        if not old_major:
            return
        old_major = int(old_major.group(1))
        services_cfg = self.ctx.manager.get("Compose", "Services", default={}) or {}
        new_image = services_cfg.get("PostgresImage", "postgres:18-alpine")
        new_major = re.match(r"postgres:(\d+)", new_image)
        if not new_major or old_major == int(new_major.group(1)):
            return
        if force:
            out(
                f"[警告] 已确认 PostgreSQL 大版本升级（{old.group(1)} → {new_image}）。"
                "请自行确保旧数据已备份或可丢弃。"
            )
            return
        raise ManageError(
            f"PostgreSQL 数据目录跨大版本不兼容（当前 {old.group(1)}，目标 {new_image}），无法直接更新。\n"
            "迁移步骤：\n"
            "  1) 确保当前后端 pg_dump 与数据库同版本后执行 `ManagePylai.py backup create` 备份数据；\n"
            "  2) `docker volume rm pylai_pgdata` 删除旧数据目录（数据已备份）；\n"
            "  3) 重新执行 `ManagePylai.py update --force-pg-upgrade`（新库将全新初始化）；\n"
            "  4) `ManagePylai.py backup restore <备份名>` 恢复数据。\n"
            "数据可丢弃时，可直接执行 `ManagePylai.py update --force-pg-upgrade`。"
        )

    def preflight_config(self, image: str) -> None:
        if not CONFIG_FILE.is_file():
            raise ManageError(f"配置文件不存在: {CONFIG_FILE}")

        out("==> 校验现有配置与新版本兼容性...")

        result = run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                PYLAIOS_BIN,
                "-v",
                f"{CONFIG_DIR}:/etc/pylai",
                image,
                "config",
                "validate",
                "--config",
                PYLAI_CONFIG_ARG,
            ],
            check=False,
            timeout=120,
        )

        output = (result.stdout + result.stderr).strip()

        if result.returncode == 0:
            out("配置校验通过。")
            return

        if output:
            out(output)

        raise ManageError(
            "现有配置不兼容新版本（见上方诊断）。请先修正 ~/.pylai/config/pylai.toml 后重试："
            "移除过时配置项（E002），补齐新版本必填项（E004），或调整越界值（E005）。"
            f"也可对照镜像模板 `docker run --rm --entrypoint cat {image} /opt/pylai/pylai.example.toml` 逐项核对。"
        )

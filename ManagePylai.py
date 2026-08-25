#!/usr/bin/env python3
"""ManagePylai - Pylai Docker Compose 部署管理工具（Python 3.12+ 重构版）。

仅使用 Python 标准库和 docker CLI。
Release 页面同时提供 Pylai-<version>-Linux-<arch>.tar 与本脚本，
下载后放在同一目录运行即可。
"""

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


# ============================================================================
# 类型别名
# ============================================================================
type Json = dict[str, Any]
type EnvMap = dict[str, str]
type TarMeta = tuple[str, str]
type ServiceName = Literal["backend", "postgres", "redis", "nginx"]
type SmtpSecurity = Literal["SslOnConnect", "StartTls", "None"]
type UserGroup = Literal["normal", "admin", "max"]
type UserStatus = Literal["active", "banned"]


# ============================================================================
# 常量
# ============================================================================
APP_NAME = "Pylai"
CONTAINER = "pylai"
PYLAIOS_BIN = "/opt/pylai/Pylaios"
PYLAI_CONFIG_ARG = "/etc/pylai/pylai.toml"

HOME = Path(os.environ.get("PYLAI_HOME", "~/.pylai")).expanduser()
STATE_FILE = HOME / "state.json"
CONFIG_DIR = HOME / "config"
CONFIG_FILE = CONFIG_DIR / "pylai.toml"
CERT_DIR = CONFIG_DIR / "certs"
CONTAINER_CONFIG_DIR = "/etc/pylai"
CONTAINER_CERT_DIR = f"{CONTAINER_CONFIG_DIR}/certs"
DATA_DIR = HOME / "data"
BACKUP_DIR = HOME / "backups"
HOST_NGINX_FILE = HOME / "host-nginx.conf"

# 云端（GitHub Release）下载的 tar 安装包缓存目录（可通过 ManagerConfig.toml [Updates] DownloadDir 覆盖）
DEFAULT_DOWNLOAD_DIR = HOME / "downloads"

# 与 deploy/entrypoint.py WEAK_SECRETS 保持一致，本地预检 Fail Closed
WEAK_SECRETS = {"change-me", "changeme", "password", "secret", "123456", "pylai"}

TAR_PATTERN = re.compile(r"^Pylai-(.+)-Linux-(AMD64|ARM64)\.tar$")
BACKEND_IMAGE_RE = re.compile(
    r"^(  backend:\s*\n(?:    .*\n)*?    image: ).*$",
    re.MULTILINE,
)
SECRET_LINE = re.compile(
    r"^(\s*[^=]*\b(?:Password|Secret|ConnectionString)\s*=\s*).*$",
    re.IGNORECASE,
)

SUPPORTED_ARCH = {
    "x86_64": "AMD64",
    "amd64": "AMD64",
    "aarch64": "ARM64",
    "arm64": "ARM64",
}

GROUP_OPTIONS: list[tuple[str, str]] = [
    ("normal — 普通用户", "normal"),
    ("admin — 管理员", "admin"),
    ("max — 超级管理员", "max"),
]
STATUS_OPTIONS: list[tuple[str, str]] = [
    ("active — 正常", "active"),
    ("banned — 封禁", "banned"),
]

__version__ = "0.0.26"


class ManageError(Exception):
    """统一管理错误。"""


# ============================================================================
# 基础工具
# ============================================================================
T = TypeVar("T")


def out(message: object = "") -> None:
    print(message, flush=True)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_home() -> None:
    for path in (CONFIG_DIR, CERT_DIR, DATA_DIR, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    ensure_home()
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_list(values: Iterable[str]) -> str:
    return f"[{', '.join(map(toml_str, values))}]"


def mask_config_text(text: str) -> str:
    lines = [SECRET_LINE.sub(r'\1"***"', line) for line in text.splitlines()]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def run(
    cmd: Sequence[str | Path],
    /,
    *,
    check: bool = True,
    timeout: int | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(x) for x in cmd],
        text=True,
        capture_output=True,
        timeout=timeout,
        input=stdin,
    )

    if check and result.returncode != 0:
        raise ManageError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"命令失败: {' '.join(map(str, cmd))}"
        )

    return result


def host_arch() -> str:
    return SUPPORTED_ARCH.get(host_platform.machine().lower(), "AMD64")


def discover_tars() -> list[Path]:
    return sorted(p for p in Path.cwd().glob("Pylai-*.tar") if TAR_PATTERN.match(p.name))


def parse_tar(path: Path) -> TarMeta | None:
    if m := TAR_PATTERN.match(path.name):
        return m.group(1), m.group(2)
    return None


def parse_env_file(path: Path) -> EnvMap:
    if not path.is_file():
        raise ManageError(f".env 文件不存在: {path}")

    env: EnvMap = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

    return env


def nested_get(data: Json, key_path: str, default: Any = None) -> Any:
    current: Any = data
    for key in key_path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def as_int(value: Any, default: int) -> int:
    with suppress(TypeError, ValueError):
        return int(value)
    return default


def env_bool(value: str | None) -> bool:
    return str(value or "").lower() in {"true", "1", "yes"}


def split_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def is_valid_url(value: str) -> bool:
    try:
        p = urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.hostname)
    except Exception:
        return False


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_valid_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return "/" in value
    except ValueError:
        return False


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def check_weak_secrets(answers: "InstallAnswers") -> None:
    for label, secret in (
        ("数据库密码", answers.db_password),
        ("Redis 密码", answers.redis_password),
    ):
        if secret.strip().lower() in WEAK_SECRETS:
            raise ManageError(f"{label} 为已知弱值，拒绝启动。请使用随机生成的强密码")


def validate_answers(answers: "InstallAnswers") -> None:
    if not is_valid_url(answers.public_url):
        raise ManageError(f"对外访问地址不是合法 URL: {answers.public_url}")
    if not (1 <= answers.public_port <= 65535 and 1 <= answers.api_port <= 65535):
        raise ManageError(f"端口越界: public={answers.public_port} api={answers.api_port}")
    if answers.public_port == answers.api_port:
        raise ManageError("对外端口与 API 端口不能相同")
    for ip in answers.trusted_proxies:
        if not is_valid_ip(ip):
            raise ManageError(f"可信代理 IP 非法: {ip}")
    for cidr in answers.trusted_networks:
        if not is_valid_cidr(cidr):
            raise ManageError(f"可信代理 CIDR 非法: {cidr}")
    for origin in answers.cors_origins:
        if not is_valid_url(origin):
            raise ManageError(f"CORS Origin 非法: {origin}")
    # 端口占用预检（仅提示，不阻断，避免误判）
    for label, port in (("对外端口", answers.public_port), ("API 端口", answers.api_port)):
        if port_in_use(port):
            out(f"[警告] {label} {port} 在本机已被占用，启动可能失败，请先释放或更换端口。")
    check_weak_secrets(answers)


def _toml_section_span(text: str, marker: str) -> tuple[int, int]:
    start = text.index(marker)
    after = start + len(marker)
    next_section = re.search(r"(?m)^\s*\[", text[after:])
    end = after + next_section.start() if next_section else len(text)
    return start, end


def replace_toml_block_value(text: str, marker: str, key: str, value: str) -> str:
    try:
        start, end = _toml_section_span(text, marker)
    except ValueError as exc:
        raise ManageError(f"未找到 TOML 段落: {marker}") from exc

    block = text[start:end]
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*).*$")

    if pattern.search(block):
        block = pattern.sub(lambda m: f"{m.group(1)}{value}", block, count=1)
    else:
        block = block.rstrip("\n") + f"\n{key} = {value}\n"

    return text[:start] + block + text[end:]


class TomlText:
    """链式 TOML 片段修改器，取代散落各处的 set_if/replace_if 闭包。"""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def set(self, marker: str, key: str, value: str, *, required: bool = False) -> Self:
        if required or marker in self.text:
            self.text = replace_toml_block_value(self.text, marker, key, value)
        return self

    def set_many(self, marker: str, values: dict[str, str]) -> Self:
        for key, value in values.items():
            self.set(marker, key, value)
        return self

    def strip_line(self, pattern: str) -> Self:
        self.text = re.sub(pattern, "", self.text)
        return self

    def __str__(self) -> str:
        return self.text


# ============================================================================
# 交互输入
# ============================================================================
def ask(
    prompt: str,
    default: str | None = None,
    *,
    secret: bool = False,
    allow_blank: bool = False,
) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    prompt_line = f"{prompt}{suffix}: "

    while True:
        try:
            raw = getpass.getpass(prompt_line) if secret else input(prompt_line)
        except (EOFError, KeyboardInterrupt):
            out("\n已退出。")
            raise SystemExit(0)

        value = raw.strip()

        if value:
            return value
        if default is not None:
            return default
        if allow_blank:
            return ""

        out("该项不能为空。")


def ask_bool(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"

    while True:
        value = ask(f"{prompt}{suffix}", allow_blank=True).strip().lower()

        if not value:
            return default
        if value in {"y", "yes", "1"}:
            return True
        if value in {"n", "no", "0"}:
            return False

        out("请输入 y 或 n。")


def ask_int(prompt: str, default: int, *, minimum: int = 1, maximum: int = 65535) -> int:
    while True:
        raw = ask(prompt, str(default))

        with suppress(ValueError):
            value = int(raw)
            if minimum <= value <= maximum:
                return value

        out(f"请输入 {minimum}-{maximum} 之间的数字。")


def choose(options: Sequence[tuple[str, T]], prompt: str = "请选择") -> T | None:
    if not options:
        out("没有可选项。")
        return None

    while True:
        for index, (label, _) in enumerate(options, 1):
            out(f"  [{index}] {label}")

        raw = ask(prompt, "1")

        with suppress(ValueError, IndexError):
            return options[int(raw) - 1][1]

        out("选择无效。\n")


def confirm_danger(text: str, *, required_word: str = "DELETE") -> bool:
    out(f"危险操作：{text}")
    return ask(f"请输入 {required_word} 确认").strip() == required_word


def random_password(length: int = 12) -> str:
    return f"{secrets.token_urlsafe(length)}Aa1"


def reveal_credentials(credentials: Iterable[tuple[str, str]], *, yes_mode: bool = False) -> None:
    credentials = list(credentials)
    if not credentials:
        return

    cred_file = HOME / ".install-credentials"
    ensure_home()

    with cred_file.open("a", encoding="utf-8") as f:
        f.writelines(f"{label}: {value}\n" for label, value in credentials)
    cred_file.chmod(0o600)

    if yes_mode:
        return

    for label, value in credentials:
        out(f"  {label}: {value}")

    out(f"  {'=' * 60}")
    out("  ⚠️  请妥善保存以上凭据，按回车后此信息将从屏幕消失")

    with suppress(EOFError, KeyboardInterrupt):
        input()

    lines = 2 + len(credentials)
    sys.stdout.write(f"\033[{lines}F\033[J")
    sys.stdout.flush()
    out("  [凭据已隐藏，如需查看请检查 ~/.pylai/.install-credentials]")


def run_submenu(
    title: str,
    parent_title: str,
    entries: Sequence[tuple[str, Callable[[], None]]],
) -> None:
    while True:
        out(f"\n### {title} ###")
        for index, (label, _) in enumerate(entries, 1):
            out(f"[{index}] {label}")
        out(f"[0] 返回 {parent_title}")

        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            out()
            return

        if raw in {"0", "back", "return"}:
            return

        try:
            action = entries[int(raw) - 1][1]
        except (ValueError, IndexError):
            out("选择无效。")
            continue

        try:
            action()
        except ManageError as exc:
            out(f"错误: {exc}")


# ============================================================================
# 密码策略
# ============================================================================
def read_password_policy() -> Json:
    defaults: Json = {
        "RequiredLength": 12,
        "AdminRequiredLength": 14,
        "RequireDigit": True,
        "RequireLowercase": False,
        "RequireUppercase": False,
        "RequireNonAlphanumeric": False,
        "CheckBreachedPasswords": True,
    }

    if not CONFIG_FILE.is_file():
        return defaults

    with suppress(OSError, tomllib.TOMLDecodeError):
        with CONFIG_FILE.open("rb") as f:
            data = tomllib.load(f)

        pwd = nested_get(data, "Identity.Password", {})
        if isinstance(pwd, dict):
            return {**defaults, **{k: pwd[k] for k in defaults if k in pwd}}

    return defaults


def validate_password_local(password: str, policy: Json, *, privileged: bool) -> list[str]:
    if not password:
        return ["密码不能为空。"]

    required = as_int(
        policy.get("AdminRequiredLength" if privileged else "RequiredLength"),
        14 if privileged else 12,
    )

    errors: list[str] = []

    if len(password) < required:
        errors.append(f"密码长度至少为 {required} 个字符。")
    if policy.get("RequireDigit") and not any(c.isdigit() for c in password):
        errors.append("密码必须包含数字。")
    if policy.get("RequireLowercase") and not any(c.islower() for c in password):
        errors.append("密码必须包含小写字母。")
    if policy.get("RequireUppercase") and not any(c.isupper() for c in password):
        errors.append("密码必须包含大写字母。")
    if policy.get("RequireNonAlphanumeric") and all(c.isalnum() for c in password):
        errors.append("密码必须包含非字母数字字符。")

    return errors


# ============================================================================
# SMTP / 证书 / 账号模型
# ============================================================================
@dataclass(frozen=True, slots=True, kw_only=True)
class SmtpSettings:
    host: str = ""
    port: int = 587
    security: SmtpSecurity = "StartTls"
    user: str = ""
    password: str = ""
    sender: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.host)


@dataclass(frozen=True, slots=True, kw_only=True)
class SeedAccount:
    role: Literal["max", "admin", "user"]
    email: str = ""
    password: str = ""
    display_name: str = ""

    @property
    def manual_password(self) -> bool:
        return bool(self.password)


SMTP_SECURITY_DESCRIPTIONS: dict[SmtpSecurity, str] = {
    "SslOnConnect": "SMTPS / 隐式 TLS（服务端从连接开始即 TLS，常见端口 465）",
    "StartTls": "STARTTLS（先明文连接再升级 TLS，常见端口 587）",
    "None": "无加密（仅限可信内网，不推荐）",
}


def ask_smtp_security(default: SmtpSecurity = "StartTls") -> SmtpSecurity:
    options: list[tuple[str, SmtpSecurity]] = [
        ("SslOnConnect — 隐式 TLS，465 端口通常选这个", "SslOnConnect"),
        ("StartTls — STARTTLS，587 端口通常选这个（推荐）", "StartTls"),
        ("None — 不加密，仅限可信内网", "None"),
    ]

    while True:
        out("SMTP 加密方式：")
        default_index = 1

        for index, (label, value) in enumerate(options, 1):
            if value == default:
                default_index = index
                marker = " <="
            else:
                marker = ""
            out(f"  [{index}] {label}{marker}")

        raw = ask("请选择", str(default_index))

        with suppress(ValueError, IndexError):
            return options[int(raw) - 1][1]

        out("选择无效。\n")


def configure_smtp_interactive() -> SmtpSettings | None:
    if not ask_bool("配置 SMTP 邮件发送？", False):
        return None

    host = ask("SMTP 服务器")

    while True:
        out("\nSMTP 端口（请按邮件服务商文档选择）：")
        out("  [1] 465 — SMTPS / 隐式 TLS（阿里云企业邮箱等）")
        out("  [2] 587 — STARTTLS（通用推荐）")
        out("  [3] 25  — 无加密（不推荐）")
        out("  [4] 自定义端口")

        raw = ask("请选择", "2")

        match raw:
            case "1":
                port, security = 465, "SslOnConnect"
            case "2":
                port, security = 587, "StartTls"
            case "3":
                port, security = 25, "None"
            case "4":
                port = ask_int("SMTP 端口", 587)
                security = ask_smtp_security()
            case _:
                out("选择无效。\n")
                continue

        out(f"\n已选择 SMTP：{host}:{port}")
        out(f"加密方式：{security} — {SMTP_SECURITY_DESCRIPTIONS[security]}")

        if ask_bool("确认以上端口与加密方式？", True):
            break

        out()

    user = ask("SMTP 用户名（无认证可留空）", "", allow_blank=True)
    password = ask("SMTP 密码（无认证可留空）", "", secret=True, allow_blank=True)
    sender = ask("发件人邮箱")

    return SmtpSettings(
        host=host,
        port=port,
        security=security,
        user=user,
        password=password,
        sender=sender,
    )


def ensure_signing_kek() -> Path:
    path = CERT_DIR / "signing-kek"
    if not path.is_file():
        ensure_home()
        path.write_text(secrets.token_hex(32), encoding="ascii")
        path.chmod(0o600)
    return path


def import_pfx(src: Path, dest_name: str) -> str:
    if not src.is_file():
        raise ManageError(f"PFX 文件不存在: {src}")

    ensure_home()
    dest = CERT_DIR / dest_name
    shutil.copy2(src, dest)
    dest.chmod(0o600)
    return f"{CONTAINER_CERT_DIR}/{dest_name}"


def generate_encryption_pfx() -> tuple[str, str]:
    ensure_home()

    host_pfx = CERT_DIR / "encryption.pfx"
    key_file = CERT_DIR / "encryption-key.pem"
    cert_file = CERT_DIR / "encryption-cert.pem"
    password = secrets.token_urlsafe(12)

    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            key_file,
            "-out",
            cert_file,
            "-days",
            "3650",
            "-subj",
            "/CN=Pylai Encryption",
        ],
        timeout=300,
    )

    run(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            host_pfx,
            "-inkey",
            key_file,
            "-in",
            cert_file,
            "-passout",
            f"pass:{password}",
        ],
        timeout=300,
    )

    host_pfx.chmod(0o600)
    key_file.unlink(missing_ok=True)
    cert_file.unlink(missing_ok=True)

    return f"{CONTAINER_CERT_DIR}/encryption.pfx", password


@dataclass(slots=True, kw_only=True)
class InstallAnswers:
    public_url: str
    public_port: int = 8080
    api_port: int = 5000

    db_user: str = "pylai"
    db_name: str = "pylai"
    db_password: str = field(default_factory=lambda: secrets.token_hex(16))
    redis_password: str = field(default_factory=lambda: secrets.token_hex(16))
    invite_pepper: str = field(default_factory=lambda: secrets.token_hex(32))

    max_account: SeedAccount = field(
        default_factory=lambda: SeedAccount(
            role="max",
            email="max@pylai.local",
            display_name="Max User",
        )
    )
    admin_account: SeedAccount | None = None
    user_account: SeedAccount | None = None

    smtp: SmtpSettings = field(default_factory=SmtpSettings)

    signing_pfx: str = ""
    signing_pfx_password: str = ""
    encryption_pfx: str = ""
    encryption_pfx_password: str = ""

    trusted_proxies: list[str] = field(default_factory=lambda: ["127.0.0.1", "::1"])
    trusted_networks: list[str] = field(default_factory=lambda: ["172.16.0.0/12"])
    extra_cors_origins: list[str] = field(default_factory=list)

    mfa_for_admin: bool = False
    mfa_webauthn_for_max: bool = False

    @property
    def origin(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def hostname(self) -> str:
        return urlparse(self.public_url).hostname or "localhost"

    @property
    def is_https(self) -> bool:
        return self.origin.startswith("https://")

    @property
    def cors_origins(self) -> list[str]:
        return [self.origin, *self.extra_cors_origins]

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = [self.hostname]
        if self.hostname not in {"localhost", "127.0.0.1", "::1"}:
            hosts.extend(("localhost", "127.0.0.1"))
        return hosts

    def account(self, role: Literal["admin", "user", "max"]) -> SeedAccount:
        match role:
            case "max":
                return self.max_account
            case "admin":
                return self.admin_account or SeedAccount(
                    role="admin",
                    display_name="Administrator",
                )
            case "user":
                return self.user_account or SeedAccount(
                    role="user",
                    display_name="Test User",
                )

    def env_lines(self) -> list[str]:
        return [
            f"PYLAI_PUBLIC_PORT={self.public_port}",
            f"PYLAI_API_PORT={self.api_port}",
            f"PYLAI_DB_USER={self.db_user}",
            f"PYLAI_DB_PASSWORD={self.db_password}",
            f"PYLAI_DB_NAME={self.db_name}",
            f"PYLAI_REDIS_PASSWORD={self.redis_password}",
        ]

    def to_template_context(self) -> dict[str, str]:
        db_connection_string = (
            f"Host=postgres;Port=5432;"
            f"Database={self.db_name};"
            f"Username={self.db_user};"
            f"Password={self.db_password}"
        )

        subs: dict[str, str] = {
            "server_url": "http://0.0.0.0:5000",
            "frontend_url": self.public_url,
            "db_connection_string": db_connection_string,
            "redis_password": self.redis_password,
            "server_pepper": self.invite_pepper,
            "backup_dir": "/var/lib/pylai/backups",
            "trusted_proxies": toml_list(self.trusted_proxies),
            "trusted_networks": toml_list(self.trusted_networks),
            "signing_key_file": "/etc/pylai/certs/signing-kek",
            "allowed_origins": toml_list(self.cors_origins),
            "issuer": self.origin,
            "allowed_hosts": toml_list(self.allowed_hosts),
            "relying_party_id": self.hostname,
            "mfa_origins": toml_list(self.cors_origins),
            "require_https": "true" if self.is_https else "false",
            "secure_policy": "Always" if self.is_https else "SameAsRequest",
            "mfa_require_for_admin": "true" if self.mfa_for_admin else "false",
            "mfa_require_webauthn_for_max": "true" if self.mfa_webauthn_for_max else "false",
        }

        for role in ("admin", "user", "max"):
            account = self.account(role)
            prefix = f"seed_{role}"
            subs[f"{prefix}_email"] = account.email
            subs[f"{prefix}_password"] = account.password
            subs[f"{prefix}_display_name"] = account.display_name or role.title()

        # 模板占位需始终有值，避免残留 ${var} 导致告警/解析歧义
        subs.update(
            {
                "smtp_from": self.smtp.sender if self.smtp.enabled else "",
                "smtp_host": self.smtp.host if self.smtp.enabled else "",
                "smtp_port": str(self.smtp.port if self.smtp.enabled else 587),
                "smtp_security": self.smtp.security if self.smtp.enabled else "StartTls",
                "smtp_user": self.smtp.user if self.smtp.enabled else "",
                "smtp_password": self.smtp.password if self.smtp.enabled else "",
                "signing_pfx_path": self.signing_pfx or "",
                "signing_pfx_password": self.signing_pfx_password or "",
                "encryption_pfx_path": self.encryption_pfx or "",
                "encryption_pfx_password": self.encryption_pfx_password or "",
            }
        )

        return subs

    @property
    def credentials(self) -> list[tuple[str, str]]:
        creds: list[tuple[str, str]] = [
            ("PostgreSQL 密码", self.db_password),
            ("Redis 密码", self.redis_password),
        ]

        for account in (self.max_account, self.admin_account, self.user_account):
            if account and account.email and account.password:
                creds.append(
                    (
                        f"{account.role.title()} 账号 ({account.email})",
                        account.password,
                    )
                )

        if self.encryption_pfx_password:
            creds.append(("加密证书密码", self.encryption_pfx_password))

        return creds

    @property
    def auto_generated_accounts(self) -> list[str]:
        return [
            account.role.title()
            for account in (self.max_account, self.admin_account, self.user_account)
            if account and account.email and not account.password
        ]

    @classmethod
    def from_env(cls, env: EnvMap) -> Self:
        public_url = env.get("PYLAI_PUBLIC_URL", "http://localhost:8080")
        origin = public_url.rstrip("/")

        max_account = SeedAccount(
            role="max",
            email=env.get("PYLAI_MAX_EMAIL", "max@pylai.local"),
            password=env.get("PYLAI_MAX_PASSWORD", ""),
            display_name="Max User",
        )

        admin_email = env.get("PYLAI_ADMIN_EMAIL", "")
        admin_account = (
            SeedAccount(
                role="admin",
                email=admin_email,
                password=env.get("PYLAI_ADMIN_PASSWORD", ""),
                display_name="Administrator",
            )
            if admin_email
            else None
        )

        user_email = env.get("PYLAI_USER_EMAIL", "")
        user_account = (
            SeedAccount(
                role="user",
                email=user_email,
                password=env.get("PYLAI_USER_PASSWORD", ""),
                display_name="Test User",
            )
            if user_email
            else None
        )

        smtp_host = env.get("PYLAI_SMTP_HOST", "")
        smtp = (
            SmtpSettings(
                host=smtp_host,
                port=as_int(env.get("PYLAI_SMTP_PORT"), 587),
                security=env.get("PYLAI_SMTP_SECURITY", "StartTls"),
                user=env.get("PYLAI_SMTP_USER", ""),
                password=env.get("PYLAI_SMTP_PASSWORD", ""),
                sender=env.get("PYLAI_SMTP_FROM", ""),
            )
            if smtp_host
            else SmtpSettings()
        )

        extra_cors = [
            x for x in split_csv(env.get("PYLAI_CORS_ORIGINS", "")) if x != origin
        ]

        return cls(
            public_url=public_url,
            public_port=as_int(env.get("PYLAI_PUBLIC_PORT"), 8080),
            api_port=as_int(env.get("PYLAI_API_PORT"), 5000),
            db_user=env.get("PYLAI_DB_USER", "pylai"),
            db_name=env.get("PYLAI_DB_NAME", "pylai"),
            db_password=env.get("PYLAI_DB_PASSWORD") or secrets.token_hex(16),
            redis_password=env.get("PYLAI_REDIS_PASSWORD") or secrets.token_hex(16),
            max_account=max_account,
            admin_account=admin_account,
            user_account=user_account,
            smtp=smtp,
            signing_pfx=env.get("PYLAI_SIGNING_PFX", ""),
            signing_pfx_password=env.get("PYLAI_SIGNING_PFX_PASSWORD", ""),
            encryption_pfx=env.get("PYLAI_ENCRYPTION_PFX", ""),
            encryption_pfx_password=env.get("PYLAI_ENCRYPTION_PFX_PASSWORD", ""),
            trusted_proxies=split_csv(env.get("PYLAI_TRUSTED_PROXIES", "127.0.0.1,::1")),
            trusted_networks=split_csv(env.get("PYLAI_TRUSTED_NETWORKS", "172.16.0.0/12")),
            extra_cors_origins=extra_cors,
            mfa_for_admin=env_bool(env.get("PYLAI_MFA_FOR_ADMIN")),
            mfa_webauthn_for_max=env_bool(env.get("PYLAI_MFA_WEBAUTHN_FOR_MAX")),
        )

    @classmethod
    def from_mapping(cls, data: Json) -> Self:
        public_url = str(data.get("public_url", "http://localhost:8080"))
        origin = public_url.rstrip("/")

        max_account = SeedAccount(
            role="max",
            email=str(data.get("max_email", "max@pylai.local")),
            password=str(data.get("max_password", "")),
            display_name="Max User",
        )

        admin_email = str(data.get("admin_email", ""))
        admin_account = (
            SeedAccount(
                role="admin",
                email=admin_email,
                password=str(data.get("admin_password", "")),
                display_name="Administrator",
            )
            if admin_email
            else None
        )

        user_email = str(data.get("user_email", ""))
        user_account = (
            SeedAccount(
                role="user",
                email=user_email,
                password=str(data.get("user_password", "")),
                display_name="Test User",
            )
            if user_email
            else None
        )

        smtp_enabled = bool(data.get("smtp_enabled") or data.get("smtp_host"))
        smtp = (
            SmtpSettings(
                host=str(data.get("smtp_host", "")),
                port=as_int(data.get("smtp_port"), 587),
                security=str(data.get("smtp_security", "StartTls")),
                user=str(data.get("smtp_user", "")),
                password=str(data.get("smtp_password", "")),
                sender=str(data.get("smtp_from", "")),
            )
            if smtp_enabled
            else SmtpSettings()
        )

        cors_origins = [str(x) for x in data.get("cors_origins", [])]
        extra_cors = [x for x in cors_origins if x != origin]

        return cls(
            public_url=public_url,
            public_port=as_int(data.get("public_port"), 8080),
            api_port=as_int(data.get("api_port"), 5000),
            db_user=str(data.get("db_user", "pylai")),
            db_name=str(data.get("db_name", "pylai")),
            db_password=str(data.get("db_password") or secrets.token_hex(16)),
            redis_password=str(data.get("redis_password") or secrets.token_hex(16)),
            invite_pepper=str(data.get("invite_pepper") or secrets.token_hex(32)),
            max_account=max_account,
            admin_account=admin_account,
            user_account=user_account,
            smtp=smtp,
            signing_pfx=str(data.get("signing_pfx", "")),
            signing_pfx_password=str(data.get("signing_pfx_password", "")),
            encryption_pfx=str(data.get("encryption_pfx", "")),
            encryption_pfx_password=str(data.get("encryption_pfx_password", "")),
            trusted_proxies=[str(x) for x in data.get("trusted_proxies", [])],
            trusted_networks=[str(x) for x in data.get("trusted_networks", [])],
            extra_cors_origins=extra_cors,
            mfa_for_admin=bool(data.get("mfa_for_admin", False)),
            mfa_webauthn_for_max=bool(data.get("mfa_webauthn_for_max", False)),
        )

    @classmethod
    def collect_interactive(cls) -> Self:
        ensure_home()

        public_url = ask("对外访问地址（浏览器访问 Pylai 的 URL）", "http://localhost:8080")
        public_port = ask_int("容器 80 映射到主机端口", 8080)
        api_port = ask_int("后端 5000 映射到本机端口（仅绑定 127.0.0.1）", 5000)

        out("\n-- 数据库 / Redis --")
        db_user = ask("PostgreSQL 用户名", "pylai")
        db_name = ask("PostgreSQL 数据库名", "pylai")
        db_password = secrets.token_hex(16)
        redis_password = secrets.token_hex(16)

        ensure_signing_kek()

        out("\n-- 初始账号 --")
        max_email = ask("Max 账号邮箱/登录名", "max@pylai.local")
        max_password = ask("Max 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
        max_account = SeedAccount(
            role="max",
            email=max_email,
            password=max_password,
            display_name="Max User",
        )

        admin_account: SeedAccount | None = None
        if ask_bool("创建初始 Admin 账号？", True):
            admin_email = ask("Admin 账号邮箱/登录名", "admin@pylai.local")
            admin_password = ask(
                "Admin 账号密码（留空自动生成）",
                "",
                secret=True,
                allow_blank=True,
            )
            admin_account = SeedAccount(
                role="admin",
                email=admin_email,
                password=admin_password,
                display_name="Administrator",
            )

        user_account: SeedAccount | None = None
        if ask_bool("创建初始 Normal 测试账号？", False):
            user_email = ask("Normal 账号邮箱/登录名", "user@pylai.local")
            user_password = ask(
                "Normal 账号密码（留空自动生成）",
                "",
                secret=True,
                allow_blank=True,
            )
            user_account = SeedAccount(
                role="user",
                email=user_email,
                password=user_password,
                display_name="Test User",
            )

        out("\n-- 邮件 --")
        smtp = configure_smtp_interactive() or SmtpSettings()

        out("\n-- 安全 --")
        signing_pfx = ""
        signing_pfx_password = ""

        if ask_bool("使用数据库托管签名密钥（推荐，后续用菜单手动轮换）？", True):
            pass
        else:
            path = ask("签名 PFX 文件路径（留空则继续使用数据库托管）", "", allow_blank=True).strip()
            if path:
                signing_pfx_password = ask("签名 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
                signing_pfx = import_pfx(Path(path).expanduser(), "signing.pfx")

        encryption_pfx = ""
        encryption_pfx_password = ""

        if ask_bool("自动生成加密证书（推荐，生产环境必需）？", True) and shutil.which("openssl"):
            encryption_pfx, encryption_pfx_password = generate_encryption_pfx()
        else:
            if shutil.which("openssl") is None:
                out("未找到 openssl，无法自动生成加密证书。")

            path = ask("请提供加密 PFX 文件路径（生产环境必需）", "", allow_blank=True).strip()
            if not path or not Path(path).expanduser().is_file():
                raise ManageError("生产环境必须配置持久化 OpenIddict 加密证书。")

            encryption_pfx_password = ask("加密 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
            encryption_pfx = import_pfx(Path(path).expanduser(), "encryption.pfx")

        trusted_proxies = ask("可信代理 IP（逗号分隔，主机 Nginx 与本机）", "127.0.0.1,::1")
        trusted_networks = ask("可信代理 CIDR（逗号分隔）", "172.16.0.0/12")

        extra_cors = ask("额外 CORS Origin（逗号分隔，没有留空）", "", allow_blank=True)

        out("\n-- 高权限账户 MFA --")
        out("MFA 可保护 Admin/Max 账户安全。HTTP/局域网部署时 WebAuthn 不可用，建议关闭或仅使用 TOTP。")

        mfa_for_admin = ask_bool("Admin 及以上角色登录时强制要求 MFA？", False)
        mfa_webauthn_for_max = (
            ask_bool(
                "Max 角色强制使用 WebAuthn（需 HTTPS 环境，HTTP 内网部署请勿开启）？",
                False,
            )
            if mfa_for_admin
            else False
        )

        return cls(
            public_url=public_url,
            public_port=public_port,
            api_port=api_port,
            db_user=db_user,
            db_name=db_name,
            db_password=db_password,
            redis_password=redis_password,
            max_account=max_account,
            admin_account=admin_account,
            user_account=user_account,
            smtp=smtp,
            signing_pfx=signing_pfx,
            signing_pfx_password=signing_pfx_password,
            encryption_pfx=encryption_pfx,
            encryption_pfx_password=encryption_pfx_password,
            trusted_proxies=split_csv(trusted_proxies),
            trusted_networks=split_csv(trusted_networks),
            extra_cors_origins=split_csv(extra_cors),
            mfa_for_admin=mfa_for_admin,
            mfa_webauthn_for_max=mfa_webauthn_for_max,
        )


# ============================================================================
# ManagerConfig / State
# ============================================================================
@dataclass(slots=True)
class ManagerConfig:
    path: Path = HOME / "ManagerConfig.toml"
    _data: Json = field(default_factory=dict, init=False, repr=False)

    _DEFAULT_TOML = """\
[Manager]
Version = "{version}"

[Manager.Source]
Mirror = "{mirror}"
BaseUrl = "{base_url}"

[Manager.State]
LastCheck = "{last_check}"
{skip_version_line}

[Compose]
ProjectName = "{project_name}"

[Security]
AutoBackupBeforeUpdate = {auto_backup}
BackupRetentionDays = {retention}

[Updates]
AutoCheck = {auto_check}
IncludePrerelease = {include_prerelease}
DownloadDir = "{download_dir}"

[Logging]
Level = "{level}"
"""

    def __post_init__(self) -> None:
        if self.path.is_file():
            with suppress(OSError, tomllib.TOMLDecodeError):
                self._data = tomllib.loads(self.path.read_text(encoding="utf-8"))
            self._migrate_keys()

    def _migrate_keys(self) -> None:
        """旧版键名（mirror / base_url，小写下划线风格）迁移到统一大写风格。"""
        mgr = self._data.get("Manager")
        if not isinstance(mgr, dict):
            return
        source = mgr.setdefault("Source", {})
        if not isinstance(source, dict):
            return
        if "mirror" in mgr and "Mirror" not in source:
            source["Mirror"] = mgr["mirror"]
        custom = mgr.get("Custom")
        if isinstance(custom, dict) and "base_url" in custom and "BaseUrl" not in source:
            source["BaseUrl"] = custom["base_url"]

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def set(self, *keys: str, value: Any) -> None:
        current: Json = self._data

        for key in keys[:-1]:
            nxt = current.get(key)
            if not isinstance(nxt, dict):
                nxt = current[key] = {}
            current = nxt

        current[keys[-1]] = value

    def save(self) -> None:
        ensure_home()

        skip = self.get("Manager", "State", "SkipVersion")
        skip_version_line = f"SkipVersion = {json.dumps(skip)}" if skip else ""

        text = self._DEFAULT_TOML.format(
            version=self.get("Manager", "Version", default=__version__),
            mirror=self.mirror,
            base_url=self.custom_mirror_base or "",
            last_check=self.get("Manager", "State", "LastCheck", default=utc_now_iso()),
            skip_version_line=skip_version_line,
            project_name=self.get("Compose", "ProjectName", default="pylai"),
            auto_backup="true" if self.auto_backup else "false",
            retention=self.get("Security", "BackupRetentionDays", default=7),
            auto_check="true" if self.auto_check else "false",
            include_prerelease="true" if self.include_prerelease else "false",
            download_dir=self.download_dir,
            level=self.get("Logging", "Level", default="info"),
        )

        services = self.get("Compose", "Services", default={}) or {}
        if services:
            text += "\n[Compose.Services]\n"
            text += "".join(f"{k} = {json.dumps(v)}\n" for k, v in services.items())

        atomic_write(self.path, text)

    @property
    def mirror(self) -> str:
        return str(self.get("Manager", "Source", "Mirror", default="Github"))

    def set_mirror(self, mirror: str) -> None:
        self.set("Manager", "Source", "Mirror", value=mirror)
        self.save()

    @property
    def custom_mirror_base(self) -> str | None:
        value = self.get("Manager", "Source", "BaseUrl", default=None)
        if not value:
            return None
        base = str(value).strip().rstrip("/")
        return base or None

    def set_custom_mirror_base(self, base_url: str | None) -> None:
        self.set("Manager", "Source", "BaseUrl", value=base_url or "")
        self.save()

    @property
    def version(self) -> str:
        return str(self.get("Manager", "Version", default=__version__))

    @property
    def logging_level(self) -> str:
        return str(self.get("Logging", "Level", default="info"))

    @property
    def project_name(self) -> str:
        return str(self.get("Compose", "ProjectName", default="pylai"))

    @property
    def auto_backup(self) -> bool:
        return bool(self.get("Security", "AutoBackupBeforeUpdate", default=True))

    def set_auto_backup(self, enabled: bool) -> None:
        self.set("Security", "AutoBackupBeforeUpdate", value=bool(enabled))
        self.save()

    @property
    def auto_check(self) -> bool:
        return bool(self.get("Updates", "AutoCheck", default=True))

    def set_auto_check(self, enabled: bool) -> None:
        self.set("Updates", "AutoCheck", value=bool(enabled))
        self.save()

    @property
    def include_prerelease(self) -> bool:
        return bool(self.get("Updates", "IncludePrerelease", default=False))

    def set_include_prerelease(self, enabled: bool) -> None:
        self.set("Updates", "IncludePrerelease", value=bool(enabled))
        self.save()

    @property
    def download_dir(self) -> str:
        value = self.get("Updates", "DownloadDir", default="")
        return str(value) if value else str(DEFAULT_DOWNLOAD_DIR)

    def set_download_dir(self, path: str) -> None:
        self.set("Updates", "DownloadDir", value=str(path) if path.strip() else "")
        self.save()

    @property
    def skip_version(self) -> str | None:
        value = self.get("Manager", "State", "SkipVersion", default=None)
        return str(value) if value else None

    def set_skip_version(self, version: str | None) -> None:
        if version is None:
            state = self._data.get("Manager", {}).get("State", {})
            state.pop("SkipVersion", None)
        else:
            self.set("Manager", "State", "SkipVersion", value=version)
        self.save()


@dataclass(slots=True)
class State:
    path: Path = STATE_FILE
    _data: Json = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.path.is_file():
            with suppress(OSError, ValueError):
                self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        ensure_home()
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.path.chmod(0o600)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def clear(self) -> None:
        self._data = {}

    @property
    def installed(self) -> bool:
        return bool(self._data)

    @property
    def version(self) -> str:
        return str(self._data.get("version", "0.0.1"))

    @property
    def architecture(self) -> str:
        return str(self._data.get("architecture", host_arch()))

    @property
    def image(self) -> str:
        return str(self._data.get("image", "pylaios:unknown"))

    @property
    def public_url(self) -> str:
        return str(self._data.get("public_url", "http://localhost"))

    @property
    def public_port(self) -> int:
        return as_int(self._data.get("public_port"), 8080)

    @property
    def api_port(self) -> int:
        return as_int(self._data.get("api_port"), 5000)

    @property
    def mode(self) -> str:
        return str(self._data.get("mode", "compose"))


# ============================================================================
# PylaiConfig
# ============================================================================
class PylaiConfig:
    FILE = CONFIG_DIR / "pylai.toml"
    TEMPLATE_NAME = "pylai.template.toml"
    EXAMPLE_NAME = "pylai.example.toml"

    def __init__(self) -> None:
        self._text = ""
        self._parsed: Json | None = None

        if self.FILE.is_file():
            self._text = self.FILE.read_text(encoding="utf-8")
            self._try_parse()

    def _try_parse(self) -> None:
        try:
            self._parsed = tomllib.loads(self._text)
        except tomllib.TOMLDecodeError:
            self._parsed = None

    @classmethod
    def from_existing(cls, source: Path) -> Self:
        if not source.is_file():
            raise ManageError(f"配置文件不存在: {source}")

        text = source.read_text(encoding="utf-8")

        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"提供的配置不是合法 TOML: {exc}") from exc

        ensure_home()
        cls.FILE.write_text(text, encoding="utf-8")
        cls.FILE.chmod(0o600)

        instance = cls()
        instance._text = text
        instance._try_parse()
        return instance

    def extract_answers(self) -> InstallAnswers:
        data = self._parsed
        if data is None and self._text:
            try:
                data = tomllib.loads(self._text)
            except tomllib.TOMLDecodeError as exc:
                raise ManageError(f"配置解析失败: {exc}") from exc

        data = data or {}

        frontend_url = str(nested_get(data, "Frontend.Url", "http://localhost:8080"))
        connection_string = str(nested_get(data, "Database.ConnectionString", ""))

        params: Json = {"public_url": frontend_url}

        for attr, pattern in (
            ("db_user", r"(?:Username|User ID)=([^;]+)"),
            ("db_password", r"Password=([^;]+)"),
            ("db_name", r"Database=([^;]+)"),
        ):
            if m := re.search(pattern, connection_string):
                params[attr] = m.group(1)

        params.setdefault("db_user", "pylai")
        params.setdefault("db_name", "pylai")
        params.setdefault("db_password", "")
        params["redis_password"] = str(nested_get(data, "Redis.Password", ""))
        params["api_port"] = 5000
        params["public_port"] = 8080
        params["invite_pepper"] = str(nested_get(data, "Identity.ServerPepper", secrets.token_hex(32)))

        for key in ("trusted_proxies", "trusted_networks", "cors_origins"):
            value = nested_get(
                data,
                {
                    "trusted_proxies": "Server.TrustedProxies",
                    "trusted_networks": "Server.TrustedNetworks",
                    "cors_origins": "Cors.AllowedOrigins",
                }[key],
                [],
            )
            params[key] = [str(x) for x in value] if isinstance(value, list) else []

        if not params["cors_origins"]:
            params["cors_origins"] = [frontend_url]

        params["max_email"] = str(nested_get(data, "Seeds.DefaultMax.Email", ""))
        params["max_password"] = str(nested_get(data, "Seeds.DefaultMax.Password", ""))
        params["admin_email"] = str(nested_get(data, "Seeds.DefaultAdmin.Email", ""))
        params["admin_password"] = str(nested_get(data, "Seeds.DefaultAdmin.Password", ""))
        params["user_email"] = str(nested_get(data, "Seeds.DefaultUser.Email", ""))
        params["user_password"] = str(nested_get(data, "Seeds.DefaultUser.Password", ""))

        params["mfa_for_admin"] = bool(nested_get(data, "Mfa.RequireForAdmin", False))
        params["mfa_webauthn_for_max"] = bool(nested_get(data, "Mfa.RequireWebAuthnForMax", False))

        signing_path = str(nested_get(data, "OpenIddict.Certificates.Signing.Path", ""))
        if signing_path:
            params["signing_pfx"] = signing_path
            params["signing_pfx_password"] = str(
                nested_get(data, "OpenIddict.Certificates.Signing.Password", "")
            )

        encryption_path = str(nested_get(data, "OpenIddict.Certificates.Encryption.Path", ""))
        if encryption_path:
            params["encryption_pfx"] = encryption_path
            params["encryption_pfx_password"] = str(
                nested_get(data, "OpenIddict.Certificates.Encryption.Password", "")
            )

        smtp_host = str(nested_get(data, "Email.Smtp.Host", ""))
        smtp_enabled = bool(nested_get(data, "Email.FromAddress", "")) or bool(smtp_host)

        params["smtp_enabled"] = smtp_enabled
        params["smtp_host"] = smtp_host
        params["smtp_port"] = as_int(nested_get(data, "Email.Smtp.Port"), 587)
        params["smtp_security"] = str(nested_get(data, "Email.Smtp.Security", "StartTls"))
        params["smtp_user"] = str(nested_get(data, "Email.Smtp.Username", ""))
        params["smtp_password"] = str(nested_get(data, "Email.Smtp.Password", ""))
        params["smtp_from"] = str(nested_get(data, "Email.FromAddress", ""))

        return InstallAnswers.from_mapping(params)

    @classmethod
    def generate_from_template(
        cls, image: str, answers: InstallAnswers, *, allow_compat: bool = False
    ) -> Self:
        template_text = cls._read_from_image(image, cls.TEMPLATE_NAME)
        if template_text:
            return cls._generate_via_template(template_text, answers)

        if allow_compat:
            out("提示：镜像未提供 pylai.template.toml，使用兼容模式（--compat）生成配置。")
            example_text = cls._read_from_image(image, cls.EXAMPLE_NAME)
            if not example_text:
                raise ManageError("无法从镜像读取配置模板（template 且 example 均不存在）")
            return cls._generate_via_replace(example_text, answers)

        raise ManageError(
            "镜像未提供 pylai.template.toml（新版镜像必需，Dockerfile 需包含 COPY OS/pylai.template.toml）。\n"
            "原因：当前 ManagePylai.py 为新版（template 主路径），但加载的镜像为旧版构建（仅含 pylai.example.toml）。\n"
            "解决：\n"
            "  1) 推荐：重新构建/下载最新镜像（构建后 docker run --rm --entrypoint cat <image> /opt/pylai/pylai.template.toml 应存在），再执行安装；\n"
            "  2) 临时兼容：python3 ManagePylai.py install --compat  （或 --compat 与 --config-file/--env-file 组合）将回退到 example 渲染；\n"
            f"  当前镜像: {image}\n"
            "  验证命令: docker run --rm --entrypoint ls <image> /opt/pylai/  应同时列出 pylai.template.toml 与 pylai.example.toml"
        )

    @classmethod
    def _read_from_image(cls, image: str, filename: str) -> str | None:
        result = run(
            ["docker", "run", "--rm", "--entrypoint", "cat", image, f"/opt/pylai/{filename}"],
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            # 明确区分镜像不存在 vs 文件不存在，便于诊断
            err = (result.stderr or result.stdout).strip()
            if "No such image" in err or "not found" in err.lower():
                raise ManageError(f"无法读取镜像 {image} 内 {filename}: 镜像不存在或拉取失败 ({err[:200]})")
            return None
        # 空文件视为不存在
        if not result.stdout.strip():
            return None
        return result.stdout

    @classmethod
    def _generate_via_template(cls, template_text: str, answers: InstallAnswers) -> Self:
        text = Template(template_text).safe_substitute(answers.to_template_context())

        # 仅扫描非注释行，避免模板头部说明文字（如 "${name}"）被误报为未替换变量
        unmatched = re.findall(
            r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?",
            "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")),
        )
        placeholders = {v for v in unmatched if v and (v[0].islower() or v.startswith("seed_"))}
        if placeholders:
            out(f"警告：模板中有未替换的变量: {placeholders}")

        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"生成的 pylai.toml 不是合法 TOML: {exc}") from exc

        instance = cls()
        instance._text = text
        instance._try_parse()
        instance._write()
        return instance

    @classmethod
    def _generate_via_replace(cls, text: str, answers: InstallAnswers) -> Self:
        connection_string = (
            f"Host=postgres;Port=5432;"
            f"Database={answers.db_name};"
            f"Username={answers.db_user};"
            f"Password={answers.db_password}"
        )

        t = TomlText(text)
        t.set("[Server]", "Url", toml_str("http://0.0.0.0:5000"))
        t.set("[Frontend]", "Url", toml_str(answers.public_url))
        t.set("[Database]", "ConnectionString", toml_str(connection_string))
        t.set_many("[Redis]", {
            "Host": toml_str("redis"),
            "Port": "6379",
            "Password": toml_str(answers.redis_password),
        })
        t.set("[Identity]", "ServerPepper", toml_str(answers.invite_pepper))
        t.set("[Backup]", "Directory", toml_str("/var/lib/pylai/backups"))
        t.set("[Server]", "TrustedProxies", toml_list(answers.trusted_proxies))
        t.set("[Server]", "TrustedNetworks", toml_list(answers.trusted_networks))
        t.set("[OpenIddict]", "Issuer", toml_str(answers.origin))
        t.set("[OpenIddict]", "RequireHttps", "true" if answers.is_https else "false")
        t.set("[Server]", "AllowedHosts", toml_list(answers.allowed_hosts))
        t.set("[Mfa]", "RelyingPartyId", toml_str(answers.hostname))
        t.set("[Mfa]", "Origins", toml_list(answers.cors_origins))
        t.set("[Cors]", "AllowedOrigins", toml_list(answers.cors_origins))
        t.set("[Cookie]", "SecurePolicy", toml_str("Always" if answers.is_https else "SameAsRequest"))

        if answers.signing_pfx:
            t.set_many("[OpenIddict.Certificates.Signing]", {
                "Path": toml_str(answers.signing_pfx),
                "Password": toml_str(answers.signing_pfx_password),
            })

        if answers.encryption_pfx:
            t.set_many("[OpenIddict.Certificates.Encryption]", {
                "Path": toml_str(answers.encryption_pfx),
                "Password": toml_str(answers.encryption_pfx_password),
            })

        for section, role in (
            ("Seeds.DefaultAdmin", "admin"),
            ("Seeds.DefaultUser", "user"),
            ("Seeds.DefaultMax", "max"),
        ):
            account = answers.account(role)
            t.set_many(f"[{section}]", {
                "Email": toml_str(account.email),
                "Password": toml_str(account.password),
                "DisplayName": toml_str(account.display_name or role.title()),
            })

        if answers.smtp.enabled:
            t.set("[Email]", "FromAddress", toml_str(answers.smtp.sender))
            t.set_many("[Email.Smtp]", {
                "Host": toml_str(answers.smtp.host),
                "Port": str(answers.smtp.port),
                "Security": toml_str(answers.smtp.security),
                "Username": toml_str(answers.smtp.user),
                "Password": toml_str(answers.smtp.password),
            })

        t.strip_line(r"(?m)^[ \t]*UseSsl[ \t]*=.*\n")
        t.set("[Mfa]", "RequireForAdmin", "true" if answers.mfa_for_admin else "false")
        t.set("[Mfa]", "RequireWebAuthnForMax", "true" if answers.mfa_webauthn_for_max else "false")

        text = str(t)

        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"生成的 pylai.toml 不是合法 TOML: {exc}") from exc

        instance = cls()
        instance._text = text
        instance._try_parse()
        instance._write()
        return instance

    def _write(self) -> None:
        atomic_write(self.FILE, self._text)

    def read(self) -> str:
        return self._text

    def reload(self) -> None:
        if self.FILE.is_file():
            self._text = self.FILE.read_text(encoding="utf-8")
            self._try_parse()

    def get_value(self, section: str, key: str, default: Any = None) -> Any:
        data = self._parsed
        if data is None and self._text:
            with suppress(tomllib.TOMLDecodeError):
                data = tomllib.loads(self._text)

        if data is None:
            return default

        return nested_get(data, f"{section}.{key}", default)

    def set_block_value(self, marker: str, key: str, value: str) -> None:
        self._text = replace_toml_block_value(self._text, marker, key, value)
        self._write()
        self._try_parse()

    def mask(self) -> str:
        return mask_config_text(self._text)

    def validate(self) -> None:
        try:
            tomllib.loads(self._text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"配置不是合法 TOML: {exc}") from exc


# ============================================================================
# Docker Compose
# ============================================================================
@dataclass(slots=True)
class DockerCompose:
    project: str = "pylai"
    compose_file: Path = HOME / "docker-compose.yml"
    env_file: Path = HOME / ".env"

    def ensure_docker(self) -> None:
        if shutil.which("docker") is None:
            raise ManageError("未找到 docker，请先安装 Docker。")

        if run(["docker", "info"], check=False).returncode != 0:
            raise ManageError("Docker daemon 不可用，请启动 Docker 服务。")

        if run(["docker", "compose", "version"], check=False).returncode != 0:
            raise ManageError(
                "未找到 docker compose 插件，请先安装："
                "Arch: pacman -S docker-compose；"
                "Debian/Ubuntu: apt install docker-compose-plugin；"
                "RHEL/Fedora: dnf install docker-compose-plugin。"
            )

    def compose(
        self,
        *args: str | Path,
        check: bool = True,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            [
                "docker",
                "compose",
                "-p",
                self.project,
                "--env-file",
                str(self.env_file),
                "-f",
                self.compose_file,
                *args,
            ],
            check=check,
            timeout=timeout,
            stdin=stdin,
        )

    def docker(
        self,
        *args: str | Path,
        check: bool = True,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return run(["docker", *args], check=check, timeout=timeout, stdin=stdin)

    def service_exists(self, service: ServiceName = "backend") -> bool:
        return bool(self.compose("ps", "-q", service, check=False).stdout.strip())

    def service_status(self, service: ServiceName = "backend") -> Literal["running", "exited"]:
        result = self.compose("ps", "--format", "json", service, check=False)
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return "exited"
        if isinstance(entries, dict):
            entries = [entries]
        return (
            "running"
            if any(e.get("Service") == service and e.get("State") == "running" for e in entries)
            else "exited"
        )

    def service_running(self, service: ServiceName = "backend") -> bool:
        return self.service_status(service) == "running"

    def write_env(self, answers: InstallAnswers) -> None:
        atomic_write(HOME / ".env", "\n".join(answers.env_lines()) + "\n")

    def set_backend_image(self, image: str) -> None:
        if not self.compose_file.is_file():
            raise ManageError("docker-compose.yml 不存在，请先执行安装。")

        text = self.compose_file.read_text(encoding="utf-8")
        text = BACKEND_IMAGE_RE.sub(rf"\1{image}", text)
        self.compose_file.write_text(text, encoding="utf-8")

    def start(self, image: str, answers: InstallAnswers) -> None:
        self.write_env(answers)
        self.set_backend_image(image)
        self.compose("up", "-d", "--remove-orphans", timeout=300)

    def stop(self, timeout_sec: int = 30) -> None:
        self.compose("stop", "-t", str(timeout_sec), timeout=120)

    def restart(self, timeout_sec: int = 30) -> None:
        self.compose("restart", "-t", str(timeout_sec), "backend", timeout=120)

    def down(self) -> None:
        self.compose("down", "-v", timeout=120)

    def validate_compose(self) -> None:
        result = self.compose("config", "--quiet", check=False)
        if result.returncode != 0:
            raise ManageError(
                f"docker-compose.yml 校验失败:\n{result.stderr.strip() or result.stdout.strip()}"
            )

    def logs_text(
        self,
        tail: int | str = 200,
        *,
        follow: bool = False,
        service: ServiceName | Literal["all"] = "all",
    ) -> str:
        cmd: list[str | Path] = ["logs", "--timestamps", "--tail", str(tail)]

        if follow:
            cmd.append("-f")
        if service != "all":
            cmd.append(service)

        result = self.compose(*cmd, check=False)
        return result.stdout + result.stderr

    def view_logs(
        self,
        tail: int | str = 200,
        *,
        follow: bool = False,
        service: ServiceName | Literal["all"] = "all",
    ) -> None:
        # 安装失败路径由 dump_diagnostics 输出更详细的诊断，此处仅面向菜单「查看日志」
        if not self.compose_file.is_file():
            out("尚未安装（docker-compose.yml 不存在）。")
            return
        if not self.service_exists("backend"):
            # 容器已退出时仍有日志可查，不直接返回误导信息
            text = self.logs_text(tail, follow=follow, service=service)
            if text.strip():
                out(text.strip())
                out("\n[提示] 后端容器未运行，以上为最近日志。")
                return
            out("尚未安装或服务不存在。")
            return

        text = self.logs_text(tail, follow=follow, service=service)
        out(text.strip() or "（暂无日志输出）")

    def dump_diagnostics(self, *, tail: int = 200) -> None:
        """安装/更新失败时输出分服务诊断，不依赖 service_exists 误导。"""
        out("\n--- 诊断信息 ---")
        # compose ps
        ps = self.compose("ps", "-a", check=False)
        if ps.stdout.strip() or ps.stderr.strip():
            out(ps.stdout.strip() or ps.stderr.strip())
        else:
            out("compose ps 无输出")

        # 按服务分别输出日志（动态获取实际存在的服务，兼容单容器/拆分拓扑）
        services: tuple[str, ...] = ("backend", "postgres", "redis", "nginx")
        listed = self.compose("config", "--services", check=False)
        if listed.returncode == 0 and listed.stdout.strip():
            services = tuple(sorted(listed.stdout.split()))
        for svc in services:
            out(f"\n--- {svc} 日志（最近 {tail} 行）---")
            txt = self.logs_text(tail, service=svc)  # type: ignore[arg-type]
            out(txt.strip() or f"（{svc} 暂无日志）")

        # 指向配置文件与下一步排查
        out("\n[提示] 可执行：")
        out(f"  docker compose -p {self.project} -f {self.compose_file} logs --tail 500 backend")
        out(f"  cat {CONFIG_FILE}")
        out(f"  docker compose -p {self.project} -f {self.compose_file} ps -a")

    def exec_pylaios(
        self,
        *args: str,
        check: bool = True,
        timeout: int | None = None,
        stdin: str | None = None,
        service: ServiceName = "backend",
    ) -> subprocess.CompletedProcess[str]:
        return self.compose(
            "exec",
            "-T",
            "-i",
            service,
            PYLAIOS_BIN,
            *args,
            check=check,
            timeout=timeout,
            stdin=stdin,
        )

    def load_image_tar(self, tar_path: Path) -> str:
        out(f"==> 加载镜像 {tar_path.name} ...")
        # 架构强校验：非兼容架构需二次确认（yes 模式除外，由调用方决定）
        meta = parse_tar(tar_path)
        if meta:
            _, arch = meta
            cur = host_arch()
            if arch != cur:
                out(f"[警告] 镜像架构 {arch} 与本机 {cur} 不一致，可能无法运行。")

        result = self.docker("load", "-i", tar_path, timeout=1200)

        # 优先通过 docker images 精确匹配最近加载的镜像（不依赖 Loaded image 文本格式）
        # 回退：解析 Loaded image 行
        candidates: list[str] = []
        for line in (result.stdout + result.stderr).splitlines():
            if "Loaded image" in line and ":" in line:
                # 形如 "Loaded image: pylaios:0.0.12-AMD64"
                try:
                    name = line.split("Loaded image", 1)[1].split(":", 1)[1].strip()
                    # 去除可能的引号与空格
                    name = name.strip().strip('"').strip("'")
                    if name:
                        candidates.append(name.split()[-1].strip())
                except Exception:
                    continue

        if candidates:
            # 取最后一个 Loaded image
            last = candidates[-1]
            if self.docker("image", "inspect", last, check=False).returncode == 0:
                out(f"  已加载: {last}")
                return last

        # 期望名兜底（兼容旧 tar 命名）
        version, arch = meta or ("0.0.1", host_arch())
        expected = f"pylaios:{version}-{arch}"
        if self.docker("image", "inspect", expected, check=False).returncode == 0:
            out(f"  已加载（按命名推断）: {expected}")
            return expected

        # 最后尝试：列出最近镜像按时间排序
        img_list = self.docker("images", "--format", "{{.Repository}}:{{.Tag}}", check=False)
        if img_list.stdout.strip():
            for line in reversed(img_list.stdout.splitlines()):
                if "pylaios" in line:
                    if self.docker("image", "inspect", line.strip(), check=False).returncode == 0:
                        out(f"  已加载（按列表推断）: {line.strip()}")
                        return line.strip()

        raise ManageError(
            f"无法确定镜像名称，请手动确认:\n{result.stdout}\n{result.stderr}"
        )

    def read_env(self) -> EnvMap:
        env_file = HOME / ".env"
        if env_file.is_file():
            return parse_env_file(env_file)
        return {}

    def wait_healthy(self, api_port: int, timeout: int | None = None, *, warn_after: int = 300) -> bool:
        """等待 /health/ready 就绪。

        - timeout=None 时永不超时（按用户要求取消自动取消），仅在超过 warn_after 后每 60s 输出警告。
        - 若 backend 容器退出则立即返回 False，由调用方输出诊断。
        """
        url = f"http://127.0.0.1:{api_port}/health/ready"
        start = time.monotonic()
        warned = False
        last_warn = start
        deadline = (start + timeout) if timeout is not None else None
        attempt = 0

        while True:
            attempt += 1
            elapsed = int(time.monotonic() - start)

            # 尝试健康检查
            health_ok = False
            health_body = ""
            health_status: int | None = None
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    health_status = resp.status
                    health_body = resp.read().decode("utf-8", errors="ignore")[:500]
                    if resp.status == 200:
                        if elapsed > 5:
                            out(f"[就绪] 健康检查通过（耗时 {elapsed}s）")
                        return True
            except urllib.error.HTTPError as e:
                health_status = e.code
                with suppress(Exception):
                    health_body = e.read().decode("utf-8", errors="ignore")[:500]
            except Exception as e:
                health_body = str(e)[:200]

            # 后置：容器是否仍存活
            if self.service_status("backend") != "running":
                out(f"[失败] 后端容器已退出（已等待 {elapsed}s，最后健康检查 status={health_status}）。")
                if health_body:
                    out(f"  health body: {health_body[:300]}")
                return False

            # 超时分支（仅当显式传入 timeout）
            if deadline is not None and time.monotonic() >= deadline:
                out(f"[超时] 健康检查 {timeout}s 内未通过（最后 status={health_status}）。")
                if health_body:
                    out(f"  health body: {health_body[:300]}")
                return False

            # 警告分支：超过 warn_after 后每 60s 警告一次
            if not warned and elapsed >= warn_after:
                out(f"[警告] 当前步骤超过5分钟无响应（已等待 {elapsed}s，最后 status={health_status}），仍在等待…")
                if health_body:
                    out(f"  详情: {health_body[:300]}")
                warned = True
                last_warn = time.monotonic()
            elif warned and time.monotonic() - last_warn >= 60:
                out(f"[等待] 仍未就绪，已等待 {elapsed}s（最后 status={health_status}）…")
                last_warn = time.monotonic()
            else:
                # 常规进度（每 15s 打印一次，避免刷屏）
                if attempt % 5 == 0 and elapsed < warn_after:
                    out(f"[等待] 后端启动中… 已等待 {elapsed}s（health status={health_status or 'unreachable'}）")

            time.sleep(3)


# ============================================================================
# Compose 配置
# ============================================================================
class ComposeConfig:
    COMPOSE_FILE = HOME / "docker-compose.yml"
    ENV_FILE = HOME / ".env"

    _COMPOSE_TEMPLATE = """\
services:
  postgres:
    image: {postgres_image}
    restart: unless-stopped
    volumes:
      - pylai_pgdata:/var/lib/postgresql
    environment:
      POSTGRES_USER: ${{PYLAI_DB_USER:?}}
      POSTGRES_PASSWORD: ${{PYLAI_DB_PASSWORD:?}}
      POSTGRES_DB: ${{PYLAI_DB_NAME:?}}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${{PYLAI_DB_USER}} -d ${{PYLAI_DB_NAME}}"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: {redis_image}
    restart: unless-stopped
    volumes:
      - pylai_redisdata:/data
    command: >
      redis-server
      --requirepass ${{PYLAI_REDIS_PASSWORD:?}}
      --appendonly yes
      --save ""
    healthcheck:
      test: ["CMD-SHELL", "redis-cli --no-auth-warning -a $$REDIS_PASSWORD --raw incr ping | grep -qE '^[0-9]+$'"]
      interval: 5s
      timeout: 3s
      retries: 5
    environment:
      REDIS_PASSWORD: ${{PYLAI_REDIS_PASSWORD}}

  backend:
    image: {backend_image}
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - {config_dir}:/etc/pylai:ro
      - pylai_data:/var/lib/pylai
      - pylai_www:/var/lib/pylai/www
    ports:
      - "127.0.0.1:${{PYLAI_API_PORT:?}}:5000"
    environment:
      PYLAI_ROLE: backend
      PYLAI_CONFIG: /etc/pylai/pylai.toml
      PYLAI_DB_USER: ${{PYLAI_DB_USER:?}}
      PYLAI_DB_PASSWORD: ${{PYLAI_DB_PASSWORD:?}}
      PYLAI_DB_NAME: ${{PYLAI_DB_NAME:?}}
      PYLAI_REDIS_PASSWORD: ${{PYLAI_REDIS_PASSWORD:?}}
    cap_drop: [ALL]
    cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]
    read_only: true
    tmpfs:
      - /tmp:rw,nosuid,size=64m
    # 镜像自带 HEALTHCHECK 探测容器内 nginx(:80)，拆分模式下后端只监听 :5000，需覆盖
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health/live', timeout=3).status == 200 else 1)"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 60s

  nginx:
    image: {nginx_image}
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "${{PYLAI_PUBLIC_PORT:?}}:80"
    volumes:
      - {config_dir}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - pylai_www:/var/lib/pylai/www:ro

volumes:
  pylai_pgdata:
  pylai_redisdata:
  pylai_data:
  pylai_www:
"""

    @classmethod
    def generate(
        cls,
        answers: InstallAnswers,
        manager: ManagerConfig | None = None,
        image: str = "pylaios:latest",
    ) -> None:
        ensure_home()

        services_cfg = manager.get("Compose", "Services", default={}) if manager else {}
        services_cfg = services_cfg or {}

        compose_text = cls._COMPOSE_TEMPLATE.format(
            postgres_image=services_cfg.get("PostgresImage", "postgres:18-alpine"),
            redis_image=services_cfg.get("RedisImage", "redis:8-alpine"),
            backend_image=services_cfg.get("BackendImage", image),
            nginx_image=services_cfg.get("NginxImage", "nginx:alpine"),
            config_dir=CONFIG_DIR,
        )

        atomic_write(cls.ENV_FILE, "\n".join(answers.env_lines()) + "\n")
        atomic_write(cls.COMPOSE_FILE, compose_text)
        cls.write_nginx_conf()

    @classmethod
    def regenerate(cls, image: str, manager: ManagerConfig | None = None) -> None:
        """更新时按最新模板全量重渲染 compose（保留现有 .env 凭据与 nginx 配置）。"""
        ensure_home()

        services_cfg = manager.get("Compose", "Services", default={}) if manager else {}
        services_cfg = services_cfg or {}

        compose_text = cls._COMPOSE_TEMPLATE.format(
            postgres_image=services_cfg.get("PostgresImage", "postgres:18-alpine"),
            redis_image=services_cfg.get("RedisImage", "redis:8-alpine"),
            backend_image=services_cfg.get("BackendImage", image),
            nginx_image=services_cfg.get("NginxImage", "nginx:alpine"),
            config_dir=CONFIG_DIR,
        )

        atomic_write(cls.COMPOSE_FILE, compose_text)
        cls.write_nginx_conf()

    @classmethod
    def write_nginx_conf(cls) -> None:
        # 拆分拓扑站点配置：静态资源来自 backend 容器同步的共享卷（/var/lib/pylai/www），
        # API/OIDC 反代到 backend 服务；conf.d 片段处于 http 上下文，types 与主配置合并追加
        # （不得下放到 server/location 级，否则整体替换 MIME 映射导致静态资源被下载）。
        template = """\
# 字体 MIME：默认 mime.types 缺少 ttf，浏览器会拒绝加载 @font-face 字体（http 级合并追加）
types {
    font/ttf ttf;
}
server_tokens off;

server {
    listen 80;
    server_name _;

    root /var/lib/pylai/www/ui;
    index index.html;
    client_max_body_size 2m;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

    location = /admin { return 301 /admin/; }
    location /admin/ {
        alias /var/lib/pylai/www/adminui/;
        index index.html;
        try_files $uri $uri/ /admin/index.html;
    }
    location /api/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /connect/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /health {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
    }
    location /.well-known/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location / { try_files $uri $uri/ /index.html; }
}
"""
        atomic_write(CONFIG_DIR / "nginx.conf", template, mode=0o644)

    @classmethod
    def ensure_volumes(cls) -> None:
        for vol in ("pylai_pgdata", "pylai_redisdata", "pylai_data", "pylai_www"):
            run(["docker", "volume", "create", vol], check=False)

    @classmethod
    def validate_compose(cls, compose_file: Path | None = None) -> None:
        target = compose_file or cls.COMPOSE_FILE
        result = run(
            ["docker", "compose", "-f", target, "config", "--quiet"],
            check=False,
        )
        if result.returncode != 0:
            raise ManageError(
                f"docker-compose.yml 校验失败:\n{result.stderr.strip() or result.stdout.strip()}"
            )


# ============================================================================
# Release 客户端与自更新
# ============================================================================
class ReleaseClient:
    REPO = "Kirsmin/Pylai"
    USER_AGENT = f"ManagePylai/{__version__}"

    PREDEFINED_API: dict[str, str] = {
        "Github": "https://api.github.com",
        "ghproxy": "https://ghproxy.com/https://api.github.com",
    }

    PREDEFINED_RAW: dict[str, str] = {
        "Github": "https://github.com",
        "ghproxy": "https://ghproxy.com/https://github.com",
    }

    def __init__(self, manager: ManagerConfig) -> None:
        self.manager = manager
        self.mirror = manager.mirror
        self.custom_base = manager.custom_mirror_base
        self.is_custom = self.mirror == "Custom" and bool(self.custom_base)

    def _api_url(self, path: str) -> str:
        if self.is_custom:
            raise ManageError("自定义镜像源不支持 GitHub API 调用")

        base = self.PREDEFINED_API.get(self.mirror, self.PREDEFINED_API["Github"])
        return f"{base}/repos/{self.REPO}/{path}"

    def _release_url(self, version: str, filename: str) -> str:
        if self.is_custom:
            base = (self.custom_base or "").rstrip("/")
            return f"{base}/releases/v{version}/{filename}"

        base = self.PREDEFINED_RAW.get(self.mirror, self.PREDEFINED_RAW["Github"])
        return f"{base}/{self.REPO}/releases/download/v{version}/{filename}"

    def _latest_url(self) -> str:
        if self.is_custom:
            base = (self.custom_base or "").rstrip("/")
            return f"{base}/releases/latest.json"
        return self._api_url("releases/latest")

    def check_latest(self) -> tuple[str, str, Json] | None:
        headers = {"User-Agent": self.USER_AGENT}

        if not self.is_custom:
            headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )

        with suppress(OSError, urllib.error.URLError, json.JSONDecodeError):
            request = urllib.request.Request(self._latest_url(), headers=headers)

            with urllib.request.urlopen(request, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if self.is_custom:
                version = str(data.get("version", ""))
                return version, f"v{version}", data

            tag = str(data.get("tag_name", ""))
            return tag.removeprefix("v"), tag, data

        return None

    def fetch_release_json(self, version: str) -> Json | None:
        if self.is_custom:
            base = (self.custom_base or "").rstrip("/")
            url = f"{base}/releases/v{version}/release.json"
        else:
            url = self._release_url(version, "release.json")

        with suppress(OSError, urllib.error.URLError, json.JSONDecodeError):
            request = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return None

    def list_releases(
        self,
        *,
        include_prerelease: bool = False,
        limit: int = 12,
    ) -> list[Json]:
        """列出远端历史发布版本（GitHub API，按发布时间倒序）。

        自定义镜像源（静态文件服务器）无法枚举历史版本，返回空列表。
        每个元素: {version, prerelease, published_at, assets: [name]}。
        """
        if self.is_custom:
            return []

        items: list[Json] = []
        try:
            request = urllib.request.Request(
                self._api_url(f"releases?per_page={limit}"),
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(request, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return []

        for rel in data or []:
            if not isinstance(rel, dict):
                continue
            tag = str(rel.get("tag_name", "")).removeprefix("v").removeprefix("V")
            if not tag:
                continue
            if rel.get("prerelease") and not include_prerelease:
                continue
            items.append(
                {
                    "version": tag,
                    "prerelease": bool(rel.get("prerelease")),
                    "published_at": str(rel.get("published_at", "")),
                    "assets": [a.get("name") for a in (rel.get("assets") or []) if isinstance(a, dict)],
                }
            )
        return items

    def fetch_asset_sha256(self, version: str, filename: str) -> str | None:
        """获取远端 <filename>.sha256 校验文件的第一段哈希；失败返回 None。"""
        url = self._release_url(version, f"{filename}.sha256")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as resp:
                text = resp.read().decode("utf-8", "replace").strip()
            if not text:
                return None
            return text.split()[0].lower()
        except (OSError, urllib.error.URLError):
            return None

    def download(
        self,
        version: str,
        filename: str,
        dest: Path,
        *,
        sha256_expected: str | None = None,
    ) -> None:
        url = self._release_url(version, filename)
        out(f"==> 下载 {filename} ...")

        try:
            request = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            digest = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=300) as resp:
                with dest.open("wb") as f:
                    while chunk := resp.read(1024 * 1024):
                        digest.update(chunk)
                        f.write(chunk)
        except (OSError, urllib.error.URLError) as exc:
            dest.unlink(missing_ok=True)
            raise ManageError(f"下载失败: {exc}") from exc

        if sha256_expected:
            actual = digest.hexdigest()
            if actual != sha256_expected:
                dest.unlink(missing_ok=True)
                raise ManageError(f"SHA256 校验失败: 期望 {sha256_expected}, 实际 {actual}")


class SelfUpdater:
    def __init__(
        self,
        client: ReleaseClient,
        manager: ManagerConfig,
        state: State | None = None,
        script_path: Path | None = None,
    ) -> None:
        self.client = client
        self.manager = manager
        self.state = state
        self.script_path = script_path or Path(__file__).resolve()

    @staticmethod
    def version_key(version: str) -> tuple[int, ...]:
        parts = [
            int(m.group()) if (m := re.match(r"\d+", part)) else 0
            for part in version.split(".")
        ]
        return (*parts, *[0] * max(0, 3 - len(parts)))

    @classmethod
    def version_gt(cls, a: str, b: str) -> bool:
        return cls.version_key(a) > cls.version_key(b)

    def check(self) -> tuple[str, Json] | None:
        result = self.client.check_latest()
        if not result:
            return None

        version, _, info = result

        if not self.version_gt(version, __version__):
            return None

        if self.manager.skip_version == version:
            out(f"版本 {version} 已标记为跳过。")
            return None

        return version, info

    def _check_schema_compat(self, release_info: Json) -> bool:
        remote_schema = release_info.get("dbSchemaVersion")
        if not remote_schema:
            return True

        if not self.state or not self.state.installed:
            return True

        current_pylai_version = self.state.version
        current_release = self.client.fetch_release_json(current_pylai_version)

        if not current_release:
            out(
                f"警告：无法获取当前 Pylai {current_pylai_version} 的 release.json，"
                "跳过 schema 兼容性检查。"
            )
            return True

        current_schema = current_release.get("dbSchemaVersion", "0")
        if remote_schema == current_schema:
            return True

        out(f"dbSchemaVersion 不兼容: 当前 {current_schema} -> 目标 {remote_schema}")
        out("此更新需要手动数据库迁移，请查看迁移文档后手动执行。")
        return False

    def update(
        self,
        *,
        force: bool = False,
        dry_run: bool = False,
        skip_prompt: bool = False,
    ) -> bool:
        result = self.client.check_latest()
        if not result:
            out("无法获取最新版本信息。")
            return False

        version, _, info = result

        if not force and not self.version_gt(version, __version__):
            out(f"当前已是最新版本 {__version__}。")
            return False

        out(f"==> 更新 ManagePylai.py: {__version__} -> {version}")

        if not self._check_schema_compat(info):
            if skip_prompt:
                out("Schema 不兼容且非交互模式，跳过更新。")
                return False

            if not ask_bool("Schema 不兼容，仍强制更新管理工具（不推荐）？", False):
                return False

        new_script = self.script_path.with_suffix(".py.new")
        sha256_file = self.script_path.with_suffix(".py.sha256")

        try:
            self.client.download(version, "ManagePylai.py", new_script)
        except ManageError as exc:
            out(f"下载失败: {exc}")
            new_script.unlink(missing_ok=True)
            return False

        sha256_expected: str | None = None

        try:
            self.client.download(version, "ManagePylai.py.sha256", sha256_file)
            sha256_content = sha256_file.read_text(encoding="ascii").strip()
            sha256_expected = sha256_content.split()[0]
        except (ManageError, OSError):
            out("警告：无法下载或读取 SHA256 校验文件")

        if sha256_expected:
            actual = hashlib.sha256(new_script.read_bytes()).hexdigest()
            if actual != sha256_expected:
                out(f"SHA256 校验失败: 期望 {sha256_expected}, 实际 {actual}")
                new_script.unlink(missing_ok=True)
                sha256_file.unlink(missing_ok=True)
                return False
            out("SHA256 校验通过。")

        if dry_run:
            out(f"[dry-run] 将替换 {self.script_path} 为版本 {version}")
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            return True

        try:
            backup = self.script_path.with_suffix(f".py.bak.{__version__}")
            shutil.copy2(self.script_path, backup)
            os.replace(new_script, self.script_path)
            self.manager.set_skip_version(None)
            out(f"ManagePylai.py 已更新至 {version}，请重新运行脚本。")
            return True
        except OSError as exc:
            out(f"替换失败: {exc}")
            return False
        finally:
            sha256_file.unlink(missing_ok=True)

    def ensure_up_to_date(self, *, yes: bool = False) -> None:
        result = self.check()
        if not result:
            return

        version, info = result
        message = f"ManagePylai.py 有新版本 {version}，是否先更新管理工具？"

        if yes:
            out(message + " [Y/n] Y (非交互模式)")
            if self.update(skip_prompt=yes):
                out("管理工具已更新，请重新运行命令。")
                sys.exit(0)
            return

        if ask_bool(message, True):
            if self.update():
                out("管理工具已更新，请重新运行命令。")
                sys.exit(0)
        else:
            if ask_bool(f"是否跳过版本 {version} 的后续提醒？", False):
                self.manager.set_skip_version(version)
                out(f"已设置跳过版本 {version}。")

            out("警告：使用旧版本管理工具更新可能存在兼容性问题。")


# ============================================================================
# 云端分发（GitHub Release 下载 + 版本选择）
# ============================================================================
RELEASE_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$")


def normalize_release_version(raw: str) -> str:
    """规范化用户输入的版本号：去掉 v/V 前缀，校验合法格式。"""
    version = str(raw).strip()
    if version.startswith(("v", "V")):
        version = version[1:]
    if not RELEASE_VERSION_RE.match(version):
        raise ManageError(
            f"非法版本号: {raw!r}（格式应为 0.0.1，可选 -预发布后缀）"
        )
    return version


def resolve_remote_version(
    client: ReleaseClient,
    manager: ManagerConfig,
    *,
    requested: str | None = None,
    yes: bool = False,
    prompt: str = "请选择要从云端使用（安装/更新）的版本",
) -> str:
    """解析云端目标版本：--version 指定 > 交互选择列表 > 默认最新。"""
    if requested:
        return normalize_release_version(requested)

    releases = client.list_releases(include_prerelease=manager.include_prerelease, limit=12)
    # 过滤后为空（如仅剩预发布）时回退列出全部
    if not releases and not manager.include_prerelease:
        releases = client.list_releases(include_prerelease=True, limit=12)

    if not releases:
        # 自定义镜像源或列表失败：回退到最新版本
        if latest := client.check_latest():
            version, _, _ = latest
            if yes:
                out(f"云端最近版本: v{version}（自定义镜像源无法枚举历史版本）")
                return version
            out(f"云端最近版本: v{version}")
            if ask_bool("使用该版本？", True):
                return version
        raise ManageError("无法获取云端版本信息，请检查网络与镜像源设置。")

    if yes:
        # 非交互模式：默认取列表首个（已按配置过滤预发布，最新优先）
        return releases[0]["version"]

    options = [
        (
            f"v{r['version']}（{'预发布' if r['prerelease'] else '正式版'}）",
            r["version"],
        )
        for r in releases
    ]
    chosen = choose(options, prompt)
    if not chosen:
        raise ManageError("未选择版本。")
    return chosen


def ensure_remote_tar(
    client: ReleaseClient,
    manager: ManagerConfig,
    version: str,
    *,
    force: bool = False,
) -> Path:
    """从云端下载（或复用缓存）Pylai-<version>-Linux-<arch>.tar，并 SHA256 校验。

    下载目录默认 ~/.pylai/downloads，可通过 ManagerConfig.toml [Updates] DownloadDir 配置。
    已缓存且哈希匹配时直接复用，避免重复下载大文件。
    """
    arch = host_arch()
    filename = f"Pylai-{version}-Linux-{arch}.tar"

    dest_dir = Path(manager.download_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    remote_sha = client.fetch_asset_sha256(version, filename)
    if not remote_sha:
        raise ManageError(
            f"无法获取 {filename}.sha256（版本 v{version} 可能未发布对应架构产物或网络异常）。"
        )

    if dest.is_file() and not force:
        actual = hashlib.sha256(dest.read_bytes()).hexdigest()
        if actual == remote_sha:
            out(f"==> 使用已下载的安装包: {dest}")
            return dest
        out("[警告] 缓存安装包校验不匹配，重新下载。")

    client.download(version, filename, dest, sha256_expected=remote_sha)
    out(f"==> 下载完成: {dest}（SHA256 校验通过）")
    return dest


def choose_install_source(prompt: str = "请选择安装/更新来源") -> str:
    """交互选择安装/更新包的来源：本地 tar 或云端 GitHub Release。"""
    chosen = choose(
        [
            ("本地磁盘上的 Pylai-<version>-Linux-<arch>.tar", "local"),
            ("从云端 GitHub Release 下载并选择版本", "remote"),
        ],
        prompt,
    )
    if chosen is None:
        raise ManageError("未选择来源。")
    return chosen


# ============================================================================
# AppContext
# ============================================================================
@dataclass(slots=True)
class AppContext:
    manager: ManagerConfig
    state: State
    docker: DockerCompose
    config: PylaiConfig

    @classmethod
    def create(cls, manager_config: Path | None = None) -> Self:
        manager = ManagerConfig(manager_config or HOME / "ManagerConfig.toml")
        state = State()
        docker = DockerCompose(project=manager.project_name)
        config = PylaiConfig()
        return cls(manager=manager, state=state, docker=docker, config=config)

    def require_installed(self) -> None:
        if not self.state.installed:
            raise ManageError("尚未安装，请先执行安装。")

    def require_running(self, service: ServiceName = "backend") -> None:
        if not self.docker.service_running(service):
            raise ManageError("服务未运行。")


# ============================================================================
# 通用服务函数
# ============================================================================
def _version_key(path: Path) -> tuple[int, ...]:
    meta = parse_tar(path)
    if meta is None:
        return (0,)
    try:
        return tuple(int(part) for part in meta[0].split("."))
    except ValueError:
        return (0,)


def select_tar(*, yes: bool, prompt: str = "请选择安装包") -> Path:
    tars = discover_tars()
    if not tars:
        raise ManageError("当前目录未找到 Pylai-<version>-Linux-<arch>.tar。")

    if yes:
        compatible = [
            p
            for p in tars
            if (meta := parse_tar(p)) and meta[1] == host_arch()
        ]
        if not compatible:
            raise ManageError(f"当前目录没有与主机架构 {host_arch()} 匹配的安装包。")
        return sorted(compatible, key=_version_key)[-1]

    options: list[tuple[str, Path]] = []
    for path in tars:
        meta = parse_tar(path)
        compatible = meta is not None and meta[1] == host_arch()
        label = f"{path.name}（{'兼容' if compatible else '其他架构'}）"
        options.append((label, path))

    selected = choose(options, prompt)
    if selected is None:
        raise ManageError("未选择安装包。")

    return selected


def generate_host_nginx_template(state: State) -> Path:
    host_part = state.public_url.split("//", 1)[-1].split("/", 1)[0]

    template = f"""# Pylai 主机 Nginx 配置模板
# 安装前请替换证书路径和 server_name。

server {{
    listen 80;
    server_name {host_part};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {host_part};

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

    client_max_body_size 2m;

    location / {{
        proxy_pass http://127.0.0.1:{state.public_port};
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

    atomic_write(HOST_NGINX_FILE, template)
    return HOST_NGINX_FILE


def uninstall(ctx: AppContext, *, yes: bool, purge: bool) -> None:
    ctx.require_installed()

    if not yes and not confirm_danger("卸载会停止并删除 Compose 服务，可能删除全部数据。"):
        out("已取消。")
        return

    ctx.docker.down()

    for vol in ("pylai_data", "pylai_pgdata", "pylai_redisdata"):
        ctx.docker.docker("volume", "rm", "-f", vol, check=False)

    if image := ctx.state.image:
        ctx.docker.docker("rmi", image, check=False)

    if purge or (
        not yes
        and confirm_danger("同时删除 ~/.pylai 全部数据目录（建议保留备份）？")
    ):
        shutil.rmtree(HOME, ignore_errors=True)
        out("已删除全部数据目录。")

    STATE_FILE.unlink(missing_ok=True)
    ctx.state.clear()
    ctx.state.save()
    out("卸载完成。")


type ServiceAction = Literal["start", "stop", "restart", "status"]


def service_action(ctx: AppContext, action: ServiceAction) -> None:
    """统一处理 start/stop/restart/status，取代原先的四个孪生函数。"""
    if action == "status":
        result = ctx.docker.docker(
            "ps", "-a", "--filter", f"name={ctx.docker.project}",
            "--format", "{{.Names}} {{.Status}}", check=False,
        )
        out(result.stdout.strip() or "未找到服务")
        return

    ctx.require_installed()

    match action:
        case "start":
            ctx.docker.compose("up", "-d", timeout=120)
            try:
                ctx.docker.validate_compose()
            except ManageError as e:
                out(f"Compose 校验警告: {e}")
            healthy = ctx.docker.wait_healthy(ctx.state.api_port, timeout=None, warn_after=300)
            if healthy:
                out("启动完成。")
            else:
                out("服务已启动，但健康检查未通过。")
                ctx.docker.dump_diagnostics(tail=200)
        case "stop":
            ctx.docker.stop()
            out("已停止。")
        case "restart":
            ctx.docker.restart()
            out("已重启。")


# ============================================================================
# 安装 / 更新 / 备份 / 用户 / 安全 / 配置服务
# ============================================================================
class InstallService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def install_cli(self, args: argparse.Namespace) -> None:
        tar_path = self._resolve_install_tar(args)
        image = self.ctx.docker.load_image_tar(tar_path)
        answers = self.resolve_answers(args)
        interactive = not (args.yes or args.pylai_config or args.env_file)
        allow_compat = bool(getattr(args, "compat", False))

        if getattr(args, "dry_run", False):
            out("[dry-run] 预览安装配置（不实际启动）：")
            validate_answers(answers)
            out(f"  public_url: {answers.public_url}")
            out(f"  public_port: {answers.public_port}  api_port: {answers.api_port}")
            out(f"  db: {answers.db_user}@{answers.db_name}  redis: ***")
            out(f"  image: {image}  compat: {allow_compat}")
            # 尝试生成配置到内存并校验，不落盘
            try:
                PylaiConfig.generate_from_template(image, answers, allow_compat=allow_compat)
                out("  配置模板渲染通过（已写入 pylai.toml，dry-run 场景可手动检查）")
            except Exception as e:
                out(f"  配置生成失败: {e}")
            out("  Compose 预览: ~/.pylai/docker-compose.yml / ~/.pylai/.env")
            return

        self.core_install(
            tar_path,
            image,
            answers,
            from_existing=bool(args.pylai_config),
            interactive=interactive,
            allow_compat=allow_compat,
            yes_mode=args.yes,
        )

    def _resolve_install_tar(self, args: argparse.Namespace) -> Path:
        """解析安装包来源：--from-remote 从云端下载，否则从本地磁盘选择。"""
        from_remote = bool(getattr(args, "from_remote", False))
        if from_remote:
            client = ReleaseClient(self.ctx.manager)
            version = resolve_remote_version(
                client,
                self.ctx.manager,
                requested=getattr(args, "version", None),
                yes=bool(args.yes),
                prompt="请选择要安装的版本",
            )
            return ensure_remote_tar(client, self.ctx.manager, version, force=bool(getattr(args, "force", False)))
        return select_tar(yes=args.yes)

    def install_interactive(self) -> None:
        source = choose_install_source("请选择安装包的来源")
        client = ReleaseClient(self.ctx.manager)

        if source == "remote":
            version = resolve_remote_version(
                client,
                self.ctx.manager,
                prompt="请选择要安装的版本",
            )
            tar_path = ensure_remote_tar(client, self.ctx.manager, version)
        else:
            tar_path = select_tar(yes=False)

        image = self.ctx.docker.load_image_tar(tar_path)
        answers = InstallAnswers.collect_interactive()

        self.core_install(
            tar_path,
            image,
            answers,
            from_existing=False,
            interactive=True,
            allow_compat=False,
            yes_mode=False,
        )

    def resolve_answers(self, args: argparse.Namespace) -> InstallAnswers:
        if args.pylai_config:
            source = Path(args.pylai_config).expanduser()
            self.ctx.config = PylaiConfig.from_existing(source)
            answers = self.ctx.config.extract_answers()

            answers.public_port = as_int(
                os.environ.get("PYLAI_PUBLIC_PORT"),
                answers.public_port,
            )
            answers.api_port = as_int(
                os.environ.get("PYLAI_API_PORT"),
                answers.api_port,
            )

            if not answers.db_password or not answers.redis_password:
                raise ManageError(
                    "从现有配置无法提取数据库/Redis 密码，请检查 pylai.toml。"
                )

            return answers

        if args.env_file:
            return InstallAnswers.from_env(parse_env_file(Path(args.env_file).expanduser()))

        if args.yes:
            env = {k: v for k, v in os.environ.items() if k.startswith("PYLAI_")}
            return InstallAnswers.from_env(env)

        return InstallAnswers.collect_interactive()

    def core_install(
        self,
        tar_path: Path,
        image: str,
        answers: InstallAnswers,
        *,
        from_existing: bool,
        interactive: bool,
        allow_compat: bool = False,
        yes_mode: bool = False,
    ) -> None:
        ctx = self.ctx

        # ---- 安装流水线（每步带序号，便于定位失败点） ----
        steps: list[tuple[str, Callable[[], None]]] = []

        def step_validate() -> None:
            validate_answers(answers)

        def step_config() -> None:
            if not from_existing:
                PylaiConfig.generate_from_template(image, answers, allow_compat=allow_compat)
                ctx.config.reload()
            self.fix_container_hosts()
            # 生成后再次校验 TOML 合法性
            ctx.config.validate()
            out(f"  配置已写入: {CONFIG_FILE}（脱敏预览见 [6] 查看配置）")

        def step_compose() -> None:
            ComposeConfig.generate(answers, ctx.manager, image)
            # 预检 compose 语法
            try:
                ctx.docker.validate_compose()
            except ManageError as e:
                raise ManageError(f"Compose 校验失败:\n{e}") from e
            out(f"  Compose 已生成: {HOME / 'docker-compose.yml'} / {HOME / '.env'}")

        def step_volumes() -> None:
            ComposeConfig.ensure_volumes()

        def step_certs() -> None:
            ensure_signing_kek()
            self.ensure_signing_certificate(answers)
            self.ensure_encryption_certificate(answers, interactive=interactive)
            if answers.encryption_pfx:
                out(f"  加密证书: {answers.encryption_pfx}")

        def step_start() -> None:
            ctx.docker.ensure_docker()
            ctx.docker.start(image, answers)
            out(f"  容器已启动: {image} (public:{answers.public_port} api:{answers.api_port})")

        def step_health() -> None:
            out(f"==> 等待健康检查 http://127.0.0.1:{answers.api_port}/health/ready ...")
            # 取消超时自动取消，超过 300s 仅警告（按用户要求）
            healthy = ctx.docker.wait_healthy(answers.api_port, timeout=None, warn_after=300)
            if not healthy:
                ctx.docker.dump_diagnostics(tail=200)
                # 失败时保留现场，询问是否清理（yes_mode 则默认保留）
                if not yes_mode and not interactive:
                    # 非交互非 yes 模式（CLI --yes 已在外层）默认保留，提示手动清理
                    pass
                elif not yes_mode:
                    out("\n[提示] 安装失败，现场已保留以便排查。")
                    if ask_bool("是否清理本次创建的容器与数据卷（保留则可手动排查）？", False):
                        out("==> 清理中...")
                        with suppress(Exception):
                            ctx.docker.compose("down", "-v", check=False)
                raise ManageError("服务启动失败，请根据上方诊断信息排查。")

        steps = [
            ("校验输入与弱密码预检", step_validate),
            ("生成配置", step_config),
            ("生成 Compose", step_compose),
            ("创建数据卷", step_volumes),
            ("准备证书与 KEK", step_certs),
            ("启动容器", step_start),
            ("健康检查", step_health),
        ]

        total = len(steps)
        for idx, (label, fn) in enumerate(steps, 1):
            out(f"\n[{idx}/{total}] {label} ...")
            try:
                fn()
                out(f"  ✓ {label} 完成")
            except ManageError:
                out(f"  ✗ {label} 失败")
                # 任何一步失败后，若已生成 compose 则提示诊断
                if idx >= 3:
                    with suppress(Exception):
                        ctx.docker.dump_diagnostics(tail=100)
                raise
            except Exception as exc:
                out(f"  ✗ {label} 异常: {exc}")
                raise ManageError(f"{label} 失败: {exc}") from exc

        self.save_state(tar_path, image, answers)
        self.print_summary(answers)
        out("提示：建议使用主机 Nginx 反代，主菜单 [8] 可生成配置模板。")

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
        version, arch = parse_tar(tar_path) or ("0.0.1", host_arch())
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
        out("\n" + "=" * 64)
        out("  Pylai 安装完成")
        out(f"  前端:     {answers.public_url}/")
        out(f"  管理台:   {answers.public_url}/admin/")
        out(f"  健康检查: http://127.0.0.1:{answers.api_port}/health/ready")
        out()

        reveal_credentials(answers.credentials)

        if auto := answers.auto_generated_accounts:
            out(
                f"  提示: {', '.join(auto)} 密码已自动生成，"
                "请在容器日志中查看（[DbSeeder] 标记）。"
            )

        out("=" * 64)


class UpdateService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def update_cli(self, args: argparse.Namespace) -> None:
        if args.check_only:
            self.check_manager_update()
            self.check_app_update()
            return

        self.ensure_manager_up_to_date(args.yes)

        from_remote = bool(getattr(args, "from_remote", False))
        self.update_app(
            yes=args.yes,
            force_pg_upgrade=args.force_pg_upgrade,
            source="remote" if from_remote else "local",
            version=getattr(args, "version", None),
            force=getattr(args, "force", False),
        )

    def update_interactive(self) -> None:
        source = choose_install_source("请选择更新包的来源")
        self.update_app(
            yes=False,
            source=source,
            version=None,
        )

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
            input_text=input_text,
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
            f"将软删除用户 {target}，其全部会话将被吊销。"
        ):
            out("已取消。")
            return

        data = self.execute("delete", target)
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


# ============================================================================
# 网页配置编辑器（config web-edit / 主菜单 [7] 置顶入口）
# ============================================================================
def find_free_port() -> int:
    """获取一个 127.0.0.1 上当前无占用的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def generate_editor_password() -> str:
    """临时密码：前四位大写字母，后四位数字，例如 PAHE-0123。"""
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{digits}"


def editor_value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string"


def serialize_editor_value(change: Json) -> str:
    """把网页端提交的 JSON 值序列化为 TOML 字面量。"""
    kind = change.get("type")
    value = change.get("value")

    if kind == "boolean":
        return "true" if value else "false"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not _finite_number(value):
            raise ManageError(f"数值类型非法: {value!r}")
        return str(value)
    if kind == "array":
        items = value if isinstance(value, list) else []
        parts = [
            str(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and _finite_number(x) else toml_str(str(x))
            for x in items
        ]
        return f"[{', '.join(parts)}]"
    return toml_str("" if value is None else str(value))


def strip_multiline_value(text: str, marker: str, key: str) -> str:
    """替换多行字符串（''' / \"\"\"）前，先移除其续行，避免残留导致 TOML 非法。"""
    try:
        start, end = _toml_section_span(text, marker)
    except ValueError:
        return text

    block = text[start:end]
    lines = block.splitlines(keepends=True)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(?P<rhs>.*)$")

    for index, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue
        rhs = match.group("rhs")
        opener = re.match(r"^('''|\"\"\")", rhs)
        if not opener or opener.group(1) in rhs[3:]:
            return text  # 单行值，无需处理
        quote = opener.group(1)
        for tail in range(index + 1, len(lines)):
            if quote in lines[tail]:
                del lines[index + 1 : tail + 1]
                break
        return text[:start] + "".join(lines) + text[end:]

    return text


# ============================================================================
# 配置字段校验规则（白名单，与后端 OS/Features/Config/ConfigValidator.cs 对齐）
# 每条规则含中文说明 desc（下发前端展示）与校验约束（前端实时 + 服务端保存前双重校验）
# ============================================================================
def _bool(desc: str) -> Json:
    """布尔值：无需额外约束，仅保证类型。"""
    return {"kind": "boolean", "desc": desc}


def _num(desc: str, lo: int, hi: int, *, neg1: bool = False) -> Json:
    """数值：限制范围 [lo, hi]，neg1 表示允许 -1（如永久封禁）。"""
    rule: Json = {"kind": "number", "desc": desc, "min": lo, "max": hi}
    if neg1:
        rule["allowNegOne"] = True
    return rule


def _enum(desc: str, values: list[str]) -> Json:
    """枚举：值必须在可选列表内。"""
    return {"kind": "enum", "desc": desc, "enum": values}


def _url(desc: str, *, no_path: bool = False) -> Json:
    """URL：必须为 http(s)://host[:port]，no_path 要求不带路径。"""
    return {"kind": "url", "desc": desc, "noPath": no_path}


def _ip(desc: str) -> Json:
    return {"kind": "ip", "desc": desc}


def _cidr(desc: str) -> Json:
    return {"kind": "cidr", "desc": desc}


def _str(desc: str, *, required: bool = False, require_placeholder: str | None = None) -> Json:
    rule: Json = {"kind": "string", "desc": desc}
    if required:
        rule["required"] = True
    if require_placeholder:
        rule["requirePlaceholder"] = require_placeholder
    return rule


def _arr(desc: str, elem: str, **extra: Any) -> Json:
    """数组：元素按 elem（url/ip/cidr/number/string）逐个校验。"""
    rule: Json = {"kind": "array", "desc": desc, "arrayKind": elem, **extra}
    return rule


EDITOR_RULES: dict[str, Json] = {
    # ---- 服务监听 ----
    "Server.Url": _url("后端监听地址，形如 http://0.0.0.0:5000，不带路径", no_path=True),
    "Server.AllowedHosts": _arr("允许的请求 Host 白名单（生产禁止使用 *）", "string", required=True),
    "Server.MaxRequestBodyMB": _num("单个请求体最大体积（MB），默认 2", 1, 1024),

    # ---- 跨域 ----
    "Cors.Enabled": _bool("是否启用 CORS"),
    "Cors.AllowedOrigins": _arr("允许跨域的前端 Origin 列表", "url"),
    "Cors.AllowedMethods": _arr("允许的 HTTP 方法", "string"),
    "Cors.AllowedHeaders": _arr("允许的请求头", "string"),
    "Cors.AllowCredentials": _bool("是否允许携带 Cookie 凭证（开启时禁止通配符 *）"),

    # ---- 前端地址 ----
    "Frontend.Url": _url("浏览器访问 Pylai 的公开地址"),

    # ---- IP 解析 ----
    "IpResolution.TrustedProxies": _arr("可信反向代理 IP 列表", "ip"),
    "IpResolution.TrustedHeaders": _arr("可信的转发请求头", "string"),
    "IpResolution.IpWhitelist": _arr("IP 白名单（空为不限制）", "ip"),
    "IpResolution.ForwardedHeadersEnabled": _bool("是否启用转发请求头解析"),
    "IpResolution.TrustedNetworks": _arr("可信代理 CIDR 网段列表", "cidr"),

    # ---- 数据库 ----
    "Database.ConnectionString": _str("PostgreSQL 连接串（含密码，保存后不可见）", required=True),

    # ---- Redis ----
    "Redis.Host": _str("Redis 主机地址", required=True),
    "Redis.Port": _num("Redis 端口", 1, 65535),
    "Redis.Password": _str("Redis 密码（不能为弱口令）"),
    "Redis.Database": _num("Redis 数据库编号（0-15）", 0, 15),
    "Redis.ConnectTimeoutMs": _num("Redis 连接超时（毫秒）", 1, 600000),

    # ---- 备份 ----
    "Backup.Directory": _str("备份文件保存目录", required=True),

    # ---- 身份 ----
    "Identity.EmailCodeExpireMinutes": _num("邮箱验证码有效期（分钟）", 1, 60),
    "Identity.Password.RequiredLength": _num("普通用户密码最短长度", 4, 128),
    "Identity.Password.AdminRequiredLength": _num("Admin/Max 密码最短长度", 4, 128),
    "Identity.Password.CheckBreachedPasswords": _bool("是否校验密码已泄露（HIBP）"),
    "Identity.Password.RequireDigit": _bool("密码是否必须包含数字"),
    "Identity.Password.RequireLowercase": _bool("密码是否必须包含小写字母"),
    "Identity.Password.RequireUppercase": _bool("密码是否必须包含大写字母"),
    "Identity.Password.RequireNonAlphanumeric": _bool("密码是否必须包含特殊字符"),
    "Identity.Lockout.DefaultTimeoutMinutes": _num("登录失败锁定时长（分钟）", 1, 1440),
    "Identity.Lockout.MaxFailedAttempts": _num("触发锁定前的连续失败次数", 1, 100),

    # ---- Cookie ----
    "Cookie.Name": _str("身份认证 Cookie 名称", required=True),
    "Cookie.SessionName": _str("会话 Cookie 名称", required=True),
    "Cookie.HttpOnly": _bool("Cookie 是否禁止 JS 读取"),
    "Cookie.SameSite": _enum("SameSite 策略", ["Unspecified", "None", "Lax", "Strict"]),
    "Cookie.SecurePolicy": _enum("Cookie 安全策略", ["None", "Always", "SameAsRequest"]),
    "Cookie.ExpireDays": _num("登录有效期（天）", 1, 365),
    "Cookie.SlidingExpiration": _bool("是否滑动续期"),

    # ---- 数据保护 ----
    "DataProtection.KeyDirectory": _str("DataProtection 密钥目录（生产必须持久化）", required=True),

    # ---- 部署 ----
    "Deployment.BundledNginx": _bool("是否由镜像内置 Nginx 反代"),

    # ---- OpenIddict ----
    "OpenIddict.Issuer": _url("OIDC 颁发者地址，不带路径", no_path=True),
    "OpenIddict.RequireHttps": _bool("是否强制 HTTPS（开启后 Issuer 必须为 https）"),
    "OpenIddict.AccessToken.LifetimeHours": _num("访问令牌有效期（小时）", 1, 720),
    "OpenIddict.AccessToken.DisableEncryption": _bool("是否禁用访问令牌加密"),
    "OpenIddict.RefreshToken.LifetimeDays": _num("刷新令牌有效期（天）", 1, 365),
    "OpenIddict.IdentityToken.LifetimeHours": _num("身份令牌有效期（小时）", 1, 720),
    "OpenIddict.Endpoints.Authorize": _str("授权端点路径", required=True),
    "OpenIddict.Endpoints.Token": _str("令牌端点路径", required=True),
    "OpenIddict.Endpoints.UserInfo": _str("UserInfo 端点路径", required=True),
    "OpenIddict.Endpoints.Introspect": _str("内省端点路径", required=True),
    "OpenIddict.Endpoints.EndSession": _str("登出端点路径", required=True),
    "OpenIddict.Grants.AuthorizationCode": _bool("启用授权码授权"),
    "OpenIddict.Grants.RefreshToken": _bool("启用刷新令牌"),
    "OpenIddict.Grants.ClientCredentials": _bool("启用客户端凭证"),
    "OpenIddict.Scopes.openId": _bool("启用 openid scope"),
    "OpenIddict.Scopes.profileBasic": _bool("启用 profile:basic scope"),
    "OpenIddict.Scopes.profileMail": _bool("启用 profile:mail scope"),
    "OpenIddict.Scopes.profileRole": _bool("启用 profile:role scope"),
    "OpenIddict.Scopes.offlineAccess": _bool("启用 offline_access scope"),
    "OpenIddict.Certificates.Signing.Path": _str("签名证书 PFX 路径（数据库托管签名时可为空）"),
    "OpenIddict.Certificates.Signing.Password": _str("签名证书 PFX 密码"),
    "OpenIddict.Certificates.Encryption.Path": _str("加密证书 PFX 路径（生产环境必需）"),
    "OpenIddict.Certificates.Encryption.Password": _str("加密证书 PFX 密码"),
    "OpenIddict.SigningKeyEncryption.KeyFile": _str("签名密钥加密 KEK 文件路径（数据库托管签名时必需）"),

    # ---- 第三方登录 ----
    "ExternalLogin.Facebook.AppId": _str("Facebook AppId（留空关闭）"),
    "ExternalLogin.Facebook.AppSecret": _str("Facebook AppSecret"),
    "ExternalLogin.Microsoft.ClientId": _str("Microsoft ClientId（留空关闭）"),
    "ExternalLogin.Microsoft.ClientSecret": _str("Microsoft ClientSecret"),
    "ExternalLogin.Github.ClientId": _str("GitHub ClientId（留空关闭）"),
    "ExternalLogin.Github.ClientSecret": _str("GitHub ClientSecret"),

    # ---- 邮件 ----
    "Email.FromName": _str("发件人显示名称"),
    "Email.FromAddress": _str("发件人邮箱（与 SMTP Host 同空或同配）"),
    "Email.Smtp.Host": _str("SMTP 服务器地址（与 FromAddress 同空或同配）"),
    "Email.Smtp.Port": _num("SMTP 端口（465 隐式 TLS / 587 STARTTLS / 25 明文）", 1, 65535),
    "Email.Smtp.Security": _enum("SMTP 加密方式", ["None", "StartTls", "SslOnConnect"]),
    "Email.Smtp.Username": _str("SMTP 用户名（无认证留空）"),
    "Email.Smtp.Password": _str("SMTP 密码（无认证留空）"),

    # ---- 邮件模板 ----
    "MailTheme.Register.Title": _str("注册邮件标题", required=True),
    "MailTheme.Register.Context": _str("注册邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.Bind.Title": _str("绑定邮箱邮件标题", required=True),
    "MailTheme.Bind.Context": _str("绑定邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.Change.Title": _str("更换邮箱邮件标题", required=True),
    "MailTheme.Change.Context": _str("更换邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.PasswordReset.Title": _str("密码重置邮件标题", required=True),
    "MailTheme.PasswordReset.Context": _str("密码重置邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),

    # ---- 日志 ----
    "Logging.DefaultLevel": _enum("默认日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),
    "Logging.MicrosoftAspNetCoreLevel": _enum("ASP.NET Core 框架日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),
    "Logging.PylaiosLevel": _enum("Pylaios 日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),

    # ---- 清理 ----
    "TokenCleanup.Enabled": _bool("是否定期清理过期 Token"),

    # ---- 登录限流 ----
    "LoginRateLimit.MaxFailuresPerIp": _num("单个 IP 触发封禁的失败次数", 1, 1000),
    "LoginRateLimit.BanDurationMinutes": _arr("逐级封禁时长（分钟，-1 为永久）", "number", arrayMin=1, allowNegOne=True),
    "LoginRateLimit.CooldownDays": _num("封禁冷却天数（0 为不冷却）", 0, 365),

    # ---- 管理 API 限流 ----
    "AdminRateLimit.MaxFailuresFirstBan": _num("管理 API 首次封禁失败次数", 1, 100),
    "AdminRateLimit.FirstBanDurationSeconds": _num("管理 API 首次封禁时长（秒）", 1, 3600),
    "AdminRateLimit.MaxFailuresSecondBan": _num("管理 API 二次封禁失败次数", 1, 1000),
    "AdminRateLimit.SecondBanDurationHours": _num("管理 API 二次封禁时长（小时）", 1, 8760),

    # ---- 邀请码 ----
    "InviteCode.ServerPepper": _str("邀请码 HMAC 密钥（生产必须配置）", required=True),
    "InviteCode.MaxFailuresPerIp": _num("单 IP 邀请码失败次数上限", 1, 1000),
    "InviteCode.BanDurationHours": _num("邀请码失败封禁时长（小时）", 1, 8760),
    "InviteCode.EmailCodeBanDurationHours": _num("邮箱验证码失败封禁时长（小时）", 1, 8760),
    "InviteCode.UsernameCheckMaxPerHourPerIp": _num("单 IP 每小时用户名检查次数上限", 1, 10000),
    "InviteCode.MaxRedemptions": _num("单个邀请码最大核销次数", 1, 100000),
    "InviteCode.DefaultLifetimeHours": _num("邀请码默认有效期（小时）", 1, 8760),

    # ---- 种子账号 ----
    "Seeds.DefaultAdmin.Email": _str("初始 Admin 邮箱/登录名"),
    "Seeds.DefaultAdmin.Password": _str("初始 Admin 密码（留空由后端按策略生成）"),
    "Seeds.DefaultAdmin.DisplayName": _str("初始 Admin 显示名"),
    "Seeds.DefaultUser.Email": _str("初始 Normal 邮箱/登录名"),
    "Seeds.DefaultUser.Password": _str("初始 Normal 密码（留空由后端按策略生成）"),
    "Seeds.DefaultUser.DisplayName": _str("初始 Normal 显示名"),
    "Seeds.DefaultMax.Email": _str("初始 Max 邮箱/登录名"),
    "Seeds.DefaultMax.Password": _str("初始 Max 密码（留空由后端按策略生成）"),
    "Seeds.DefaultMax.DisplayName": _str("初始 Max 显示名"),

    # ---- 用户 Token ----
    "UserToken.DefaultLifetimeDays": _num("用户 Token 默认有效期（天，0 为永久，生产上限 90）", 0, 90),

    # ---- 二次验证限流 ----
    "ConfirmationRateLimit.MaxFailures": _num("特殊功能二次验证失败次数上限", 1, 1000),
    "ConfirmationRateLimit.BanDurationHours": _num("二次验证失败封禁时长（小时）", 1, 8760),

    # ---- MFA ----
    "Mfa.RelyingPartyId": _str("WebAuthn 依赖方 ID（通常为域名，必填）", required=True),
    "Mfa.RelyingPartyName": _str("WebAuthn 依赖方显示名称"),
    "Mfa.Origins": _arr("WebAuthn 允许的 Origin 列表（必填，不带路径）", "url", noPath=True, required=True),
    "Mfa.ChallengeLifetimeMinutes": _num("MFA 挑战有效期（分钟）", 1, 60),
    "Mfa.RequireForAdmin": _bool("Admin 及以上角色是否强制 MFA"),
    "Mfa.RequireWebAuthnForMax": _bool("Max 角色是否强制使用 WebAuthn（需 HTTPS）"),
}

# 密码弱值（与 deploy/entrypoint.py WEAK_SECRETS 保持一致）
EDITOR_WEAK_SECRETS = {"change-me", "changeme", "password", "secret", "123456", "pylai"}
DB_PASSWORD_RE = re.compile(r"Password=([^;]+)")  # 仅用于连接串弱口令检测


def _finite_number(value: Any) -> bool:
    """过滤 NaN / Infinity 等非法数值（Python 会序列化它们进 TOML 造成启动失败）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == float(value) and abs(float(value)) != float("inf")


def _value_error(message: str) -> list[str]:
    return [message] if message else []


def _check_scalar(rule: Json, value: Any) -> list[str]:
    """按规则校验单个标量值，返回错误文案列表。"""
    kind = rule.get("kind")
    errors: list[str] = []

    if kind == "boolean":
        return errors

    if kind == "number":
        if not _finite_number(value):
            return [f"必须是有限数字（不能为 NaN / Infinity）"]
        lo, hi = rule.get("min"), rule.get("max")
        if rule.get("allowNegOne") and value == -1:
            return errors
        if lo is not None and value < lo:
            errors.append(f"不能小于 {lo}")
        if hi is not None and value > hi:
            errors.append(f"不能大于 {hi}")
        return errors

    if kind == "enum":
        allowed = rule.get("enum", [])
        if value not in allowed:
            return [f"必须是以下之一: {', '.join(allowed)}"]
        return errors

    if kind in ("url", "ip", "cidr"):
        if not isinstance(value, str) or not value.strip():
            return [f"{kind.upper()} 不能为空"]
        value = value.strip()
        if kind == "url":
            if not is_valid_url(value):
                return ["不是合法 URL（应为 http(s)://host[:port]）"]
            if rule.get("noPath") and urlparse(value).path not in ("", "/"):
                return ["不允许包含路径（应为 http(s)://host[:port]）"]
        elif kind == "ip":
            if not is_valid_ip(value):
                return [f"不是合法 IP: {value}"]
        elif kind == "cidr":
            if not is_valid_cidr(value):
                return [f"不是合法 CIDR: {value}"]
        return errors

    if kind == "string":
        if not isinstance(value, str):
            return ["必须是字符串"]
        if rule.get("required") and not value.strip():
            return ["不能为空"]
        if rule.get("requirePlaceholder") and rule["requirePlaceholder"] not in value:
            return [f"必须包含占位符 {rule['requirePlaceholder']}"]
        if rule.get("pattern") and not re.fullmatch(rule["pattern"], value):
            return [f"格式不合法: {value}"]
        return errors

    return errors


def _check_array(rule: Json, value: Any) -> list[str]:
    """按规则校验数组（及数组内元素）。"""
    if not isinstance(value, list):
        return ["必须是列表"]

    if rule.get("required") and not value:
        return ["不能为空"]

    elem = rule.get("arrayKind", "string")
    errors: list[str] = []
    for index, item in enumerate(value):
        if elem == "url":
            if not (isinstance(item, str) and is_valid_url(item)):
                errors.append(f"第 {index + 1} 项不是合法 URL: {item}")
            elif rule.get("noPath") and urlparse(item).path not in ("", "/"):
                errors.append(f"第 {index + 1} 项不允许包含路径: {item}")
        elif elem == "ip":
            if not (isinstance(item, str) and is_valid_ip(item)):
                errors.append(f"第 {index + 1} 项不是合法 IP: {item}")
        elif elem == "cidr":
            if not (isinstance(item, str) and is_valid_cidr(item)):
                errors.append(f"第 {index + 1} 项不是合法 CIDR: {item}")
        elif elem == "number":
            if not _finite_number(item):
                errors.append(f"第 {index + 1} 项不是有效数字: {item}")
                continue
            if rule.get("allowNegOne") and item == -1:
                continue
            lo, hi = rule.get("arrayMin"), rule.get("arrayMax")
            if lo is not None and item < lo:
                errors.append(f"第 {index + 1} 项不能小于 {lo}")
            if hi is not None and item > hi:
                errors.append(f"第 {index + 1} 项不能大于 {hi}")
        elif elem == "string":
            if not isinstance(item, str):
                errors.append(f"第 {index + 1} 项必须是字符串")
    return errors


def check_rule(rule: Json, value: Any) -> list[str]:
    """按规则校验一个值（数组走 _check_array，其余走 _check_scalar）。"""
    if rule.get("kind") == "array":
        return _check_array(rule, value)
    return _check_scalar(rule, value)


def extract_connection_string_password(connection_string: str) -> str:
    """从连接串中提取密码，仅用于弱口令检测。"""
    if m := DB_PASSWORD_RE.search(connection_string):
        return m.group(1).strip()
    return ""


def weak_secret_hit(value: str) -> bool:
    """命中已知弱值清单则拒绝（与后端 ProductionSecurityGate / entrypoint 一致）。"""
    return value.strip().lower() in EDITOR_WEAK_SECRETS


def validate_full_text(text: str) -> list[tuple[str, str, str]]:
    """对整份配置做语义校验（与后端四阶段校验对齐，Fail Closed）。

    返回 [(section, key, 错误信息)]，空列表表示通过。
    """
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [("", "", f"配置不是合法 TOML: {exc}")]

    issues: list[tuple[str, str, str]] = []

    def visit(path: str, table: dict[str, Any]) -> None:
        for key, value in table.items():
            if isinstance(value, dict):
                visit(f"{path}.{key}" if path else key, value)
                continue
            rule = EDITOR_RULES.get(f"{path}.{key}")
            if not rule:
                continue
            for message in check_rule(rule, value):
                issues.append((path, key, f"[{path}].{key}：{message}"))

    for key, value in parsed.items():
        if isinstance(value, dict):
            visit(key, value)
        else:
            rule = EDITOR_RULES.get(key)
            if rule:
                for message in check_rule(rule, value):
                    issues.append(("", key, f"{key}：{message}"))

    # ---- 跨键校验（与 ConfigValidator.cs 对齐） ----
    def g(path: str, default: Any = None) -> Any:
        current: Any = parsed
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    smtp_host = g("Email.Smtp.Host", "")
    from_address = g("Email.FromAddress", "")
    if bool(smtp_host.strip()) != bool(from_address.strip()):
        issues.append(("Email", "Email", "[Email] 邮件服务未配置完整：Email.Smtp.Host 与 Email.FromAddress 必须同时配置或同时留空"))

    smtp_security = g("Email.Smtp.Security", "")
    smtp_port = g("Email.Smtp.Port", 587)
    if smtp_port == 465 and str(smtp_security).lower() != "sslconnect":
        issues.append(("Email.Smtp", "Security", "[Email.Smtp].Security：端口 465 为隐式 TLS，必须使用 SslOnConnect"))

    allow_credentials = g("Cors.AllowCredentials", False)
    allowed_origins = g("Cors.AllowedOrigins", [])
    if allow_credentials and "*" in allowed_origins:
        issues.append(("Cors", "AllowedOrigins", "[Cors].AllowedOrigins：AllowCredentials=true 时禁止使用通配符 *"))

    require_https = g("OpenIddict.RequireHttps", False)
    issuer = g("OpenIddict.Issuer", "")
    if require_https and not str(issuer).startswith("https://"):
        issues.append(("OpenIddict", "Issuer", "[OpenIddict].Issuer：RequireHttps=true 时必须使用 https"))

    # 邮件模板必须完整：段落/键缺失时规则遍历不可达，这里兜底（值缺失占位符由规则层 requirePlaceholder 拦截）
    for theme in ("Register", "Bind", "Change", "PasswordReset"):
        theme_table = g(f"MailTheme.{theme}", None)
        if not isinstance(theme_table, dict):
            issues.append(("MailTheme", theme, f"[MailTheme.{theme}] 段落缺失：必须配置邮件模板（正文须包含占位符 %%CaptchaCode%%）"))
        elif "Context" not in theme_table:
            issues.append((f"MailTheme.{theme}", "Context", f"[MailTheme.{theme}].Context：不能为空（正文必须包含占位符 %%CaptchaCode%%）"))

    # ---- 弱口令检测 ----
    db_connection = g("Database.ConnectionString", "")
    if isinstance(db_connection, str) and weak_secret_hit(extract_connection_string_password(db_connection)):
        issues.append(("Database", "ConnectionString", "[Database].ConnectionString：数据库密码为已知弱值，请使用随机强密码"))
    redis_password = g("Redis.Password", "")
    if isinstance(redis_password, str) and redis_password and weak_secret_hit(redis_password):
        issues.append(("Redis", "Password", "[Redis].Password：Redis 密码为已知弱值，请使用随机强密码"))

    return issues


# 供前端实时校验下发的精简规则（保留约束，去除内部字段）
def frontend_rule(rule: Json) -> Json:
    out_rule: Json = {"kind": rule.get("kind"), "desc": rule.get("desc", "")}
    for field in ("enum", "min", "max", "required", "noPath", "allowNegOne", "arrayKind", "arrayMin", "arrayMax", "requirePlaceholder"):
        if field in rule:
            out_rule[field] = rule[field]
    return out_rule


# 网页编辑器运行上下文（由 ManagePylai 注入 docker/state，用于保存后容器权威校验）
EDITOR_CTX: dict[str, Any] = {}


def authoritative_validate() -> list[str]:
    """若 backend 容器正在运行，用容器内 CLI 做权威校验（config validate）。

    返回错误文案列表，空列表表示通过或容器不可用。
    """
    docker = EDITOR_CTX.get("docker")
    if docker is None:
        return []
    try:
        if not docker.service_running("backend"):
            return []
    except Exception:
        return []

    result = docker.exec_pylaios(
        "config",
        "validate",
        "--config",
        PYLAI_CONFIG_ARG,
        check=False,
        timeout=120,
    )
    if result.returncode == 0:
        return []
    output = (result.stdout + result.stderr).strip()
    return [output or "容器内 config validate 校验未通过"]


class ConfigEditorServer(ThreadingHTTPServer):
    """仅监听 127.0.0.1 的一次性配置编辑器服务。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, password: str) -> None:
        self.password = password
        self.token = secrets.token_hex(16)
        super().__init__(("127.0.0.1", port), ConfigEditorHandler)


class ConfigEditorHandler(BaseHTTPRequestHandler):
    server: ConfigEditorServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ---- 基础工具 ----
    def _send_json(self, payload: Json, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Json:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1 << 20:
            raise ManageError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManageError(f"请求不是合法 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManageError("请求体必须是 JSON 对象")
        return data

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            body = CONFIG_EDITOR_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/config":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                self._send_json(self._config_payload())
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        try:
            data = self._read_json()
        except ManageError as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        if path == "/api/auth":
            if secrets.compare_digest(str(data.get("password", "")), self.server.password):
                self._send_json({"token": self.server.token})
            else:
                time.sleep(0.5)  # 减缓口令爆破
                self._send_json({"error": "临时密码错误"}, 401)
            return

        if path == "/api/validate":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                issues = self._validate_changes(data.get("changes"))
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"ok": not issues, "errors": [
                {"section": sec, "key": key, "message": msg} for sec, key, msg in issues
            ]})
            return

        if path == "/api/save":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                preview = self._apply_changes(data.get("changes"))
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"ok": True, "preview": preview, "authoritative": True})
            return

        self._send_json({"error": "Not Found"}, 404)

    # ---- 业务 ----
    def _config_payload(self) -> Json:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"配置解析失败: {exc}") from exc

        sections: list[Json] = []

        def visit(path: str, table: Json) -> None:
            entries = []
            for key, value in table.items():
                if isinstance(value, dict):
                    continue
                rule = EDITOR_RULES.get(f"{path}.{key}")
                entries.append({
                    "key": key,
                    "type": editor_value_kind(value),
                    "value": value,
                    "secret": bool(re.search(r"Password|Secret|ConnectionString", key, re.IGNORECASE)),
                    "desc": rule.get("desc", "") if rule else "",
                    "rules": frontend_rule(rule) if rule else {"kind": editor_value_kind(value), "desc": ""},
                })
            if entries:
                sections.append({"name": path, "entries": entries})
            for key, value in table.items():
                if isinstance(value, dict):
                    visit(f"{path}.{key}" if path else key, value)

        for key, value in parsed.items():
            if isinstance(value, dict):
                visit(key, value)

        return {
            "path": str(CONFIG_FILE),
            "sections": sections,
            "preview": mask_config_text(text),
        }

    def _build_changes_text(self, changes: Any) -> str:
        """把变更应用到当前配置文本，返回新文本（不写盘）。"""
        if not isinstance(changes, list) or not changes:
            raise ManageError("没有需要提交的变更")
        if len(changes) > 500:
            raise ManageError("单次变更过多")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        t = TomlText(text)

        for change in changes:
            if not isinstance(change, dict):
                raise ManageError("变更格式非法")
            section = str(change.get("section", ""))
            key = str(change.get("key", ""))
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*", section):
                raise ManageError(f"非法的配置段落: {section!r}")
            if not re.fullmatch(r"[A-Za-z0-9_]+", key):
                raise ManageError(f"非法的配置键: {key!r}")

            marker = f"[{section}]"
            t.text = strip_multiline_value(t.text, marker, key)
            t.set(marker, key, serialize_editor_value(change), required=True)

        return str(t)

    def _validate_changes(self, changes: Any) -> list[tuple[str, str, str]]:
        """对变更后的整份配置做语义校验（含跨键规则），返回问题列表。"""
        new_text = self._build_changes_text(changes)
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"变更后配置不是合法 TOML: {exc}") from exc
        return validate_full_text(new_text)

    def _apply_changes(self, changes: Any) -> str:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        new_text = self._build_changes_text(changes)

        # 语义校验（Fail Closed）：有错误绝不写盘
        issues = validate_full_text(new_text)
        if issues:
            detail = "\n".join(msg for _, _, msg in issues[:10])
            more = f"（另有 {len(issues) - 10} 项）" if len(issues) > 10 else ""
            raise ManageError(f"配置校验未通过，已拒绝保存：\n{detail}{more}")

        old_text = CONFIG_FILE.read_text(encoding="utf-8")
        atomic_write(CONFIG_FILE, new_text)

        # 容器权威校验兜底：失败则还原旧配置
        container_errors = authoritative_validate()
        if container_errors:
            atomic_write(CONFIG_FILE, old_text)
            raise ManageError("容器内 config validate 校验未通过，已还原原配置：\n" + "\n".join(container_errors))

        return mask_config_text(new_text)

CONFIG_EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pylai 配置编辑器</title>
<style>
/* ---------- 主题变量：默认浅色，跟随系统自动切换深色 ---------- */
:root {
  color-scheme: light;
  --bg: #f4f5f7;
  --panel: #ffffff;
  --panel-soft: #f8f9fb;
  --border: #e2e5ea;
  --border-strong: #cfd4db;
  --text: #1d2330;
  --muted: #6b7280;
  --accent: #2f6bff;
  --accent-hover: #1f59e8;
  --accent-soft: rgba(47, 107, 255, .1);
  --danger: #d64541;
  --danger-soft: rgba(214, 69, 65, .1);
  --warning: #e8930c;
  --ok: #189a58;
  --toast-bg: #1d2330;
  --toast-text: #ffffff;
  --radius: 10px;
  --mono: ui-monospace, "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0e1013;
    --panel: #15181d;
    --panel-soft: #1b1f26;
    --border: #272c35;
    --border-strong: #39414d;
    --text: #e4e7ec;
    --muted: #8b94a1;
    --accent: #5f8dff;
    --accent-hover: #7ba1ff;
    --accent-soft: rgba(95, 141, 255, .14);
    --danger: #e06560;
    --danger-soft: rgba(224, 101, 96, .14);
    --warning: #e5a13c;
    --ok: #3fbf7f;
    --toast-bg: #e8ebf0;
    --toast-text: #1d2330;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 14px;
  background: var(--bg);
  color: var(--text);
  overflow: hidden;
}
button { font: inherit; cursor: pointer; }
::placeholder { color: var(--muted); opacity: .7; }

/* ---------- 临时密码验证 ---------- */
#gate {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg);
}
.gate-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 40px 44px;
  text-align: center;
}
.gate-card h1 { font-size: 19px; font-weight: 600; margin-bottom: 6px; }
.gate-card p { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.code-row { display: flex; gap: 8px; align-items: center; justify-content: center; }
.code-row input {
  width: 42px; height: 52px;
  font-size: 21px; font-family: var(--mono);
  text-align: center; text-transform: uppercase;
  border: 1px solid var(--border-strong); border-radius: 8px;
  outline: none; transition: border-color .15s, box-shadow .15s;
  background: var(--panel-soft); color: var(--text);
}
.code-row input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.code-dash { color: var(--muted); font-size: 18px; }
#gate-btn {
  width: 42px; height: 42px; border-radius: 50%;
  border: none; background: var(--accent); color: #fff;
  font-size: 17px; margin-left: 8px;
  display: none; align-items: center; justify-content: center;
  transition: background .15s;
}
#gate-btn:hover { background: var(--accent-hover); }
#gate-err { color: var(--danger); font-size: 13px; margin-top: 16px; min-height: 18px; }
.shake { animation: shake .3s; }
@keyframes shake {
  25% { transform: translateX(-6px); } 50% { transform: translateX(6px); } 75% { transform: translateX(-4px); }
}

/* ---------- 主界面框架 ---------- */
#app { display: none; flex-direction: column; height: 100vh; }
.topbar {
  display: flex; align-items: center; gap: 6px;
  background: var(--panel); border-bottom: 1px solid var(--border);
  padding: 0 16px; height: 54px; flex: none;
}
.brand { font-weight: 600; font-size: 15px; margin-right: 18px; }
.brand span { color: var(--accent); }
.tab {
  border: none; background: none; color: var(--muted);
  padding: 6px 14px; border-radius: 8px; font-size: 14px;
  transition: background .15s, color .15s;
}
.tab:hover { color: var(--text); }
.tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
.topbar .spacer { flex: 1; }
#dirty-dot { color: var(--warning); font-size: 12px; display: none; }
#err-count { color: var(--danger); font-size: 12px; display: none; margin-right: 8px; }
#submit-btn {
  border: none; background: var(--accent); color: #fff;
  padding: 7px 22px; border-radius: 8px; font-size: 14px;
  transition: background .15s, opacity .15s;
}
#submit-btn:hover:not(:disabled) { background: var(--accent-hover); }
#submit-btn:disabled { opacity: .4; cursor: not-allowed; }

.main { display: flex; flex: 1; min-height: 0; }

/* ---------- 目录 ---------- */
#sidebar {
  width: 224px; flex: none; background: var(--panel);
  border-right: 1px solid var(--border);
  overflow-y: auto; padding: 12px 10px;
}
#sidebar h2 { font-size: 12px; color: var(--muted); padding: 4px 10px 8px; font-weight: 500; }
.sec-item {
  display: block; width: 100%; text-align: left;
  border: none; background: none; border-radius: 8px;
  padding: 7px 10px; font-size: 13px; font-family: var(--mono);
  color: var(--text); transition: background .12s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sec-item:hover { background: var(--panel-soft); }
.sec-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
.sec-item .badge { float: right; font-size: 11px; color: var(--warning); }
.sec-item .badge.err { color: var(--danger); font-weight: 700; }

/* ---------- 编辑区 ---------- */
#editor { flex: 1; overflow-y: auto; padding: 24px 32px 40px; min-width: 0; }
#editor h2 { font-size: 16px; margin-bottom: 4px; font-family: var(--mono); }
#editor .hint { font-size: 12.5px; color: var(--muted); margin-bottom: 18px; }
.field {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px; margin-bottom: 10px;
  transition: border-color .15s;
}
.field.changed { border-color: var(--warning); }
.field.invalid { border-color: var(--danger); }
.field label { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; margin-bottom: 6px; }
.field label .type { font-size: 11px; color: var(--muted); font-weight: 400; font-family: var(--mono); }
.field label .secret-tag { font-size: 11px; color: var(--danger); background: var(--danger-soft); padding: 1px 7px; border-radius: 6px; }
.field .desc { font-size: 12px; color: var(--muted); margin-bottom: 8px; line-height: 1.5; }
.field .err { font-size: 12px; color: var(--danger); margin-top: 6px; display: none; }
.field.invalid .err { display: block; }
.field input[type=text], .field input[type=number], .field input[type=password], .field textarea, .field select {
  width: 100%; border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 12px; font-size: 13px; font-family: var(--mono);
  outline: none; background: var(--panel-soft); color: var(--text);
  transition: border-color .15s, box-shadow .15s, background .15s;
}
.field textarea { min-height: 140px; resize: vertical; line-height: 1.6; }
.field input:focus, .field textarea:focus, .field select:focus {
  border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); background: var(--panel);
}
.field.invalid input, .field.invalid textarea, .field.invalid select { border-color: var(--danger); }
.empty { color: var(--muted); font-size: 14px; padding: 40px; text-align: center; }

/* 占位符插入按钮 */
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip {
  border: 1px solid var(--border); background: var(--panel-soft);
  color: var(--muted); border-radius: 999px; padding: 3px 11px;
  font-size: 12px; font-family: var(--mono);
  transition: color .12s, border-color .12s, background .12s;
}
.chip:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }

/* ---------- 预览（跟随主题，明暗自适应） ---------- */
#preview {
  width: 420px; flex: none;
  background: var(--panel-soft); color: var(--text);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column; min-height: 0;
}
#preview h2 {
  font-size: 12px; color: var(--muted); font-weight: 500;
  padding: 12px 16px; border-bottom: 1px solid var(--border); flex: none;
}
#preview pre {
  flex: 1; overflow: auto; padding: 14px 16px;
  color: var(--text); font-size: 12px; font-family: var(--mono); line-height: 1.7;
  white-space: pre-wrap; word-break: break-all;
}
#preview pre .cfg-line { display: block; padding: 0 4px; border-radius: 4px; }
#preview pre .sec-block {
  border-left: 3px solid transparent; padding-left: 6px; margin: 4px 0;
  border-radius: 6px; transition: border-color .15s, background .15s;
}
#preview pre .sec-block.active-sec {
  border-left-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: inset 0 0 0 1px var(--accent);
}
#preview pre .sec-title { color: var(--accent); font-weight: 600; }
#preview pre .focus-line { border-bottom: 2px solid var(--warning); }
#preview pre .valid-line { border-bottom: 2px solid var(--ok); }
#preview pre .invalid-line { border-bottom: 2px solid var(--danger); }

/* ---------- 弹窗 ---------- */
.modal-mask {
  position: fixed; inset: 0; background: rgba(16, 24, 40, .45);
  display: none; align-items: center; justify-content: center; z-index: 40;
}
.modal {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 14px; width: 560px; max-width: 92vw;
  max-height: 80vh; display: flex; flex-direction: column;
}
.modal h3 { padding: 18px 22px 0; font-size: 15px; }
.modal .body { padding: 14px 22px; overflow-y: auto; flex: 1; }
.diff-group { margin-bottom: 14px; }
.diff-group h4 {
  font-family: var(--mono); font-size: 13px; color: var(--accent);
  margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border);
}
.diff-item {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 8px; font-size: 13px;
  align-items: start;
}
.diff-item .k { grid-column: 1 / -1; font-family: var(--mono); font-weight: 600; margin-bottom: 6px; color: var(--text); }
.diff-item .old, .diff-item .new { font-family: var(--mono); font-size: 12px; word-break: break-all; line-height: 1.5; }
.diff-item .old { color: var(--danger); }
.diff-item .new { color: var(--ok); }
.diff-item .old::before { content: "改前: "; color: var(--muted); font-family: inherit; }
.diff-item .new::before { content: "改后: "; color: var(--muted); font-family: inherit; }
.diff-empty { color: var(--muted); text-align: center; padding: 30px; }
.modal .foot { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 22px 18px; }
.btn {
  border: 1px solid var(--border-strong); background: var(--panel); color: var(--text);
  border-radius: 8px; padding: 8px 18px; font-size: 14px;
  transition: border-color .15s, background .15s;
}
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { background: var(--accent-hover); }

#toast {
  position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
  background: var(--toast-bg); color: var(--toast-text);
  padding: 10px 22px; border-radius: 10px;
  font-size: 13.5px; display: none; z-index: 60;
}
#status-modal .body p { font-size: 13.5px; margin-bottom: 10px; color: var(--text); line-height: 1.6; }
#status-modal .body b { font-family: var(--mono); font-weight: 600; }
#status-modal .status-summary { font-size: 14px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
#status-modal .status-sec { margin-top: 12px; font-size: 13px; color: var(--accent); }
#status-modal .status-row { margin: 4px 0 4px 12px; }
#status-modal .status-row .old { color: var(--danger); text-decoration: line-through; font-family: var(--mono); font-size: 12px; }
#status-modal .status-row .new { color: var(--ok); font-family: var(--mono); font-size: 12px; }
#status-modal .status-err { color: var(--danger); font-size: 12px; }
@media (max-width: 1000px) { #preview { display: none; } }
@media (max-width: 720px) { #sidebar { display: none; } }
</style>
</head>
<body>

<!-- 临时密码验证 -->
<div id="gate">
  <div class="gate-card" id="gate-card">
    <h1>Pylai 配置编辑器</h1>
    <p>验证临时密码</p>
    <div class="code-row" id="code-row">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <span class="code-dash">-</span>
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <button id="gate-btn" title="验证">&#10140;</button>
    </div>
    <div id="gate-err"></div>
  </div>
</div>

<!-- 编辑器主界面 -->
<div id="app">
  <div class="topbar">
    <div class="brand">Pylai <span>配置编辑器</span></div>
    <button class="tab active" data-tab="catalog">目录</button>
    <button class="tab" data-tab="editor">编辑器</button>
    <button class="tab" data-tab="status">状态</button>
    <div class="spacer"></div>
    <span id="dirty-dot">&#9679; 有未提交变更</span>
    <span id="err-count"></span>
    <button id="submit-btn" disabled>提交</button>
  </div>
  <div class="main">
    <aside id="sidebar"><h2>目录</h2><div id="sec-list"></div></aside>
    <section id="editor"><div class="empty">正在加载配置…</div></section>
    <aside id="preview"><h2>配置文件预览</h2><pre id="preview-pre"></pre></aside>
  </div>
</div>

<!-- 提交确认弹窗 -->
<div class="modal-mask" id="diff-modal">
  <div class="modal">
    <h3>确认以下变更</h3>
    <div class="body" id="diff-body"></div>
    <div class="foot">
      <button class="btn" id="diff-cancel">取消</button>
      <button class="btn primary" id="diff-confirm">确认提交</button>
    </div>
  </div>
</div>

<!-- 状态弹窗 -->
<div class="modal-mask" id="status-modal">
  <div class="modal">
    <h3>状态</h3>
    <div class="body" id="status-body"></div>
    <div class="foot"><button class="btn" id="status-close">关闭</button></div>
  </div>
</div>

<div id="toast"></div>

<script>
"use strict";
const $ = (s) => document.querySelector(s);
let token = null;
let configData = null;          // 配置数据：{ sections, preview, path }
let original = new Map();       // "Section.Key" -> 原始值
let edits = new Map();          // "Section.Key" -> {section,key,type,value,secret,rules,error}
let activeSection = null;
let currentFocusId = null;

// 邮件模板可用占位符（与后端 EmailSender 渲染一致）
const MAIL_PLACEHOLDERS = [
  ["%%CaptchaCode%%", "验证码"],
  ["%%Browser%%", "浏览器"],
  ["%%IPAddress%%", "IP 地址"],
  ["%%ExpireMinutes%%", "有效分钟数"],
];

/* ---------- 临时密码 ---------- */
const boxes = [...document.querySelectorAll("#code-row input")];
const gateBtn = $("#gate-btn");

boxes.forEach((box, i) => {
  box.addEventListener("input", () => {
    // 只允许字母数字并自动聚焦下一格
    box.value = box.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    if (box.value && i < boxes.length - 1) boxes[i + 1].focus();
    gateBtn.style.display = boxes.every(b => b.value) ? "inline-flex" : "none";
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && !box.value && i > 0) boxes[i - 1].focus();
    if (e.key === "Enter" && boxes.every(b => b.value)) doAuth();
  });
  box.addEventListener("paste", (e) => {
    // 整段粘贴：过滤非法字符后按位填充
    e.preventDefault();
    const text = (e.clipboardData.getData("text") || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    [...text].slice(0, 8).forEach((ch, j) => { if (boxes[j]) boxes[j].value = ch; });
    boxes[Math.min(text.length, 7)].focus();
    gateBtn.style.display = boxes.every(b => b.value) ? "inline-flex" : "none";
  });
});
boxes[0].focus();
gateBtn.addEventListener("click", doAuth);

async function doAuth() {
  // 拼装 XXXX-XXXX 格式临时密码并验证
  const password = boxes.slice(0, 4).map(b => b.value).join("") + "-" + boxes.slice(4).map(b => b.value).join("");
  try {
    const res = await fetch("/api/auth", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "验证失败");
    token = data.token;
    $("#gate").style.display = "none";
    $("#app").style.display = "flex";
    document.title = "Pylai 配置编辑器";
    await loadConfig();
  } catch (err) {
    $("#gate-err").textContent = err.message;
    $("#gate-card").classList.remove("shake");
    void $("#gate-card").offsetWidth;
    $("#gate-card").classList.add("shake");
    boxes.forEach(b => b.value = "");
    gateBtn.style.display = "none";
    boxes[0].focus();
  }
}

/* ---------- 数据加载 ---------- */
async function api(path, options = {}) {
  // 统一请求封装：自动附带 Bearer Token，HTTP 非 2xx 时抛出错误
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token, ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("请求失败: " + res.status));
  return data;
}

async function loadConfig() {
  // 加载配置：建立原始值映射、重置编辑与错误状态
  configData = await api("/api/config");
  original.clear(); edits.clear();
  for (const sec of configData.sections)
    for (const e of sec.entries)
      original.set(sec.name + "." + e.key, e.value);
  activeSection = configData.sections[0]?.name ?? null;
  renderSidebar(); renderEditor(); renderPreview(); scrollPreviewToSection(activeSection); refreshDirty();
}

/* ---------- 序列化（与服务端 TomlText 一致） ---------- */
function serialize(type, value) {
  if (type === "boolean") return value ? "true" : "false";
  if (type === "number") return String(value);
  if (type === "array") {
    return "[" + value.map(x => (typeof x === "number") ? String(x) : JSON.stringify(String(x))).join(", ") + "]";
  }
  return JSON.stringify(String(value));
}
function displayValue(v, secret) {
  if (secret) return '"***"';
  if (typeof v === "string") return JSON.stringify(v);
  return Array.isArray(v) ? "[" + v.join(", ") + "]" : String(v);
}

/* ---------- 实时校验（与服务端 check_rule 对齐） ---------- */
function isValidUrl(s) {
  // 校验 http(s)://host[:port] 形式的合法 URL
  try {
    const u = new URL(s);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.hostname;
  } catch { return false; }
}
function isValidIp(s) {
  // 校验 IPv4（分段 0-255）或简化的 IPv6（十六进制冒号形式）
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
  const m = s.match(ipv4);
  if (m) return m.slice(1).every(n => Number(n) <= 255);
  return /^[0-9a-fA-F:]+$/.test(s) && s.includes(":") && (s.match(/:/g) || []).length <= 7;
}
function isValidCidr(s) {
  // 校验 CIDR：合法 IP + /前缀长度
  const idx = s.lastIndexOf("/");
  if (idx <= 0) return false;
  const ip = s.slice(0, idx), prefix = Number(s.slice(idx + 1));
  if (!isValidIp(ip) || !Number.isInteger(prefix)) return false;
  const max = ip.includes(":") ? 128 : 32;
  return prefix >= 0 && prefix <= max;
}
function checkScalar(rules, value) {
  // 按规则校验标量值，返回错误文案（空串表示通过）
  const kind = rules.kind;
  if (kind === "boolean") return "";
  if (kind === "number") {
    if (typeof value !== "number" || !isFinite(value)) return "必须是有限数字（不能为 NaN / Infinity）";
    if (rules.allowNegOne && value === -1) return "";
    if (rules.min != null && value < rules.min) return "不能小于 " + rules.min;
    if (rules.max != null && value > rules.max) return "不能大于 " + rules.max;
    return "";
  }
  if (kind === "enum") return rules.enum.includes(value) ? "" : "必须是以下之一: " + rules.enum.join(", ");
  if (kind === "url") {
    if (!value || !isValidUrl(value)) return "不是合法 URL（应为 http(s)://host[:port]）";
    if (rules.noPath) {
      const u = new URL(value);
      if (u.pathname !== "" && u.pathname !== "/") return "不允许包含路径（应为 http(s)://host[:port]）";
    }
    return "";
  }
  if (kind === "ip") return isValidIp(value) ? "" : "不是合法 IP";
  if (kind === "cidr") return isValidCidr(value) ? "" : "不是合法 CIDR";
  if (kind === "string") {
    if (rules.required && !String(value).trim()) return "不能为空";
    if (rules.requirePlaceholder && String(value) && !String(value).includes(rules.requirePlaceholder))
      return "必须包含占位符 " + rules.requirePlaceholder;
    return "";
  }
  return "";
}
function checkArray(rules, value) {
  // 按规则校验数组及元素，返回错误文案
  if (!Array.isArray(value)) return "必须是列表";
  if (rules.required && value.length === 0) return "不能为空";
  const elem = rules.arrayKind || "string";
  for (let i = 0; i < value.length; i++) {
    const item = value[i];
    if (elem === "url") {
      if (!isValidUrl(item)) return "第 " + (i + 1) + " 项不是合法 URL: " + item;
      if (rules.noPath) {
        const u = new URL(item);
        if (u.pathname !== "" && u.pathname !== "/") return "第 " + (i + 1) + " 项不允许包含路径";
      }
    }
    if (elem === "ip" && !isValidIp(item)) return "第 " + (i + 1) + " 项不是合法 IP: " + item;
    if (elem === "cidr" && !isValidCidr(item)) return "第 " + (i + 1) + " 项不是合法 CIDR: " + item;
    if (elem === "number") {
      if (typeof item !== "number" || !isFinite(item)) return "第 " + (i + 1) + " 项不是有效数字";
      if (rules.allowNegOne && item === -1) continue;
      if (rules.arrayMin != null && item < rules.arrayMin) return "第 " + (i + 1) + " 项不能小于 " + rules.arrayMin;
      if (rules.arrayMax != null && item > rules.arrayMax) return "第 " + (i + 1) + " 项不能大于 " + rules.arrayMax;
    }
    if (elem === "string" && typeof item !== "string") return "第 " + (i + 1) + " 项必须是字符串";
  }
  return "";
}
function checkValue(rules, value) {
  // 统一入口：数组走 checkArray，其余走 checkScalar
  if (!rules) return "";
  if (rules.kind === "array") return checkArray(rules, value);
  return checkScalar(rules, value);
}

/* ---------- 目录 ---------- */
function renderSidebar() {
  const list = $("#sec-list");
  list.innerHTML = "";
  for (const sec of configData.sections) {
    const btn = document.createElement("button");
    btn.className = "sec-item" + (sec.name === activeSection ? " active" : "");
    let badge = "";
    if (sec.entries.some(e => edits.has(sec.name + "." + e.key))) badge = '<span class="badge">●</span>';
    if (sec.entries.some(e => edits.get(sec.name + "." + e.key)?.error)) badge = '<span class="badge err">!</span>';
    btn.innerHTML = escapeHtml("[" + sec.name + "]") + badge;
    btn.onclick = () => { activeSection = sec.name; renderSidebar(); renderEditor(); updatePreviewActiveSection(); scrollPreviewToSection(activeSection); setTab("editor"); };
    list.appendChild(btn);
  }
}
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- 占位符插入 ---------- */
function insertAtCursor(el, text) {
  // 在光标处插入文本（覆盖选区），插入后触发 input 事件走正常编辑流程
  el.focus();
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? start;
  el.setRangeText(text, start, end, "end");
  el.dispatchEvent(new Event("input"));
}

/* ---------- 表单编辑 ---------- */
function renderEditor() {
  currentFocusId = null;
  const sec = configData.sections.find(s => s.name === activeSection);
  const box = $("#editor");
  if (!sec) { box.innerHTML = '<div class="empty">没有可编辑的配置段落</div>'; return; }
  box.innerHTML = "<h2>[" + escapeHtml(sec.name) + "]</h2>" +
    '<div class="hint">共 ' + sec.entries.length + ' 项</div>';
  const isMailTheme = sec.name === "MailTheme" || sec.name.startsWith("MailTheme.");
  for (const entry of sec.entries) {
    const id = sec.name + "." + entry.key;
    const current = edits.has(id) ? edits.get(id).value : entry.value;
    const field = document.createElement("div");
    field.className = "field" + (edits.has(id) ? " changed" : "");
    field.dataset.id = id;
    const label = '<label><span>' + escapeHtml(entry.key) + "</span>" +
      '<span class="type">' + entry.type + "</span>" +
      (entry.secret ? '<span class="secret-tag">敏感</span>' : "") + "</label>";
    const desc = entry.desc ? '<div class="desc">' + escapeHtml(entry.desc) + "</div>" : "";
    const errLine = '<div class="err"></div>';
    let control = "";
    if (entry.type === "boolean") {
      control = '<select><option value="true"' + (current ? " selected" : "") + '>true</option>' +
        '<option value="false"' + (!current ? " selected" : "") + ">false</option></select>";
    } else if (entry.type === "number") {
      control = '<input type="number" step="any" value="' + escapeHtml(String(current)) + '">';
    } else if (entry.type === "array") {
      control = '<input type="text" value="' + escapeHtml(current.join(", ")) + '" placeholder="以英文逗号分隔">';
    } else if (typeof current === "string" && current.includes("\n")) {
      control = "<textarea>" + escapeHtml(current) + "</textarea>";
    } else {
      control = '<input type="' + (entry.secret ? "password" : "text") + '" value="' + escapeHtml(String(current)) + '">';
    }
    // 邮件模板字段：附加占位符插入按钮
    let chips = "";
    if (isMailTheme && entry.type === "string") {
      chips = '<div class="chips">' + MAIL_PLACEHOLDERS.map(p =>
        '<button type="button" class="chip" data-text="' + p[0] + '" title="插入' + p[1] + '占位符">' + p[0] + "</button>"
      ).join("") + "</div>";
    }
    field.innerHTML = label + desc + chips + control + errLine;
    const input = field.querySelector("input,select,textarea");
    input.addEventListener("input", () => onEdit(sec.name, entry, input.value));
    input.addEventListener("change", () => onEdit(sec.name, entry, input.value));
    input.addEventListener("focus", () => previewFocusLine(sec.name, entry.key));
    input.addEventListener("blur", () => previewBlurLine(sec.name, entry.key));
    field.querySelectorAll(".chip").forEach(chip =>
      chip.addEventListener("click", () => insertAtCursor(input, chip.dataset.text)));
    box.appendChild(field);
  }
}

function onEdit(section, entry, raw) {
  // 输入时：类型转换 + 实时校验 + 更新编辑记录与界面状态
  const id = section + "." + entry.key;
  let value;
  if (entry.type === "boolean") value = raw === "true";
  else if (entry.type === "number") value = raw === "" ? 0 : Number(raw);
  else if (entry.type === "array") {
    const parts = raw.split(",").map(s => s.trim()).filter(s => s !== "");
    const numeric = Array.isArray(entry.value) && entry.value.every(x => typeof x === "number");
    // 数值数组：仅将可解析项转为数字，非法项保留字符串以便实时报错
    value = numeric ? parts.map(p => (p === "-1" || /^-?\d+(\.\d+)?$/.test(p)) ? Number(p) : p) : parts;
  } else value = raw;

  let error = "";
  if (entry.type === "number" && raw === "") error = "该项不能为空";
  else error = checkValue(entry.rules, value);

  if (JSON.stringify(value) === JSON.stringify(original.get(id))) edits.delete(id);
  else edits.set(id, { section, key: entry.key, type: entry.type, value, secret: entry.secret, rules: entry.rules, error });

  // 更新字段外观：橙色=有改动，红色=校验错误
  const field = document.querySelector('.field[data-id="' + CSS.escape(id) + '"]');
  if (field) {
    field.classList.toggle("changed", edits.has(id));
    field.classList.toggle("invalid", Boolean(error));
    const errEl = field.querySelector(".err");
    if (errEl) errEl.textContent = error;
  }
  renderSidebar(); renderPreview(); refreshDirty();
}

/* ---------- 预览（在脱敏原文上打补丁） ---------- */
function patchPreview(text, section, key, serialized) {
  const lines = text.split("\n");
  let inSec = false;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*\[([^\]]+)\]\s*$/);
    if (m) { inSec = m[1].trim() === section; continue; }
    if (!inSec) continue;
    const km = lines[i].match(new RegExp("^(\\s*" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*)(.*)$"));
    if (!km) continue;
    const rhs = km[2];
    const triple = rhs.match(/^('''|\"\"\")/);
    let end = i;
    if (triple && rhs.indexOf(triple[1], 3) === -1) {
      for (let j = i + 1; j < lines.length; j++) { end = j; if (lines[j].includes(triple[1])) break; }
    }
    lines.splice(i, end - i + 1, km[1] + serialized);
    return lines.join("\n");
  }
  return text;
}

function stripLeadingComments(text) {
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === "" || t.startsWith("#")) i++;
    else break;
  }
  return lines.slice(i).join("\n");
}

function renderPreview() {
  let text = configData.preview;
  text = stripLeadingComments(text);
  for (const e of edits.values()) {
    const serialized = e.secret ? '"***"' : serialize(e.type, e.value);
    text = patchPreview(text, e.section, e.key, serialized);
  }

  const lines = text.split("\n");
  let html = "";
  let currentSec = null;
  let buffer = "";
  function flush() {
    if (currentSec !== null) {
      const active = currentSec === activeSection ? " active-sec" : "";
      html += '<div class="sec-block' + active + '" data-sec="' + escapeHtml(currentSec) + '">' + buffer + '</div>';
    } else {
      html += buffer;
    }
    buffer = "";
  }
  for (const line of lines) {
    const m = line.match(/^\s*\[([^\]]+)\]\s*$/);
    if (m) {
      flush();
      currentSec = m[1].trim();
      buffer += '<span class="cfg-line sec-title" data-sec="' + escapeHtml(currentSec) + '">' + escapeHtml(line) + '</span>';
    } else if (currentSec !== null) {
      const km = line.match(/^(\s*)([^=\s]+)\s*=\s*(.*)$/);
      const keyAttr = km ? ' data-key="' + escapeHtml(km[2]) + '"' : "";
      buffer += '<span class="cfg-line" data-sec="' + escapeHtml(currentSec) + '"' + keyAttr + '>' + escapeHtml(line) + '</span>';
    } else {
      buffer += '<span class="cfg-line">' + escapeHtml(line) + '</span>';
    }
  }
  flush();
  $("#preview-pre").innerHTML = html;
  refreshPreviewHighlights();
}

function scrollPreviewToSection(secName) {
  if (!secName) return;
  const block = $("#preview-pre").querySelector('.sec-block[data-sec="' + CSS.escape(secName) + '"]');
  if (block) block.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updatePreviewActiveSection() {
  $("#preview-pre").querySelectorAll(".sec-block").forEach(b =>
    b.classList.toggle("active-sec", b.dataset.sec === activeSection));
}

function refreshPreviewHighlights() {
  const pre = $("#preview-pre");
  pre.querySelectorAll(".focus-line, .valid-line, .invalid-line").forEach(el =>
    el.classList.remove("focus-line", "valid-line", "invalid-line"));
  for (const [id, e] of edits) {
    if (id === currentFocusId) continue;
    const [section, key] = id.split(".");
    const line = pre.querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
    if (line) line.classList.add(e.error ? "invalid-line" : "valid-line");
  }
  if (currentFocusId) {
    const [section, key] = currentFocusId.split(".");
    const line = pre.querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
    if (line) {
      line.classList.remove("valid-line", "invalid-line");
      line.classList.add("focus-line");
    }
  }
}

function previewFocusLine(section, key) {
  currentFocusId = section + "." + key;
  refreshPreviewHighlights();
  const line = $("#preview-pre").querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
  if (line) line.scrollIntoView({ behavior: "smooth", block: "center" });
}

function previewBlurLine(section, key) {
  const id = section + "." + key;
  if (currentFocusId === id) currentFocusId = null;
  refreshPreviewHighlights();
}

/* ---------- 提交 ---------- */
function refreshDirty() {
  // 有未提交变更 且 全部通过实时校验 时才允许提交
  const dirty = edits.size > 0;
  const errCount = [...edits.values()].filter(e => e.error).length;
  $("#submit-btn").disabled = !dirty || errCount > 0;
  $("#dirty-dot").style.display = dirty ? "inline" : "none";
  $("#err-count").style.display = errCount > 0 ? "inline" : "none";
  $("#err-count").textContent = "⚠ " + errCount + " 项校验错误";
}

$("#submit-btn").addEventListener("click", async () => {
  // 提交前先请求服务端做整份配置校验（含跨键规则，如 SMTP 配对/CORS 通配符）
  try {
    const changes = [...edits.values()].map(e => ({ section: e.section, key: e.key, type: e.type, value: e.value }));
    const result = await api("/api/validate", { method: "POST", body: JSON.stringify({ changes }) });
    if (result.errors && result.errors.length) {
      const first = result.errors[0];
      toast("校验未通过：[" + first.section + "]. " + first.message);
      return;
    }
  } catch (err) {
    toast("校验请求失败：" + err.message);
    return;
  }

  // 校验通过后展示变更确认弹窗
  const body = $("#diff-body");
  body.innerHTML = "";
  const groups = {};
  for (const e of edits.values()) {
    if (!groups[e.section]) groups[e.section] = [];
    groups[e.section].push(e);
  }
  for (const sec of Object.keys(groups).sort()) {
    const group = document.createElement("div");
    group.className = "diff-group";
    group.innerHTML = "<h4>[" + escapeHtml(sec) + "]</h4>";
    for (const e of groups[sec]) {
      const oldV = displayValue(original.get(e.section + "." + e.key), e.secret);
      const newV = displayValue(e.value, e.secret);
      const div = document.createElement("div");
      div.className = "diff-item";
      div.innerHTML = '<div class="k">' + escapeHtml(e.key) + "</div>" +
        '<span class="old">' + escapeHtml(oldV) + "</span>" +
        '<span class="new">' + escapeHtml(newV) + "</span>";
      group.appendChild(div);
    }
    body.appendChild(group);
  }
  $("#diff-modal").style.display = "flex";
});
$("#diff-cancel").addEventListener("click", () => $("#diff-modal").style.display = "none");

$("#diff-confirm").addEventListener("click", async () => {
  $("#diff-modal").style.display = "none";
  try {
    const changes = [...edits.values()].map(e => ({ section: e.section, key: e.key, type: e.type, value: e.value }));
    const result = await api("/api/save", { method: "POST", body: JSON.stringify({ changes }) });
    configData.preview = result.preview;
    edits.clear();
    await loadConfig();
    toast("配置已写入，重启实例后生效");
  } catch (err) {
    toast("提交失败：" + err.message);
  }
});

/* ---------- 页签 / 状态 ---------- */
function setTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
}
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  setTab(t.dataset.tab);
  if (t.dataset.tab === "catalog") $("#sidebar").scrollIntoView();
  if (t.dataset.tab === "editor") $("#editor").scrollIntoView();
  if (t.dataset.tab === "status") {
    const body = $("#status-body");
    if (edits.size === 0) {
      body.innerHTML = "<p>当前没有未提交的变更。</p>";
    } else {
      const groups = {};
      for (const e of edits.values()) {
        if (!groups[e.section]) groups[e.section] = [];
        groups[e.section].push(e);
      }
      let html = '<p class="status-summary">未提交变更 <b>' + edits.size + '</b> 项</p>';
      for (const sec of Object.keys(groups).sort()) {
        html += '<div class="status-sec"><b>[' + escapeHtml(sec) + ']</b></div>';
        for (const e of groups[sec]) {
          const oldV = displayValue(original.get(e.section + "." + e.key), e.secret);
          const newV = displayValue(e.value, e.secret);
          html += '<p class="status-row"><b>' + escapeHtml(e.key) + '</b>：<span class="old">' + escapeHtml(oldV) +
            '</span> → <span class="new">' + escapeHtml(newV) + '</span>' +
            (e.error ? ' <span class="status-err">（错误）</span>' : '') + '</p>';
        }
      }
      body.innerHTML = html;
    }
    $("#status-modal").style.display = "flex";
  }
}));
$("#status-close").addEventListener("click", () => $("#status-modal").style.display = "none");
document.querySelectorAll(".modal-mask").forEach(m =>
  m.addEventListener("click", (e) => { if (e.target === m) m.style.display = "none"; }));

let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg; el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.style.display = "none", 3200);
}
</script>
</body>
</html>

"""


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
# 交互菜单
# ============================================================================
class InteractiveMenu:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def print_header(self) -> None:
        ctx = self.ctx

        out(f"\n{'=' * 50}")
        out(f"  ManagePylai  v{__version__}")
        out(f"  项目: {ctx.manager.project_name}")

        if ctx.state.installed:
            status = "运行中" if ctx.docker.service_running() else "已停止"
            out(f"  状态: {status}  |  版本: {ctx.state.version}")
            out(f"  地址: {ctx.state.public_url}")
        else:
            out("  状态: 未安装")

        out(f"{'=' * 50}")

    def print_menu(self) -> None:
        out("\n[安装与更新]")
        out("  [1] 安装 Pylai")
        out("  [2] 更新 Pylai")
        out("  [3] 卸载 Pylai")

        out("\n[运行控制]")
        out("  [4] 状态 / 启动 / 停止 / 重启")
        out("  [5] 查看日志")

        out("\n[配置管理]")
        out("  [6] 查看配置（脱敏）")
        out("  [7] 修改配置")
        out("  [8] 生成主机 Nginx 配置")

        out("\n[用户管理]")
        out("  [9] 用户管理")

        out("\n[数据与安全]")
        out("  [10] 备份与恢复")
        out("  [11] 安全维护")

        out("\n[工具]")
        out("  [12] 检查 ManagePylai.py 更新")
        out("  [13] 管理工具设置（镜像源/自动检查/下载目录）")

        out("\n[0] 退出")

    def run(self) -> None:
        self.auto_check_notify()

        while True:
            self.print_header()
            self.print_menu()

            try:
                choice = input("\n> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                out("\n再见。")
                return

            try:
                match choice:
                    case "0" | "q" | "quit" | "exit":
                        out("再见。")
                        return
                    case "1":
                        self.install()
                    case "2":
                        self.update()
                    case "3":
                        self.uninstall()
                    case "4":
                        self.run_control()
                    case "5":
                        self.logs()
                    case "6":
                        self.view_config()
                    case "7":
                        self.edit_config()
                    case "8":
                        self.generate_nginx()
                    case "9":
                        self.users()
                    case "10":
                        self.backup()
                    case "11":
                        self.security()
                    case "12":
                        self.self_update()
                    case "13":
                        self.settings()
                    case _:
                        out("选择无效。")
            except ManageError as exc:
                out(f"错误: {exc}")
            except SystemExit:
                raise
            except Exception as exc:
                out(f"未预期错误: {exc}")

    def auto_check_notify(self) -> None:
        """启动时按 ManagerConfig [Updates] AutoCheck 配置静默检查并提示新版本。"""
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

        if updater.version_gt(version, __version__) and ctx.manager.skip_version != version:
            out(f"[通知] 管理工具新版本可用 v{version}，主菜单 [12] 可更新。")

        if ctx.state.installed and updater.version_gt(version, ctx.state.version):
            if info and "dbSchemaVersion" in info:
                out(
                    f"[通知] Pylai 新版本可用 v{version}（当前 v{ctx.state.version}，"
                    f"dbSchemaVersion: {info['dbSchemaVersion']}），主菜单 [2] 可从云端更新。"
                )
            else:
                out(
                    f"[通知] Pylai 新版本可用 v{version}（当前 v{ctx.state.version}），"
                    "主菜单 [2] 可从云端更新。"
                )

    def install(self) -> None:
        if self.ctx.state.installed:
            out("检测到已有安装。如需重新安装，请先卸载。")
            return

        InstallService(self.ctx).install_interactive()

    def update(self) -> None:
        UpdateService(self.ctx).update_interactive()

    def settings(self) -> None:
        settings = SettingsService(self.ctx)

        run_submenu(
            "管理工具设置（写入 ~/.pylai/ManagerConfig.toml）",
            "主菜单",
            [
                ("查看当前设置", settings.view),
                ("修改镜像源（Mirror / BaseUrl）", settings.change_mirror),
                ("自动检查更新（AutoCheck）", settings.change_auto_check),
                ("版本列表包含预发布（IncludePrerelease）", settings.change_include_prerelease),
                ("下载缓存目录（DownloadDir）", settings.change_download_dir),
                ("更新前自动备份（AutoBackupBeforeUpdate）", settings.change_auto_backup),
            ],
        )

    def uninstall(self) -> None:
        uninstall(self.ctx, yes=False, purge=False)

    def run_control(self) -> None:
        self.ctx.require_installed()
        status = self.ctx.docker.service_status()
        out(f"\n当前状态: {status}")

        run_submenu(
            "运行控制",
            "主菜单",
            [
                ("启动", lambda: service_action(self.ctx, "start")),
                ("停止", lambda: service_action(self.ctx, "stop")),
                ("重启", lambda: service_action(self.ctx, "restart")),
                ("查看简要状态", lambda: service_action(self.ctx, "status")),
            ],
        )

    def logs(self) -> None:
        self.ctx.require_installed()

        run_submenu(
            "日志查看",
            "主菜单",
            [
                ("最近 100 行", lambda: self.ctx.docker.view_logs(100)),
                ("最近 500 行", lambda: self.ctx.docker.view_logs(500)),
                ("最近 2000 行", lambda: self.ctx.docker.view_logs(2000)),
                ("全部日志", lambda: self.ctx.docker.view_logs("all")),
            ],
        )

    def view_config(self) -> None:
        ConfigService(self.ctx).view()

    def edit_config(self) -> None:
        self.ctx.require_installed()

        config_service = ConfigService(self.ctx)

        run_submenu(
            "修改配置",
            "主菜单",
            [
                ("在网页编辑 ->", config_service.edit_in_web),
                ("修改公开地址", config_service.change_url),
                ("修改端口", config_service.change_ports),
                ("修改 SMTP 邮件配置", config_service.change_smtp),
                ("修改 MFA 配置", config_service.change_mfa),
                ("修改 Max 账号密码", lambda: config_service.reset_password("max")),
                ("修改 Admin 账号密码", lambda: config_service.reset_password("admin")),
            ],
        )

    def generate_nginx(self) -> None:
        ConfigService(self.ctx).generate_nginx()

    def users(self) -> None:
        self.ctx.require_running()

        users = UserService(self.ctx)

        run_submenu(
            "用户管理",
            "主菜单",
            [
                ("用户列表", users.list_users),
                ("查看用户详情", users.show_user),
                ("创建用户", lambda: users.create_user(interactive=True)),
                ("删除用户", users.delete_user),
                ("修改用户密码", users.reset_password),
                ("设置用户组", lambda: users.set_group(interactive=True)),
                ("设置用户状态", lambda: users.set_status(interactive=True)),
                ("吊销用户全部会话", users.revoke_sessions),
            ],
        )

    def backup(self) -> None:
        self.ctx.require_installed()

        backup = BackupService(self.ctx)

        run_submenu(
            "备份与恢复",
            "主菜单",
            [
                ("导出全部数据（数据库全量快照）", backup.export),
                ("导入全部数据（停止后端并全量覆盖）", backup.restore_interactive),
                ("查看主机备份目录", backup.list_backups),
            ],
        )

    def security(self) -> None:
        self.ctx.require_running()

        security = SecurityService(self.ctx)

        run_submenu(
            "安全维护",
            "主菜单",
            [
                ("签名密钥状态", security.key_status),
                ("人工轮换签名密钥", security.key_rotate),
                ("数据库迁移状态", security.db_status),
                ("执行 db bootstrap（幂等）", security.db_bootstrap),
            ],
        )

    def self_update(self) -> None:
        client = ReleaseClient(self.ctx.manager)
        updater = SelfUpdater(client, self.ctx.manager, self.ctx.state)

        if result := updater.check():
            version, _ = result
            out(f"发现新版本: {version}")

            if ask_bool("是否更新管理工具？", True):
                updater.update()
        else:
            out("当前已是最新版本，或无法获取版本信息。")


# ============================================================================
# CLI 命令
# ============================================================================
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

    if args.follow:
        ctx.docker.view_logs(tail=200, follow=True, service=args.service)
    else:
        text = ctx.docker.logs_text(tail=200, service=args.service)
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
        case _:
            raise ManageError("请指定 user 子命令")


# ============================================================================
# 主入口
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ManagePylai.py",
        description="Pylai Docker Compose 部署管理工具",
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
    logs_p.add_argument("-f", "--follow", action="store_true", help="持续跟踪")

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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        out("\n再见。")


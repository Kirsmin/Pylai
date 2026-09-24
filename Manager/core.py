#!/usr/bin/env python3
"""ManagePylai 核心运行时。

包含共享类型、配置/状态、Docker Compose、Release/自更新以及通用工具。
该模块不负责交互菜单，也不直接启动程序。
"""

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
import zipfile

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

__version__ = "0.1.30"


class ManageError(Exception):
    """统一管理错误。"""


class UnsupportedArchitectureError(ManageError):
    """主机 CPU 架构不受支持（无静默回退）。"""


def manager_entry_path() -> Path:
    """返回用户实际执行的管理器入口，而不是当前模块文件。

    发布模式下是下载得到的 ManagePylai.pyz；源码模式下是
    ``Manager/__main__.py``（此时自更新会被拒绝）。
    """
    return Path(sys.argv[0]).expanduser().resolve()


def manager_artifact_version(path: Path) -> str | None:
    """读取 ManagePylai.pyz 内声明的版本。"""
    version_re = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)

    try:
        with zipfile.ZipFile(path) as archive:
            for name in ("core.py", "__main__.py"):
                try:
                    candidate = archive.read(name).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                if match := version_re.search(candidate):
                    return match.group(1)
    except (OSError, zipfile.BadZipFile):
        return None

    return None


def out(message: object = "", end: str = "\n") -> None:
    print(message, end=end, flush=True)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_home() -> None:
    for path in (CONFIG_DIR, CERT_DIR, DATA_DIR, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    """真原子写入：同目录临时文件 → fsync 落盘 → os.replace() 原子替换。

    中途断电/崩溃不会留下截断的半份文件；临时文件按目标 mode 创建，避免
    以更宽权限短暂存在。
    """
    ensure_home()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            raise
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # os.replace 后目标文件保留临时文件的权限（mode 已在 open 时设定）；
    # 若目标已存在且权限不同，显式纠正以符合调用方预期
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
    machine = host_platform.machine().lower()
    arch = SUPPORTED_ARCH.get(machine)
    if arch is None:
        raise UnsupportedArchitectureError(
            f"不支持的主机架构: {machine}。"
            f"支持的架构: {', '.join(sorted(set(SUPPORTED_ARCH.values())))}。"
        )
    return arch


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
    """统一的轻量问答提示。

    风格刻意接近 create-vue：一行一个问题，默认值放在括号中，不绘制边框。
    """
    default_hint = f" ({default})" if default not in (None, "") else ""
    prompt_line = f"? {prompt}{default_hint} › "

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
        out("! 该项不能为空。")


def ask_bool(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"? {prompt} ({hint}) › ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("\n已退出。")
            raise SystemExit(0)

        if not raw:
            return default
        if raw in {"y", "yes", "1", "true"}:
            return True
        if raw in {"n", "no", "0", "false"}:
            return False
        out("! 请输入 y 或 n。")


def ask_int(prompt: str, default: int, *, minimum: int = 1, maximum: int = 65535) -> int:
    while True:
        raw = ask(prompt, str(default))
        with suppress(ValueError):
            value = int(raw)
            if minimum <= value <= maximum:
                return value
        out(f"! 请输入 {minimum}-{maximum} 之间的数字。")


def choose(options: Sequence[tuple[str, T]], prompt: str = "请选择") -> T | None:
    if not options:
        out("! 没有可选项。")
        return None

    while True:
        out(f"? {prompt}")
        for index, (label, _) in enumerate(options, 1):
            out(f"  {index}. {label}")
        try:
            raw = input("› ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            out()
            return None

        with suppress(ValueError, IndexError):
            index = int(raw) - 1
            if 0 <= index < len(options):
                return options[index][1]
        out("! 选择无效。")


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

    out("  请妥善保存以上凭据；按 Enter 后将清除本次显示。")

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
    public_url: str = "http://localhost:8080"
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
# 组件管理：可独立开关的组件（key → ManagerConfig [Components] 键名）
COMPONENTS: dict[str, str] = {"backend": "Backend", "ui": "Ui", "adminui": "AdminUi"}
# 单独开关后端/用户前端属于高级操作（影响整体可用性），Admin UI 为常规运维开关
ADVANCED_COMPONENTS: frozenset[str] = frozenset({"backend", "ui"})


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

        components = self.get("Components", default={}) or {}
        if components:
            text += "\n# 组件开关（ManagePylai 组件管理维护，缺省视为启用）\n[Components]\n"
            text += "".join(
                f"{k} = {'true' if v else 'false'}\n" for k, v in components.items()
            )

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
    def components(self) -> dict[str, bool]:
        """组件开关状态（未记录的一律视为启用）。"""
        return {
            key: bool(self.get("Components", name, default=True))
            for key, name in COMPONENTS.items()
        }

    def set_components(self, states: dict[str, bool], *, save: bool = True) -> None:
        for key, enabled in states.items():
            if key in COMPONENTS:
                self.set("Components", COMPONENTS[key], value=bool(enabled))
        if save:
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
        return str(self._data.get("version", __version__))

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
            "原因：当前管理工具为新版（template 主路径），但加载的镜像为旧版构建（仅含 pylai.example.toml）。\n"
            "解决：\n"
            "  1) 推荐：重新构建/下载最新镜像（构建后 docker run --rm --entrypoint cat <image> /opt/pylai/pylai.template.toml 应存在），再执行安装；\n"
            "  2) 临时兼容：python3 ManagePylai.pyz install --compat  （或 --compat 与 --config-file/--env-file 组合）将回退到 example 渲染；\n"
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
        verbose: bool = False,
    ) -> None:
        if not self.compose_file.is_file():
            out("尚未安装（docker-compose.yml 不存在）。")
            return
        if not self.service_exists("backend"):
            text = self.logs_text(tail, follow=False, service=service)
            if text.strip():
                out(text.strip())
                out("\n[提示] 后端容器未运行，以上为最近日志。")
                return
            out("尚未安装或服务不存在。")
            return

        if follow:
            self._stream_logs(tail=tail, service=service, verbose=verbose)
        else:
            text = self.logs_text(tail, follow=False, service=service)
            out(text.strip() or "（暂无日志输出）")

    def _stream_logs(
        self,
        tail: int | str = 200,
        *,
        service: ServiceName | Literal["all"] = "all",
        verbose: bool = False,
    ) -> None:
        """直接流式输出 docker compose logs -f 到终端，支持 Ctrl+C 优雅退出。

        详细诊断模式(verbose=True)下会自动屏蔽 Nginx 访问日志，避免其淹没后端输出。
        """
        cmd: list[str | Path] = ["logs", "--timestamps"]

        if verbose:
            service = "all"
            tail = "all"
            out("\n实时日志 · 详细诊断")
            out("  服务: 全部(已屏蔽 Nginx) | 时间戳: 启用 | 历史: 全部")
            self._print_service_status()
        else:
            out(f"\n实时日志 · {service if service != 'all' else '所有服务'}（Ctrl+C 退出）")

        cmd.extend(["--tail", str(tail)])
        cmd.append("-f")
        if service != "all":
            cmd.append(service)

        full_cmd = [
            "docker", "compose",
            "-p", self.project,
            "--env-file", str(self.env_file),
            "-f", self.compose_file,
            *cmd,
        ]

        # 详细诊断模式下通过管道读取并过滤 Nginx 日志，避免访问日志淹没后端输出
        if verbose:
            import re
            # docker compose logs 格式: "service-name  |  [timestamp] log content"
            # 服务名可能是 pylai-nginx-1、nginx 等形式
            nginx_pattern = re.compile(r"^[\w-]*nginx[\w-]*\s+\|")

            try:
                process = subprocess.Popen(
                    [str(x) for x in full_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                assert process.stdout is not None
                for line in process.stdout:
                    if not nginx_pattern.match(line):
                        sys.stdout.write(line)
                        sys.stdout.flush()
                process.wait()
            except KeyboardInterrupt:
                out("\n[正在停止日志跟踪...]")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                out("[日志跟踪已退出]")
            return

        try:
            process = subprocess.Popen(
                [str(x) for x in full_cmd],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            process.wait()
        except KeyboardInterrupt:
            out("\n[正在停止日志跟踪...]")
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            out("[日志跟踪已退出]")

    def _print_service_status(self) -> None:
        """打印当前各服务状态（用于诊断）。"""
        result = self.compose("ps", "-a", "--format", "json", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return
        try:
            entries = json.loads(result.stdout)
            if isinstance(entries, dict):
                entries = [entries]
            out("  当前服务状态:")
            for e in entries:
                name = e.get("Name", e.get("Service", "unknown"))
                state = e.get("State", "unknown")
                status = e.get("Status", "unknown")
                health = e.get("Health", "")
                health_str = f" [{health}]" if health else ""
                out(f"    • {name}: {state} ({status}){health_str}")
        except (json.JSONDecodeError, TypeError):
            pass

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
        version, arch = meta or (__version__, host_arch())
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
      --loglevel warning
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
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
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
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
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

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
        cls.write_nginx_conf(manager)

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
        cls.write_nginx_conf(manager)

    @classmethod
    def write_nginx_conf(cls, manager: ManagerConfig | None = None) -> None:
        # 拆分拓扑站点配置：静态资源来自 backend 容器同步的共享卷（/var/lib/pylai/www），
        # API/OIDC 反代到 backend 服务；conf.d 片段处于 http 上下文，types 与主配置合并追加
        # （不得下放到 server/location 级，否则整体替换 MIME 映射导致静态资源被下载）。
        # 组件开关（ManagePylai 组件管理）在此落地：关闭的用户前端/管理面板一律 404。
        components = (manager or ManagerConfig()).components
        admin_block = (
            """\
    location = /admin { return 301 /admin/; }
    location /admin/ {
        alias /var/lib/pylai/www/adminui/;
        index index.html;
        try_files $uri $uri/ /admin/index.html;
    }"""
            if components["adminui"]
            else """\
    # Admin UI 已关闭（ManagePylai 组件管理）
    location /admin { return 404; }
    location /admin/ { return 404; }"""
        )
        root_block = (
            "    location / { try_files $uri $uri/ /index.html; }"
            if components["ui"]
            else """\
    # Pylai UI 已关闭（ManagePylai 组件管理）
    location / { return 404; }"""
        )
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
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

@@ADMIN_BLOCK@@
    location /api/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /connect/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /health {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
    }
    location /.well-known/ {
        proxy_pass http://backend:5000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_set_header X-Real-IP $remote_addr;
    }
@@ROOT_BLOCK@@
}
"""
        template = template.replace("@@ADMIN_BLOCK@@", admin_block)
        template = template.replace("@@ROOT_BLOCK@@", root_block)
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
        self.script_path = script_path or manager_entry_path()

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
        target_version: str | None = None,
        reexec_args: Sequence[str] | None = None,
    ) -> bool:
        """更新管理工具。

        target_version 用于云端应用更新：管理工具会先更新到与目标 Release
        一致的版本，再通过 os.execv 在同一终端中继续原更新命令。
        """
        if target_version:
            version = normalize_release_version(target_version)
            info = self.client.fetch_release_json(version) or {}
        else:
            result = self.client.check_latest()
            if not result:
                out("无法获取最新版本信息。")
                return False
            version, _, info = result

        if not force and not self.version_gt(version, __version__):
            if target_version:
                out(f"管理工具 v{__version__} 已满足目标版本 v{version}。")
            else:
                out(f"当前已是最新版本 {__version__}。")
            return False

        out(f"==> 更新管理工具: {__version__} -> {version}")

        if not self._check_schema_compat(info):
            if skip_prompt:
                out("Schema 不兼容且非交互模式，拒绝更新管理工具。")
                return False
            if not ask_bool("Schema 不兼容，仍强制更新管理工具（不推荐）？", False):
                return False

        if self.script_path.suffix.lower() != ".pyz":
            raise ManageError(
                "当前不是发布物（源码模式或旧版 ManagePylai.py）。"
                "请从 Release 下载 ManagePylai.pyz 后运行。"
            )

        asset_name = "ManagePylai.pyz"
        new_script = self.script_path.with_name(f".{self.script_path.name}.new")
        sha256_file = self.script_path.with_name(f".{self.script_path.name}.sha256")

        try:
            self.client.download(version, asset_name, new_script)
        except ManageError as exc:
            out(f"下载失败: {exc}")
            new_script.unlink(missing_ok=True)
            return False

        # Fail Closed：校验和文件缺失/不可读即终止更新（防供应链投毒）。
        try:
            self.client.download(version, f"{asset_name}.sha256", sha256_file)
            sha256_content = sha256_file.read_text(encoding="ascii").strip()
            sha256_expected = sha256_content.split()[0] if sha256_content else ""
        except (ManageError, OSError) as exc:
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            raise ManageError(f"无法下载或读取 SHA256 校验文件，拒绝更新（Fail Closed）: {exc}") from exc

        if not sha256_expected:
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            raise ManageError("SHA256 校验文件内容为空，拒绝更新（Fail Closed）。")

        actual = hashlib.sha256(new_script.read_bytes()).hexdigest()
        if actual != sha256_expected:
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            raise ManageError(f"SHA256 校验失败，拒绝更新: 期望 {sha256_expected}, 实际 {actual}")
        out("SHA256 校验通过。")

        # 发布物必须声明同一版本。文本兼容启动器与纯 .pyz 都支持。
        declared = manager_artifact_version(new_script)
        if not declared or normalize_release_version(declared) != version:
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            raise ManageError(
                f"Release v{version} 的 {asset_name} 版本声明为 {declared or '<missing>'}，"
                "版本不一致，拒绝更新。"
            )

        if dry_run:
            out(f"[dry-run] 将替换 {self.script_path} 为版本 {version}")
            if reexec_args:
                out(f"[dry-run] 随后将继续执行: {self.script_path.name} {' '.join(reexec_args)}")
            new_script.unlink(missing_ok=True)
            sha256_file.unlink(missing_ok=True)
            return True

        try:
            backup = self.script_path.with_name(f"{self.script_path.name}.bak.{__version__}")
            shutil.copy2(self.script_path, backup)
            os.replace(new_script, self.script_path)
            self.manager.set_skip_version(None)
            if reexec_args is None:
                out(f"{self.script_path.name} 已更新至 {version}，请重新运行脚本。")
            else:
                out(f"{self.script_path.name} 已更新至 {version}，正在继续更新 Pylai 后端...")
                os.execv(
                    sys.executable,
                    [sys.executable, str(self.script_path), *reexec_args],
                )
            return True
        except OSError as exc:
            out(f"替换或重新执行失败: {exc}")
            return False
        finally:
            sha256_file.unlink(missing_ok=True)

    def ensure_up_to_date(self, *, yes: bool = False) -> None:
        result = self.check()
        if not result:
            return

        version, info = result
        message = f"管理工具有新版本 {version}，是否先更新？"

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
#
# Cloudflare 场景说明：
#   若前端有 Cloudflare CDN，建议：
#   1. 在 pylai.toml [IpResolution] 中填入 Cloudflare IP 范围到 TrustedNetworks
#   2. 在 TrustedHeaders 中加入 CF-Connecting-IP（优先）或保留 X-Forwarded-For
#   3. 如需 Nginx 层直接解析真实 IP，取消下方 real_ip 段注释并填入 Cloudflare CIDR

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
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

    client_max_body_size 2m;

    # ---- Cloudflare 真实 IP 解析（可选，需 ngx_http_realip_module）----
    # set_real_ip_from 173.245.48.0/20;
    # set_real_ip_from 103.21.244.0/22;
    # ... 更多 Cloudflare CIDR 见 https://www.cloudflare.com/ips/
    # real_ip_header CF-Connecting-IP;
    # real_ip_recursive on;

    location / {{
        proxy_pass http://127.0.0.1:{state.public_port};
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
        proxy_set_header X-Real-IP $remote_addr;
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

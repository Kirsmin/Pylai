#!/usr/bin/env python3
"""ManagePylai - Pylai Docker 部署管理工具。

仅使用 Python 标准库和 docker CLI。Release 页面同时提供
Pylai-<version>-Linux-<arch>.tar 与本脚本，下载后放在同一目录运行即可。
"""
from __future__ import annotations

import getpass
import json
import os
import platform as host_platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "Pylai"
CONTAINER = "pylai"
# 镜像把发布产物放在 /opt/pylai，但该目录不在容器 PATH 中，
# 因此 docker exec 必须写完整路径（entrypoint/supervisor 均使用 /opt/pylai/Pylaios）。
PYLAIOS_BIN = "/opt/pylai/Pylaios"
HOME = Path(os.environ.get("PYLAI_HOME", "~/.pylai")).expanduser()
STATE_FILE = HOME / "state.json"
CONFIG_DIR = HOME / "config"
CONFIG_FILE = CONFIG_DIR / "pylai.toml"
CERT_DIR = CONFIG_DIR / "certs"
# 容器内挂载路径（CONFIG_DIR -> /etc/pylai），写入 TOML 的证书路径必须使用该路径
CONTAINER_CONFIG_DIR = "/etc/pylai"
CONTAINER_CERT_DIR = f"{CONTAINER_CONFIG_DIR}/certs"
DATA_DIR = HOME / "data"
PG_DATA_DIR = HOME / "pgdata"
BACKUP_DIR = HOME / "backups"
HOST_NGINX_FILE = HOME / "host-nginx.conf"

TAR_PATTERN = re.compile(r"^Pylai-(.+)-Linux-(AMD64|ARM64)\.tar$")
SUPPORTED_ARCH = {
    "x86_64": "AMD64",
    "amd64": "AMD64",
    "aarch64": "ARM64",
    "arm64": "ARM64",
}


class ManageError(Exception):
    pass


def out(message: str = "") -> None:
    print(message, flush=True)


def random_password(length: int = 12) -> str:
    """生成同时包含数字、小写和大写字母的初始密码。"""
    return f"{secrets.token_urlsafe(length)}Aa1"


def ask(
    prompt: str,
    default: str | None = None,
    secret: bool = False,
    allow_blank: bool = False,
) -> str:
    """读取一行输入。

    default 非空：空输入返回默认值；default 为空且 allow_blank=True：空输入返回空字符串；
    否则提示“该项不能为空。”并重新询问。
    """
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = getpass.getpass(f"{prompt}{suffix}: ") if secret else input(f"{prompt}{suffix}: ")
        except (EOFError, KeyboardInterrupt):
            out("\n已退出。")
            raise SystemExit(0)
        value = value.strip()
        if value:
            return value
        if default:
            return default
        if allow_blank:
            return ""
        out("该项不能为空。")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        value = ask(prompt + suffix, "", allow_blank=True).strip().lower()
        if not value:
            return default
        if value in ("y", "yes", "1"):
            return True
        if value in ("n", "no", "0"):
            return False
        out("请输入 y 或 n。")


def ask_int(prompt: str, default: int, minimum: int = 1, maximum: int = 65535) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            out("请输入数字。")
            continue
        if minimum <= value <= maximum:
            return value
        out(f"请输入 {minimum}-{maximum} 之间的数字。")


def choose(options: list[tuple[str, str]], prompt: str = "请选择") -> str | None:
    if not options:
        out("没有可选项。")
        return None
    while True:
        for index, (label, _) in enumerate(options, 1):
            out(f"  [{index}] {label}")
        raw = ask(prompt, "1")
        try:
            return options[int(raw) - 1][1]
        except (ValueError, IndexError):
            out("选择无效。\n")


def confirm_danger(text: str, required_word: str = "DELETE") -> bool:
    out(f"危险操作：{text}")
    value = ask(f"请输入 {required_word} 确认", "").strip()
    return value == required_word


def run(
    cmd: list[str],
    check: bool = True,
    timeout: int | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, input=input_text)
    if check and result.returncode != 0:
        raise ManageError(result.stderr.strip() or result.stdout.strip() or f"命令失败: {' '.join(cmd)}")
    return result


def docker(*args: str, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return run(["docker", *args], check=check, timeout=timeout)


def ensure_docker() -> None:
    if shutil.which("docker") is None:
        raise ManageError("未找到 docker，请先安装 Docker。")
    result = docker("info", check=False)
    if result.returncode != 0:
        raise ManageError("Docker daemon 不可用，请启动 Docker 服务。")


def ensure_home() -> None:
    for path in (CONFIG_DIR, CERT_DIR, DATA_DIR, PG_DATA_DIR, BACKUP_DIR):
        path.mkdir(parents=True, exist_ok=True)
    PG_DATA_DIR.chmod(0o777)


def load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    ensure_home()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE_FILE.chmod(0o600)


def container_exists() -> bool:
    result = docker("inspect", CONTAINER, check=False)
    return result.returncode == 0


def container_status() -> str | None:
    result = docker("inspect", "-f", "{{.State.Status}}", CONTAINER, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def container_restart_count() -> int | None:
    result = docker("inspect", "-f", "{{.RestartCount}}", CONTAINER, check=False)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def container_running() -> bool:
    return container_status() == "running"


def print_container_logs(tail: int = 60) -> None:
    result = docker("logs", "--timestamps", "--tail", str(tail), CONTAINER, check=False)
    output = (result.stdout + result.stderr).strip()
    if output:
        out(output)
    else:
        out("（容器暂无日志输出）")


def view_container_logs(tail: int | str = 200, follow: bool = False) -> None:
    """用 less 查看容器日志；follow=True 时使用 less +F 持续跟踪。"""
    if not container_exists():
        out("尚未安装或容器不存在。")
        return

    cmd = ["docker", "logs", "--timestamps", "--tail", str(tail)]
    if follow:
        cmd.append("-f")
    cmd.append(CONTAINER)

    less = shutil.which("less")
    if less is None:
        subprocess.run(cmd, check=False)
        return

    if follow:
        out("已进入持续跟踪：Ctrl+C 停止跟踪，按 q 退出；退出后返回日志菜单。\n")
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as docker_proc:
            less_cmd = [less, "-R"]
            if follow:
                less_cmd.append("+F")
            subprocess.run(less_cmd, stdin=docker_proc.stdout, check=False)
            if docker_proc.stdout is not None:
                docker_proc.stdout.close()
            try:
                docker_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                docker_proc.terminate()
                try:
                    docker_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    docker_proc.kill()
    except (OSError, subprocess.SubprocessError) as exc:
        out(f"日志查看失败: {exc}")


def wait_healthy(api_port: int, timeout: int = 180) -> bool:
    url = f"http://127.0.0.1:{api_port}/health/ready"
    restart_count = container_restart_count()
    if restart_count is None:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # 容器退出/进入重启循环时无需继续等待，尽快把日志交给用户排查
        if container_status() != "running":
            return False
        current_restart_count = container_restart_count()
        if current_restart_count is None or current_restart_count > restart_count:
            return False
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(3)
    return False


def host_arch() -> str:
    machine = host_platform.machine().lower()
    return SUPPORTED_ARCH.get(machine, "AMD64")


def discover_tars() -> list[Path]:
    tars: list[Path] = []
    for path in sorted(Path.cwd().glob("Pylai-*.tar")):
        if TAR_PATTERN.match(path.name):
            tars.append(path)
    return tars


def parse_tar(path: Path) -> tuple[str, str] | None:
    match = TAR_PATTERN.match(path.name)
    if not match:
        return None
    return match.group(1), match.group(2)


def load_image_tar(tar_path: Path) -> str:
    out(f"==> 加载镜像 {tar_path.name} ...")
    result = docker("load", "-i", str(tar_path), timeout=1200)
    version, arch = parse_tar(tar_path) or ("0.0.1", host_arch())
    expected = f"pylaios:{version}-{arch}"
    lines = result.stdout.splitlines() + result.stderr.splitlines()
    for line in lines:
        if "Loaded image" in line:
            name = line.split(":", 1)[1].strip() if ":" in line else ""
            if name:
                return name
    inspect = docker("image", "inspect", expected, check=False)
    if inspect.returncode == 0:
        return expected
    raise ManageError(f"无法确定镜像名称，请手动确认: {result.stdout}\n{result.stderr}")


def read_template(image: str) -> str:
    result = docker("run", "--rm", "--entrypoint", "cat", image, "/opt/pylai/pylai.example.toml",
                    check=False, timeout=120)
    if result.returncode != 0:
        raise ManageError("无法从镜像读取配置模板: " + (result.stderr.strip() or "未知错误"))
    return result.stdout


def replace_one(text: str, old: str, new: str, count: int = 1) -> str:
    if old not in text:
        raise ManageError(f"配置模板缺少预期内容: {old[:60]}...")
    return text.replace(old, new, count)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_string_list(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def generate_config(image: str, answers: dict) -> None:
    text = read_template(image)

    text = replace_one(text, 'Url = "http://localhost:5000"', 'Url = "http://0.0.0.0:5000"')
    text = replace_one(text, 'Url = "http://localhost:5173"', f'Url = "{answers["public_url"]}"')
    text = replace_one(
        text,
        'ConnectionString = "Host=127.0.0.1;Port=5432;Database=postgres;Username=postgres;Password="',
        f'ConnectionString = "Host=127.0.0.1;Port=5432;Database={answers["db_name"]};Username={answers["db_user"]};Password={answers["db_password"]}"',
    )
    text = replace_one(text, 'Password = ""', f'Password = "{answers["redis_password"]}"', 1)
    text = replace_one(text, 'ServerPepper = ""', f'ServerPepper = "{answers["invite_pepper"]}"')
    text = replace_one(text, 'Directory = "backups"', 'Directory = "/var/lib/pylai/backups"')
    text = replace_one(text, 'ForwardedHeadersEnabled = true', "ForwardedHeadersEnabled = true")
    text = replace_one(text, 'TrustedProxies = ["127.0.0.1", "::1"]', f'TrustedProxies = {toml_string_list(answers["trusted_proxies"])}')
    text = replace_one(text, 'TrustedNetworks = []', f'TrustedNetworks = {toml_string_list(answers["trusted_networks"])}')
    text = replace_one(text, 'KeyFile = ""', 'KeyFile = "/etc/pylai/certs/signing-kek"')
    text = replace_one(text, 'AllowedOrigins = ["http://localhost:5173"]',
                       f'AllowedOrigins = {toml_string_list(answers["cors_origins"])}')
    text = replace_one(text, 'Issuer = "http://localhost:5000"', f'Issuer = "{answers["origin"]}"')
    external_host = urlparse(answers["public_url"]).hostname or "localhost"
    allowed_hosts = [external_host]
    if external_host not in ("localhost", "127.0.0.1", "::1"):
        allowed_hosts.extend(("localhost", "127.0.0.1"))
    text = replace_one(text, 'AllowedHosts = ["localhost", "127.0.0.1"]',
                       f'AllowedHosts = {toml_string_list(allowed_hosts)}')
    text = replace_one(text, 'RelyingPartyId = "localhost"', f'RelyingPartyId = "{external_host}"')
    text = replace_one(text, 'Origins = ["http://localhost:5173"]', f'Origins = {toml_string_list(cors_origins)}')

    if answers["public_url"].startswith("https://"):
        text = replace_one(text, "RequireHttps = false", "RequireHttps = true") if "RequireHttps = false" in text else text
        text = replace_one(text, "RequireHttps = true", "RequireHttps = true")
        text = replace_one(text, 'SecurePolicy = "Always"', 'SecurePolicy = "Always"')
    else:
        text = replace_one(text, "RequireHttps = true", "RequireHttps = false")
        text = replace_one(text, 'SecurePolicy = "Always"', 'SecurePolicy = "SameAsRequest"')

    if answers["signing_pfx"]:
        text = replace_one(text, '[OpenIddict.Certificates.Signing]\nPath = ""',
                           f'[OpenIddict.Certificates.Signing]\nPath = "{answers["signing_pfx"]}"')
        text = replace_one(text, f'[OpenIddict.Certificates.Signing]\nPath = "{answers["signing_pfx"]}"\nPassword = ""',
                           f'[OpenIddict.Certificates.Signing]\nPath = "{answers["signing_pfx"]}"\nPassword = "{answers["signing_pfx_password"]}"')
    if answers["encryption_pfx"]:
        text = replace_one(text, '[OpenIddict.Certificates.Encryption]\nPath = ""',
                           f'[OpenIddict.Certificates.Encryption]\nPath = "{answers["encryption_pfx"]}"')
        text = replace_one(text, f'[OpenIddict.Certificates.Encryption]\nPath = "{answers["encryption_pfx"]}"\nPassword = ""',
                           f'[OpenIddict.Certificates.Encryption]\nPath = "{answers["encryption_pfx"]}"\nPassword = "{answers["encryption_pfx_password"]}"')

    seed_blocks = [
        ("Seeds.DefaultAdmin", "admin_email", "admin_password", "Administrator"),
        ("Seeds.DefaultUser", "user_email", "user_password", "Test User"),
        ("Seeds.DefaultMax", "max_email", "max_password", "Max User"),
    ]
    for section, email_key, password_key, display_name in seed_blocks:
        prefix = f"[{section}]"
        if prefix not in text:
            continue
        start = text.index(prefix)
        end = text.find("\n\n", start)
        end = len(text) if end < 0 else end
        block = text[start:end]
        block = block.replace('Email = "admin@pylaios.local"', f'Email = "{answers[email_key]}"')
        block = block.replace('Email = "user@pylaios.local"', f'Email = "{answers[email_key]}"')
        block = block.replace('Email = "max@pylaios.local"', f'Email = "{answers[email_key]}"')
        block = block.replace('Password = ""', f'Password = "{answers[password_key]}"', 1)
        block = block.replace('DisplayName = "Administrator"', f'DisplayName = "{display_name}"')
        block = block.replace('DisplayName = "Test User"', f'DisplayName = "{display_name}"')
        block = block.replace('DisplayName = "Max User"', f'DisplayName = "{display_name}"')
        text = text[:start] + block + text[end:]

    if answers["smtp_enabled"]:
        text = replace_one(text, '[Email]\nFromName = "Pylaios"\nFromAddress = ""',
                           f'[Email]\nFromName = "Pylaios"\nFromAddress = "{answers["smtp_from"]}"')
        smtp_marker = "[Email.Smtp]"
        smtp_start = text.index(smtp_marker)
        smtp_end = text.find("\n\n", smtp_start)
        smtp_end = len(text) if smtp_end < 0 else smtp_end
        smtp_block = text[smtp_start:smtp_end]
        smtp_block = replace_one(smtp_block, 'Host = ""', f'Host = "{answers["smtp_host"]}"')
        smtp_block = replace_one(smtp_block, "Port = 587", f"Port = {answers['smtp_port']}")
        smtp_block = replace_one(smtp_block, 'Security = "StartTls"', f'Security = "{answers["smtp_security"]}"')
        smtp_block = replace_one(smtp_block, 'Username = ""', f'Username = "{answers["smtp_user"]}"')
        smtp_block = smtp_block.replace('Password = ""', f'Password = "{answers["smtp_password"]}"', 1)
        text = text[:smtp_start] + smtp_block + text[smtp_end:]

    ensure_home()
    CONFIG_FILE.write_text(text, encoding="utf-8")
    CONFIG_FILE.chmod(0o600)


SMTP_SECURITY_DESCRIPTIONS = {
    "SslOnConnect": "SMTPS / 隐式 TLS（服务端从连接开始即 TLS，常见端口 465）",
    "StartTls": "STARTTLS（先明文连接再升级 TLS，常见端口 587）",
    "None": "无加密（仅限可信内网，不推荐）",
}


def ask_smtp_security(default: str = "StartTls") -> str:
    options = [
        ("SslOnConnect — 隐式 TLS，465 端口通常选这个", "SslOnConnect"),
        ("StartTls — STARTTLS，587 端口通常选这个（推荐）", "StartTls"),
        ("None — 不加密，仅限可信内网", "None"),
    ]
    while True:
        out("SMTP 加密方式：")
        for index, (label, value) in enumerate(options, 1):
            marker = " <=" if value == default else ""
            out(f"  [{index}] {label}{marker}")
        raw = ask("请选择", str(next(i for i, (_, value) in enumerate(options, 1) if value == default)))
        try:
            return options[int(raw) - 1][1]
        except (ValueError, IndexError):
            out("选择无效。\n")


def configure_smtp_interactive() -> dict | None:
    """SMTP 配置向导；返回 None 表示用户选择不配置。"""
    if not ask_yes_no("配置 SMTP 邮件发送？", False):
        return None

    smtp_host = ask("SMTP 服务器")
    while True:
        out("\nSMTP 端口（请按邮件服务商文档选择）：")
        out("  [1] 465 — SMTPS / 隐式 TLS（阿里云企业邮箱等）")
        out("  [2] 587 — STARTTLS（通用推荐）")
        out("  [3] 25  — 无加密（不推荐）")
        out("  [4] 自定义端口")
        raw = ask("请选择", "2")
        if raw == "1":
            smtp_port, smtp_security = 465, "SslOnConnect"
        elif raw == "2":
            smtp_port, smtp_security = 587, "StartTls"
        elif raw == "3":
            smtp_port, smtp_security = 25, "None"
        elif raw == "4":
            smtp_port = ask_int("SMTP 端口", 587)
            smtp_security = ask_smtp_security()
        else:
            out("选择无效。\n")
            continue

        out(f"\n已选择 SMTP：{smtp_host}:{smtp_port}")
        out(f"加密方式：{smtp_security} — {SMTP_SECURITY_DESCRIPTIONS[smtp_security]}")
        if ask_yes_no("确认以上端口与加密方式？", True):
            break
        out()

    smtp_user = ask("SMTP 用户名（无认证可留空）", "", allow_blank=True)
    smtp_password = ask("SMTP 密码（无认证可留空）", "", secret=True, allow_blank=True)
    smtp_from = ask("发件人邮箱")

    return {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_security": smtp_security,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "smtp_from": smtp_from,
    }


def mask_config_text(text: str) -> str:
    """对配置中的密码/密钥/连接串等敏感值做掩码显示。"""
    masked_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r'^(\s*[^=]*\b(?:Password|Secret|ConnectionString)\s*=\s*).*$', line, re.IGNORECASE)
        if match:
            masked_lines.append(f'{match.group(1)}"***"')
        else:
            masked_lines.append(line)
    return "\n".join(masked_lines) + ("\n" if text.endswith("\n") else "")


def _replace_toml_block_value(text: str, marker: str, key: str, value: str) -> str:
    """替换 TOML 段内指定键值；键不存在时插到段首行之后。"""
    start = text.index(marker)
    end = text.find("\n\n", start)
    end = len(text) if end < 0 else end
    block = text[start:end]
    pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*).*$', re.MULTILINE)
    replacement = f'{value}'
    if pattern.search(block):
        block = pattern.sub(lambda m: f"{m.group(1)}{replacement}", block, count=1)
    else:
        first_line_end = block.find("\n")
        first_line_end = len(block) if first_line_end < 0 else first_line_end + 1
        block = block[:first_line_end] + f"{key} = {replacement}\n" + block[first_line_end:]
    return text[:start] + block + text[end:]


def write_smtp_config(smtp: dict) -> None:
    """把 SMTP 配置写回 pylai.toml 的 [Email] / [Email.Smtp] 段。"""
    if not CONFIG_FILE.is_file():
        raise ManageError("配置文件不存在")
    text = CONFIG_FILE.read_text(encoding="utf-8")
    text = _replace_toml_block_value(text, "[Email]", "FromAddress", toml_string(smtp["smtp_from"]))
    text = _replace_toml_block_value(text, "[Email.Smtp]", "Host", toml_string(smtp["smtp_host"]))
    text = _replace_toml_block_value(text, "[Email.Smtp]", "Port", str(smtp["smtp_port"]))
    text = _replace_toml_block_value(text, "[Email.Smtp]", "Security", toml_string(smtp["smtp_security"]))
    text = _replace_toml_block_value(text, "[Email.Smtp]", "Username", toml_string(smtp["smtp_user"]))
    text = _replace_toml_block_value(text, "[Email.Smtp]", "Password", toml_string(smtp["smtp_password"]))
    text = re.sub(r'(?m)^[ \t]*UseSsl[ \t]*=.*\n', "", text)

    CONFIG_FILE.write_text(text, encoding="utf-8")
    CONFIG_FILE.chmod(0o600)


def collect_install_answers() -> dict:
    ensure_home()
    public_url = ask("对外访问地址（浏览器访问 Pylai 的 URL）", "http://localhost:8080")
    public_port = ask_int("容器 80 映射到主机端口", 8080)
    api_port = ask_int("后端 5000 映射到本机端口（仅绑定 127.0.0.1）", 5000)

    out("\n-- 数据库 / Redis --")
    db_user = ask("PostgreSQL 用户名", "pylai")
    db_name = ask("PostgreSQL 数据库名", "pylai")
    db_password = secrets.token_hex(16)
    redis_password = secrets.token_hex(16)
    ensure_home()
    signing_kek = secrets.token_hex(32)
    signing_kek_path = CERT_DIR / "signing-kek"
    signing_kek_path.write_text(signing_kek, encoding="ascii")
    signing_kek_path.chmod(0o600)

    out("\n-- 初始账号 --")
    max_email = ask("Max 账号邮箱/登录名", "max@pylai.local")
    max_password = secrets.token_urlsafe(12)
    if ask_yes_no("创建初始 Admin 账号？", True):
        admin_email = ask("Admin 账号邮箱/登录名", "admin@pylai.local")
        admin_password = random_password(14)
    else:
        admin_email, admin_password = "", ""
    if ask_yes_no("创建初始 Normal 测试账号？", False):
        user_email = ask("Normal 账号邮箱/登录名", "user@pylai.local")
        user_password = random_password(12)
    else:
        user_email, user_password = "", ""

    out("\n-- 邮件 --")
    smtp = configure_smtp_interactive()
    if smtp:
        smtp_host = smtp["smtp_host"]
        smtp_port = smtp["smtp_port"]
        smtp_security = smtp["smtp_security"]
        smtp_user = smtp["smtp_user"]
        smtp_password = smtp["smtp_password"]
        smtp_from = smtp["smtp_from"]
        smtp_enabled = True
    else:
        smtp_host, smtp_port, smtp_security, smtp_user, smtp_password, smtp_from = "", 587, "StartTls", "", "", ""
        smtp_enabled = False

    out("\n-- 安全 --")
    if ask_yes_no("使用数据库托管签名密钥（推荐，后续用菜单手动轮换）？", True):
        signing_pfx = ""
        signing_pfx_password = ""
    else:
        signing_pfx = ask("签名 PFX 文件路径（留空则继续使用数据库托管）", "", allow_blank=True).strip()
        signing_pfx_password = ""
        if signing_pfx and Path(signing_pfx).is_file():
            ensure_home()
            signing_pfx_password = ask("签名 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
            destination = CERT_DIR / "signing.pfx"
            shutil.copy2(signing_pfx, destination)
            destination.chmod(0o600)
            signing_pfx = f"{CONTAINER_CERT_DIR}/signing.pfx"
    encryption_pfx = ""
    encryption_pfx_password = ""
    if ask_yes_no("自动生成加密证书（推荐，生产环境必需）？", True) and shutil.which("openssl"):
        ensure_home()
        host_pfx = CERT_DIR / "encryption.pfx"
        key_file = CERT_DIR / "encryption-key.pem"
        cert_file = CERT_DIR / "encryption-cert.pem"
        encryption_pfx_password = secrets.token_urlsafe(12)
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key_file), "-out", str(cert_file), "-days", "3650",
             "-subj", "/CN=Pylai Encryption"], timeout=300)
        run(["openssl", "pkcs12", "-export", "-out", str(host_pfx),
             "-inkey", str(key_file), "-in", str(cert_file),
             "-passout", f"pass:{encryption_pfx_password}"], timeout=300)
        Path(host_pfx).chmod(0o600)
        key_file.unlink(missing_ok=True)
        cert_file.unlink(missing_ok=True)
        encryption_pfx = f"{CONTAINER_CERT_DIR}/encryption.pfx"

    if not encryption_pfx:
        if shutil.which("openssl") is None:
            out("未找到 openssl，无法自动生成加密证书。")
        encryption_pfx = ask("请提供加密 PFX 文件路径（生产环境必需）", "", allow_blank=True).strip()
        if not encryption_pfx or not Path(encryption_pfx).is_file():
            raise ManageError("生产环境必须配置持久化 OpenIddict 加密证书。")
        encryption_pfx_password = ask("加密 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
        destination = CERT_DIR / "encryption.pfx"
        shutil.copy2(encryption_pfx, destination)
        destination.chmod(0o600)
        encryption_pfx = f"{CONTAINER_CERT_DIR}/encryption.pfx"
    trusted_proxies = ask("可信代理 IP（逗号分隔，主机 Nginx 与本机）", "127.0.0.1,::1")
    trusted_networks = ask("可信代理 CIDR（逗号分隔）", "172.16.0.0/12")

    origin = public_url.rstrip("/")
    cors_origins = [origin]
    extra_cors = ask("额外 CORS Origin（逗号分隔，没有留空）", "", allow_blank=True).strip()
    if extra_cors:
        cors_origins.extend(x.strip() for x in extra_cors.split(",") if x.strip())

    return {
        "public_url": public_url,
        "origin": public_url.rstrip("/"),
        "public_port": public_port,
        "api_port": api_port,
        "db_user": db_user,
        "db_name": db_name,
        "db_password": db_password,
        "redis_password": redis_password,
        "invite_pepper": secrets.token_hex(32),
        "max_email": max_email,
        "max_password": max_password,
        "admin_email": admin_email,
        "admin_password": admin_password,
        "user_email": user_email,
        "user_password": user_password,
        "smtp_enabled": smtp_enabled,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_security": smtp_security,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "smtp_from": smtp_from,
        "signing_pfx": signing_pfx,
        "signing_pfx_password": signing_pfx_password,
        "encryption_pfx": encryption_pfx,
        "encryption_pfx_password": encryption_pfx_password,
        "trusted_proxies": [x.strip() for x in trusted_proxies.split(",") if x.strip()],
        "trusted_networks": [x.strip() for x in trusted_networks.split(",") if x.strip()],
        "cors_origins": cors_origins,
    }


def start_container(image: str, answers: dict, read_only: bool = True) -> None:
    if container_exists():
        docker("rm", "-f", CONTAINER)
    ensure_home()
    cmd = [
        "docker", "run", "-d", "--name", CONTAINER,
        "--restart", "unless-stopped",
    ]
    if read_only:
        cmd.append("--read-only")
    cmd += [
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
        "-p", f"{answers['public_port']}:80",
        "-p", f"127.0.0.1:{answers['api_port']}:5000",
        "-v", f"{CONFIG_DIR}:/etc/pylai",
        "-v", f"{DATA_DIR}:/var/lib/pylai",
        "-v", f"{PG_DATA_DIR}:/var/lib/postgresql",
        "-e", "PYLAI_ROLE=server",
        "-e", f"PYLAI_UI_URL={answers['public_url']}",
        "-e", f"PYLAI_DB_USER={answers['db_user']}",
        "-e", f"PYLAI_DB_PASSWORD={answers['db_password']}",
        "-e", f"PYLAI_DB_NAME={answers['db_name']}",
        "-e", f"PYLAI_REDIS_PASSWORD={answers['redis_password']}",
        image,
    ]
    run(cmd, timeout=120)
    out("==> 等待服务健康检查 ...")
    if not wait_healthy(int(answers["api_port"])):
        print_container_logs()
        raise ManageError("服务启动超时，请根据上方日志排查。")
    out("==> 服务已就绪。")


def print_install_summary(answers: dict) -> None:
    out("\n" + "=" * 64)
    out("  Pylai 安装完成")
    out(f"  前端:     {answers['public_url']}/")
    out(f"  管理台:   {answers['public_url']}/admin/")
    out(f"  健康检查: http://127.0.0.1:{answers['api_port']}/health/ready")
    if answers["max_password"]:
        out(f"  Max 账号: {answers['max_email']} / {answers['max_password']}")
    if answers["admin_password"]:
        out(f"  Admin 账号: {answers['admin_email']} / {answers['admin_password']}")
    if answers["user_password"]:
        out(f"  Normal 账号: {answers['user_email']} / {answers['user_password']}")
    out("  以上初始密码仅在本次安装时显示，请妥善保存。")
    out("=" * 64)


def run_submenu(title: str, parent_title: str, entries: list[tuple[str, object]]) -> None:
    """二级/三级菜单循环：[0] 返回上级，操作完成后仍停留当前菜单。"""
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
        if raw in ("0", "back", "return"):
            return
        try:
            action = entries[int(raw) - 1][1]
        except (ValueError, IndexError):
            out("选择无效。")
            continue
        try:
            action()  # type: ignore[operator]
        except ManageError as exc:
            out(f"错误: {exc}")


def menu_install() -> None:
    ensure_docker()
    state = load_state()
    if state:
        out("检测到已有安装。如需重新安装，请先卸载或使用更新。")
        return

    tars = discover_tars()
    if not tars:
        out("当前目录未找到 Pylai-<version>-Linux-<arch>.tar。")
        return
    options = [(f"{p.name}（{'与当前主机兼容' if parse_tar(p)[1] == host_arch() else '其他架构'}）", p.name) for p in tars]
    name = choose(options, "请选择安装包")
    if not name:
        return
    tar_path = Path.cwd() / name
    version, arch = parse_tar(tar_path) or ("0.0.1", host_arch())
    image = load_image_tar(tar_path)

    out("\n==> 开始安装配置（涉及密码的项直接回车可自动生成）")
    answers = collect_install_answers()
    generate_config(image, answers)
    start_container(image, answers)
    state = {
        "version": version,
        "architecture": arch,
        "image": image,
        "public_url": answers["public_url"],
        "public_port": answers["public_port"],
        "api_port": answers["api_port"],
        "max_email": answers["max_email"],
        "admin_email": answers["admin_email"],
        "installed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    save_state(state)
    print_install_summary(answers)
    out("提示：建议使用主机 Nginx 反代，主菜单 [6] 可生成配置模板。")


def action_status() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    result = docker("ps", "-a", "--filter", f"name={CONTAINER}", "--format", "{{.Names}} {{.Status}}", check=False)
    out(result.stdout.strip() or "未找到容器")


def action_start() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    docker("start", CONTAINER, timeout=60)
    state = load_state()
    if not wait_healthy(int(state.get("api_port", 5000))):
        out("容器已启动，但健康检查尚未通过。")
    else:
        out("启动完成。")


def action_stop() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    docker("stop", "-t", "30", CONTAINER, timeout=120)
    out("已停止。")


def action_restart() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    docker("restart", CONTAINER, timeout=120)
    out("已重启。")


def submenu_logs() -> None:
    entries = [
        ("最近 100 行", lambda: view_container_logs(100, follow=False)),
        ("最近 500 行", lambda: view_container_logs(500, follow=False)),
        ("最近 2000 行", lambda: view_container_logs(2000, follow=False)),
        ("全部日志", lambda: view_container_logs("all", follow=False)),
        ("持续跟踪（less +F）", lambda: view_container_logs(200, follow=True)),
    ]
    run_submenu("运行控制 / 日志", "运行控制", entries)


def submenu_run() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    running = container_running()
    entries = [
        ("状态", action_status),
        ("启动", action_start),
        ("停止", action_stop),
        ("重启", action_restart),
        ("日志", submenu_logs),
    ]
    out(f"当前状态: {'运行中' if running else '已停止'}")
    run_submenu("运行控制", "主菜单", entries)


def action_view_config() -> None:
    if not CONFIG_FILE.is_file():
        out("配置文件不存在")
        return
    out(mask_config_text(CONFIG_FILE.read_text(encoding="utf-8")))


def action_change_url() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    new_url = ask("新公开地址", state.get("public_url"))
    if not CONFIG_FILE.is_file():
        raise ManageError("配置文件不存在")
    origin = new_url.rstrip("/")
    external_host = urlparse(new_url).hostname or "localhost"
    allowed_hosts = [external_host]
    if external_host not in ("localhost", "127.0.0.1", "::1"):
        allowed_hosts.extend(("localhost", "127.0.0.1"))
    text = CONFIG_FILE.read_text(encoding="utf-8")
    text = _replace_toml_block_value(text, "[Frontend]", "Url", toml_string(new_url))
    text = _replace_toml_block_value(text, "[OpenIddict]", "Issuer", toml_string(origin))
    text = _replace_toml_block_value(text, "[OpenIddict]", "RequireHttps", "true" if origin.startswith("https://") else "false")
    text = _replace_toml_block_value(text, "[Server]", "AllowedHosts", toml_string_list(allowed_hosts))
    text = _replace_toml_block_value(text, "[Mfa]", "RelyingPartyId", toml_string(external_host))
    text = _replace_toml_block_value(text, "[Mfa]", "Origins", toml_string_list([origin]))
    text = _replace_toml_block_value(text, "[Cookie]", "SecurePolicy", toml_string("Always" if origin.startswith("https://") else "SameAsRequest"))
    CONFIG_FILE.write_text(text, encoding="utf-8")
    CONFIG_FILE.chmod(0o600)
    state["public_url"] = new_url
    save_state(state)
    out("配置已修改，注意：需要手动重启实例才能生效")


def action_change_ports() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    new_public = ask_int("新公开端口", int(state.get("public_port", 8080)))
    new_api = ask_int("新本机 API 端口", int(state.get("api_port", 5000)))
    state["public_port"] = new_public
    state["api_port"] = new_api
    if container_exists() and ask_yes_no("端口映射需要重建容器才能生效，是否立即应用？", True):
        env = read_container_env()
        image = state.get("image") or "pylaios:unknown"
        answers = {
            "public_url": state.get("public_url", "http://localhost"),
            "public_port": new_public,
            "api_port": new_api,
            "db_user": env.get("PYLAI_DB_USER", "pylai"),
            "db_name": env.get("PYLAI_DB_NAME", "pylai"),
            "db_password": env.get("PYLAI_DB_PASSWORD", ""),
            "redis_password": env.get("PYLAI_REDIS_PASSWORD", ""),
        }
        if not answers["db_password"] or not answers["redis_password"]:
            save_state(state)
            out("无法读取现有容器环境变量，端口已记录，将在下次重建容器时生效。")
            return
        start_container(image, answers)
        if not wait_healthy(new_api):
            print_container_logs()
            raise ManageError("重建后健康检查未通过，请根据上方日志排查。")
        out("端口已更新并重建容器。")
    else:
        out("端口已记录，将在下次重建容器时生效。")
    save_state(state)


def action_change_smtp() -> None:
    if not CONFIG_FILE.is_file():
        out("配置文件不存在")
        return
    smtp = configure_smtp_interactive()
    if not smtp:
        out("已取消。")
        return
    write_smtp_config(smtp)
    out(f"SMTP 配置已更新：{smtp['smtp_host']}:{smtp['smtp_port']} / {smtp['smtp_security']}")
    out("注意：需要手动重启实例才能生效")


def action_reset_password(kind: str) -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    if not container_running():
        out("容器未运行，无法重置密码。")
        return
    default_email = state.get("max_email") if kind == "max" else state.get("admin_email")
    email = ask("账号邮箱/登录名", default_email or (f"{kind}@pylai.local"))
    password = ask("新密码", "", secret=True)
    run(["docker", "exec", "-i", CONTAINER, PYLAIOS_BIN, "user", "reset-password", email,
         "--password-stdin", "--config", "/etc/pylai/pylai.toml"],
        input_text=password + "\n", timeout=120)
    out("密码已重置，该用户全部会话与 token 已吊销。")


def submenu_config() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    out(f"当前公开地址: {state.get('public_url')}")
    out(f"当前端口: {state.get('public_port')} -> 80, 127.0.0.1:{state.get('api_port')} -> 5000")
    entries = [
        ("查看当前配置（脱敏）", action_view_config),
        ("修改公开地址", action_change_url),
        ("修改端口", action_change_ports),
        ("修改 SMTP 邮件配置", action_change_smtp),
        ("修改 Max 账号密码", lambda: action_reset_password("max")),
        ("修改 Admin 账号密码", lambda: action_reset_password("admin")),
    ]
    run_submenu("配置管理", "主菜单", entries)

def export_database() -> None:
    if not container_running():
        out("容器未运行，无法在线导出。")
        return
    ensure_home()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"manage-export-{stamp}"
    run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "backup", "create", name,
         "--config", "/etc/pylai/pylai.toml"], timeout=1200)
    docker("cp", f"{CONTAINER}:/var/lib/pylai/backups/{name}.dump", str(BACKUP_DIR / f"{name}.dump"), timeout=1200)
    out(f"已导出: {BACKUP_DIR / (name + '.dump')}")


def import_database() -> None:
    if not container_exists():
        out("尚未安装。")
        return
    backups = sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        out("没有可用备份。请先执行导出，或将 .dump 放入备份目录。")
        return
    name = choose([(p.name, p.name) for p in backups], "请选择要导入的备份")
    if not name:
        return
    if not confirm_danger(f"将用 {name} 全量覆盖当前数据库，且不可撤销。"):
        out("已取消。")
        return
    if not container_running():
        docker("start", CONTAINER, timeout=120)
        wait_healthy(int(load_state().get("api_port", 5000)))
    docker("cp", str(BACKUP_DIR / name), f"{CONTAINER}:/var/lib/pylai/backups/{name}", timeout=1200)
    run(["docker", "exec", CONTAINER, "supervisorctl", "stop", "backend"], timeout=120)
    try:
        run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "backup", "restore", name,
             "--config", "/etc/pylai/pylai.toml"], timeout=1800)
    finally:
        run(["docker", "exec", CONTAINER, "supervisorctl", "start", "backend"], check=False, timeout=120)
    if wait_healthy(int(load_state().get("api_port", 5000))):
        out("导入完成，服务已恢复。")
    else:
        out("导入命令已完成，但健康检查未通过，请查看日志。")


def action_list_backups() -> None:
    backups = sorted(BACKUP_DIR.glob("*.dump"))
    if not backups:
        out("备份目录为空。")
        return
    for path in backups:
        out(f"{path.name}  {path.stat().st_size} bytes")


def submenu_data() -> None:
    entries = [
        ("导出全部数据（数据库全量快照）", export_database),
        ("导入全部数据（停止后端并全量覆盖）", import_database),
        ("查看主机备份目录", action_list_backups),
    ]
    run_submenu("数据备份与恢复", "主菜单", entries)


def action_key_status() -> None:
    run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "key", "status", "--config", "/etc/pylai/pylai.toml"], timeout=120)


def action_key_rotate() -> None:
    state = load_state()
    mfa_user = ask("用于 MFA 验证的 Admin/Max 账户", state.get("max_email") or "max@pylai.local")
    mfa_code = ask("该账户 TOTP 验证码", "", secret=True)
    if not mfa_code:
        raise ManageError("签名密钥轮换需要 MFA 验证码。")
    run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "key", "rotate",
         "--mfa-user", mfa_user, "--mfa-code", mfa_code,
         "--config", "/etc/pylai/pylai.toml"], timeout=120)


def action_db_status() -> None:
    run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "db", "status", "--config", "/etc/pylai/pylai.toml"], timeout=120)


def action_bootstrap() -> None:
    run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "db", "bootstrap", "--config", "/etc/pylai/pylai.toml"], timeout=120)


def submenu_security() -> None:
    if not container_running():
        out("容器未运行。")
        return
    entries = [
        ("签名密钥状态", action_key_status),
        ("人工轮换签名密钥", action_key_rotate),
        ("数据库迁移状态", action_db_status),
        ("执行 db bootstrap（幂等）", action_bootstrap),
    ]
    run_submenu("安全维护", "主菜单", entries)

def generate_host_nginx() -> None:
    state = load_state()
    port = state.get("public_port", 8080)
    public_url = state.get("public_url", "https://sso.example.com")
    template = f"""# Pylai 主机 Nginx 配置模板
# 安装前请替换证书路径和 server_name。
server {{
    listen 80;
    server_name {public_url.replace('https://', '').replace('http://', '').split('/')[0]};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {public_url.replace('https://', '').replace('http://', '').split('/')[0]};

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 2m;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'" always;

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
    ensure_home()
    HOST_NGINX_FILE.write_text(template, encoding="utf-8")
    HOST_NGINX_FILE.chmod(0o600)
    out(f"模板已生成: {HOST_NGINX_FILE}")
    out("请自行替换证书路径和 server_name，然后安装到 /etc/nginx/conf.d/ 并 reload。")


def action_health() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    port = int(state.get("api_port", 5000))
    if wait_healthy(port, timeout=5):
        out("健康检查通过。")
    else:
        out("健康检查未通过。")


def submenu_network_health() -> None:
    entries = [
        ("健康检查", action_health),
        ("生成主机 Nginx 配置", generate_host_nginx),
    ]
    run_submenu("网络与健康", "主菜单", entries)


def read_container_env() -> dict[str, str]:
    result = docker("inspect", CONTAINER, "--format", "{{range .Config.Env}}{{println .}}{{end}}")
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def read_config_credentials() -> dict[str, str]:
    """从 pylai.toml 解析数据库/Redis 凭据（容器不存在时的回退路径）。"""
    if not CONFIG_FILE.is_file():
        return {}
    text = CONFIG_FILE.read_text(encoding="utf-8")
    creds: dict[str, str] = {}
    match = re.search(r'ConnectionString\s*=\s*"([^"]+)"', text)
    if match:
        for key, pattern in (
            ("db_user", r"(?:Username|User ID)=([^;]+)"),
            ("db_password", r"Password=([^;]+)"),
            ("db_name", r"Database=([^;]+)"),
        ):
            inner = re.search(pattern, match.group(1))
            if inner:
                creds[key] = inner.group(1)
    section = re.search(r"\[Redis\]\s*\n(.*?)(?=\n\[|\Z)", text, re.S)
    if section:
        inner = re.search(r'^Password\s*=\s*"([^"]*)"', section.group(1), re.M)
        if inner:
            creds["redis_password"] = inner.group(1)
    return creds


def preflight_config(image: str) -> None:
    """用新镜像对现有 pylai.toml 做四阶段配置校验，提前暴露 E002 等不兼容项。"""
    if not CONFIG_FILE.is_file():
        raise ManageError(f"配置文件不存在: {CONFIG_FILE}")
    out("==> 校验现有配置与新版本兼容性（config validate）...")
    result = docker(
        "run", "--rm", "--entrypoint", PYLAIOS_BIN,
        "-v", f"{CONFIG_DIR}:/etc/pylai",
        image, "config", "validate", "--config", "/etc/pylai/pylai.toml",
        check=False, timeout=120,
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
        "也可对照镜像模板 `docker run --rm --entrypoint cat {image} /opt/pylai/pylai.example.toml` 逐项核对。"
    )


def update() -> None:
    state = load_state()
    if not state:
        out("尚未安装，请先执行安装。")
        return
    tars = discover_tars()
    if not tars:
        out("当前目录未找到新的 Pylai-*.tar。")
        return
    name = choose([(p.name, p.name) for p in tars], "请选择新版本安装包")
    if not name:
        return
    tar_path = Path.cwd() / name
    version, arch = parse_tar(tar_path) or (state.get("version", "0.0.1"), state.get("architecture", "AMD64"))
    old_image = state.get("image", "pylaios:unknown")
    creds = read_config_credentials()
    env = read_container_env() if container_exists() else {}
    if not container_exists():
        out("未找到容器，将从 pylai.toml 读取凭据执行更新。")
    answers = {
        "public_url": state.get("public_url", "http://localhost"),
        "public_port": int(state.get("public_port", 8080)),
        "api_port": int(state.get("api_port", 5000)),
        "db_user": env.get("PYLAI_DB_USER") or creds.get("db_user") or "pylai",
        "db_name": env.get("PYLAI_DB_NAME") or creds.get("db_name") or "pylai",
        "db_password": env.get("PYLAI_DB_PASSWORD") or creds.get("db_password") or "",
        "redis_password": env.get("PYLAI_REDIS_PASSWORD") or creds.get("redis_password") or "",
    }
    if not answers["db_password"] or not answers["redis_password"]:
        raise ManageError("无法读取数据库/Redis 凭据（容器环境变量与 pylai.toml 均缺失）。")

    out("更新前建议先导出数据库。")
    if ask_yes_no("是否现在导出数据库备份？", True) and container_running():
        export_database()

    image = load_image_tar(tar_path)
    preflight_config(image)

    if container_exists():
        docker("stop", "-t", "30", CONTAINER, timeout=120)
    else:
        out("容器不存在，跳过停止步骤。")
    try:
        start_container(image, answers)
        state["version"] = version
        state["architecture"] = arch
        state["image"] = image
        save_state(state)
        out("更新完成。")
    except Exception:
        out("更新失败，尝试回滚旧镜像。")
        try:
            start_container(old_image, answers)
        except Exception:
            out("旧镜像以只读容器启动失败，尝试去掉 --read-only 重试...")
            try:
                start_container(old_image, answers, read_only=False)
                out("回滚完成（旧镜像以非只读容器运行，容器安全性已降低）。")
            except Exception:
                out("回滚失败，请检查 docker logs pylai。")
        save_state(state)
        raise


def uninstall() -> None:
    state = load_state()
    if not state and not container_exists():
        out("没有已安装实例。")
        return
    if not confirm_danger("卸载会停止并删除容器，可能删除全部数据。"):
        out("已取消。")
        return
    if container_exists():
        docker("stop", "-t", "30", CONTAINER, check=False, timeout=120)
        docker("rm", "-f", CONTAINER, check=False)
    image = state.get("image")
    if image:
        docker("rmi", image, check=False)
    if confirm_danger("同时删除 ~/.pylai 全部数据目录（建议保留备份）？"):
        shutil.rmtree(HOME, ignore_errors=True)
        out("已删除全部数据目录。")
    STATE_FILE.unlink(missing_ok=True) if not HOME.exists() else None
    out("卸载完成。")


def submenu_install_update() -> None:
    entries = [
        ("安装", menu_install),
        ("更新", update),
        ("卸载", uninstall),
    ]
    run_submenu("安装 / 更新 / 卸载", "主菜单", entries)


def main_menu() -> None:
    while True:
        out("\n### ManagePylai ###")
        out("[0/quit/exit/Ctrl+C] 退出")
        out("[1] 安装 / 更新 / 卸载")
        out("[2] 运行控制")
        out("[3] 配置管理")
        out("[4] 数据备份与恢复")
        out("[5] 安全维护（签名密钥 / 迁移 / bootstrap）")
        out("[6] 网络与健康")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("\n再见。")
            return
        if choice in ("0", "quit", "exit"):
            return
        actions = {
            "1": submenu_install_update,
            "2": submenu_run,
            "3": submenu_config,
            "4": submenu_data,
            "5": submenu_security,
            "6": submenu_network_health,
        }
        action = actions.get(choice)
        if action is None:
            out("选择无效。")
            continue
        try:
            action()
        except ManageError as exc:
            out(f"错误: {exc}")

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        out("\n再见。")

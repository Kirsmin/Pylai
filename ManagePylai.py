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
    for index, (label, _) in enumerate(options, 1):
        out(f"  [{index}] {label}")
    raw = ask(prompt, "1")
    try:
        return options[int(raw) - 1][1]
    except (ValueError, IndexError):
        out("选择无效。")
        return None


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
    result = docker("logs", "--tail", str(tail), CONTAINER, check=False)
    output = (result.stdout + result.stderr).strip()
    if output:
        out(output)
    else:
        out("（容器暂无日志输出）")


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
    text = replace_one(text, 'Directory = "backups"', 'Directory = "/var/lib/pylai/backups"')
    text = replace_one(text, 'ForwardedHeadersEnabled = false', "ForwardedHeadersEnabled = true")
    text = replace_one(text, 'TrustedProxies = []', f'TrustedProxies = {toml_string_list(answers["trusted_proxies"])}')
    text = replace_one(text, 'TrustedNetworks = []', f'TrustedNetworks = {toml_string_list(answers["trusted_networks"])}')
    text = replace_one(text, 'AllowedOrigins = ["http://localhost:5173"]',
                       f'AllowedOrigins = {toml_string_list(answers["cors_origins"])}')

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
        text = replace_one(text, 'Host = ""\nPort = 587', f'Host = "{answers["smtp_host"]}"\nPort = {answers["smtp_port"]}')
        text = replace_one(text, "UseSsl = true", f"UseSsl = {str(answers['smtp_ssl']).lower()}")
        text = replace_one(text, 'Username = ""', f'Username = "{answers["smtp_user"]}"', 1)
        smtp_marker = "[Email.Smtp]"
        smtp_start = text.index(smtp_marker)
        smtp_end = text.find("\n\n", smtp_start)
        smtp_end = len(text) if smtp_end < 0 else smtp_end
        smtp_block = text[smtp_start:smtp_end].replace('Password = ""', f'Password = "{answers["smtp_password"]}"', 1)
        text = text[:smtp_start] + smtp_block + text[smtp_end:]

    ensure_home()
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

    out("\n-- 初始账号 --")
    max_email = ask("Max 账号邮箱/登录名", "max@pylai.local")
    max_password = secrets.token_urlsafe(12)
    if ask_yes_no("创建初始 Admin 账号？", True):
        admin_email = ask("Admin 账号邮箱/登录名", "admin@pylai.local")
        admin_password = secrets.token_urlsafe(12)
    else:
        admin_email, admin_password = "", ""
    if ask_yes_no("创建初始 Normal 测试账号？", False):
        user_email = ask("Normal 账号邮箱/登录名", "user@pylai.local")
        user_password = secrets.token_urlsafe(12)
    else:
        user_email, user_password = "", ""

    out("\n-- 邮件 --")
    smtp_enabled = ask_yes_no("配置 SMTP 邮件发送？", False)
    if smtp_enabled:
        smtp_host = ask("SMTP 服务器")
        smtp_port = ask_int("SMTP 端口", 587)
        smtp_ssl = ask_yes_no("使用 STARTTLS？", True)
        smtp_user = ask("SMTP 用户名（无认证可留空）", "", allow_blank=True)
        smtp_password = ask("SMTP 密码（无认证可留空）", "", secret=True, allow_blank=True)
        smtp_from = ask("发件人邮箱")
    else:
        smtp_host, smtp_port, smtp_ssl, smtp_user, smtp_password, smtp_from = "", 587, True, "", "", ""

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
    if ask_yes_no("自动生成加密证书（推荐，避免重启后 token 失效）？", True):
        if shutil.which("openssl") is None:
            out("未找到 openssl，将使用临时加密密钥（重启后已签发 token 会失效）。")
        else:
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
    else:
        encryption_pfx = ask("加密 PFX 文件路径（留空则使用临时密钥）", "", allow_blank=True).strip()
        if encryption_pfx and Path(encryption_pfx).is_file():
            encryption_pfx_password = ask("加密 PFX 密码（无密码可留空）", "", secret=True, allow_blank=True)
            destination = CERT_DIR / "encryption.pfx"
            shutil.copy2(encryption_pfx, destination)
            destination.chmod(0o600)
            encryption_pfx = f"{CONTAINER_CERT_DIR}/encryption.pfx"
        else:
            encryption_pfx = ""
    trusted_proxies = ask("可信代理 IP（逗号分隔，主机 Nginx 与本机）", "127.0.0.1")
    trusted_networks = ask("可信代理 CIDR（逗号分隔）", "172.16.0.0/12")

    origin = public_url.rstrip("/")
    cors_origins = [origin]
    extra_cors = ask("额外 CORS Origin（逗号分隔，没有留空）", "", allow_blank=True).strip()
    if extra_cors:
        cors_origins.extend(x.strip() for x in extra_cors.split(",") if x.strip())

    return {
        "public_url": public_url,
        "public_port": public_port,
        "api_port": api_port,
        "db_user": db_user,
        "db_name": db_name,
        "db_password": db_password,
        "redis_password": redis_password,
        "max_email": max_email,
        "max_password": max_password,
        "admin_email": admin_email,
        "admin_password": admin_password,
        "user_email": user_email,
        "user_password": user_password,
        "smtp_enabled": smtp_enabled,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_ssl": smtp_ssl,
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


def start_container(image: str, answers: dict) -> None:
    if container_exists():
        docker("rm", "-f", CONTAINER)
    ensure_home()
    cmd = [
        "docker", "run", "-d", "--name", CONTAINER,
        "--restart", "unless-stopped",
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
    out("提示：建议使用主机 Nginx 反代，菜单 [6] 可生成配置模板。")


def menu_run() -> None:
    if not container_exists():
        out("尚未安装或容器不存在。")
        return
    running = container_running()
    out(f"当前状态: {'运行中' if running else '已停止'}")
    options = [
        ("启动", "start"),
        ("停止", "stop"),
        ("重启", "restart"),
        ("状态", "status"),
        ("日志", "logs"),
    ]
    action = choose(options)
    if action == "start":
        docker("start", CONTAINER, timeout=60)
        state = load_state()
        if not wait_healthy(int(state.get("api_port", 5000))):
            out("容器已启动，但健康检查尚未通过。")
        else:
            out("启动完成。")
    elif action == "stop":
        docker("stop", "-t", "30", CONTAINER, timeout=120)
        out("已停止。")
    elif action == "restart":
        docker("restart", CONTAINER, timeout=120)
        out("已重启。")
    elif action == "status":
        result = docker("ps", "-a", "--filter", f"name={CONTAINER}", "--format", "{{.Names}} {{.Status}}", check=False)
        out(result.stdout.strip() or "未找到容器")
    elif action == "logs":
        result = docker("logs", "--tail", "100", CONTAINER, check=False)
        out(result.stdout + result.stderr)


def menu_config() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    out(f"当前公开地址: {state.get('public_url')}")
    out(f"当前端口: {state.get('public_port')} -> 80, 127.0.0.1:{state.get('api_port')} -> 5000")
    options = [
        ("查看当前配置（脱敏）", "view"),
        ("修改公开地址", "url"),
        ("修改端口", "ports"),
        ("修改 Max 账号密码", "max-password"),
        ("修改 Admin 账号密码", "admin-password"),
    ]
    action = choose(options)
    if action == "view":
        out(CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.is_file() else "配置文件不存在")
    elif action in ("url", "ports"):
        if CONFIG_FILE.is_file():
            text = CONFIG_FILE.read_text(encoding="utf-8")
            if action == "url":
                new_url = ask("新公开地址", state.get("public_url"))
                text = replace_one(text, f'Url = "{state["public_url"]}"', f'Url = "{new_url}"')
                state["public_url"] = new_url
            else:
                new_public = ask_int("新公开端口", int(state.get("public_port", 8080)))
                new_api = ask_int("新本机 API 端口", int(state.get("api_port", 5000)))
                state["public_port"] = new_public
                state["api_port"] = new_api
            CONFIG_FILE.write_text(text, encoding="utf-8")
            CONFIG_FILE.chmod(0o600)
            save_state(state)
            out("配置已修改，需要重启容器生效。")
    elif action in ("max-password", "admin-password"):
        email = ask("账号邮箱/登录名", state.get("max_email") or "max@pylai.local")
        password = ask("新密码", "", secret=True)
        run(["docker", "exec", "-i", CONTAINER, PYLAIOS_BIN, "user", "reset-password", email,
             "--password-stdin", "--config", "/etc/pylai/pylai.toml"],
            input_text=password + "\n", timeout=120)
        out("密码已重置，该用户全部会话与 token 已吊销。")


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


def menu_data() -> None:
    options = [
        ("导出全部数据（数据库全量快照）", "export"),
        ("导入全部数据（停止后端并全量覆盖）", "import"),
        ("查看主机备份目录", "list"),
    ]
    action = choose(options)
    if action == "export":
        export_database()
    elif action == "import":
        import_database()
    elif action == "list":
        for path in sorted(BACKUP_DIR.glob("*.dump")):
            out(f"{path.name}  {path.stat().st_size} bytes")


def menu_security() -> None:
    if not container_running():
        out("容器未运行。")
        return
    options = [
        ("签名密钥状态", "key-status"),
        ("人工轮换签名密钥", "key-rotate"),
        ("数据库迁移状态", "db-status"),
        ("执行 db bootstrap（幂等）", "bootstrap"),
    ]
    action = choose(options)
    if action == "key-status":
        run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "key", "status", "--config", "/etc/pylai/pylai.toml"], timeout=120)
    elif action == "key-rotate":
        run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "key", "rotate", "--config", "/etc/pylai/pylai.toml"], timeout=120)
    elif action == "db-status":
        run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "db", "status", "--config", "/etc/pylai/pylai.toml"], timeout=120)
    elif action == "bootstrap":
        run(["docker", "exec", CONTAINER, PYLAIOS_BIN, "db", "bootstrap", "--config", "/etc/pylai/pylai.toml"], timeout=120)


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


def menu_health() -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    port = int(state.get("api_port", 5000))
    if wait_healthy(port, timeout=5):
        out("健康检查通过。")
    else:
        out("健康检查未通过。")


def read_container_env() -> dict[str, str]:
    result = docker("inspect", CONTAINER, "--format", "{{range .Config.Env}}{{println .}}{{end}}")
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def update() -> None:
    state = load_state()
    if not state:
        out("尚未安装，请先执行安装。")
        return
    if not container_exists():
        out("未找到容器，请先安装或启动。")
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
    env = read_container_env()
    answers = {
        "public_url": state.get("public_url", "http://localhost"),
        "public_port": int(state.get("public_port", 8080)),
        "api_port": int(state.get("api_port", 5000)),
        "db_user": env.get("PYLAI_DB_USER", "pylai"),
        "db_name": env.get("PYLAI_DB_NAME", "pylai"),
        "db_password": env.get("PYLAI_DB_PASSWORD", ""),
        "redis_password": env.get("PYLAI_REDIS_PASSWORD", ""),
    }
    if not answers["db_password"] or not answers["redis_password"]:
        raise ManageError("无法读取现有容器环境变量，请使用安装或手动迁移。")

    out("更新前建议先导出数据库。")
    if ask_yes_no("是否现在导出数据库备份？", True) and container_running():
        export_database()

    image = load_image_tar(tar_path)
    docker("stop", "-t", "30", CONTAINER, timeout=120)
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


def main_menu() -> None:
    while True:
        out("\n### ManagePylai ###")
        out("[0/quit/exit/Ctrl+C] 退出")
        out("[1] 安装 / 更新 / 卸载")
        out("[2] 启动 / 停止 / 重启 / 状态 / 日志")
        out("[3] 配置管理")
        out("[4] 数据备份与恢复")
        out("[5] 安全维护（签名密钥 / 迁移 / bootstrap）")
        out("[6] 生成主机 Nginx 配置")
        out("[7] 健康检查")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("\n再见。")
            return
        if choice in ("0", "quit", "exit"):
            return
        if choice == "1":
            options = [("安装", "install"), ("更新", "update"), ("卸载", "uninstall")]
            action = choose(options)
            try:
                if action == "install":
                    menu_install()
                elif action == "update":
                    update()
                elif action == "uninstall":
                    uninstall()
            except ManageError as exc:
                out(f"错误: {exc}")
        elif choice == "2":
            menu_run()
        elif choice == "3":
            menu_config()
        elif choice == "4":
            menu_data()
        elif choice == "5":
            menu_security()
        elif choice == "6":
            generate_host_nginx()
        elif choice == "7":
            menu_health()
        else:
            out("选择无效。")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        out("\n再见。")

#!/usr/bin/env python3
"""ManagePylai - Pylai Docker 部署管理工具。

仅使用 Python 标准库和 docker CLI。Release 页面同时提供
Pylai-<version>-Linux-<arch>.tar 与本脚本，下载后放在同一目录运行即可。
"""
from __future__ import annotations

import json
import os
import platform as host_platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
import argparse
from string import Template

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

__version__ = "1.0.0"
MANAGER_CONFIG_FILE = HOME / "ManagerConfig.toml"


class ManagerConfig:
    """ManagePylai 自身配置（~/.pylai/ManagerConfig.toml）读写。

    使用 tomllib 读取；因标准库无 TOML 写入，save() 基于硬编码模板
    拼接，足以覆盖 ManagerConfig 的扁平结构。
    """

    DEFAULT_PATH = HOME / "ManagerConfig.toml"

    _DEFAULT_TOML = """\
[Manager]
Version = "{version}"
mirror = "{mirror}"

[Manager.State]
LastCheck = "{last_check}"
{skip_version_line}

[Compose]
ProjectName = "{project_name}"

[Security]
AutoBackupBeforeUpdate = {auto_backup}
BackupRetentionDays = {retention}

[Logging]
Level = "{level}"
"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.DEFAULT_PATH
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            try:
                self._data = tomllib.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                self._data = {}

    def save(self) -> None:
        ensure_home()
        mgr = self._data.get("Manager", {})
        state = self._data.get("Manager.State", {})
        sec = self._data.get("Security", {})
        log = self._data.get("Logging", {})

        skip = state.get("SkipVersion")
        skip_version_line = f"SkipVersion = {json.dumps(skip)}" if skip else ""

        text = self._DEFAULT_TOML.format(
            version=mgr.get("Version", __version__),
            mirror=mgr.get("mirror", "Github"),
            last_check=state.get("LastCheck", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            skip_version_line=skip_version_line,
            project_name=self._data.get("Compose", {}).get("ProjectName", "pylai"),
            auto_backup="true" if sec.get("AutoBackupBeforeUpdate", True) else "false",
            retention=sec.get("BackupRetentionDays", 7),
            level=log.get("Level", "info"),
        )

        # 追加自定义 mirror
        custom = self._data.get("Manager.Custom", {})
        if custom:
            text += "\n[Manager.Custom]\n"
            for k, v in custom.items():
                text += f'{k} = {json.dumps(v)}\n'

        # 追加服务镜像覆盖
        services = self._data.get("Compose.Services", {})
        if services:
            text += "\n[Compose.Services]\n"
            for k, v in services.items():
                text += f'{k} = {json.dumps(v)}\n'

        self.path.write_text(text, encoding="utf-8")
        self.path.chmod(0o600)

    def get(self, *keys: str, default=None):
        d = self._data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, *keys: str, value) -> None:
        d = self._data
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    @property
    def mirror(self) -> str:
        return self.get("Manager", "mirror", default="Github")

    @property
    def version(self) -> str:
        return self.get("Manager", "Version", default=__version__)

    @property
    def logging_level(self) -> str:
        return self.get("Logging", "Level", default="info")

    @property
    def project_name(self) -> str:
        return self.get("Compose", "ProjectName", default="pylai")

    @property
    def auto_backup(self) -> bool:
        return self.get("Security", "AutoBackupBeforeUpdate", default=True)

    # ---------- Phase 2 新增 ----------

    @property
    def skip_version(self) -> str | None:
        """用户选择跳过的 ManagePylai.py 版本。"""
        return self.get("Manager.State", "SkipVersion", default=None)

    def set_skip_version(self, version: str | None) -> None:
        self.set("Manager.State", "SkipVersion", version)
        self.save()

    @property
    def custom_mirror_base(self) -> str | None:
        """自定义镜像源 base_url（仅当 mirror == 'Custom' 时生效）。"""
        return self.get("Manager.Custom", "base_url", default=None)


class State:
    """Pylai 安装状态（~/.pylai/state.json）—— 兼容层。

    将原有的 load_state / save_state 过程封装为类，后续可扩展
    版本迁移、schema 校验等逻辑。
    """

    FILE = HOME / "state.json"

    def __init__(self) -> None:
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.FILE.is_file():
            try:
                self._data = json.loads(self.FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}

    def save(self) -> None:
        ensure_home()
        self.FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.FILE.chmod(0o600)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def clear(self) -> None:
        self._data = {}

    @property
    def installed(self) -> bool:
        return bool(self._data)

    @property
    def version(self) -> str:
        return self._data.get("version", "0.0.1")

    @property
    def image(self) -> str:
        return self._data.get("image", "pylaios:unknown")

    @property
    def public_url(self) -> str:
        return self._data.get("public_url", "http://localhost")

    @property
    def public_port(self) -> int:
        return int(self._data.get("public_port", 8080))

    @property
    def api_port(self) -> int:
        return int(self._data.get("api_port", 5000))


class PylaiConfig:
    """pylai.toml 配置管理：生成（string.Template）、读写、校验、脱敏。

    生成策略：
      1. 优先从镜像读取 pylai.template.toml（$var 占位符），用
         string.Template.safe_substitute() 生成。
      2. 若镜像未提供新模板，回退到 pylai.example.toml + 旧字符串替换。
    """

    FILE = CONFIG_DIR / "pylai.toml"
    TEMPLATE_NAME = "pylai.template.toml"
    EXAMPLE_NAME = "pylai.example.toml"

    def __init__(self) -> None:
        self._text: str = ""
        if self.FILE.is_file():
            self._text = self.FILE.read_text(encoding="utf-8")

    # ---------- 生成 ----------

    @classmethod
    def generate_from_template(cls, image: str, answers: dict) -> "PylaiConfig":
        """从镜像模板生成新配置；优先 string.Template，回退旧替换方式。"""
        template_text = cls._read_from_image(image, cls.TEMPLATE_NAME)
        if template_text:
            return cls._generate_via_template(image, template_text, answers)

        out("提示：镜像未提供 pylai.template.toml，使用兼容模式生成配置。")
        example_text = cls._read_from_image(image, cls.EXAMPLE_NAME)
        if not example_text:
            raise ManageError("无法从镜像读取配置模板")
        return cls._generate_via_replace(image, example_text, answers)

    @classmethod
    def _read_from_image(cls, image: str, filename: str) -> str | None:
        result = docker(
            "run", "--rm", "--entrypoint", "cat", image,
            f"/opt/pylai/{filename}", check=False, timeout=120,
        )
        return result.stdout if result.returncode == 0 else None

    @classmethod
    def _generate_via_template(cls, image: str, template_text: str, answers: dict) -> "PylaiConfig":
        """string.Template 方式生成配置。"""
        origin = answers["public_url"].rstrip("/")
        external_host = urlparse(answers["public_url"]).hostname or "localhost"
        allowed_hosts = [external_host]
        if external_host not in ("localhost", "127.0.0.1", "::1"):
            allowed_hosts.extend(("localhost", "127.0.0.1"))

        cs = (
            f'Host=127.0.0.1;Port=5432;'
            f'Database={answers["db_name"]};'
            f'Username={answers["db_user"]};'
            f'Password={answers["db_password"]}'
        )

        is_https = origin.startswith("https://")

        subs: dict[str, str] = {
            "server_url": "http://0.0.0.0:5000",
            "frontend_url": answers["public_url"],
            "db_connection_string": cs,
            "redis_password": answers["redis_password"],
            "server_pepper": answers["invite_pepper"],
            "backup_dir": "/var/lib/pylai/backups",
            "trusted_proxies": toml_string_list(answers["trusted_proxies"]),
            "trusted_networks": toml_string_list(answers["trusted_networks"]),
            "signing_key_file": "/etc/pylai/certs/signing-kek",
            "allowed_origins": toml_string_list(answers["cors_origins"]),
            "issuer": origin,
            "allowed_hosts": toml_string_list(allowed_hosts),
            "relying_party_id": external_host,
            "mfa_origins": toml_string_list(answers["cors_origins"]),
            "require_https": "true" if is_https else "false",
            "secure_policy": "Always" if is_https else "SameAsRequest",
            "mfa_require_for_admin": "true" if answers.get("mfa_for_admin", False) else "false",
            "mfa_require_webauthn_for_max": "true" if answers.get("mfa_webauthn_for_max", False) else "false",
        }

        # 种子用户
        seed_map = [
            ("seed_admin", "admin_email", "admin_password", "Administrator"),
            ("seed_user", "user_email", "user_password", "Test User"),
            ("seed_max", "max_email", "max_password", "Max User"),
        ]
        for prefix, email_key, pwd_key, display in seed_map:
            subs[f"{prefix}_email"] = answers[email_key]
            subs[f"{prefix}_password"] = answers[pwd_key]
            subs[f"{prefix}_display_name"] = display

        # SMTP
        if answers.get("smtp_enabled"):
            subs["smtp_from"] = answers["smtp_from"]
            subs["smtp_host"] = answers["smtp_host"]
            subs["smtp_port"] = str(answers["smtp_port"])
            subs["smtp_security"] = answers["smtp_security"]
            subs["smtp_user"] = answers["smtp_user"]
            subs["smtp_password"] = answers["smtp_password"]

        # 证书
        if answers.get("signing_pfx"):
            subs["signing_pfx_path"] = answers["signing_pfx"]
            subs["signing_pfx_password"] = answers["signing_pfx_password"]
        if answers.get("encryption_pfx"):
            subs["encryption_pfx_path"] = answers["encryption_pfx"]
            subs["encryption_pfx_password"] = answers["encryption_pfx_password"]

        template = Template(template_text)
        text = template.safe_substitute(subs)

        # 检查未替换的占位符（排除 TOML 中可能的 $ 字面量）
        unmatched = re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', text)
        placeholders = {v for v in unmatched if v[0].islower() or v.startswith("seed_")}
        if placeholders:
            out(f"警告：模板中有未替换的变量: {placeholders}")

        # Fail Closed
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"生成的 pylai.toml 不是合法 TOML: {exc}") from exc

        instance = cls()
        instance._text = text
        instance._write()
        return instance

    @classmethod
    def _generate_via_replace(cls, image: str, text: str, answers: dict) -> "PylaiConfig":
        """回退：复用现有 generate_config 逻辑（旧字符串替换方式）。"""
        # 旧 generate_config 会自己 read_template，这里直接调用
        generate_config(image, answers)
        return cls()

    # ---------- 读写 ----------

    def _write(self) -> None:
        ensure_home()
        self.FILE.write_text(self._text, encoding="utf-8")
        self.FILE.chmod(0o600)

    def read(self) -> str:
        return self._text

    def reload(self) -> None:
        if self.FILE.is_file():
            self._text = self.FILE.read_text(encoding="utf-8")

    def get_value(self, section: str, key: str, default=None):
        """从 TOML 解析获取指定段键值。"""
        try:
            data = tomllib.loads(self._text)
            sec = data.get(section, {})
            return sec.get(key, default) if isinstance(sec, dict) else default
        except tomllib.TOMLDecodeError:
            return default

    def set_block_value(self, marker: str, key: str, value: str) -> None:
        """替换 TOML 段内指定键值；键不存在时插到段首行之后。"""
        self._text = _replace_toml_block_value(self._text, marker, key, value)
        self._write()

    def mask(self) -> str:
        """脱敏显示。"""
        return mask_config_text(self._text)

    def validate(self) -> None:
        """Fail Closed：校验整体为合法 TOML。"""
        try:
            tomllib.loads(self._text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"配置不是合法 TOML: {exc}") from exc


class DockerCompose:
    """Docker / docker compose 操作封装。

    当前为单容器兼容层；所有方法命名与行为预留多服务
    Compose 接口（如 logs(service)、exec(service) 等）。
    """

    CONTAINER = "pylai"
    PROJECT_NAME = "pylai"

    def __init__(self, container: str | None = None, project: str | None = None) -> None:
        self.container = container or self.CONTAINER
        self.project = project or self.PROJECT_NAME

    # --- 基础 ---

    def ensure_docker(self) -> None:
        if shutil.which("docker") is None:
            raise ManageError("未找到 docker，请先安装 Docker。")
        result = run(["docker", "info"], check=False)
        if result.returncode != 0:
            raise ManageError("Docker daemon 不可用，请启动 Docker 服务。")

    def _docker(self, *args: str, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
        return run(["docker", *args], check=check, timeout=timeout)

    def _compose(self, *args: str, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
        return run(["docker", "compose", "-p", self.project, *args], check=check, timeout=timeout)

    # --- 容器状态 ---

    def container_exists(self) -> bool:
        result = self._docker("inspect", self.container, check=False)
        return result.returncode == 0

    def container_status(self) -> str | None:
        result = self._docker("inspect", "-f", "{{.State.Status}}", self.container, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def container_running(self) -> bool:
        return self.container_status() == "running"

    def container_restart_count(self) -> int | None:
        result = self._docker("inspect", "-f", "{{.RestartCount}}", self.container, check=False)
        if result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    # --- 生命周期 ---

    def start(self, image: str, answers: dict, read_only: bool = True) -> None:
        """启动单容器（兼容层，直接复用现有 start_container 逻辑）。"""
        if self.container_exists():
            self._docker("rm", "-f", self.container)
        ensure_home()
        cmd = [
            "docker", "run", "-d", "--name", self.container,
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
            "-v", "pylai_data:/var/lib/pylai",
            "-v", "pylai_pgdata:/var/lib/postgresql",
            "-e", "PYLAI_ROLE=server",
            "-e", f"PYLAI_UI_URL={answers['public_url']}",
            "-e", f"PYLAI_DB_USER={answers['db_user']}",
            "-e", f"PYLAI_DB_PASSWORD={answers['db_password']}",
            "-e", f"PYLAI_DB_NAME={answers['db_name']}",
            "-e", f"PYLAI_REDIS_PASSWORD={answers['redis_password']}",
            image,
        ]
        run(cmd, timeout=120)

    def stop(self, timeout_sec: int = 30) -> None:
        self._docker("stop", "-t", str(timeout_sec), self.container, timeout=120)

    def restart(self, timeout_sec: int = 30) -> None:
        self._docker("restart", "-t", str(timeout_sec), self.container, timeout=120)

    def rm(self, force: bool = True) -> None:
        args = ["rm", "-f"] if force else ["rm"]
        self._docker(*args, self.container, check=False)

    # --- 日志 ---

    def logs_text(self, tail: int | str = 200, follow: bool = False) -> str:
        cmd = ["docker", "logs", "--timestamps", "--tail", str(tail)]
        if follow:
            cmd.append("-f")
        cmd.append(self.container)
        result = run(cmd, check=False)
        return result.stdout + result.stderr

    def view_logs(self, tail: int | str = 200, follow: bool = False) -> None:
        """用 less 查看容器日志；follow=True 时使用 less +F 持续跟踪。"""
        if not self.container_exists():
            out("尚未安装或容器不存在。")
            return
        cmd = ["docker", "logs", "--timestamps", "--tail", str(tail)]
        if follow:
            cmd.append("-f")
        cmd.append(self.container)
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

    # --- 执行 ---

    def exec(self, *args: str, check: bool = True, timeout: int | None = None,
             input_text: str | None = None) -> subprocess.CompletedProcess:
        return self._docker("exec", *args, self.container, check=check, timeout=timeout, input_text=input_text)

    def exec_pylaios(self, *args: str, check: bool = True, timeout: int | None = None,
                     input_text: str | None = None) -> subprocess.CompletedProcess:
        return self.exec("-i", PYLAIOS_BIN, *args, check=check, timeout=timeout, input_text=input_text)

    # --- 镜像 ---

    def load_image_tar(self, tar_path: Path) -> str:
        out(f"==> 加载镜像 {tar_path.name} ...")
        result = self._docker("load", "-i", str(tar_path), timeout=1200)
        version, arch = parse_tar(tar_path) or ("0.0.1", host_arch())
        expected = f"pylaios:{version}-{arch}"
        lines = result.stdout.splitlines() + result.stderr.splitlines()
        for line in lines:
            if "Loaded image" in line:
                name = line.split(":", 1)[1].strip() if ":" in line else ""
                if name:
                    return name
        inspect = self._docker("image", "inspect", expected, check=False)
        if inspect.returncode == 0:
            return expected
        raise ManageError(f"无法确定镜像名称，请手动确认: {result.stdout}\n{result.stderr}")

    def read_env(self) -> dict[str, str]:
        result = self._docker(
            "inspect", self.container, "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        )
        env: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                env[key] = value
        return env

    # --- 健康检查 ---

    def wait_healthy(self, api_port: int, timeout: int = 180) -> bool:
        url = f"http://127.0.0.1:{api_port}/health/ready"
        restart_count = self.container_restart_count()
        if restart_count is None:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.container_status() != "running":
                return False
            current = self.container_restart_count()
            if current is None or current > restart_count:
                return False
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if resp.status == 200:
                        return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(3)
        return False


class ReleaseClient:
    """GitHub Release / 镜像源 客户端。

    支持三种模式：
      1. Github  — 直接调用 GitHub API
      2. ghproxy — 通过 ghproxy 代理访问 GitHub API
      3. Custom  — 用户自定义 CDN，直接读取 {base_url}/releases/latest.json
    """

    REPO = "Kirsmin/Pylai"
    USER_AGENT = f"ManagePylai/{__version__}"

    # 预定义镜像的 API 根（仅用于 GitHub 原生 API 调用）
    PREDEFINED_API: dict[str, str] = {
        "Github": "https://api.github.com",
        "ghproxy": "https://ghproxy.com/https://api.github.com",
    }

    # 预定义镜像的 Raw 下载根
    PREDEFINED_RAW: dict[str, str] = {
        "Github": "https://github.com",
        "ghproxy": "https://ghproxy.com/https://github.com",
    }

    def __init__(self, manager_cfg: ManagerConfig) -> None:
        self.cfg = manager_cfg
        self.mirror = manager_cfg.mirror
        self.custom_base = manager_cfg.custom_mirror_base
        self._is_custom = self.mirror == "Custom" and bool(self.custom_base)

    def _api_url(self, path: str) -> str:
        if self._is_custom:
            raise ManageError("自定义镜像源不支持 GitHub API 调用")
        base = self.PREDEFINED_API.get(self.mirror, self.PREDEFINED_API["Github"])
        return f"{base}/repos/{self.REPO}/{path}"

    def _release_url(self, version: str, filename: str) -> str:
        if self._is_custom:
            base = self.custom_base.rstrip("/")
            return f"{base}/releases/v{version}/{filename}"
        base = self.PREDEFINED_RAW.get(self.mirror, self.PREDEFINED_RAW["Github"])
        return f"{base}/{self.REPO}/releases/download/v{version}/{filename}"

    def _latest_url(self) -> str:
        if self._is_custom:
            return f"{self.custom_base.rstrip('/')}/releases/latest.json"
        return self._api_url("releases/latest")

    def check_latest(self) -> tuple[str, str, dict] | None:
        """返回 (version, tag_or_ref, release_info_dict) 或 None。

        release_info_dict 在 Custom 模式下就是 latest.json 本身；
        在 GitHub 模式下是 releases/latest API 的完整 JSON。
        """
        try:
            headers: dict[str, str] = {
                "User-Agent": self.USER_AGENT,
            }
            if not self._is_custom:
                headers["Accept"] = "application/vnd.github+json"
                headers["X-GitHub-Api-Version"] = "2022-11-28"

            req = urllib.request.Request(self._latest_url(), headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if self._is_custom:
                version = str(data.get("version", ""))
                return version, f"v{version}", data
            else:
                tag = data.get("tag_name", "")
                version = tag.lstrip("v")
                return version, tag, data
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def fetch_release_json(self, version: str) -> dict | None:
        """获取 release.json 用于 dbSchemaVersion 兼容性校验。

        Custom 镜像源同样支持 {base_url}/releases/v{X.Y.Z}/release.json。
        """
        if self._is_custom:
            url = f"{self.custom_base.rstrip('/')}/releases/v{version}/release.json"
        else:
            url = self._release_url(version, "release.json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def download(self, version: str, filename: str, dest: Path,
                 sha256_expected: str | None = None) -> None:
        """下载 release 文件；可选 SHA256 校验。"""
        url = self._release_url(version, filename)
        out(f"==> 下载 {filename} ...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
        except (OSError, urllib.error.URLError) as exc:
            raise ManageError(f"下载失败: {exc}") from exc

        if sha256_expected:
            import hashlib
            actual = hashlib.sha256(data).hexdigest()
            if actual != sha256_expected:
                raise ManageError(
                    f"SHA256 校验失败: 期望 {sha256_expected}, 实际 {actual}"
                )

        dest.write_bytes(data)


class SelfUpdater:
    """ManagePylai.py 自更新逻辑。

    流程：
      1. 读取 ManagerConfig 中的 mirror / skip_version
      2. 调用 ReleaseClient 获取 latest（含 release_info）
      3. 版本比较 + 跳过版本过滤
      4. dbSchemaVersion 兼容性校验（需要 State 中的当前 Pylai 版本）
      5. 下载 ManagePylai.py.new + .sha256
      6. SHA256 校验
      7. 备份旧脚本 → 原子替换 → 清除 skip_version
    """

    def __init__(
        self,
        client: ReleaseClient,
        manager_cfg: ManagerConfig,
        state: State | None = None,
        script_path: Path | None = None,
    ) -> None:
        self.client = client
        self.cfg = manager_cfg
        self.state = state
        self.script_path = script_path or Path(__file__).resolve()

    # ---------- 版本检查 ----------

    def check(self) -> tuple[str, dict] | None:
        """返回 (version, release_info) 或 None（无更新/网络失败/已跳过）。"""
        result = self.client.check_latest()
        if not result:
            return None
        version, _, info = result

        if not self._version_gt(version, __version__):
            return None

        skip = self.cfg.skip_version
        if skip and version == skip:
            out(f"版本 {version} 已标记为跳过。")
            return None

        return version, info

    @staticmethod
    def _version_gt(a: str, b: str) -> bool:
        """语义化版本比较：a > b。支持 X.Y.Z，忽略非数字后缀。"""
        def _parts(v: str) -> list[int]:
            parts: list[int] = []
            for x in v.split("."):
                m = re.match(r"(\d+)", x)
                parts.append(int(m.group(1)) if m else 0)
            while len(parts) < 3:
                parts.append(0)
            return parts
        return _parts(a) > _parts(b)

    # ---------- Schema 兼容性 ----------

    def _check_schema_compat(self, release_info: dict) -> bool:
        """检查 dbSchemaVersion 兼容性。返回 True 表示可以继续更新。

        逻辑：
          - release_info 无 dbSchemaVersion → 兼容（旧版本）
          - 未安装 Pylai（state 为空）    → 兼容
          - 当前版本 release.json 无法获取 → 警告并放行
          - 当前 schema == 目标 schema      → 兼容
          - 否则                           → 不兼容，需手动迁移
        """
        remote_schema = release_info.get("dbSchemaVersion")
        if not remote_schema:
            return True
        if not self.state or not self.state.installed:
            return True

        current_pylai_ver = self.state.version
        current_release = self.client.fetch_release_json(current_pylai_ver)
        if not current_release:
            out(f"警告：无法获取当前 Pylai {current_pylai_ver} 的 release.json，跳过 schema 兼容性检查。")
            return True

        current_schema = current_release.get("dbSchemaVersion", "0")
        if remote_schema == current_schema:
            return True

        out(f"dbSchemaVersion 不兼容: 当前 {current_schema} -> 目标 {remote_schema}")
        out("此更新需要手动数据库迁移，请查看迁移文档后手动执行。")
        return False

    # ---------- 执行更新 ----------

    def update(self, force: bool = False, dry_run: bool = False,
               skip_prompt: bool = False) -> bool:
        """执行自更新；返回是否成功。"""
        result = self.client.check_latest()
        if not result:
            out("无法获取最新版本信息。")
            return False
        version, _, info = result

        if not force and not self._version_gt(version, __version__):
            out(f"当前已是最新版本 {__version__}。")
            return False

        out(f"==> 更新 ManagePylai.py: {__version__} -> {version}")

        # 1. dbSchemaVersion 兼容性校验
        if not self._check_schema_compat(info):
            if skip_prompt:
                out("Schema 不兼容且非交互模式，跳过更新。")
                return False
            if not ask_yes_no("Schema 不兼容，仍强制更新管理工具（不推荐）？", False):
                return False

        # 2. 下载 ManagePylai.py.new
        new_script = self.script_path.with_suffix(".py.new")
        sha256_file = self.script_path.with_suffix(".py.sha256")

        try:
            self.client.download(version, "ManagePylai.py", new_script)
        except ManageError as exc:
            out(f"下载失败: {exc}")
            new_script.unlink(missing_ok=True)
            return False

        # 3. 下载并解析 SHA256
        sha256_expected: str | None = None
        try:
            self.client.download(version, "ManagePylai.py.sha256", sha256_file)
            sha256_content = sha256_file.read_text(encoding="ascii").strip()
            # 支持两种格式: "hash" 或 "hash  filename"
            sha256_expected = sha256_content.split()[0]
        except (ManageError, OSError):
            out("警告：无法下载或读取 SHA256 校验文件")

        # 4. SHA256 校验
        if sha256_expected:
            import hashlib
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

        # 5. 备份 + 原子替换
        try:
            backup = self.script_path.with_suffix(f".py.bak.{__version__}")
            shutil.copy2(self.script_path, backup)
            os.replace(new_script, self.script_path)
            # 更新成功后清除 skip_version
            self.cfg.set_skip_version(None)
            out(f"ManagePylai.py 已更新至 {version}，请重新运行脚本。")
            return True
        except OSError as exc:
            out(f"替换失败: {exc}")
            return False
        finally:
            sha256_file.unlink(missing_ok=True)

    # ---------- 更新前钩子 ----------

    def ensure_up_to_date(self, yes: bool = False) -> None:
        """在 `update` 命令开始时检查并提示/强制自更新。

        如果更新成功，直接 sys.exit(0) 要求用户重新运行。
        """
        result = self.check()
        if not result:
            return
        version, info = result

        msg = f"ManagePylai.py 有新版本 {version}，是否先更新管理工具？"
        if yes:
            out(msg + " [Y/n] Y (非交互模式)")
            self.update(skip_prompt=yes)
            out("管理工具已更新，请重新运行命令。")
            sys.exit(0)

        if ask_yes_no(msg, default=True):
            self.update()
            out("管理工具已更新，请重新运行命令。")
            sys.exit(0)
        else:
            # 用户拒绝更新，询问是否跳过此版本
            if ask_yes_no(f"是否跳过版本 {version} 的后续提醒？", False):
                self.cfg.set_skip_version(version)
                out(f"已设置跳过版本 {version}。")
            out("警告：使用旧版本管理工具更新可能存在兼容性问题。")


class InteractiveMenu:
    """旧交互式菜单（兼容层）。

    Phase 1 中直接代理到原有全局函数，保持所有交互行为不变。
    后续 Phase 可逐步将 action/submenu 函数内联为类方法。
    """

    def __init__(self, docker: DockerCompose, state: State, config: PylaiConfig) -> None:
        self.docker = docker
        self.state = state
        self.config = config

    def run(self) -> None:
        """进入主菜单循环（替代原有 main_menu）。"""
        main_menu()


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
    prompt_line = f"{prompt}{suffix}: "
    while True:
        try:
            value = input(prompt_line)
        except (EOFError, KeyboardInterrupt):
            out("\n已退出。")
            raise SystemExit(0)
        if secret and sys.stdout.isatty():
            # 输入时明文显示；回车后回退一行清除整行并重印提示（密码从屏幕消失）
            sys.stdout.write("\033[1A\033[2K")
            sys.stdout.write(prompt_line + "\n")
            sys.stdout.flush()
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
    PG_DATA_DIR.chmod(0o700)


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
    text = replace_one(text, 'Url = "http://localhost:5173"', f'Url = {toml_string(answers["public_url"])}')
    cs = f'Host=127.0.0.1;Port=5432;Database={answers["db_name"]};Username={answers["db_user"]};Password={answers["db_password"]}'
    text = replace_one(
        text,
        'ConnectionString = "Host=127.0.0.1;Port=5432;Database=postgres;Username=postgres;Password="',
        f'ConnectionString = {toml_string(cs)}',
    )
    text = replace_one(text, 'Password = ""', f'Password = {toml_string(answers["redis_password"])}', 1)
    text = replace_one(text, 'ServerPepper = ""', f'ServerPepper = {toml_string(answers["invite_pepper"])}')
    text = replace_one(text, 'Directory = "backups"', 'Directory = "/var/lib/pylai/backups"')
    text = replace_one(text, 'ForwardedHeadersEnabled = true', "ForwardedHeadersEnabled = true")
    text = replace_one(text, 'TrustedProxies = ["127.0.0.1", "::1"]', f'TrustedProxies = {toml_string_list(answers["trusted_proxies"])}')
    text = replace_one(text, 'TrustedNetworks = []', f'TrustedNetworks = {toml_string_list(answers["trusted_networks"])}')
    text = replace_one(text, 'KeyFile = ""', 'KeyFile = "/etc/pylai/certs/signing-kek"')
    text = replace_one(text, 'AllowedOrigins = ["http://localhost:5173"]',
                       f'AllowedOrigins = {toml_string_list(answers["cors_origins"])}')
    text = replace_one(text, 'Issuer = "http://localhost:5000"', f'Issuer = {toml_string(answers["origin"])}')
    external_host = urlparse(answers["public_url"]).hostname or "localhost"
    allowed_hosts = [external_host]
    if external_host not in ("localhost", "127.0.0.1", "::1"):
        allowed_hosts.extend(("localhost", "127.0.0.1"))
    text = replace_one(text, 'AllowedHosts = ["localhost", "127.0.0.1"]',
                       f'AllowedHosts = {toml_string_list(allowed_hosts)}')
    text = replace_one(text, 'RelyingPartyId = "localhost"', f'RelyingPartyId = {toml_string(external_host)}')
    text = replace_one(text, 'Origins = ["http://localhost:5173"]', f'Origins = {toml_string_list(answers["cors_origins"])}')

    if answers["public_url"].startswith("https://"):
        text = replace_one(text, "RequireHttps = false", "RequireHttps = true") if "RequireHttps = false" in text else text
        text = replace_one(text, "RequireHttps = true", "RequireHttps = true")
        text = replace_one(text, 'SecurePolicy = "Always"', 'SecurePolicy = "Always"')
    else:
        text = replace_one(text, "RequireHttps = true", "RequireHttps = false")
        text = replace_one(text, 'SecurePolicy = "Always"', 'SecurePolicy = "SameAsRequest"')

    if answers["signing_pfx"]:
        # 段内键值替换（容忍段首行与键之间存在的注释行）
        text = _replace_toml_block_value(text, "[OpenIddict.Certificates.Signing]", "Path", toml_string(answers["signing_pfx"]))
        text = _replace_toml_block_value(text, "[OpenIddict.Certificates.Signing]", "Password", toml_string(answers["signing_pfx_password"]))
    if answers["encryption_pfx"]:
        text = _replace_toml_block_value(text, "[OpenIddict.Certificates.Encryption]", "Path", toml_string(answers["encryption_pfx"]))
        text = _replace_toml_block_value(text, "[OpenIddict.Certificates.Encryption]", "Password", toml_string(answers["encryption_pfx_password"]))

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
        block = block.replace('Email = "admin@pylaios.local"', f'Email = {toml_string(answers[email_key])}')
        block = block.replace('Email = "user@pylaios.local"', f'Email = {toml_string(answers[email_key])}')
        block = block.replace('Email = "max@pylaios.local"', f'Email = {toml_string(answers[email_key])}')
        block = block.replace('Password = ""', f'Password = {toml_string(answers[password_key])}', 1)
        block = block.replace('DisplayName = "Administrator"', f'DisplayName = "{display_name}"')
        block = block.replace('DisplayName = "Test User"', f'DisplayName = "{display_name}"')
        block = block.replace('DisplayName = "Max User"', f'DisplayName = "{display_name}"')
        text = text[:start] + block + text[end:]

    if answers["smtp_enabled"]:
        text = replace_one(text, '[Email]\nFromName = "Pylaios"\nFromAddress = ""',
                           f'[Email]\nFromName = "Pylaios"\nFromAddress = {toml_string(answers["smtp_from"])}')
        smtp_marker = "[Email.Smtp]"
        smtp_start = text.index(smtp_marker)
        smtp_end = text.find("\n\n", smtp_start)
        smtp_end = len(text) if smtp_end < 0 else smtp_end
        smtp_block = text[smtp_start:smtp_end]
        smtp_block = replace_one(smtp_block, 'Host = ""', f'Host = {toml_string(answers["smtp_host"])}')
        smtp_block = replace_one(smtp_block, "Port = 587", f"Port = {answers['smtp_port']}")
        smtp_block = replace_one(smtp_block, 'Security = "StartTls"', f'Security = {toml_string(answers["smtp_security"])}')
        smtp_block = replace_one(smtp_block, 'Username = ""', f'Username = {toml_string(answers["smtp_user"])}')
        smtp_block = smtp_block.replace('Password = ""', f'Password = {toml_string(answers["smtp_password"])}', 1)
        text = text[:smtp_start] + smtp_block + text[smtp_end:]

    text = _replace_toml_block_value(text, "[Mfa]", "RequireForAdmin", "true" if answers.get("mfa_for_admin", False) else "false")
    text = _replace_toml_block_value(text, "[Mfa]", "RequireWebAuthnForMax", "true" if answers.get("mfa_webauthn_for_max", False) else "false")

    ensure_home()
    # Fail Closed：写出前用 tomllib 校验整体为合法 TOML，避免结构错误带病落地
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManageError(f"生成的 pylai.toml 不是合法 TOML（模板或生成逻辑问题）: {exc}") from exc
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


def read_password_policy() -> dict:
    """从本地 pylai.toml 读取密码策略，失败则返回默认值。"""
    defaults = {
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
    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        pwd = data.get("Identity", {}).get("Password", {}) if isinstance(data.get("Identity"), dict) else {}
        # 兼容部分配置直接扁平的情况，但主要走嵌套
        for key in list(defaults.keys()):
            if key in pwd:
                defaults[key] = pwd[key]
            # TOML 中键可能为驼峰，保持一致
        return defaults
    except (OSError, tomllib.TOMLDecodeError, ValueError, AttributeError):
        return defaults


def validate_password_local(password: str, policy: dict, is_privileged: bool) -> list[str]:
    """本地密码策略预校验，返回错误描述列表（空列表表示通过）。"""
    errs: list[str] = []
    if not password:
        errs.append("密码不能为空。")
        return errs
    required = policy.get("AdminRequiredLength", 14) if is_privileged else policy.get("RequiredLength", 12)
    try:
        required = int(required)
    except (TypeError, ValueError):
        required = 14 if is_privileged else 12
    if len(password) < required:
        errs.append(f"密码长度至少为 {required} 个字符。")
    if policy.get("RequireDigit") and not any(c.isdigit() for c in password):
        errs.append("密码必须包含数字。")
    if policy.get("RequireLowercase") and not any(c.islower() for c in password):
        errs.append("密码必须包含小写字母。")
    if policy.get("RequireUppercase") and not any(c.isupper() for c in password):
        errs.append("密码必须包含大写字母。")
    if policy.get("RequireNonAlphanumeric") and all(c.isalnum() for c in password):
        errs.append("密码必须包含非字母数字字符。")
    return errs


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
    max_password = ask("Max 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
    max_password_input = bool(max_password)
    if ask_yes_no("创建初始 Admin 账号？", True):
        admin_email = ask("Admin 账号邮箱/登录名", "admin@pylai.local")
        admin_password = ask("Admin 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
        admin_password_input = bool(admin_password)
    else:
        admin_email, admin_password = "", ""
        admin_password_input = False
    if ask_yes_no("创建初始 Normal 测试账号？", False):
        user_email = ask("Normal 账号邮箱/登录名", "user@pylai.local")
        user_password = ask("Normal 账号密码（留空自动生成）", "", secret=True, allow_blank=True)
        user_password_input = bool(user_password)
    else:
        user_email, user_password = "", ""
        user_password_input = False

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

    out("\n-- 高权限账户 MFA --")
    out("MFA 可保护 Admin/Max 账户安全。HTTP/局域网部署时 WebAuthn 不可用，建议关闭或仅使用 TOTP。")
    mfa_for_admin = ask_yes_no("Admin 及以上角色登录时强制要求 MFA？", False)
    if mfa_for_admin:
        mfa_webauthn_for_max = ask_yes_no("Max 角色强制使用 WebAuthn（需 HTTPS 环境，HTTP 内网部署请勿开启）？", False)
    else:
        mfa_webauthn_for_max = False

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
        "max_password_input": max_password_input,
        "admin_email": admin_email,
        "admin_password": admin_password,
        "admin_password_input": admin_password_input,
        "user_email": user_email,
        "user_password": user_password,
        "user_password_input": user_password_input,
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
        "mfa_for_admin": mfa_for_admin,
        "mfa_webauthn_for_max": mfa_webauthn_for_max,
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
        # 单容器回退形态：容器 root 需要读取宿主 ~/.pylai/config（0600/0700）的
        # 配置与证书 bind 挂载（无 DAC_OVERRIDE 时容器 root 按 other 位无法读取），
        # 且 postgres 需对命名 volume 执行 chown。DAC_OVERRIDE/FOWNER 是单容器
        # 部署的代价（生产升级为 compose 拆分后可移除）。
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
        # 写目录改用命名 volume（宿主目录为 0700 时容器内 root 无 DAC_OVERRIDE 无法写入；
        # 命名 volume 由 Docker 管理，owner 随镜像内目录，可正常 chown/写入）
        "-v", "pylai_data:/var/lib/pylai",
        "-v", "pylai_pgdata:/var/lib/postgresql",
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
    if answers.get("max_email"):
        if answers.get("max_password"):
            out(f"  Max 账号: {answers['max_email']} / {answers['max_password']}")
        else:
            out(f"  Max 账号: {answers['max_email']} / (已自动生成，见容器日志: docker logs {CONTAINER})")
    if answers.get("admin_email"):
        if answers.get("admin_password"):
            out(f"  Admin 账号: {answers['admin_email']} / {answers['admin_password']}")
        else:
            out(f"  Admin 账号: {answers['admin_email']} / (已自动生成，见容器日志: docker logs {CONTAINER})")
    if answers.get("user_email"):
        if answers.get("user_password"):
            out(f"  Normal 账号: {answers['user_email']} / {answers['user_password']}")
        else:
            out(f"  Normal 账号: {answers['user_email']} / (已自动生成，见容器日志: docker logs {CONTAINER})")
    out("  以上初始密码仅在本次安装时显示，请妥善保存。")
    if not answers.get("max_password") or (answers.get("admin_email") and not answers.get("admin_password")) or (answers.get("user_email") and not answers.get("user_password")):
        out("  提示: 自动生成的密码已在容器启动日志中打印（[DbSeeder] 标记），也可执行 docker logs 查看。")
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


def action_reset_password(kind: str, target_email: str | None = None) -> None:
    state = load_state()
    if not state:
        out("尚未安装。")
        return
    if not container_running():
        out("容器未运行，无法重置密码。")
        return
    default_email = target_email or (state.get("max_email") if kind == "max" else state.get("admin_email"))
    email = ask("账号邮箱/登录名", default_email or (f"{kind}@pylai.local"))
    policy = read_password_policy()
    is_privileged = kind in ("max", "admin")
    while True:
        password = ask("新密码", "", secret=True)
        errs = validate_password_local(password, policy, is_privileged)
        if not errs:
            break
        out(f"密码不符合策略: {', '.join(errs)}")
        if not ask_yes_no("重新输入？"):
            return
    run(["docker", "exec", "-i", CONTAINER, PYLAIOS_BIN, "user", "reset-password", email,
         "--password-stdin", "--config", "/etc/pylai/pylai.toml"],
        input_text=password + "\n", timeout=120)
    out("密码已重置，该用户全部会话与 token 已吊销。")


def action_change_mfa() -> None:
    if not CONFIG_FILE.is_file():
        out("配置文件不存在")
        return
    text = CONFIG_FILE.read_text(encoding="utf-8")
    mfa_for_admin = False
    mfa_webauthn_for_max = False
    try:
        parsed = tomllib.loads(text)
        mfa = parsed.get("Mfa", {})
        mfa_for_admin = bool(mfa.get("RequireForAdmin", False))
        mfa_webauthn_for_max = bool(mfa.get("RequireWebAuthnForMax", False))
    except tomllib.TOMLDecodeError as exc:
        out(f"配置解析失败: {exc}")
        return
    out("当前 MFA 配置：")
    out(f"  RequireForAdmin = {'true' if mfa_for_admin else 'false'}")
    out(f"  RequireWebAuthnForMax = {'true' if mfa_webauthn_for_max else 'false'}")
    new_mfa_for_admin = ask_yes_no("Admin 及以上角色登录时强制要求 MFA？", mfa_for_admin)
    if new_mfa_for_admin:
        new_mfa_webauthn_for_max = ask_yes_no("Max 角色强制使用 WebAuthn（需 HTTPS 环境，HTTP 内网部署请勿开启）？", mfa_webauthn_for_max)
    else:
        new_mfa_webauthn_for_max = False
    text = _replace_toml_block_value(text, "[Mfa]", "RequireForAdmin", "true" if new_mfa_for_admin else "false")
    text = _replace_toml_block_value(text, "[Mfa]", "RequireWebAuthnForMax", "true" if new_mfa_webauthn_for_max else "false")
    CONFIG_FILE.write_text(text, encoding="utf-8")
    CONFIG_FILE.chmod(0o600)
    out("MFA 配置已更新，注意：需要手动重启实例才能生效")


def _cli_user_cmd(*args: str, input_text: str | None = None) -> dict:
    """执行 Pylaios user CLI 并解析 JSON 输出。"""
    cmd = ["docker", "exec", "-i", CONTAINER, PYLAIOS_BIN, "user", *args,
           "--config", "/etc/pylai/pylai.toml"]
    result = run(cmd, check=False, timeout=120, input_text=input_text)
    try:
        return json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        out(result.stdout.strip() or result.stderr.strip())
        return {"success": False}


def action_user_list() -> None:
    if not container_running():
        out("容器未运行。")
        return
    data = _cli_user_cmd("list")
    if not data.get("success"):
        out("获取用户列表失败。")
        return
    users = data.get("users", [])
    total = data.get("total", 0)
    out(f"共 {total} 位用户：")
    out(f"{'UID':<36} {'用户名':<20} {'显示名':<20} {'邮箱':<30} {'组':<8} {'状态':<8}")
    out("-" * 120)
    for u in users:
        out(f"{u.get('uid',''):<36} {u.get('name',''):<20} {u.get('displayName','') or '-':<20} "
            f"{u.get('email',''):<30} {u.get('group',''):<8} {u.get('status',''):<8}")


def action_user_show() -> None:
    if not container_running():
        out("容器未运行。")
        return
    target = ask("用户标识（uid/用户名/邮箱）")
    data = _cli_user_cmd("show", target)
    if not data.get("success"):
        out("用户不存在或查询失败。")
        return
    u = data.get("user", {})
    out(f"UID:         {u.get('uid')}")
    out(f"用户名:      {u.get('name')}")
    out(f"显示名:      {u.get('displayName')}")
    out(f"邮箱:        {u.get('email')}")
    out(f"组:          {u.get('group')}")
    out(f"状态:        {u.get('status')}")
    out(f"注册时间:    {u.get('registerTime')}")
    out(f"最后登录:    {u.get('lastLoginAt') or '从未登录'}")
    out(f"活跃会话数:  {u.get('activeSessions', 0)}")
    if u.get("externalLogins"):
        out("外部登录绑定:")
        for login in u["externalLogins"]:
            out(f"  - {login['provider']} ({login['boundAt']})")


def action_user_create() -> None:
    if not container_running():
        out("容器未运行。")
        return
    email = ask("邮箱")
    name = ask("登录名（留空使用邮箱前缀）", "", allow_blank=True)
    display_name = ask("显示名（留空使用登录名）", "", allow_blank=True)
    group = choose([
        ("normal — 普通用户", "normal"),
        ("admin — 管理员", "admin"),
        ("max — 超级管理员", "max"),
    ], "请选择用户组") or "normal"
    policy = read_password_policy()
    is_privileged = group in ("admin", "max")
    if ask_yes_no("手动指定密码？（留空则自动生成）", False):
        while True:
            password = ask("密码", "", secret=True)
            errs = validate_password_local(password, policy, is_privileged)
            if not errs:
                break
            out(f"密码不符合策略: {', '.join(errs)}")
            if not ask_yes_no("重新输入？"):
                return
        data = _cli_user_cmd("create", email, "--name", name or "", "--display-name", display_name or "",
                             "--group", group, "--password-stdin", input_text=password + "\n")
    else:
        data = _cli_user_cmd("create", email, "--name", name or "", "--display-name", display_name or "",
                             "--group", group)
    if data.get("success"):
        out(f"创建成功: {data.get('message')}")
        if "generatedPassword" in data:
            out(f"自动生成的密码: {data['generatedPassword']}")
            out("请立即保存，该密码不会再次显示。")
    else:
        out(f"创建失败: {data.get('message', '未知错误')}")


def action_user_delete() -> None:
    if not container_running():
        out("容器未运行。")
        return
    target = ask("要删除的用户标识（uid/用户名/邮箱）")
    if not confirm_danger(f"将软删除用户 {target}，其全部会话将被吊销。", required_word="DELETE"):
        out("已取消。")
        return
    data = _cli_user_cmd("delete", target)
    if data.get("success"):
        out(data.get("message"))
    else:
        out(f"删除失败: {data.get('message', '未知错误')}")


def action_user_set_group() -> None:
    if not container_running():
        out("容器未运行。")
        return
    target = ask("用户标识（uid/用户名/邮箱）")
    group = choose([
        ("normal — 普通用户", "normal"),
        ("admin — 管理员", "admin"),
        ("max — 超级管理员", "max"),
    ], "请选择新用户组") or "normal"
    data = _cli_user_cmd("set-group", target, group)
    if data.get("success"):
        out(data.get("message"))
    else:
        out(f"设置失败: {data.get('message', '未知错误')}")


def action_user_set_status() -> None:
    if not container_running():
        out("容器未运行。")
        return
    target = ask("用户标识（uid/用户名/邮箱）")
    status = choose([
        ("active — 正常", "active"),
        ("banned — 封禁", "banned"),
    ], "请选择新状态") or "active"
    data = _cli_user_cmd("set-status", target, status)
    if data.get("success"):
        out(data.get("message"))
    else:
        out(f"设置失败: {data.get('message', '未知错误')}")


def action_user_revoke_sessions() -> None:
    if not container_running():
        out("容器未运行。")
        return
    target = ask("用户标识（uid/用户名/邮箱）")
    data = _cli_user_cmd("revoke-sessions", target)
    if data.get("success"):
        out(data.get("message"))
    else:
        out(f"吊销失败: {data.get('message', '未知错误')}")


def submenu_users() -> None:
    if not container_running():
        out("容器未运行。")
        return
    entries = [
        ("用户列表", action_user_list),
        ("查看用户详情", action_user_show),
        ("创建用户", action_user_create),
        ("删除用户", action_user_delete),
        ("修改用户密码", lambda: action_reset_password("any", None)),
        ("设置用户组", action_user_set_group),
        ("设置用户状态", action_user_set_status),
        ("吊销用户全部会话", action_user_revoke_sessions),
    ]
    run_submenu("用户管理", "主菜单", entries)


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
        ("修改 MFA 配置", action_change_mfa),
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

    # 强制清理命名卷，防止旧数据库残留导致新安装 KEK 不匹配
    for vol in ("pylai_data", "pylai_pgdata"):
        docker("volume", "rm", "-f", vol, check=False)

    image = state.get("image")
    if image:
        docker("rmi", image, check=False)
    if confirm_danger("同时删除 ~/.pylai 全部数据目录（建议保留备份）？"):
        shutil.rmtree(HOME, ignore_errors=True)
        out("已删除全部数据目录。")
    STATE_FILE.unlink(missing_ok=True) if not HOME.exists() else None
    out("卸载完成。")


# ============================================================================
# CLI 命令处理（非交互模式）
# ============================================================================

def _cmd_install(args: argparse.Namespace, docker: DockerCompose, state: State,
                 config: PylaiConfig) -> None:
    if args.pylai_config:
        # 非交互：从现有 pylai.toml 安装
        raise ManageError("非交互安装 --config-file 尚未实现（Phase 3）")
    elif args.env_file:
        # 非交互：从 .env 文件安装
        raise ManageError("非交互安装 --env-file 尚未实现（Phase 3）")
    else:
        menu_install()


def _cmd_update(args: argparse.Namespace, docker: DockerCompose, state: State,
                config: PylaiConfig, manager_cfg: ManagerConfig) -> None:
    if args.check_only:
        client = ReleaseClient(manager_cfg)
        updater = SelfUpdater(client, manager_cfg, state)
        result = updater.check()
        if result:
            ver, info = result
            out(f"最新 ManagePylai.py 版本: {ver}")
            if "dbSchemaVersion" in info:
                out(f"  dbSchemaVersion: {info['dbSchemaVersion']}")
        else:
            out("当前已是最新，或无法获取版本信息。")
        return

    # 更新前 Self-Update 检查（Phase 2 核心）
    client = ReleaseClient(manager_cfg)
    updater = SelfUpdater(client, manager_cfg, state)
    updater.ensure_up_to_date(yes=args.yes)

    # 继续执行 Pylai 本体更新（复用 Phase 0 的 update()）
    update()


def _cmd_self_update(args: argparse.Namespace, manager_cfg: ManagerConfig,
                     state: State) -> None:
    client = ReleaseClient(manager_cfg)
    updater = SelfUpdater(client, manager_cfg, state)
    if args.check_only:
        result = updater.check()
        if result:
            ver, info = result
            out(f"最新版本: {ver}")
        else:
            out("当前已是最新，或无法获取版本信息。")
    else:
        updater.update(force=args.force, dry_run=args.dry_run, skip_prompt=args.yes)


def _cmd_start(args: argparse.Namespace, docker: DockerCompose, state: State) -> None:
    if not docker.container_exists():
        raise ManageError("尚未安装。")
    docker._docker("start", docker.container, timeout=60)
    if docker.wait_healthy(state.api_port):
        out("启动完成。")
    else:
        out("容器已启动，但健康检查尚未通过。")


def _cmd_stop(args: argparse.Namespace, docker: DockerCompose) -> None:
    if not docker.container_exists():
        raise ManageError("尚未安装。")
    docker.stop()
    out("已停止。")


def _cmd_restart(args: argparse.Namespace, docker: DockerCompose, state: State) -> None:
    if not docker.container_exists():
        raise ManageError("尚未安装。")
    docker.restart()
    out("已重启。")


def _cmd_status(args: argparse.Namespace, docker: DockerCompose) -> None:
    if not docker.container_exists():
        out("尚未安装或容器不存在。")
        return
    result = docker._docker(
        "ps", "-a", "--filter", f"name={docker.container}",
        "--format", "{{.Names}} {{.Status}}", check=False,
    )
    out(result.stdout.strip() or "未找到容器")


def _cmd_logs(args: argparse.Namespace, docker: DockerCompose) -> None:
    if not docker.container_exists():
        raise ManageError("尚未安装。")
    if args.follow:
        docker.view_logs(tail=200, follow=True)
    else:
        text = docker.logs_text(tail=200)
        out(text.strip() or "（暂无日志输出）")


def _cmd_config(args: argparse.Namespace, config: PylaiConfig) -> None:
    if args.config_cmd == "view":
        if not config.FILE.is_file():
            raise ManageError("配置文件不存在")
        out(config.mask())
    elif args.config_cmd == "edit":
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, str(config.FILE)])
    elif args.config_cmd == "validate":
        config.validate()
        out("配置校验通过。")
    elif args.config_cmd == "generate-nginx":
        generate_host_nginx()
    else:
        raise ManageError("请指定 config 子命令: view / edit / validate / generate-nginx")


def _cmd_backup(args: argparse.Namespace, docker: DockerCompose, state: State) -> None:
    if args.backup_cmd == "create":
        export_database()
    elif args.backup_cmd == "list":
        action_list_backups()
    elif args.backup_cmd == "restore":
        import_database()  # 现有 import_database 会交互式选择文件
    else:
        raise ManageError("请指定 backup 子命令: create / list / restore <file>")


def _cmd_uninstall(args: argparse.Namespace, docker: DockerCompose, state: State) -> None:
    if args.purge:
        # --purge 直接确认
        uninstall()
    else:
        # 复用现有交互确认逻辑
        uninstall()


def _cmd_rotate_keys(args: argparse.Namespace, docker: DockerCompose, state: State) -> None:
    if not docker.container_running():
        raise ManageError("容器未运行。")
    action_key_rotate()


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
        out("[7] 用户管理")
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
            "7": submenu_users,
        }
        action = actions.get(choice)
        if action is None:
            out("选择无效。")
            continue
        try:
            action()
        except ManageError as exc:
            out(f"错误: {exc}")

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ManagePylai.py",
        description="Pylai Docker 部署管理工具",
    )
    parser.add_argument(
        "--config", dest="manager_config",
        default=str(ManagerConfig.DEFAULT_PATH),
        help="ManagerConfig.toml 路径（默认 ~/.pylai/ManagerConfig.toml）",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="非交互模式，所有确认默认 Yes",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印将要执行的操作",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="详细输出",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # install
    install_p = subparsers.add_parser("install", help="安装 Pylai")
    install_p.add_argument("--config-file", dest="pylai_config",
                          help="从现有 pylai.toml 非交互安装")
    install_p.add_argument("--env-file", help="从 .env 文件非交互安装")

    # update
    update_p = subparsers.add_parser("update", help="更新 Pylai")
    update_p.add_argument("--version", help="更新到指定版本")
    update_p.add_argument("--check-only", action="store_true",
                         help="只检查更新，不执行")

    # self-update
    self_up_p = subparsers.add_parser("self-update", help="更新管理工具自身")
    self_up_p.add_argument("--check-only", action="store_true")
    self_up_p.add_argument("--force", action="store_true")

    # start / stop / restart / status
    subparsers.add_parser("start", help="启动服务")
    subparsers.add_parser("stop", help="停止服务")
    subparsers.add_parser("restart", help="重启服务")
    subparsers.add_parser("status", help="查看状态")

    # logs
    logs_p = subparsers.add_parser("logs", help="查看日志")
    logs_p.add_argument(
        "service", nargs="?", default="all",
        choices=["backend", "nginx", "postgres", "redis", "all"],
        help="服务名（多服务模式下有效，当前仅 all 生效）",
    )
    logs_p.add_argument("-f", "--follow", action="store_true",
                       help="持续跟踪")

    # config
    cfg_p = subparsers.add_parser("config", help="配置管理")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd")
    cfg_sub.add_parser("view", help="查看当前配置（脱敏）")
    cfg_sub.add_parser("edit", help="编辑 pylai.toml")
    cfg_sub.add_parser("validate", help="验证配置合法性")
    cfg_sub.add_parser("generate-nginx", help="生成主机 Nginx 配置模板")

    # backup
    bak_p = subparsers.add_parser("backup", help="备份管理")
    bak_sub = bak_p.add_subparsers(dest="backup_cmd")
    bak_sub.add_parser("create", help="创建备份")
    bak_sub.add_parser("list", help="列出备份")
    restore_p = bak_sub.add_parser("restore", help="从备份恢复")
    restore_p.add_argument("file")

    # uninstall
    un_p = subparsers.add_parser("uninstall", help="卸载")
    un_p.add_argument("--purge", action="store_true",
                     help="完全卸载（删除所有数据）")

    # rotate-keys
    rot_p = subparsers.add_parser("rotate-keys", help="轮换签名密钥")
    rot_p.add_argument("--signing", action="store_true")
    rot_p.add_argument("--encryption", action="store_true")

    args = parser.parse_args()

    # 初始化核心对象
    manager_cfg = ManagerConfig(
        Path(args.manager_config) if args.manager_config else None
    )
    docker = DockerCompose()
    state = State()
    config = PylaiConfig()

    # 向后兼容：无命令时进入交互菜单
    if args.command is None:
        docker.ensure_docker()
        menu = InteractiveMenu(docker, state, config)
        menu.run()
        return

    # 非交互模式
    docker.ensure_docker()

    try:
        if args.command == "install":
            _cmd_install(args, docker, state, config)
        elif args.command == "update":
            _cmd_update(args, docker, state, config, manager_cfg)
        elif args.command == "self-update":
            _cmd_self_update(args, manager_cfg, state)
        elif args.command == "start":
            _cmd_start(args, docker, state)
        elif args.command == "stop":
            _cmd_stop(args, docker)
        elif args.command == "restart":
            _cmd_restart(args, docker, state)
        elif args.command == "status":
            _cmd_status(args, docker)
        elif args.command == "logs":
            _cmd_logs(args, docker)
        elif args.command == "config":
            _cmd_config(args, config)
        elif args.command == "backup":
            _cmd_backup(args, docker, state)
        elif args.command == "uninstall":
            _cmd_uninstall(args, docker, state)
        elif args.command == "rotate-keys":
            _cmd_rotate_keys(args, docker, state)
        else:
            parser.print_help()
            sys.exit(1)
    except ManageError as exc:
        out(f"错误: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        out("\n再见。")

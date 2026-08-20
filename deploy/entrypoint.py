#!/usr/bin/env python3
"""
Pylai 单容器部署入口脚本。
替代原有的 Bash entrypoint，提供结构化日志、显式错误码和可测试性。
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ============ 配置常量 ============
CONFIG_FILE = Path(os.environ.get("PYLAI_CONFIG", "/etc/pylai/pylai.toml"))
RUNTIME_CONFIG = Path("/var/lib/pylai/pylai.toml")
SECRET_DIR = Path("/var/lib/pylai/secrets")
DP_KEK_FILE = SECRET_DIR / "dp-kek"
PYLAIOS_BIN = Path("/opt/pylai/Pylaios")

# ============ 日志 ============
def log(level: str, msg: str) -> None:
    print(f"[pylai] [{level}] {msg}", flush=True)

def fatal(msg: str, code: int = 1) -> None:
    log("FATAL", msg)
    sys.exit(code)

# ============ 工具函数 ============
def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """执行命令，失败时 fatal（等效 Bash set -e）。"""
    log("DEBUG", f"exec: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""
        fatal(f"命令失败 (rc={result.returncode}): {' '.join(cmd)}\nstderr: {stderr}\nstdout: {stdout}")
    return result

# ============ 阶段 1: 环境检查 ============
def check_env() -> None:
    required = ["PYLAI_DB_USER", "PYLAI_DB_PASSWORD", "PYLAI_DB_NAME", "PYLAI_REDIS_PASSWORD"]
    for var in required:
        if not os.environ.get(var):
            fatal(f"{var} is required")

# ============ 阶段 2: 配置重映射 ============
def remap_config() -> None:
    """将配置中引用的敏感文件复制到受保护的 secret_dir，并改写路径。"""
    if not CONFIG_FILE.exists():
        fatal(f"配置文件不存在: {CONFIG_FILE}")

    text = CONFIG_FILE.read_text(encoding="utf-8")

    def remap(section: str, key: str, dest_name: str) -> None:
        nonlocal text
        pattern = re.compile(
            rf'^\[{re.escape(section)}\]\s*\n(?:[^\[]*?)^({re.escape(key)} = "([^\n]*)")$',
            re.MULTILINE | re.DOTALL
        )
        match = pattern.search(text)
        if not match:
            return
        raw = match.group(2).strip()
        if not raw:
            return
        src = Path(raw)
        if not src.is_absolute():
            src = CONFIG_FILE.parent / src
        if not src.exists():
            fatal(f"配置引用的敏感文件不存在: {src}")
        dest = SECRET_DIR / dest_name
        shutil.copy2(src, dest)
        dest.chmod(0o600)
        text = text[:match.start(1)] + f'{key} = "{dest}"' + text[match.end(1):]

    remap("OpenIddict.SigningKeyEncryption", "KeyFile", "signing-kek")
    remap("OpenIddict.Certificates.Signing", "Path", "signing.pfx")
    remap("OpenIddict.Certificates.Encryption", "Path", "encryption.pfx")

    RUNTIME_CONFIG.write_text(text, encoding="utf-8")
    RUNTIME_CONFIG.chmod(0o600)

# ============ 阶段 3: DataProtection KEK ============
def setup_dp_kek() -> None:
    """初始化 DataProtection 独立 KEK。"""
    injected = os.environ.get("PYLAI_DP_KEK_FILE")
    if injected:
        injected_path = Path(injected)
        if not injected_path.exists() or injected_path.stat().st_size == 0:
            fatal(f"DataProtection KEK 注入文件不存在或为空: {injected}")
        shutil.copy2(injected_path, DP_KEK_FILE)
    elif not DP_KEK_FILE.exists() or DP_KEK_FILE.stat().st_size == 0:
        dp_dir = Path("/var/lib/pylai/dataprotection")
        if dp_dir.exists() and any(
            "<pylai-aes-gcm" in f.read_text()
            for f in dp_dir.rglob("*.xml") if f.is_file()
        ):
            fatal("已存在 AES-GCM 加密的 DataProtection 密钥环，但持久化 KEK 丢失；拒绝生成新 KEK。")
        DP_KEK_FILE.write_bytes(os.urandom(32))

    DP_KEK_FILE.chmod(0o600)
    os.environ["PYLAI_DP_KEK_FILE"] = str(DP_KEK_FILE)

# ============ 阶段 4: PostgreSQL ============
def setup_postgres() -> None:
    """初始化并启动 PostgreSQL。"""
    pg_ver = next(Path("/usr/lib/postgresql").iterdir()).name
    pg_data = Path(f"/var/lib/postgresql/{pg_ver}/main")
    pg_bin = Path(f"/usr/lib/postgresql/{pg_ver}/bin")

    pg_data.parent.mkdir(parents=True, exist_ok=True)
    run(["chown", "postgres:postgres", str(pg_data.parent)])

    if not (pg_data / "PG_VERSION").exists():
        log("INFO", "初始化 PostgreSQL 数据目录...")
        run(["su", "postgres", "-c",
             f"{pg_bin}/initdb -D {pg_data} --auth-local=peer --auth-host=scram-sha-256 --username=postgres"])

    src_conf = Path(f"/etc/postgresql/{pg_ver}/main/postgresql.conf")
    if not (pg_data / "postgresql.conf").exists() and src_conf.exists():
        shutil.copy2(src_conf, pg_data / "postgresql.conf")
        shutil.copytree(Path(f"/etc/postgresql/{pg_ver}/main/conf.d"), pg_data / "conf.d", dirs_exist_ok=True)
        run(["chown", "-R", "postgres:postgres", str(pg_data)])

    pg_hba = pg_data / "pg_hba.conf"
    src_hba = Path(f"/etc/postgresql/{pg_ver}/main/pg_hba.conf")
    if not pg_hba.exists() and src_hba.exists():
        shutil.copy2(src_hba, pg_hba)
        run(["chown", "postgres:postgres", str(pg_hba)])

    hba_content = pg_hba.read_text() if pg_hba.exists() else ""
    with open(pg_hba, "a") as f:
        if "host all all 127.0.0.1/32" not in hba_content:
            f.write("host all all 127.0.0.1/32 scram-sha-256\n")
        if "host all all ::1/128" not in hba_content:
            f.write("host all all ::1/128 scram-sha-256\n")
    run(["chown", "postgres:postgres", str(pg_hba)])

    pg_opts = f"-h 127.0.0.1 -p 5432 -k /run/postgresql -c config_file={pg_data}/postgresql.conf -c hba_file={pg_hba}"
    run(["su", "postgres", "-c",
         f"{pg_bin}/pg_ctl -D {pg_data} -l /run/postgresql/pg.log -o '{pg_opts}' start"])

    for i in range(30):
        result = subprocess.run(
            ["su", "postgres", "-c", f"{pg_bin}/pg_isready -q -h /run/postgresql -p 5432"],
            capture_output=True
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        fatal("PostgreSQL 启动超时")

    db_user = os.environ["PYLAI_DB_USER"]
    db_pass = os.environ["PYLAI_DB_PASSWORD"]
    db_name = os.environ["PYLAI_DB_NAME"]

    run(["su", "postgres", "-c",
         f"psql -q -h /run/postgresql -v ON_ERROR_STOP=1 -c \"DO \\$\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{db_user}') THEN CREATE ROLE {db_user} LOGIN PASSWORD '{db_pass}'; ELSE ALTER ROLE {db_user} WITH LOGIN PASSWORD '{db_pass}'; END IF; END \\$\\$;\""])

    result = subprocess.run(
        ["su", "postgres", "-c",
         f"psql -q -h /run/postgresql -tAc \"SELECT 1 FROM pg_database WHERE datname='{db_name}'\""],
        capture_output=True, text=True
    )
    if "1" not in result.stdout:
        run(["su", "postgres", "-c", f"createdb -h /run/postgresql -O {db_user} {db_name}"])

# ============ 阶段 5: Redis ============
def setup_redis() -> None:
    redis_pass = os.environ["PYLAI_REDIS_PASSWORD"]
    redis_conf = Path("/var/lib/pylai/redis.conf")
    redis_conf.write_text(
        f"bind 127.0.0.1\nport 6379\nsave \"\"\nappendonly no\nrequirepass {redis_pass}\n",
        encoding="utf-8"
    )
    run(["chown", "redis:redis", str(redis_conf)])
    run(["chmod", "600", str(redis_conf)])
    run(["su", "-s", "/bin/bash", "redis", "-c",
         f"redis-server {redis_conf} --daemonize yes --pidfile /run/redis.pid --dir /var/lib/pylai"])

    for i in range(20):
        result = subprocess.run(
            ["redis-cli", "-p", "6379", "-a", redis_pass, "--no-auth-warning", "ping"],
            capture_output=True
        )
        if result.returncode == 0:
            break
        time.sleep(0.2)
    else:
        fatal("Redis 启动超时")

def shutdown_redis() -> None:
    redis_pass = os.environ.get("PYLAI_REDIS_PASSWORD", "")
    subprocess.run(
        ["redis-cli", "-p", "6379", "-a", redis_pass, "--no-auth-warning", "shutdown", "nosave"],
        capture_output=True
    )
    pid_file = Path("/run/redis.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 15)
        except (ValueError, ProcessLookupError):
            pass

# ============ 阶段 6: Pylaios CLI 初始化 ============
def run_pylaios_cli(args: list[str]) -> None:
    """以 pylai 用户运行 Pylaios CLI。"""
    dp_kek = shlex.quote(str(DP_KEK_FILE))
    config = shlex.quote(str(RUNTIME_CONFIG))
    arg_str = " ".join(shlex.quote(a) for a in args)
    cmd = f"cd /opt/pylai && env PYLAI_DP_KEK_FILE={dp_kek} {PYLAIOS_BIN} {arg_str} --config {config}"
    run(["su", "-s", "/bin/bash", "pylai", "-c", cmd])

def bootstrap() -> None:
    """执行数据库迁移、种子和密钥初始化。任何一步失败直接 fatal（等效 set -e）。"""
    steps = [
        ("数据库迁移", ["db", "migrate"]),
        ("邀请码遗留迁移", ["invite", "migrate-legacy"]),
        ("数据库引导", ["db", "bootstrap"]),
        ("数据库种子", ["db", "seed"]),
        ("密钥重新加密", ["key", "reencrypt"]),
        ("密钥轮换（如空）", ["key", "rotate", "--if-empty"]),
    ]
    for label, args in steps:
        log("INFO", f"执行: {label}...")
        run_pylaios_cli(args)

# ============ 主流程 ============
def main() -> None:
    if os.environ.get("PYLAI_ROLE", "server") == "dev":
        os.execv("/usr/local/bin/pylai-dev-entrypoint", sys.argv)

    check_env()

    # 目录准备
    Path("/var/lib/pylai/log").mkdir(parents=True, exist_ok=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    for d in ["/run/supervisor", "/run/postgresql", "/tmp/nginx-client-body",
              "/tmp/nginx-proxy", "/tmp/nginx-fastcgi", "/tmp/nginx-uwsgi", "/tmp/nginx-scgi"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    run(["chown", "postgres:postgres", "/run/postgresql"])
    for d in ["/tmp/nginx-client-body", "/tmp/nginx-proxy", "/tmp/nginx-fastcgi", "/tmp/nginx-uwsgi", "/tmp/nginx-scgi"]:
        run(["chown", "www-data:www-data", d])

    remap_config()
    setup_dp_kek()
    setup_postgres()
    setup_redis()

    run(["chown", "-R", "pylai:pylai", "/var/lib/pylai"])

    bootstrap()

    shutdown_redis()

    log("INFO", "数据库、签名密钥与 DataProtection KEK 检查完成，启动服务...")
    os.execv("/usr/bin/supervisord", ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/pylai-server.conf"])

if __name__ == "__main__":
    main()
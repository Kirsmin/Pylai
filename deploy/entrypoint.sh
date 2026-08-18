#!/bin/bash
set -euo pipefail

if [ "${PYLAI_ROLE:-server}" = "dev" ]; then
    exec /usr/local/bin/pylai-dev-entrypoint
fi

: "${PYLAI_DB_USER:?PYLAI_DB_USER is required}"
: "${PYLAI_DB_PASSWORD:?PYLAI_DB_PASSWORD is required}"
: "${PYLAI_DB_NAME:?PYLAI_DB_NAME is required}"
: "${PYLAI_REDIS_PASSWORD:?PYLAI_REDIS_PASSWORD is required}"

CONFIG_FILE="${PYLAI_CONFIG:-/etc/pylai/pylai.toml}"
RUNTIME_CONFIG=/var/lib/pylai/pylai.toml
SECRET_DIR=/var/lib/pylai/secrets

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[pylai] 配置文件不存在: $CONFIG_FILE" >&2
    exit 1
fi

mkdir -p /var/lib/pylai/log "$SECRET_DIR"
mkdir -p /run/supervisor /run/postgresql /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi
chown postgres:postgres /run/postgresql
chown www-data:www-data /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi

# 敏感文件从只读挂载复制到数据卷，并将路径重写为 pylai 用户可读的数据卷路径。
python3 - "$CONFIG_FILE" "$RUNTIME_CONFIG" "$SECRET_DIR" <<'PY'
import re, shutil, sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
secret_dir = Path(sys.argv[3])
text = source.read_text(encoding='utf-8')

def remap(section: str, key: str, dest_name: str) -> None:
    global text
    pattern = re.compile(rf'^\[{re.escape(section)}\]\s*\n(?:[^\[]*?)^({re.escape(key)} = "([^\n]*)")$', flags=re.M | re.S)
    match = pattern.search(text)
    if not match:
        return
    raw = match.group(2).strip()
    if not raw:
        return
    src = Path(raw)
    if not src.is_absolute():
        src = source.parent / src
    if not src.exists():
        raise SystemExit(f"配置引用的敏感文件不存在: {src}")
    dest = secret_dir / dest_name
    shutil.copy2(src, dest)
    dest.chmod(0o600)
    text = text[:match.start(1)] + f'{key} = "{dest}"' + text[match.end(1):]

remap('OpenIddict.SigningKeyEncryption', 'KeyFile', 'signing-kek')
remap('OpenIddict.Certificates.Signing', 'Path', 'signing.pfx')
remap('OpenIddict.Certificates.Encryption', 'Path', 'encryption.pfx')
target.write_text(text, encoding='utf-8')
target.chmod(0o600)
PY

chown -R pylai:pylai /var/lib/pylai

run_as_pylai() {
    local command
    command=$(printf '%q ' "$@")
    su -s /bin/bash pylai -c "$command"
}

PG_VER=$(ls /usr/lib/postgresql | head -1)
PG_DATA=/var/lib/postgresql/$PG_VER/main
PG_BIN=/usr/lib/postgresql/$PG_VER/bin

mkdir -p "$(dirname "$PG_DATA")"
chown postgres:postgres "$(dirname "$PG_DATA")"
if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    echo "[pylai] 初始化 PostgreSQL 数据目录..."
    su postgres -c "$PG_BIN/initdb -D $PG_DATA --auth-local=peer --auth-host=scram-sha-256 --username=postgres"
fi

PG_CONF="$PG_DATA/postgresql.conf"
PG_HBA="$PG_DATA/pg_hba.conf"
if [ ! -f "$PG_CONF" ] && [ -f "/etc/postgresql/$PG_VER/main/postgresql.conf" ]; then
    cp "/etc/postgresql/$PG_VER/main/postgresql.conf" "$PG_CONF"
    cp -r "/etc/postgresql/$PG_VER/main/conf.d" "$PG_DATA/conf.d" 2>/dev/null || true
    chown -R postgres:postgres "$PG_DATA"
fi
if [ ! -f "$PG_HBA" ] && [ -f "/etc/postgresql/$PG_VER/main/pg_hba.conf" ]; then
    cp "/etc/postgresql/$PG_VER/main/pg_hba.conf" "$PG_HBA"
    chown postgres:postgres "$PG_HBA"
fi

if [ -f "$PG_HBA" ]; then
    if ! grep -q "^host all all 127.0.0.1/32" "$PG_HBA"; then
        echo "host all all 127.0.0.1/32 scram-sha-256" >> "$PG_HBA"
    fi
    if ! grep -q "^host all all ::1/128" "$PG_HBA"; then
        echo "host all all ::1/128 scram-sha-256" >> "$PG_HBA"
    fi
else
    echo "host all all 127.0.0.1/32 scram-sha-256" > "$PG_HBA"
    echo "host all all ::1/128 scram-sha-256" >> "$PG_HBA"
    chown postgres:postgres "$PG_HBA"
fi

PG_START_OPTS="-h 127.0.0.1 -p 5432 -k /run/postgresql -c config_file=$PG_CONF -c hba_file=$PG_HBA"

su postgres -c "$PG_BIN/pg_ctl -D $PG_DATA -l /run/postgresql/pg.log -o \"$PG_START_OPTS\" start"

for i in $(seq 1 30); do
    su postgres -c "$PG_BIN/pg_isready -q -h /run/postgresql -p 5432" && break
    sleep 1
done

su postgres -c "psql -q -h /run/postgresql -v ON_ERROR_STOP=1 -c \"DO \\\$\\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$PYLAI_DB_USER') THEN CREATE ROLE $PYLAI_DB_USER LOGIN PASSWORD '$PYLAI_DB_PASSWORD'; ELSE ALTER ROLE $PYLAI_DB_USER WITH LOGIN PASSWORD '$PYLAI_DB_PASSWORD'; END IF; END \\\$\\\$;\""
su postgres -c "psql -q -h /run/postgresql -tAc \"SELECT 1 FROM pg_database WHERE datname='$PYLAI_DB_NAME'\"" | grep -q 1 \
    || su postgres -c "createdb -h /run/postgresql -O $PYLAI_DB_USER $PYLAI_DB_NAME"

cat > /var/lib/pylai/redis.conf <<EOF_REDIS
bind 127.0.0.1
port 6379
save ""
appendonly no
requirepass $PYLAI_REDIS_PASSWORD
EOF_REDIS
chown redis:redis /var/lib/pylai/redis.conf
chmod 600 /var/lib/pylai/redis.conf

# CLI 命令会解析 Redis 状态缓存服务，先临时启动 Redis，命令完成后关闭，再由 supervisord 正式拉起。
su -s /bin/bash redis -c "redis-server /var/lib/pylai/redis.conf --daemonize yes --pidfile /run/redis.pid --dir /var/lib/pylai"
for i in $(seq 1 20); do
    redis-cli -p 6379 -a "$PYLAI_REDIS_PASSWORD" --no-auth-warning ping >/dev/null 2>&1 && break
    sleep 0.2
done

cd /opt/pylai
run_as_pylai ./Pylaios db migrate --config "$RUNTIME_CONFIG"
run_as_pylai ./Pylaios invite migrate-legacy --config "$RUNTIME_CONFIG"
run_as_pylai ./Pylaios db bootstrap --config "$RUNTIME_CONFIG"
run_as_pylai ./Pylaios db seed --config "$RUNTIME_CONFIG"
run_as_pylai ./Pylaios key reencrypt --config "$RUNTIME_CONFIG"
run_as_pylai ./Pylaios key rotate --if-empty --config "$RUNTIME_CONFIG"

redis-cli -p 6379 -a "$PYLAI_REDIS_PASSWORD" --no-auth-warning shutdown nosave >/dev/null 2>&1 \
    || kill "$(cat /run/redis.pid)" 2>/dev/null || true

echo "[pylai] 数据库与签名密钥检查完成，启动服务..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/pylai-server.conf

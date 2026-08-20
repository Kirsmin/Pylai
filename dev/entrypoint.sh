#!/bin/bash
set -euo pipefail

RUNTIME_CONFIG=/var/lib/pylai/pylai.toml
PG_VER=$(ls /usr/lib/postgresql | head -1)
PG_DATA=/var/lib/postgresql/$PG_VER/main
PG_BIN=/usr/lib/postgresql/$PG_VER/bin
SECRETS_FILE=/var/lib/pylai/.secrets
DP_KEK_FILE=/var/lib/pylai/dp-kek

mkdir -p /var/lib/pylai/log /run/supervisor /run/postgresql /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi
chown postgres:postgres /run/postgresql
chown www-data:www-data /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi

touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE"
# shellcheck disable=SC1090
. "$SECRETS_FILE"

append_secret() {
    local key="$1" value="$2"
    printf "%s='%s'\n" "$key" "$value" >> "$SECRETS_FILE"
}

if [ -z "${ADMIN_PASSWORD:-}" ]; then ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-12)Aa1"; append_secret ADMIN_PASSWORD "$ADMIN_PASSWORD"; fi
if [ -z "${USER_PASSWORD:-}" ]; then USER_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-12)Aa1"; append_secret USER_PASSWORD "$USER_PASSWORD"; fi
if [ -z "${MAX_PASSWORD:-}" ]; then MAX_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-12)Aa1"; append_secret MAX_PASSWORD "$MAX_PASSWORD"; fi
if [ -z "${CLIENT_SECRET:-}" ]; then CLIENT_SECRET="$(openssl rand -hex 16)"; append_secret CLIENT_SECRET "$CLIENT_SECRET"; fi
if [ -z "${INVITE_PEPPER:-}" ]; then INVITE_PEPPER="$(openssl rand -hex 32)"; append_secret INVITE_PEPPER "$INVITE_PEPPER"; fi
if [ -z "${SIGNING_KEK:-}" ]; then SIGNING_KEK="$(openssl rand -hex 32)"; append_secret SIGNING_KEK "$SIGNING_KEK"; fi

printf '%s' "$SIGNING_KEK" > /var/lib/pylai/signing-kek
chmod 600 /var/lib/pylai/signing-kek

# DataProtection KEK is intentionally separate from the signing KEK.
if [ ! -s "$DP_KEK_FILE" ]; then
    umask 077
    openssl rand 32 > "$DP_KEK_FILE"
fi
chmod 600 "$DP_KEK_FILE"
export PYLAI_DP_KEK_FILE="$DP_KEK_FILE"

UI_URL=${PYL_UI_URL:-http://localhost}
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
    if ! grep -qE '^local[[:space:]]+all[[:space:]]+pylai[[:space:]]+peer([[:space:]]|$)' "$PG_HBA"; then
        { echo "local all pylai peer"; cat "$PG_HBA"; } > "$PG_HBA.tmp"
        mv "$PG_HBA.tmp" "$PG_HBA"
        chown postgres:postgres "$PG_HBA"
    fi
    if ! grep -q "^host all all 127.0.0.1/32" "$PG_HBA"; then
        echo "host all all 127.0.0.1/32 scram-sha-256" >> "$PG_HBA"
    fi
    if ! grep -q "^host all all ::1/128" "$PG_HBA"; then
        echo "host all all ::1/128 scram-sha-256" >> "$PG_HBA"
    fi
else
    echo "local all pylai peer" > "$PG_HBA"
    echo "host all all 127.0.0.1/32 scram-sha-256" >> "$PG_HBA"
    echo "host all all ::1/128 scram-sha-256" >> "$PG_HBA"
    chown postgres:postgres "$PG_HBA"
fi
PG_START_OPTS="-h 127.0.0.1 -p 5432 -k /run/postgresql -c config_file=$PG_CONF -c hba_file=$PG_HBA"
su postgres -c "$PG_BIN/pg_ctl -D $PG_DATA -l /run/postgresql/pg.log -o \"$PG_START_OPTS\" start"

for i in $(seq 1 30); do
    su postgres -c "$PG_BIN/pg_isready -q -h /run/postgresql -p 5432" && break
    sleep 1
done
su postgres -c "psql -q -h /run/postgresql -v ON_ERROR_STOP=1 -c \"DO \\\$\\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='pylai') THEN CREATE ROLE pylai LOGIN; ELSE ALTER ROLE pylai WITH LOGIN; END IF; END \\\$\\\$;\""
su postgres -c "psql -q -h /run/postgresql -tAc \"SELECT 1 FROM pg_database WHERE datname='pylai'\"" | grep -q 1 \
    || su postgres -c "createdb -h /run/postgresql -O pylai pylai"

export ADMIN_PASSWORD USER_PASSWORD MAX_PASSWORD CLIENT_SECRET INVITE_PEPPER SIGNING_KEK UI_URL
python3 - <<'PY'
import os
import re
from pathlib import Path
from urllib.parse import urlparse

text = Path('/opt/pylai/pylai.example.toml').read_text(encoding='utf-8')
ui_origin = os.environ['UI_URL'].rstrip('/')
ui_host = urlparse(ui_origin).hostname or 'localhost'
ui_origins = list(dict.fromkeys([ui_origin, 'http://localhost:5173', 'http://localhost:5174']))
allowed_hosts = ['localhost', '127.0.0.1']
if ui_host not in allowed_hosts:
    allowed_hosts.append(ui_host)
allowed_hosts_toml = '[' + ', '.join(f'"{host}"' for host in allowed_hosts) + ']'

def block(name):
    start = text.index(f'[{name}]')
    return text[start:]

text = re.sub(r'^ConnectionString = ".*"$',
    'ConnectionString = "Host=/run/postgresql;Database=pylai;Username=pylai"',
    text, count=1, flags=re.M)
text = re.sub(r'^Url = "http://localhost:5000"$', 'Url = "http://0.0.0.0:5000"', text, count=1, flags=re.M)
text = re.sub(r'^Url = "http://localhost:5173"$', f'Url = "{os.environ["UI_URL"]}"', text, count=1, flags=re.M)
text = re.sub(r'^Issuer = "http://localhost:5000"$', f'Issuer = "{os.environ["UI_URL"]}"', text, count=1, flags=re.M)
text = re.sub(r'^AllowedHosts = \["localhost", "127.0.0.1"\]$', f'AllowedHosts = {allowed_hosts_toml}', text, count=1, flags=re.M)
text = re.sub(r'^TrustedProxies = \["127.0.0.1", "::1"\]$', 'TrustedProxies = ["127.0.0.1", "::1"]', text, count=1, flags=re.M)
text = re.sub(r'^TrustedNetworks = \[\]$', 'TrustedNetworks = ["172.16.0.0/12"]', text, count=1, flags=re.M)
text = re.sub(r'^ServerPepper = ""$', f'ServerPepper = "{os.environ["INVITE_PEPPER"]}"', text, count=1, flags=re.M)
text = re.sub(r'^KeyFile = ""$', 'KeyFile = "/var/lib/pylai/signing-kek"', text, count=1, flags=re.M)
text = re.sub(r'^RelyingPartyId = "localhost"$', f'RelyingPartyId = "{ui_host}"', text, count=1, flags=re.M)
text = re.sub(r'^Origins = \["http://localhost:5173"\]$', f'Origins = {ui_origins!r}'.replace("'", '"'), text, count=1, flags=re.M)
for section, env in (("Seeds.DefaultAdmin", "ADMIN_PASSWORD"), ("Seeds.DefaultUser", "USER_PASSWORD"), ("Seeds.DefaultMax", "MAX_PASSWORD")):
    seg = block(section)
    seg = seg.replace('Password = ""', f'Password = "{os.environ[env]}"', 1)
    text = text[:text.index(f'[{section}]')] + seg

Path('/var/lib/pylai/pylai.toml').write_text(text, encoding='utf-8')
os.chmod('/var/lib/pylai/pylai.toml', 0o600)
PY

cat > /var/lib/pylai/redis.conf <<EOF_REDIS
bind 127.0.0.1
port 6379
save ""
appendonly no
EOF_REDIS
chown -R pylai:pylai /var/lib/pylai
chown redis:redis /var/lib/pylai/redis.conf
chmod 600 /var/lib/pylai/redis.conf

su -s /bin/bash redis -c "redis-server /var/lib/pylai/redis.conf --daemonize yes --pidfile /run/redis.pid --dir /var/lib/pylai"
for i in $(seq 1 20); do
    redis-cli -p 6379 ping >/dev/null 2>&1 && break
    sleep 0.2
done

run_as_pylai() {
    local command
    command=$(printf '%q ' env ASPNETCORE_ENVIRONMENT=Development PYLAI_DP_KEK_FILE="$PYLAI_DP_KEK_FILE" "$@")
    su -s /bin/bash pylai -c "$command"
}
cd /opt/pylai
run_as_pylai ./Pylaios db migrate --config "$RUNTIME_CONFIG" > /dev/null
run_as_pylai ./Pylaios invite migrate-legacy --config "$RUNTIME_CONFIG" > /dev/null
run_as_pylai ./Pylaios db bootstrap --config "$RUNTIME_CONFIG" > /dev/null
run_as_pylai ./Pylaios db seed --config "$RUNTIME_CONFIG" > /dev/null
run_as_pylai ./Pylaios key reencrypt --config "$RUNTIME_CONFIG" > /dev/null
echo "[pylai] 数据库检查完成（migrate/bootstrap/seed 幂等执行）"

create_invite() {
    local group="$1"
    local key="INVITE_${group^^}_CODE"
    if [ -n "${!key:-}" ]; then return; fi
    local result code
    result=$(run_as_pylai ./Pylaios invite create "$group" --config "$RUNTIME_CONFIG")
    code=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["code"])' <<< "$result")
    echo "$key='$code'" >> "$SECRETS_FILE"
    printf -v "$key" '%s' "$code"
}
create_invite normal
create_invite admin
create_invite max

echo "[pylai] 检查 OAuth 测试客户端 pylai-console..."
if run_as_pylai ./Pylaios client show pylai-console --config "$RUNTIME_CONFIG" > /dev/null 2>&1; then
    echo "[pylai] 客户端 pylai-console 已存在，跳过创建"
else
    echo -n "$CLIENT_SECRET" | run_as_pylai ./Pylaios client create pylai-console \
        --name "pylai-console" --secret-stdin --type Confidential \
        --scopes openid,profile:basic,profile:mail,profile:role,offline_access \
        --grant-types authorization_code,client_credentials,refresh_token \
        --redirect-uris "http://localhost:5001/signin-oidc,http://localhost:5001/callback,https://oauth.pstmn.io/v1/callback,https://oauthdebugger.com/debug" \
        --post-logout-uris "http://localhost:5001/signout-callback-oidc" \
        --description "Pylai 的 Oauth2 测试客户端" --fajor --config "$RUNTIME_CONFIG" > /dev/null \
        && echo "[pylai] OAuth 测试客户端 pylai-console 已创建"
fi
redis-cli -p 6379 shutdown nosave >/dev/null 2>&1 || kill "$(cat /run/redis.pid)" 2>/dev/null || true

echo "================================================================"
echo "  Pylai Dev 实例就绪"
echo "  前端:  $UI_URL/     管理台: $UI_URL/admin/"
echo "  后端 API:  http://localhost:5000"
echo "  数据库: pylai（Unix socket peer 认证，无数据库密码）"
echo "  测试账号/OAuth/邀请码凭据已保存至 /var/lib/pylai/.secrets"
echo "  出于日志安全考虑，不在 stdout 打印任何明文凭据"
echo "================================================================"
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/pylai.conf

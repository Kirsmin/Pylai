#!/bin/bash


set -euo pipefail

PG_VER=$(ls /usr/lib/postgresql | head -1)
PG_DATA=/var/lib/postgresql/$PG_VER/main
PG_BIN=/usr/lib/postgresql/$PG_VER/bin

SECRETS_FILE=/var/lib/pylai/.secrets
if [ -f "$SECRETS_FILE" ]; then
    . "$SECRETS_FILE"
else
    DB_PASSWORD=$(openssl rand -hex 16)
    ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '=+/')
    USER_PASSWORD=$(openssl rand -base64 12 | tr -d '=+/')
    MAX_PASSWORD=$(openssl rand -base64 12 | tr -d '=+/')
    CLIENT_SECRET=$(openssl rand -hex 16)
    {
        echo "DB_PASSWORD='$DB_PASSWORD'"
        echo "ADMIN_PASSWORD='$ADMIN_PASSWORD'"
        echo "USER_PASSWORD='$USER_PASSWORD'"
        echo "MAX_PASSWORD='$MAX_PASSWORD'"
        echo "CLIENT_SECRET='$CLIENT_SECRET'"
    } > "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"
fi
UI_URL=${PYL_UI_URL:-http://localhost}


if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    echo "[pylai] 初始化 PostgreSQL 数据目录..."
    su postgres -c "$PG_BIN/initdb -D $PG_DATA --auth-local=peer --auth-host=md5 --username=postgres"
fi


HBA=/etc/postgresql/$PG_VER/main/pg_hba.conf
if [ -f "$HBA" ]; then
    grep -v "^host all all 127.0.0.1/32" "$HBA" > /tmp/pg_hba_dev
    echo "host all all 127.0.0.1/32 md5" >> /tmp/pg_hba_dev
    mv /tmp/pg_hba_dev "$HBA"
    chown postgres:postgres "$HBA"
else
    echo "host all all 127.0.0.1/32 md5" >> "$PG_DATA/pg_hba.conf"
fi

if [ -f "/etc/postgresql/$PG_VER/main/postgresql.conf" ]; then
    su postgres -c "pg_ctlcluster $PG_VER main start"
else
    su postgres -c "$PG_BIN/pg_ctl -D $PG_DATA -l /var/log/pylai/pg.log start"
fi
for i in $(seq 1 30); do
    su postgres -c "$PG_BIN/pg_isready -q" && break
    sleep 1
done


su postgres -c "psql -q -v ON_ERROR_STOP=1 -c \"DO \\\$\\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='pylai') THEN CREATE ROLE pylai LOGIN PASSWORD '$DB_PASSWORD'; ELSE ALTER ROLE pylai WITH LOGIN PASSWORD '$DB_PASSWORD'; END IF; END \\\$\\\$;\""
su postgres -c "psql -q -tAc \"SELECT 1 FROM pg_database WHERE datname='pylai'\"" | grep -q 1 \
    || su postgres -c "createdb -O pylai pylai"


export DB_PASSWORD ADMIN_PASSWORD USER_PASSWORD MAX_PASSWORD CLIENT_SECRET UI_URL
python3 - <<'EOF'
import os
p = "/opt/pylai/pylai.example.toml"
text = open(p, encoding="utf-8").read()

def block(name):
    start = text.index(f"[{name}]")
    return text[start:]


import re
text = re.sub(r'^ConnectionString = ".*"$',
    f'ConnectionString = "Host=127.0.0.1;Port=5432;Database=pylai;Username=pylai;Password={os.environ["DB_PASSWORD"]}"',
    text, count=1, flags=re.M)


text = re.sub(r'^Url = "http://localhost:5000"$', 'Url = "http://0.0.0.0:5000"', text, count=1, flags=re.M)
text = re.sub(r'^Url = "http://localhost:5173"$', f'Url = "{os.environ["UI_URL"]}"', text, count=1, flags=re.M)


text = re.sub(r'^ForwardedHeadersEnabled = false$', 'ForwardedHeadersEnabled = true', text, count=1, flags=re.M)
text = re.sub(r'^TrustedProxies = \[\]$', 'TrustedProxies = ["127.0.0.1"]', text, count=1, flags=re.M)
text = re.sub(r'^TrustedNetworks = \[\]$', 'TrustedNetworks = ["172.16.0.0/12"]', text, count=1, flags=re.M)


for section, env in (("Seeds.DefaultAdmin", "ADMIN_PASSWORD"), ("Seeds.DefaultUser", "USER_PASSWORD"), ("Seeds.DefaultMax", "MAX_PASSWORD")):
    seg = block(section)
    seg = seg.replace('Password = ""', f'Password = "{os.environ[env]}"', 1)
    text = text[:text.index(f"[{section}]")] + seg

open("/etc/pylai/pylai.toml", "w", encoding="utf-8").write(text)
EOF


cd /opt/pylai
./Pylaios db migrate --config /etc/pylai/pylai.toml > /dev/null
./Pylaios db bootstrap --config /etc/pylai/pylai.toml > /dev/null
./Pylaios db seed --config /etc/pylai/pylai.toml > /dev/null
echo "[pylai] 数据库检查完成（migrate/bootstrap/seed 幂等执行）"


echo "[pylai] 检查 OAuth 测试客户端 pylai-console..."
if ./Pylaios client show pylai-console --config /etc/pylai/pylai.toml > /dev/null 2>&1; then
    echo "[pylai] 客户端 pylai-console 已存在，跳过创建"
else
    echo -n "$CLIENT_SECRET" | ./Pylaios client create pylai-console \
        --name "pylai-console" \
        --secret-stdin \
        --type Confidential \
        --scopes openid,profile:basic,profile:mail,profile:role,offline_access \
        --grant-types authorization_code,client_credentials,refresh_token \
        --redirect-uris "http://localhost:5001/signin-oidc,http://localhost:5001/callback,https://oauth.pstmn.io/v1/callback,https://oauthdebugger.com/debug" \
        --post-logout-uris "http://localhost:5001/signout-callback-oidc" \
        --description "Pylai 的 Oauth2 测试客户端" \
        --fajor \
        --config /etc/pylai/pylai.toml > /dev/null \
        && echo "[pylai] OAuth 测试客户端 pylai-console 已创建"
fi


echo "[pylai] 检查 OAuth 管理台客户端 pylai-admin..."
ADMIN_REDIRECT_URI="${UI_URL}/admin/"
ADMIN_DEV_REDIRECT_URI="http://localhost:5174/admin/"
if ./Pylaios client show pylai-admin --config /etc/pylai/pylai.toml > /dev/null 2>&1; then
    echo "[pylai] 客户端 pylai-admin 已存在，按当前 UI_URL 更新 redirect URI"
    ./Pylaios client update pylai-admin \
        --redirect-uris "$ADMIN_REDIRECT_URI,$ADMIN_DEV_REDIRECT_URI" \
        --post-logout-uris "$ADMIN_REDIRECT_URI" \
        --config /etc/pylai/pylai.toml > /dev/null
else
    ./Pylaios client create pylai-admin \
        --name "Pylai 管理台" \
        --type Public \
        --scopes openid,profile:basic,profile:mail,profile:role,offline_access \
        --grant-types authorization_code,refresh_token \
        --redirect-uris "$ADMIN_REDIRECT_URI,$ADMIN_DEV_REDIRECT_URI" \
        --post-logout-uris "$ADMIN_REDIRECT_URI" \
        --description "Pylai 管理台（AdminUI），Public OAuth 客户端，使用 PKCE" \
        --fajor \
        --config /etc/pylai/pylai.toml > /dev/null \
        && echo "[pylai] OAuth 管理台客户端 pylai-admin 已创建（Public/PKCE，无需 secret）"
fi


echo "================================================================"
echo "  Pylai Dev 实例就绪"
echo "  前端:  $UI_URL/     管理台: $UI_URL/admin/"
echo "  后端 API:  http://localhost:5000"
echo "  数据库: pylai / pylai / $DB_PASSWORD"
echo "  Max 账号: max@pylaios.local / $MAX_PASSWORD"
echo "  管理员: admin@pylaios.local / $ADMIN_PASSWORD"
echo "  普通用户: user@pylaios.local / $USER_PASSWORD"
echo "  OAuth 客户端: pylai-console / $CLIENT_SECRET"
echo "  管理台客户端: pylai-admin（Public/PKCE，无需 secret）"
echo "================================================================"


exec /usr/bin/supervisord -c /etc/supervisor/conf.d/pylai.conf

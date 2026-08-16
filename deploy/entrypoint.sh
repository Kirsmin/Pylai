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
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[pylai] 配置文件不存在: $CONFIG_FILE" >&2
    exit 1
fi
chmod 600 "$CONFIG_FILE"

PG_VER=$(ls /usr/lib/postgresql | head -1)
PG_DATA=/var/lib/postgresql/$PG_VER/main
PG_BIN=/usr/lib/postgresql/$PG_VER/bin

if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    echo "[pylai] 初始化 PostgreSQL 数据目录..."
    su postgres -c "$PG_BIN/initdb -D $PG_DATA --auth-local=peer --auth-host=md5 --username=postgres"
fi

HBA=/etc/postgresql/$PG_VER/main/pg_hba.conf
if [ -f "$HBA" ]; then
    grep -v "^host all all 127.0.0.1/32" "$HBA" > /tmp/pg_hba_server
    echo "host all all 127.0.0.1/32 md5" >> /tmp/pg_hba_server
    mv /tmp/pg_hba_server "$HBA"
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

su postgres -c "psql -q -v ON_ERROR_STOP=1 -c \"DO \\\$\\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$PYLAI_DB_USER') THEN CREATE ROLE $PYLAI_DB_USER LOGIN PASSWORD '$PYLAI_DB_PASSWORD'; ELSE ALTER ROLE $PYLAI_DB_USER WITH LOGIN PASSWORD '$PYLAI_DB_PASSWORD'; END IF; END \\\$\\\$;\""
su postgres -c "psql -q -tAc \"SELECT 1 FROM pg_database WHERE datname='$PYLAI_DB_NAME'\"" | grep -q 1 \
    || su postgres -c "createdb -O $PYLAI_DB_USER $PYLAI_DB_NAME"

mkdir -p /etc/redis
cat > /etc/redis/pylai.conf <<EOF_REDIS
bind 127.0.0.1
port 6379
save ""
appendonly no
requirepass $PYLAI_REDIS_PASSWORD
EOF_REDIS

ln -sf /etc/nginx/sites-available/pylai-server /etc/nginx/sites-enabled/pylai
rm -f /etc/nginx/sites-enabled/default

cd /opt/pylai
./Pylaios db migrate --config "$CONFIG_FILE"
./Pylaios db bootstrap --config "$CONFIG_FILE"
./Pylaios db seed --config "$CONFIG_FILE"
./Pylaios key rotate --if-empty --config "$CONFIG_FILE"

UI_URL="${PYLAI_UI_URL:-http://localhost}"
ADMIN_REDIRECT_URI="${UI_URL%/}/admin/"
if ./Pylaios client show pylai-admin --config "$CONFIG_FILE" > /dev/null 2>&1; then
    ./Pylaios client update pylai-admin --redirect-uris "$ADMIN_REDIRECT_URI" --post-logout-uris "$ADMIN_REDIRECT_URI" --config "$CONFIG_FILE" > /dev/null
else
    ./Pylaios client create pylai-admin \
        --name "Pylai 管理台" \
        --type Public \
        --scopes openid,profile:basic,profile:mail,profile:role,offline_access \
        --grant-types authorization_code,refresh_token \
        --redirect-uris "$ADMIN_REDIRECT_URI" \
        --post-logout-uris "$ADMIN_REDIRECT_URI" \
        --description "Pylai 管理台（Public OAuth 客户端，使用 PKCE）" \
        --fajor \
        --config "$CONFIG_FILE" > /dev/null
fi

echo "[pylai] 数据库、签名密钥与管理台客户端检查完成，启动服务..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/pylai-server.conf

# syntax=docker/dockerfile:1

ARG PYLAI_VERSION=0.0.1
ARG PYLAI_DB_SCHEMA=dev

FROM node:24 AS ui
WORKDIR /ui
RUN corepack enable
COPY UI/package.json UI/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY UI/ ./
RUN pnpm build

FROM node:24 AS admin-ui
WORKDIR /adminui
RUN corepack enable
COPY AdminUI/package.json AdminUI/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY AdminUI/ ./
RUN pnpm build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS backend
WORKDIR /src
COPY OS/ ./
RUN dotnet publish Pylaios.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql redis-server nginx supervisor openssl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ui /ui/dist /opt/pylai/ui
COPY --from=admin-ui /adminui/dist /opt/pylai/adminui
COPY --from=backend /app /opt/pylai
ARG PYLAI_VERSION
ARG PYLAI_DB_SCHEMA
COPY OS/pylai.example.toml /opt/pylai/pylai.example.toml
COPY dev/entrypoint.sh /usr/local/bin/pylai-dev-entrypoint
COPY dev/nginx.conf /etc/nginx/sites-available/pylai-dev
COPY dev/supervisord.conf /etc/supervisor/conf.d/pylai.conf
COPY deploy/entrypoint.sh /usr/local/bin/pylai-entrypoint
COPY deploy/nginx.conf /etc/nginx/sites-available/pylai-server
COPY deploy/supervisord.conf /etc/supervisor/conf.d/pylai-server.conf

LABEL org.opencontainers.image.version="${PYLAI_VERSION}" \
      org.opencontainers.image.title="Pylai" \
      pylai.role="server" \
      pylai.db-schema="${PYLAI_DB_SCHEMA}"

RUN chmod +x /usr/local/bin/pylai-entrypoint /usr/local/bin/pylai-dev-entrypoint \
    && ln -sf /etc/nginx/sites-available/pylai-dev /etc/nginx/sites-enabled/pylai \
    && rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /etc/pylai /var/log/pylai /var/lib/pylai \
    && chown -R postgres:postgres /var/lib/postgresql

EXPOSE 80 5000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1/health/ready', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/pylai-entrypoint"]

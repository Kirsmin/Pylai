#!/usr/bin/env python3
"""ManagePylai 网页配置编辑器与配置规则。"""

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

from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Any, Literal, Self, TypeVar
from urllib.parse import urlparse

from managepylai_core import (
    CONFIG_FILE,
    Json,
    ManageError,
    PYLAI_CONFIG_ARG,
    TomlText,
    _toml_section_span,
    atomic_write,
    is_valid_cidr,
    is_valid_ip,
    is_valid_url,
    mask_config_text,
    toml_str,
)

def find_free_port() -> int:
    """获取一个 127.0.0.1 上当前无占用的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def generate_editor_password() -> str:
    """临时密码：前四位大写字母，后四位数字，例如 PAHE-0123。"""
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return f"{letters}-{digits}"


def editor_value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string"


def serialize_editor_value(change: Json) -> str:
    """把网页端提交的 JSON 值序列化为 TOML 字面量。"""
    kind = change.get("type")
    value = change.get("value")

    if kind == "boolean":
        return "true" if value else "false"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not _finite_number(value):
            raise ManageError(f"数值类型非法: {value!r}")
        return str(value)
    if kind == "array":
        items = value if isinstance(value, list) else []
        parts = [
            str(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and _finite_number(x) else toml_str(str(x))
            for x in items
        ]
        return f"[{', '.join(parts)}]"
    return toml_str("" if value is None else str(value))


def strip_multiline_value(text: str, marker: str, key: str) -> str:
    """替换多行字符串（''' / \"\"\"）前，先移除其续行，避免残留导致 TOML 非法。"""
    try:
        start, end = _toml_section_span(text, marker)
    except ValueError:
        return text

    block = text[start:end]
    lines = block.splitlines(keepends=True)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(?P<rhs>.*)$")

    for index, line in enumerate(lines):
        match = key_re.match(line)
        if not match:
            continue
        rhs = match.group("rhs")
        opener = re.match(r"^('''|\"\"\")", rhs)
        if not opener or opener.group(1) in rhs[3:]:
            return text  # 单行值，无需处理
        quote = opener.group(1)
        for tail in range(index + 1, len(lines)):
            if quote in lines[tail]:
                del lines[index + 1 : tail + 1]
                break
        return text[:start] + "".join(lines) + text[end:]

    return text


# ============================================================================
# 配置字段校验规则（白名单，与后端 OS/Features/Config/ConfigValidator.cs 对齐）
# 每条规则含中文说明 desc（下发前端展示）与校验约束（前端实时 + 服务端保存前双重校验）
# ============================================================================
def _bool(desc: str) -> Json:
    """布尔值：无需额外约束，仅保证类型。"""
    return {"kind": "boolean", "desc": desc}


def _num(desc: str, lo: int, hi: int, *, neg1: bool = False) -> Json:
    """数值：限制范围 [lo, hi]，neg1 表示允许 -1（如永久封禁）。"""
    rule: Json = {"kind": "number", "desc": desc, "min": lo, "max": hi}
    if neg1:
        rule["allowNegOne"] = True
    return rule


def _enum(desc: str, values: list[str]) -> Json:
    """枚举：值必须在可选列表内。"""
    return {"kind": "enum", "desc": desc, "enum": values}


def _url(desc: str, *, no_path: bool = False) -> Json:
    """URL：必须为 http(s)://host[:port]，no_path 要求不带路径。"""
    return {"kind": "url", "desc": desc, "noPath": no_path}


def _ip(desc: str) -> Json:
    return {"kind": "ip", "desc": desc}


def _cidr(desc: str) -> Json:
    return {"kind": "cidr", "desc": desc}


def _str(desc: str, *, required: bool = False, require_placeholder: str | None = None) -> Json:
    rule: Json = {"kind": "string", "desc": desc}
    if required:
        rule["required"] = True
    if require_placeholder:
        rule["requirePlaceholder"] = require_placeholder
    return rule


def _arr(desc: str, elem: str, **extra: Any) -> Json:
    """数组：元素按 elem（url/ip/cidr/number/string）逐个校验。"""
    rule: Json = {"kind": "array", "desc": desc, "arrayKind": elem, **extra}
    return rule


EDITOR_RULES: dict[str, Json] = {
    # ---- 服务监听 ----
    "Server.Url": _url("后端监听地址，形如 http://0.0.0.0:5000，不带路径", no_path=True),
    "Server.AllowedHosts": _arr("允许的请求 Host 白名单（生产禁止使用 *）", "string", required=True),
    "Server.MaxRequestBodyMB": _num("单个请求体最大体积（MB），默认 2", 1, 1024),

    # ---- 跨域 ----
    "Cors.Enabled": _bool("是否启用 CORS"),
    "Cors.AllowedOrigins": _arr("允许跨域的前端 Origin 列表", "url"),
    "Cors.AllowedMethods": _arr("允许的 HTTP 方法", "string"),
    "Cors.AllowedHeaders": _arr("允许的请求头", "string"),
    "Cors.AllowCredentials": _bool("是否允许携带 Cookie 凭证（开启时禁止通配符 *）"),

    # ---- 前端地址 ----
    "Frontend.Url": _url("浏览器访问 Pylai 的公开地址"),

    # ---- IP 解析 ----
    "IpResolution.TrustedProxies": _arr("可信反向代理 IP 列表", "ip"),
    "IpResolution.TrustedHeaders": _arr("可信的转发请求头", "string"),
    "IpResolution.IpWhitelist": _arr("IP 白名单（空为不限制）", "ip"),
    "IpResolution.ForwardedHeadersEnabled": _bool("是否启用转发请求头解析"),
    "IpResolution.TrustedNetworks": _arr("可信代理 CIDR 网段列表", "cidr"),

    # ---- 数据库 ----
    "Database.ConnectionString": _str("PostgreSQL 连接串（含密码，保存后不可见）", required=True),

    # ---- Redis ----
    "Redis.Host": _str("Redis 主机地址", required=True),
    "Redis.Port": _num("Redis 端口", 1, 65535),
    "Redis.Password": _str("Redis 密码（不能为弱口令）"),
    "Redis.Database": _num("Redis 数据库编号（0-15）", 0, 15),
    "Redis.ConnectTimeoutMs": _num("Redis 连接超时（毫秒）", 1, 600000),

    # ---- 备份 ----
    "Backup.Directory": _str("备份文件保存目录", required=True),

    # ---- 身份 ----
    "Identity.EmailCodeExpireMinutes": _num("邮箱验证码有效期（分钟）", 1, 60),
    "Identity.Password.RequiredLength": _num("普通用户密码最短长度", 4, 128),
    "Identity.Password.AdminRequiredLength": _num("Admin/Max 密码最短长度", 4, 128),
    "Identity.Password.CheckBreachedPasswords": _bool("是否校验密码已泄露（HIBP）"),
    "Identity.Password.RequireDigit": _bool("密码是否必须包含数字"),
    "Identity.Password.RequireLowercase": _bool("密码是否必须包含小写字母"),
    "Identity.Password.RequireUppercase": _bool("密码是否必须包含大写字母"),
    "Identity.Password.RequireNonAlphanumeric": _bool("密码是否必须包含特殊字符"),
    "Identity.Lockout.DefaultTimeoutMinutes": _num("登录失败锁定时长（分钟）", 1, 1440),
    "Identity.Lockout.MaxFailedAttempts": _num("触发锁定前的连续失败次数", 1, 100),

    # ---- Cookie ----
    "Cookie.Name": _str("身份认证 Cookie 名称", required=True),
    "Cookie.SessionName": _str("会话 Cookie 名称", required=True),
    "Cookie.HttpOnly": _bool("Cookie 是否禁止 JS 读取"),
    "Cookie.SameSite": _enum("SameSite 策略", ["Unspecified", "None", "Lax", "Strict"]),
    "Cookie.SecurePolicy": _enum("Cookie 安全策略", ["None", "Always", "SameAsRequest"]),
    "Cookie.ExpireDays": _num("登录有效期（天）", 1, 365),
    "Cookie.SlidingExpiration": _bool("是否滑动续期"),

    # ---- 数据保护 ----
    "DataProtection.KeyDirectory": _str("DataProtection 密钥目录（生产必须持久化）", required=True),

    # ---- 部署 ----
    "Deployment.BundledNginx": _bool("是否由镜像内置 Nginx 反代"),

    # ---- OpenIddict ----
    "OpenIddict.Issuer": _url("OIDC 颁发者地址，不带路径", no_path=True),
    "OpenIddict.RequireHttps": _bool("是否强制 HTTPS（开启后 Issuer 必须为 https）"),
    "OpenIddict.AccessToken.LifetimeHours": _num("访问令牌有效期（小时）", 1, 720),
    "OpenIddict.AccessToken.DisableEncryption": _bool("是否禁用访问令牌加密"),
    "OpenIddict.RefreshToken.LifetimeDays": _num("刷新令牌有效期（天）", 1, 365),
    "OpenIddict.IdentityToken.LifetimeHours": _num("身份令牌有效期（小时）", 1, 720),
    "OpenIddict.Endpoints.Authorize": _str("授权端点路径", required=True),
    "OpenIddict.Endpoints.Token": _str("令牌端点路径", required=True),
    "OpenIddict.Endpoints.UserInfo": _str("UserInfo 端点路径", required=True),
    "OpenIddict.Endpoints.Introspect": _str("内省端点路径", required=True),
    "OpenIddict.Endpoints.EndSession": _str("登出端点路径", required=True),
    "OpenIddict.Grants.AuthorizationCode": _bool("启用授权码授权"),
    "OpenIddict.Grants.RefreshToken": _bool("启用刷新令牌"),
    "OpenIddict.Grants.ClientCredentials": _bool("启用客户端凭证"),
    "OpenIddict.Scopes.openId": _bool("启用 openid scope"),
    "OpenIddict.Scopes.profileBasic": _bool("启用 profile:basic scope"),
    "OpenIddict.Scopes.profileMail": _bool("启用 profile:mail scope"),
    "OpenIddict.Scopes.profileRole": _bool("启用 profile:role scope"),
    "OpenIddict.Scopes.offlineAccess": _bool("启用 offline_access scope"),
    "OpenIddict.Certificates.Signing.Path": _str("签名证书 PFX 路径（数据库托管签名时可为空）"),
    "OpenIddict.Certificates.Signing.Password": _str("签名证书 PFX 密码"),
    "OpenIddict.Certificates.Encryption.Path": _str("加密证书 PFX 路径（生产环境必需）"),
    "OpenIddict.Certificates.Encryption.Password": _str("加密证书 PFX 密码"),
    "OpenIddict.SigningKeyEncryption.KeyFile": _str("签名密钥加密 KEK 文件路径（数据库托管签名时必需）"),

    # ---- 第三方登录 ----
    "ExternalLogin.Facebook.AppId": _str("Facebook AppId（留空关闭）"),
    "ExternalLogin.Facebook.AppSecret": _str("Facebook AppSecret"),
    "ExternalLogin.Microsoft.ClientId": _str("Microsoft ClientId（留空关闭）"),
    "ExternalLogin.Microsoft.ClientSecret": _str("Microsoft ClientSecret"),
    "ExternalLogin.Github.ClientId": _str("GitHub ClientId（留空关闭）"),
    "ExternalLogin.Github.ClientSecret": _str("GitHub ClientSecret"),

    # ---- 邮件 ----
    "Email.FromName": _str("发件人显示名称"),
    "Email.FromAddress": _str("发件人邮箱（与 SMTP Host 同空或同配）"),
    "Email.Smtp.Host": _str("SMTP 服务器地址（与 FromAddress 同空或同配）"),
    "Email.Smtp.Port": _num("SMTP 端口（465 隐式 TLS / 587 STARTTLS / 25 明文）", 1, 65535),
    "Email.Smtp.Security": _enum("SMTP 加密方式", ["None", "StartTls", "SslOnConnect"]),
    "Email.Smtp.Username": _str("SMTP 用户名（无认证留空）"),
    "Email.Smtp.Password": _str("SMTP 密码（无认证留空）"),

    # ---- 邮件模板 ----
    "MailTheme.Register.Title": _str("注册邮件标题", required=True),
    "MailTheme.Register.Context": _str("注册邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.Bind.Title": _str("绑定邮箱邮件标题", required=True),
    "MailTheme.Bind.Context": _str("绑定邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.Change.Title": _str("更换邮箱邮件标题", required=True),
    "MailTheme.Change.Context": _str("更换邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),
    "MailTheme.PasswordReset.Title": _str("密码重置邮件标题", required=True),
    "MailTheme.PasswordReset.Context": _str("密码重置邮件正文（必须包含 %%CaptchaCode%%）", required=True, require_placeholder="%%CaptchaCode%%"),

    # ---- 日志 ----
    "Logging.DefaultLevel": _enum("默认日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),
    "Logging.MicrosoftAspNetCoreLevel": _enum("ASP.NET Core 框架日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),
    "Logging.PylaiosLevel": _enum("Pylaios 日志级别", ["Trace", "Debug", "Information", "Warning", "Error", "Critical", "None"]),

    # ---- 清理 ----
    "TokenCleanup.Enabled": _bool("是否定期清理过期 Token"),

    # ---- 登录限流 ----
    "LoginRateLimit.MaxFailuresPerIp": _num("单个 IP 触发封禁的失败次数", 1, 1000),
    "LoginRateLimit.BanDurationMinutes": _arr("逐级封禁时长（分钟，-1 为永久）", "number", arrayMin=1, allowNegOne=True),
    "LoginRateLimit.CooldownDays": _num("封禁冷却天数（0 为不冷却）", 0, 365),

    # ---- 管理 API 限流 ----
    "AdminRateLimit.MaxFailuresFirstBan": _num("管理 API 首次封禁失败次数", 1, 100),
    "AdminRateLimit.FirstBanDurationSeconds": _num("管理 API 首次封禁时长（秒）", 1, 3600),
    "AdminRateLimit.MaxFailuresSecondBan": _num("管理 API 二次封禁失败次数", 1, 1000),
    "AdminRateLimit.SecondBanDurationHours": _num("管理 API 二次封禁时长（小时）", 1, 8760),

    # ---- 邀请码 ----
    "InviteCode.ServerPepper": _str("邀请码 HMAC 密钥（生产必须配置）", required=True),
    "InviteCode.MaxFailuresPerIp": _num("单 IP 邀请码失败次数上限", 1, 1000),
    "InviteCode.BanDurationHours": _num("邀请码失败封禁时长（小时）", 1, 8760),
    "InviteCode.EmailCodeBanDurationHours": _num("邮箱验证码失败封禁时长（小时）", 1, 8760),
    "InviteCode.UsernameCheckMaxPerHourPerIp": _num("单 IP 每小时用户名检查次数上限", 1, 10000),
    "InviteCode.MaxRedemptions": _num("单个邀请码最大核销次数", 1, 100000),
    "InviteCode.DefaultLifetimeHours": _num("邀请码默认有效期（小时）", 1, 8760),

    # ---- 种子账号 ----
    "Seeds.DefaultAdmin.Email": _str("初始 Admin 邮箱/登录名"),
    "Seeds.DefaultAdmin.Password": _str("初始 Admin 密码（留空由后端按策略生成）"),
    "Seeds.DefaultAdmin.DisplayName": _str("初始 Admin 显示名"),
    "Seeds.DefaultUser.Email": _str("初始 Normal 邮箱/登录名"),
    "Seeds.DefaultUser.Password": _str("初始 Normal 密码（留空由后端按策略生成）"),
    "Seeds.DefaultUser.DisplayName": _str("初始 Normal 显示名"),
    "Seeds.DefaultMax.Email": _str("初始 Max 邮箱/登录名"),
    "Seeds.DefaultMax.Password": _str("初始 Max 密码（留空由后端按策略生成）"),
    "Seeds.DefaultMax.DisplayName": _str("初始 Max 显示名"),

    # ---- 用户 Token ----
    "UserToken.DefaultLifetimeDays": _num("用户 Token 默认有效期（天，0 为永久，生产上限 90）", 0, 90),

    # ---- 二次验证限流 ----
    "ConfirmationRateLimit.MaxFailures": _num("特殊功能二次验证失败次数上限", 1, 1000),
    "ConfirmationRateLimit.BanDurationHours": _num("二次验证失败封禁时长（小时）", 1, 8760),

    # ---- MFA ----
    "Mfa.RelyingPartyId": _str("WebAuthn 依赖方 ID（通常为域名，必填）", required=True),
    "Mfa.RelyingPartyName": _str("WebAuthn 依赖方显示名称"),
    "Mfa.Origins": _arr("WebAuthn 允许的 Origin 列表（必填，不带路径）", "url", noPath=True, required=True),
    "Mfa.ChallengeLifetimeMinutes": _num("MFA 挑战有效期（分钟）", 1, 60),
    "Mfa.RequireForAdmin": _bool("Admin 及以上角色是否强制 MFA"),
    "Mfa.RequireWebAuthnForMax": _bool("Max 角色是否强制使用 WebAuthn（需 HTTPS）"),

    # ---- AltCHA ----
    "Altcha.Enabled": _bool("是否启用 AltCHA 人机验证（PoW）"),
    "Altcha.SecretKey": _str("AltCHA HMAC 密钥（启用时必填，建议 32+ 字节随机串，可用环境变量 PYLAI_ALTCHA_SECRET 覆盖）"),
    "Altcha.MaxNumber": _num("AltCHA PoW 难度上限（越大计算越久，建议 50万~200万）", 1000, 10_000_000),
    "Altcha.ExpirySeconds": _num("AltCHA Challenge 有效期（秒）", 30, 3600),
}

# 密码弱值（与 deploy/entrypoint.py WEAK_SECRETS 保持一致）
EDITOR_WEAK_SECRETS = {"change-me", "changeme", "password", "secret", "123456", "pylai"}
DB_PASSWORD_RE = re.compile(r"Password=([^;]+)")  # 仅用于连接串弱口令检测


def _finite_number(value: Any) -> bool:
    """过滤 NaN / Infinity 等非法数值（Python 会序列化它们进 TOML 造成启动失败）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == float(value) and abs(float(value)) != float("inf")


def _value_error(message: str) -> list[str]:
    return [message] if message else []


def _check_scalar(rule: Json, value: Any) -> list[str]:
    """按规则校验单个标量值，返回错误文案列表。"""
    kind = rule.get("kind")
    errors: list[str] = []

    if kind == "boolean":
        return errors

    if kind == "number":
        if not _finite_number(value):
            return [f"必须是有限数字（不能为 NaN / Infinity）"]
        lo, hi = rule.get("min"), rule.get("max")
        if rule.get("allowNegOne") and value == -1:
            return errors
        if lo is not None and value < lo:
            errors.append(f"不能小于 {lo}")
        if hi is not None and value > hi:
            errors.append(f"不能大于 {hi}")
        return errors

    if kind == "enum":
        allowed = rule.get("enum", [])
        if value not in allowed:
            return [f"必须是以下之一: {', '.join(allowed)}"]
        return errors

    if kind in ("url", "ip", "cidr"):
        if not isinstance(value, str) or not value.strip():
            return [f"{kind.upper()} 不能为空"]
        value = value.strip()
        if kind == "url":
            if not is_valid_url(value):
                return ["不是合法 URL（应为 http(s)://host[:port]）"]
            if rule.get("noPath") and urlparse(value).path not in ("", "/"):
                return ["不允许包含路径（应为 http(s)://host[:port]）"]
        elif kind == "ip":
            if not is_valid_ip(value):
                return [f"不是合法 IP: {value}"]
        elif kind == "cidr":
            if not is_valid_cidr(value):
                return [f"不是合法 CIDR: {value}"]
        return errors

    if kind == "string":
        if not isinstance(value, str):
            return ["必须是字符串"]
        if rule.get("required") and not value.strip():
            return ["不能为空"]
        if rule.get("requirePlaceholder") and rule["requirePlaceholder"] not in value:
            return [f"必须包含占位符 {rule['requirePlaceholder']}"]
        if rule.get("pattern") and not re.fullmatch(rule["pattern"], value):
            return [f"格式不合法: {value}"]
        return errors

    return errors


def _check_array(rule: Json, value: Any) -> list[str]:
    """按规则校验数组（及数组内元素）。"""
    if not isinstance(value, list):
        return ["必须是列表"]

    if rule.get("required") and not value:
        return ["不能为空"]

    elem = rule.get("arrayKind", "string")
    errors: list[str] = []
    for index, item in enumerate(value):
        if elem == "url":
            if not (isinstance(item, str) and is_valid_url(item)):
                errors.append(f"第 {index + 1} 项不是合法 URL: {item}")
            elif rule.get("noPath") and urlparse(item).path not in ("", "/"):
                errors.append(f"第 {index + 1} 项不允许包含路径: {item}")
        elif elem == "ip":
            if not (isinstance(item, str) and is_valid_ip(item)):
                errors.append(f"第 {index + 1} 项不是合法 IP: {item}")
        elif elem == "cidr":
            if not (isinstance(item, str) and is_valid_cidr(item)):
                errors.append(f"第 {index + 1} 项不是合法 CIDR: {item}")
        elif elem == "number":
            if not _finite_number(item):
                errors.append(f"第 {index + 1} 项不是有效数字: {item}")
                continue
            if rule.get("allowNegOne") and item == -1:
                continue
            lo, hi = rule.get("arrayMin"), rule.get("arrayMax")
            if lo is not None and item < lo:
                errors.append(f"第 {index + 1} 项不能小于 {lo}")
            if hi is not None and item > hi:
                errors.append(f"第 {index + 1} 项不能大于 {hi}")
        elif elem == "string":
            if not isinstance(item, str):
                errors.append(f"第 {index + 1} 项必须是字符串")
    return errors


def check_rule(rule: Json, value: Any) -> list[str]:
    """按规则校验一个值（数组走 _check_array，其余走 _check_scalar）。"""
    if rule.get("kind") == "array":
        return _check_array(rule, value)
    return _check_scalar(rule, value)


def extract_connection_string_password(connection_string: str) -> str:
    """从连接串中提取密码，仅用于弱口令检测。"""
    if m := DB_PASSWORD_RE.search(connection_string):
        return m.group(1).strip()
    return ""


def weak_secret_hit(value: str) -> bool:
    """命中已知弱值清单则拒绝（与后端 ProductionSecurityGate / entrypoint 一致）。"""
    return value.strip().lower() in EDITOR_WEAK_SECRETS


def validate_full_text(text: str) -> list[tuple[str, str, str]]:
    """对整份配置做语义校验（与后端四阶段校验对齐，Fail Closed）。

    返回 [(section, key, 错误信息)]，空列表表示通过。
    """
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [("", "", f"配置不是合法 TOML: {exc}")]

    issues: list[tuple[str, str, str]] = []

    def visit(path: str, table: dict[str, Any]) -> None:
        for key, value in table.items():
            if isinstance(value, dict):
                visit(f"{path}.{key}" if path else key, value)
                continue
            rule = EDITOR_RULES.get(f"{path}.{key}")
            if not rule:
                continue
            for message in check_rule(rule, value):
                issues.append((path, key, f"[{path}].{key}：{message}"))

    for key, value in parsed.items():
        if isinstance(value, dict):
            visit(key, value)
        else:
            rule = EDITOR_RULES.get(key)
            if rule:
                for message in check_rule(rule, value):
                    issues.append(("", key, f"{key}：{message}"))

    # ---- 跨键校验（与 ConfigValidator.cs 对齐） ----
    def g(path: str, default: Any = None) -> Any:
        current: Any = parsed
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    smtp_host = g("Email.Smtp.Host", "")
    from_address = g("Email.FromAddress", "")
    if bool(smtp_host.strip()) != bool(from_address.strip()):
        issues.append(("Email", "Email", "[Email] 邮件服务未配置完整：Email.Smtp.Host 与 Email.FromAddress 必须同时配置或同时留空"))

    smtp_security = g("Email.Smtp.Security", "")
    smtp_port = g("Email.Smtp.Port", 587)
    if smtp_port == 465 and str(smtp_security).lower() != "sslonconnect":
        issues.append(("Email.Smtp", "Security", "[Email.Smtp].Security：端口 465 为隐式 TLS，必须使用 SslOnConnect"))

    allow_credentials = g("Cors.AllowCredentials", False)
    allowed_origins = g("Cors.AllowedOrigins", [])
    if allow_credentials and "*" in allowed_origins:
        issues.append(("Cors", "AllowedOrigins", "[Cors].AllowedOrigins：AllowCredentials=true 时禁止使用通配符 *"))

    require_https = g("OpenIddict.RequireHttps", False)
    issuer = g("OpenIddict.Issuer", "")
    if require_https and not str(issuer).startswith("https://"):
        issues.append(("OpenIddict", "Issuer", "[OpenIddict].Issuer：RequireHttps=true 时必须使用 https"))

    # 邮件模板必须完整：段落/键缺失时规则遍历不可达，这里兜底（值缺失占位符由规则层 requirePlaceholder 拦截）
    for theme in ("Register", "Bind", "Change", "PasswordReset"):
        theme_table = g(f"MailTheme.{theme}", None)
        if not isinstance(theme_table, dict):
            issues.append(("MailTheme", theme, f"[MailTheme.{theme}] 段落缺失：必须配置邮件模板（正文须包含占位符 %%CaptchaCode%%）"))
        elif "Context" not in theme_table:
            issues.append((f"MailTheme.{theme}", "Context", f"[MailTheme.{theme}].Context：不能为空（正文必须包含占位符 %%CaptchaCode%%）"))

    # ---- 弱口令检测 ----
    db_connection = g("Database.ConnectionString", "")
    if isinstance(db_connection, str) and weak_secret_hit(extract_connection_string_password(db_connection)):
        issues.append(("Database", "ConnectionString", "[Database].ConnectionString：数据库密码为已知弱值，请使用随机强密码"))
    redis_password = g("Redis.Password", "")
    if isinstance(redis_password, str) and redis_password and weak_secret_hit(redis_password):
        issues.append(("Redis", "Password", "[Redis].Password：Redis 密码为已知弱值，请使用随机强密码"))

    return issues


# 供前端实时校验下发的精简规则（保留约束，去除内部字段）
def frontend_rule(rule: Json) -> Json:
    out_rule: Json = {"kind": rule.get("kind"), "desc": rule.get("desc", "")}
    for field in ("enum", "min", "max", "required", "noPath", "allowNegOne", "arrayKind", "arrayMin", "arrayMax", "requirePlaceholder"):
        if field in rule:
            out_rule[field] = rule[field]
    return out_rule


# 网页编辑器运行上下文（由 ManagePylai 注入 docker/state，用于保存后容器权威校验）
EDITOR_CTX: dict[str, Any] = {}


def authoritative_validate() -> list[str]:
    """若 backend 容器正在运行，用容器内 CLI 做权威校验（config validate）。

    返回错误文案列表，空列表表示通过或容器不可用。
    """
    docker = EDITOR_CTX.get("docker")
    if docker is None:
        return []
    try:
        if not docker.service_running("backend"):
            return []
    except Exception:
        return []

    result = docker.exec_pylaios(
        "config",
        "validate",
        "--config",
        PYLAI_CONFIG_ARG,
        check=False,
        timeout=120,
    )
    if result.returncode == 0:
        return []
    output = (result.stdout + result.stderr).strip()
    return [output or "容器内 config validate 校验未通过"]


class ConfigEditorServer(ThreadingHTTPServer):
    """仅监听 127.0.0.1 的一次性配置编辑器服务。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, password: str) -> None:
        self.password = password
        self.token = secrets.token_hex(16)
        super().__init__(("127.0.0.1", port), ConfigEditorHandler)


class ConfigEditorHandler(BaseHTTPRequestHandler):
    server: ConfigEditorServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ---- 基础工具 ----
    def _send_json(self, payload: Json, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Json:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1 << 20:
            raise ManageError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManageError(f"请求不是合法 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManageError("请求体必须是 JSON 对象")
        return data

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            body = CONFIG_EDITOR_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/config":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                self._send_json(self._config_payload())
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        try:
            data = self._read_json()
        except ManageError as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        if path == "/api/auth":
            if secrets.compare_digest(str(data.get("password", "")), self.server.password):
                self._send_json({"token": self.server.token})
            else:
                time.sleep(0.5)  # 减缓口令爆破
                self._send_json({"error": "临时密码错误"}, 401)
            return

        if path == "/api/validate":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                issues = self._validate_changes(data.get("changes"))
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"ok": not issues, "errors": [
                {"section": sec, "key": key, "message": msg} for sec, key, msg in issues
            ]})
            return

        if path == "/api/save":
            if not self._authorized():
                self._send_json({"error": "未授权"}, 401)
                return
            try:
                preview = self._apply_changes(data.get("changes"))
            except ManageError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"ok": True, "preview": preview, "authoritative": True})
            return

        self._send_json({"error": "Not Found"}, 404)

    # ---- 业务 ----
    def _config_payload(self) -> Json:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"配置解析失败: {exc}") from exc

        sections: list[Json] = []

        def visit(path: str, table: Json) -> None:
            entries = []
            for key, value in table.items():
                if isinstance(value, dict):
                    continue
                rule = EDITOR_RULES.get(f"{path}.{key}")
                entries.append({
                    "key": key,
                    "type": editor_value_kind(value),
                    "value": value,
                    "secret": bool(re.search(r"Password|Secret|ConnectionString", key, re.IGNORECASE)),
                    "desc": rule.get("desc", "") if rule else "",
                    "rules": frontend_rule(rule) if rule else {"kind": editor_value_kind(value), "desc": ""},
                })
            if entries:
                sections.append({"name": path, "entries": entries})
            for key, value in table.items():
                if isinstance(value, dict):
                    visit(f"{path}.{key}" if path else key, value)

        for key, value in parsed.items():
            if isinstance(value, dict):
                visit(key, value)

        return {
            "path": str(CONFIG_FILE),
            "sections": sections,
            "preview": mask_config_text(text),
        }

    def _build_changes_text(self, changes: Any) -> str:
        """把变更应用到当前配置文本，返回新文本（不写盘）。"""
        if not isinstance(changes, list) or not changes:
            raise ManageError("没有需要提交的变更")
        if len(changes) > 500:
            raise ManageError("单次变更过多")

        text = CONFIG_FILE.read_text(encoding="utf-8")
        t = TomlText(text)

        for change in changes:
            if not isinstance(change, dict):
                raise ManageError("变更格式非法")
            section = str(change.get("section", ""))
            key = str(change.get("key", ""))
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*", section):
                raise ManageError(f"非法的配置段落: {section!r}")
            if not re.fullmatch(r"[A-Za-z0-9_]+", key):
                raise ManageError(f"非法的配置键: {key!r}")

            marker = f"[{section}]"
            t.text = strip_multiline_value(t.text, marker, key)
            t.set(marker, key, serialize_editor_value(change), required=True)

        return str(t)

    def _validate_changes(self, changes: Any) -> list[tuple[str, str, str]]:
        """对变更后的整份配置做语义校验（含跨键规则），返回问题列表。"""
        new_text = self._build_changes_text(changes)
        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise ManageError(f"变更后配置不是合法 TOML: {exc}") from exc
        return validate_full_text(new_text)

    def _apply_changes(self, changes: Any) -> str:
        if not CONFIG_FILE.is_file():
            raise ManageError("配置文件不存在")

        new_text = self._build_changes_text(changes)

        # 语义校验（Fail Closed）：有错误绝不写盘
        issues = validate_full_text(new_text)
        if issues:
            detail = "\n".join(msg for _, _, msg in issues[:10])
            more = f"（另有 {len(issues) - 10} 项）" if len(issues) > 10 else ""
            raise ManageError(f"配置校验未通过，已拒绝保存：\n{detail}{more}")

        old_text = CONFIG_FILE.read_text(encoding="utf-8")
        atomic_write(CONFIG_FILE, new_text)

        # 容器权威校验兜底：失败则还原旧配置
        container_errors = authoritative_validate()
        if container_errors:
            atomic_write(CONFIG_FILE, old_text)
            raise ManageError("容器内 config validate 校验未通过，已还原原配置：\n" + "\n".join(container_errors))

        return mask_config_text(new_text)

CONFIG_EDITOR_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pylai 配置编辑器</title>
<style>
/* ---------- 主题变量：默认浅色，跟随系统自动切换深色 ---------- */
:root {
  color-scheme: light;
  --bg: #f4f5f7;
  --panel: #ffffff;
  --panel-soft: #f8f9fb;
  --border: #e2e5ea;
  --border-strong: #cfd4db;
  --text: #1d2330;
  --muted: #6b7280;
  --accent: #2f6bff;
  --accent-hover: #1f59e8;
  --accent-soft: rgba(47, 107, 255, .1);
  --danger: #d64541;
  --danger-soft: rgba(214, 69, 65, .1);
  --warning: #e8930c;
  --ok: #189a58;
  --toast-bg: #1d2330;
  --toast-text: #ffffff;
  --radius: 10px;
  --mono: ui-monospace, "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0e1013;
    --panel: #15181d;
    --panel-soft: #1b1f26;
    --border: #272c35;
    --border-strong: #39414d;
    --text: #e4e7ec;
    --muted: #8b94a1;
    --accent: #5f8dff;
    --accent-hover: #7ba1ff;
    --accent-soft: rgba(95, 141, 255, .14);
    --danger: #e06560;
    --danger-soft: rgba(224, 101, 96, .14);
    --warning: #e5a13c;
    --ok: #3fbf7f;
    --toast-bg: #e8ebf0;
    --toast-text: #1d2330;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 14px;
  background: var(--bg);
  color: var(--text);
  overflow: hidden;
}
button { font: inherit; cursor: pointer; }
::placeholder { color: var(--muted); opacity: .7; }

/* ---------- 临时密码验证 ---------- */
#gate {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg);
}
.gate-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 40px 44px;
  text-align: center;
}
.gate-card h1 { font-size: 19px; font-weight: 600; margin-bottom: 6px; }
.gate-card p { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.code-row { display: flex; gap: 8px; align-items: center; justify-content: center; }
.code-row input {
  width: 42px; height: 52px;
  font-size: 21px; font-family: var(--mono);
  text-align: center; text-transform: uppercase;
  border: 1px solid var(--border-strong); border-radius: 8px;
  outline: none; transition: border-color .15s, box-shadow .15s;
  background: var(--panel-soft); color: var(--text);
}
.code-row input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.code-dash { color: var(--muted); font-size: 18px; }
#gate-btn {
  width: 42px; height: 42px; border-radius: 50%;
  border: none; background: var(--accent); color: #fff;
  font-size: 17px; margin-left: 8px;
  display: none; align-items: center; justify-content: center;
  transition: background .15s;
}
#gate-btn:hover { background: var(--accent-hover); }
#gate-err { color: var(--danger); font-size: 13px; margin-top: 16px; min-height: 18px; }
.shake { animation: shake .3s; }
@keyframes shake {
  25% { transform: translateX(-6px); } 50% { transform: translateX(6px); } 75% { transform: translateX(-4px); }
}

/* ---------- 主界面框架 ---------- */
#app { display: none; flex-direction: column; height: 100vh; }
.topbar {
  display: flex; align-items: center; gap: 6px;
  background: var(--panel); border-bottom: 1px solid var(--border);
  padding: 0 16px; height: 54px; flex: none;
}
.brand { font-weight: 600; font-size: 15px; margin-right: 18px; }
.brand span { color: var(--accent); }
.tab {
  border: none; background: none; color: var(--muted);
  padding: 6px 14px; border-radius: 8px; font-size: 14px;
  transition: background .15s, color .15s;
}
.tab:hover { color: var(--text); }
.tab.active { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
.topbar .spacer { flex: 1; }
#dirty-dot { color: var(--warning); font-size: 12px; display: none; }
#err-count { color: var(--danger); font-size: 12px; display: none; margin-right: 8px; }
#submit-btn {
  border: none; background: var(--accent); color: #fff;
  padding: 7px 22px; border-radius: 8px; font-size: 14px;
  transition: background .15s, opacity .15s;
}
#submit-btn:hover:not(:disabled) { background: var(--accent-hover); }
#submit-btn:disabled { opacity: .4; cursor: not-allowed; }

.main { display: flex; flex: 1; min-height: 0; }

/* ---------- 目录 ---------- */
#sidebar {
  width: 224px; flex: none; background: var(--panel);
  border-right: 1px solid var(--border);
  overflow-y: auto; padding: 12px 10px;
}
#sidebar h2 { font-size: 12px; color: var(--muted); padding: 4px 10px 8px; font-weight: 500; }
.sec-item {
  display: block; width: 100%; text-align: left;
  border: none; background: none; border-radius: 8px;
  padding: 7px 10px; font-size: 13px; font-family: var(--mono);
  color: var(--text); transition: background .12s;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sec-item:hover { background: var(--panel-soft); }
.sec-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
.sec-item .badge { float: right; font-size: 11px; color: var(--warning); }
.sec-item .badge.err { color: var(--danger); font-weight: 700; }

/* ---------- 编辑区 ---------- */
#editor { flex: 1; overflow-y: auto; padding: 24px 32px 40px; min-width: 0; }
#editor h2 { font-size: 16px; margin-bottom: 4px; font-family: var(--mono); }
#editor .hint { font-size: 12.5px; color: var(--muted); margin-bottom: 18px; }
.field {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px; margin-bottom: 10px;
  transition: border-color .15s;
}
.field.changed { border-color: var(--warning); }
.field.invalid { border-color: var(--danger); }
.field label { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; margin-bottom: 6px; }
.field label .type { font-size: 11px; color: var(--muted); font-weight: 400; font-family: var(--mono); }
.field label .secret-tag { font-size: 11px; color: var(--danger); background: var(--danger-soft); padding: 1px 7px; border-radius: 6px; }
.field .desc { font-size: 12px; color: var(--muted); margin-bottom: 8px; line-height: 1.5; }
.field .err { font-size: 12px; color: var(--danger); margin-top: 6px; display: none; }
.field.invalid .err { display: block; }
.field input[type=text], .field input[type=number], .field input[type=password], .field textarea, .field select {
  width: 100%; border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 12px; font-size: 13px; font-family: var(--mono);
  outline: none; background: var(--panel-soft); color: var(--text);
  transition: border-color .15s, box-shadow .15s, background .15s;
}
.field textarea { min-height: 140px; resize: vertical; line-height: 1.6; }
.field textarea.mail-context { min-height: 260px; }
.field input:focus, .field textarea:focus, .field select:focus {
  border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); background: var(--panel);
}
.field.invalid input, .field.invalid textarea, .field.invalid select { border-color: var(--danger); }
.empty { color: var(--muted); font-size: 14px; padding: 40px; text-align: center; }

/* 占位符插入按钮 */
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip {
  border: 1px solid var(--border); background: var(--panel-soft);
  color: var(--muted); border-radius: 999px; padding: 3px 11px;
  font-size: 12px; font-family: var(--mono);
  transition: color .12s, border-color .12s, background .12s;
}
.chip:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }

/* ---------- 预览（跟随主题，明暗自适应） ---------- */
#preview {
  width: 420px; flex: none;
  background: var(--panel-soft); color: var(--text);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column; min-height: 0;
}
#preview h2 {
  font-size: 12px; color: var(--muted); font-weight: 500;
  padding: 12px 16px; border-bottom: 1px solid var(--border); flex: none;
}
#preview pre {
  flex: 1; overflow: auto; padding: 14px 16px;
  color: var(--text); font-size: 12px; font-family: var(--mono); line-height: 1.7;
  white-space: pre-wrap; word-break: break-all;
}
#preview pre .cfg-line { display: block; padding: 0 4px; border-radius: 4px; }
#preview pre .sec-block {
  border-left: 3px solid transparent; padding-left: 6px; margin: 4px 0;
  border-radius: 6px; transition: border-color .15s, background .15s;
}
#preview pre .sec-block.active-sec {
  border-left-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: inset 0 0 0 1px var(--accent);
}
#preview pre .sec-title { color: var(--accent); font-weight: 600; }
#preview pre .focus-line { border-bottom: 2px solid var(--warning); }
#preview pre .valid-line { border-bottom: 2px solid var(--ok); }
#preview pre .invalid-line { border-bottom: 2px solid var(--danger); }

#preview pre .multiline-line { display: block; }
#preview pre .ml-toggle {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 10px;
  font-size: 11px;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent);
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
}
#preview pre .ml-toggle:hover { background: var(--accent); color: #fff; }

/* ---------- 弹窗 ---------- */
.modal-mask {
  position: fixed; inset: 0; background: rgba(16, 24, 40, .45);
  display: none; align-items: center; justify-content: center; z-index: 40;
}
.modal {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 14px; width: 560px; max-width: 92vw;
  max-height: 80vh; display: flex; flex-direction: column;
}
.modal h3 { padding: 18px 22px 0; font-size: 15px; }
.modal .body { padding: 14px 22px; overflow-y: auto; flex: 1; }
.diff-group { margin-bottom: 14px; }
.diff-group h4 {
  font-family: var(--mono); font-size: 13px; color: var(--accent);
  margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--border);
}
.diff-item {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 8px; font-size: 13px;
  align-items: start;
}
.diff-item .k { grid-column: 1 / -1; font-family: var(--mono); font-weight: 600; margin-bottom: 6px; color: var(--text); }
.diff-item .old, .diff-item .new { font-family: var(--mono); font-size: 12px; word-break: break-all; line-height: 1.5; }
.diff-item .old { color: var(--danger); }
.diff-item .new { color: var(--ok); }
.diff-item .old::before { content: "改前: "; color: var(--muted); font-family: inherit; }
.diff-item .new::before { content: "改后: "; color: var(--muted); font-family: inherit; }
.diff-empty { color: var(--muted); text-align: center; padding: 30px; }
.modal .foot { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 22px 18px; }
.btn {
  border: 1px solid var(--border-strong); background: var(--panel); color: var(--text);
  border-radius: 8px; padding: 8px 18px; font-size: 14px;
  transition: border-color .15s, background .15s;
}
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { background: var(--accent-hover); }

#toast {
  position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
  background: var(--toast-bg); color: var(--toast-text);
  padding: 10px 22px; border-radius: 10px;
  font-size: 13.5px; display: none; z-index: 60;
}
#status-modal .body p { font-size: 13.5px; margin-bottom: 10px; color: var(--text); line-height: 1.6; }
#status-modal .body b { font-family: var(--mono); font-weight: 600; }
#status-modal .status-summary { font-size: 14px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
#status-modal .status-sec { margin-top: 12px; font-size: 13px; color: var(--accent); }
#status-modal .status-row { margin: 4px 0 4px 12px; }
#status-modal .status-row .old { color: var(--danger); text-decoration: line-through; font-family: var(--mono); font-size: 12px; }
#status-modal .status-row .new { color: var(--ok); font-family: var(--mono); font-size: 12px; }
#status-modal .status-err { color: var(--danger); font-size: 12px; }
@media (max-width: 1000px) { #preview { display: none; } }
@media (max-width: 720px) { #sidebar { display: none; } }
</style>
</head>
<body>

<!-- 临时密码验证 -->
<div id="gate">
  <div class="gate-card" id="gate-card">
    <h1>Pylai 配置编辑器</h1>
    <p>验证临时密码</p>
    <div class="code-row" id="code-row">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <span class="code-dash">-</span>
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <input maxlength="1" autocomplete="off"><input maxlength="1" autocomplete="off">
      <button id="gate-btn" title="验证">&#10140;</button>
    </div>
    <div id="gate-err"></div>
  </div>
</div>

<!-- 编辑器主界面 -->
<div id="app">
  <div class="topbar">
    <div class="brand">Pylai <span>配置编辑器</span></div>
    <button class="tab active" data-tab="catalog">目录</button>
    <button class="tab" data-tab="editor">编辑器</button>
    <button class="tab" data-tab="status">状态</button>
    <div class="spacer"></div>
    <span id="dirty-dot">&#9679; 有未提交变更</span>
    <span id="err-count"></span>
    <button id="submit-btn" disabled>提交</button>
  </div>
  <div class="main">
    <aside id="sidebar"><h2>目录</h2><div id="sec-list"></div></aside>
    <section id="editor"><div class="empty">正在加载配置…</div></section>
    <aside id="preview"><h2>配置文件预览</h2><pre id="preview-pre"></pre></aside>
  </div>
</div>

<!-- 提交确认弹窗 -->
<div class="modal-mask" id="diff-modal">
  <div class="modal">
    <h3>确认以下变更</h3>
    <div class="body" id="diff-body"></div>
    <div class="foot">
      <button class="btn" id="diff-cancel">取消</button>
      <button class="btn primary" id="diff-confirm">确认提交</button>
    </div>
  </div>
</div>

<!-- 状态弹窗 -->
<div class="modal-mask" id="status-modal">
  <div class="modal">
    <h3>状态</h3>
    <div class="body" id="status-body"></div>
    <div class="foot"><button class="btn" id="status-close">关闭</button></div>
  </div>
</div>

<div id="toast"></div>

<script>
"use strict";
const $ = (s) => document.querySelector(s);
let token = null;
let configData = null;          // 配置数据：{ sections, preview, path }
let original = new Map();       // "Section.Key" -> 原始值
let edits = new Map();          // "Section.Key" -> {section,key,type,value,secret,rules,error}
let activeSection = null;
let currentFocusId = null;

// 邮件模板可用占位符（与后端 EmailSender 渲染一致）
const MAIL_PLACEHOLDERS = [
  ["%%CaptchaCode%%", "验证码"],
  ["%%Browser%%", "浏览器"],
  ["%%IPAddress%%", "IP 地址"],
  ["%%ExpireMinutes%%", "有效分钟数"],
];

// 字段预设（点击自动填充）
const FIELD_PRESETS = {
  "IpResolution.TrustedNetworks": [
    { label: "Cloudflare IPv4", values: ["173.245.48.0/20","103.21.244.0/22","103.22.200.0/22","103.31.4.0/22","141.101.64.0/18","108.162.192.0/18","190.93.240.0/20","188.114.96.0/20","197.234.240.0/22","198.41.128.0/17","162.158.0.0/15","104.16.0.0/13","104.24.0.0/14","172.64.0.0/13","131.0.72.0/22"] },
    { label: "Cloudflare IPv6", values: ["2400:cb00::/32","2606:4700::/32","2803:f800::/32","2405:b500::/32","2405:8100::/32","2a06:98c0::/29","2c0f:f248::/32"] },
    { label: "Cloudflare 全部", values: ["173.245.48.0/20","103.21.244.0/22","103.22.200.0/22","103.31.4.0/22","141.101.64.0/18","108.162.192.0/18","190.93.240.0/20","188.114.96.0/20","197.234.240.0/22","198.41.128.0/17","162.158.0.0/15","104.16.0.0/13","104.24.0.0/14","172.64.0.0/13","131.0.72.0/22","2400:cb00::/32","2606:4700::/32","2803:f800::/32","2405:b500::/32","2405:8100::/32","2a06:98c0::/29","2c0f:f248::/32"] },
    { label: "Docker 网桥", values: ["172.16.0.0/12"] },
  ],
  "IpResolution.TrustedHeaders": [
    { label: "Cloudflare 推荐", values: ["CF-Connecting-IP","X-Forwarded-For","X-Forwarded-Proto"] },
    { label: "标准转发头", values: ["X-Forwarded-For","X-Forwarded-Proto","X-Forwarded-Host"] },
  ],
};

/* ---------- 临时密码 ---------- */
const boxes = [...document.querySelectorAll("#code-row input")];
const gateBtn = $("#gate-btn");

boxes.forEach((box, i) => {
  box.addEventListener("input", () => {
    // 只允许字母数字并自动聚焦下一格
    box.value = box.value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    if (box.value && i < boxes.length - 1) boxes[i + 1].focus();
    gateBtn.style.display = boxes.every(b => b.value) ? "inline-flex" : "none";
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && !box.value && i > 0) boxes[i - 1].focus();
    if (e.key === "Enter" && boxes.every(b => b.value)) doAuth();
  });
  box.addEventListener("paste", (e) => {
    // 整段粘贴：过滤非法字符后按位填充
    e.preventDefault();
    const text = (e.clipboardData.getData("text") || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    [...text].slice(0, 8).forEach((ch, j) => { if (boxes[j]) boxes[j].value = ch; });
    boxes[Math.min(text.length, 7)].focus();
    gateBtn.style.display = boxes.every(b => b.value) ? "inline-flex" : "none";
  });
});
boxes[0].focus();
gateBtn.addEventListener("click", doAuth);

async function doAuth() {
  // 拼装 XXXX-XXXX 格式临时密码并验证
  const password = boxes.slice(0, 4).map(b => b.value).join("") + "-" + boxes.slice(4).map(b => b.value).join("");
  try {
    const res = await fetch("/api/auth", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "验证失败");
    token = data.token;
    $("#gate").style.display = "none";
    $("#app").style.display = "flex";
    document.title = "Pylai 配置编辑器";
    await loadConfig();
  } catch (err) {
    $("#gate-err").textContent = err.message;
    $("#gate-card").classList.remove("shake");
    void $("#gate-card").offsetWidth;
    $("#gate-card").classList.add("shake");
    boxes.forEach(b => b.value = "");
    gateBtn.style.display = "none";
    boxes[0].focus();
  }
}

/* ---------- 数据加载 ---------- */
async function api(path, options = {}) {
  // 统一请求封装：自动附带 Bearer Token，HTTP 非 2xx 时抛出错误
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token, ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("请求失败: " + res.status));
  return data;
}

async function loadConfig() {
  // 加载配置：建立原始值映射、重置编辑与错误状态
  configData = await api("/api/config");
  original.clear(); edits.clear();
  for (const sec of configData.sections)
    for (const e of sec.entries)
      original.set(sec.name + "." + e.key, e.value);
  activeSection = configData.sections[0]?.name ?? null;
  renderSidebar(); renderEditor(); renderPreview(); scrollPreviewToSection(activeSection); refreshDirty();
}

/* ---------- 序列化（与服务端 TomlText 一致） ---------- */
function serialize(type, value) {
  if (type === "boolean") return value ? "true" : "false";
  if (type === "number") return String(value);
  if (type === "array") {
    return "[" + value.map(x => (typeof x === "number") ? String(x) : JSON.stringify(String(x))).join(", ") + "]";
  }
  return JSON.stringify(String(value));
}
function displayValue(v, secret) {
  if (secret) return '"***"';
  if (typeof v === "string") return JSON.stringify(v);
  return Array.isArray(v) ? "[" + v.join(", ") + "]" : String(v);
}

/* ---------- 实时校验（与服务端 check_rule 对齐） ---------- */
function isValidUrl(s) {
  // 校验 http(s)://host[:port] 形式的合法 URL
  try {
    const u = new URL(s);
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.hostname;
  } catch { return false; }
}
function isValidIp(s) {
  // 校验 IPv4（分段 0-255）或简化的 IPv6（十六进制冒号形式）
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
  const m = s.match(ipv4);
  if (m) return m.slice(1).every(n => Number(n) <= 255);
  return /^[0-9a-fA-F:]+$/.test(s) && s.includes(":") && (s.match(/:/g) || []).length <= 7;
}
function isValidCidr(s) {
  // 校验 CIDR：合法 IP + /前缀长度
  const idx = s.lastIndexOf("/");
  if (idx <= 0) return false;
  const ip = s.slice(0, idx), prefix = Number(s.slice(idx + 1));
  if (!isValidIp(ip) || !Number.isInteger(prefix)) return false;
  const max = ip.includes(":") ? 128 : 32;
  return prefix >= 0 && prefix <= max;
}
function checkScalar(rules, value) {
  // 按规则校验标量值，返回错误文案（空串表示通过）
  const kind = rules.kind;
  if (kind === "boolean") return "";
  if (kind === "number") {
    if (typeof value !== "number" || !isFinite(value)) return "必须是有限数字（不能为 NaN / Infinity）";
    if (rules.allowNegOne && value === -1) return "";
    if (rules.min != null && value < rules.min) return "不能小于 " + rules.min;
    if (rules.max != null && value > rules.max) return "不能大于 " + rules.max;
    return "";
  }
  if (kind === "enum") return rules.enum.includes(value) ? "" : "必须是以下之一: " + rules.enum.join(", ");
  if (kind === "url") {
    if (!value || !isValidUrl(value)) return "不是合法 URL（应为 http(s)://host[:port]）";
    if (rules.noPath) {
      const u = new URL(value);
      if (u.pathname !== "" && u.pathname !== "/") return "不允许包含路径（应为 http(s)://host[:port]）";
    }
    return "";
  }
  if (kind === "ip") return isValidIp(value) ? "" : "不是合法 IP";
  if (kind === "cidr") return isValidCidr(value) ? "" : "不是合法 CIDR";
  if (kind === "string") {
    if (rules.required && !String(value).trim()) return "不能为空";
    if (rules.requirePlaceholder && String(value) && !String(value).includes(rules.requirePlaceholder))
      return "必须包含占位符 " + rules.requirePlaceholder;
    return "";
  }
  return "";
}
function checkArray(rules, value) {
  // 按规则校验数组及元素，返回错误文案
  if (!Array.isArray(value)) return "必须是列表";
  if (rules.required && value.length === 0) return "不能为空";
  const elem = rules.arrayKind || "string";
  for (let i = 0; i < value.length; i++) {
    const item = value[i];
    if (elem === "url") {
      if (!isValidUrl(item)) return "第 " + (i + 1) + " 项不是合法 URL: " + item;
      if (rules.noPath) {
        const u = new URL(item);
        if (u.pathname !== "" && u.pathname !== "/") return "第 " + (i + 1) + " 项不允许包含路径";
      }
    }
    if (elem === "ip" && !isValidIp(item)) return "第 " + (i + 1) + " 项不是合法 IP: " + item;
    if (elem === "cidr" && !isValidCidr(item)) return "第 " + (i + 1) + " 项不是合法 CIDR: " + item;
    if (elem === "number") {
      if (typeof item !== "number" || !isFinite(item)) return "第 " + (i + 1) + " 项不是有效数字";
      if (rules.allowNegOne && item === -1) continue;
      if (rules.arrayMin != null && item < rules.arrayMin) return "第 " + (i + 1) + " 项不能小于 " + rules.arrayMin;
      if (rules.arrayMax != null && item > rules.arrayMax) return "第 " + (i + 1) + " 项不能大于 " + rules.arrayMax;
    }
    if (elem === "string" && typeof item !== "string") return "第 " + (i + 1) + " 项必须是字符串";
  }
  return "";
}
function checkValue(rules, value) {
  // 统一入口：数组走 checkArray，其余走 checkScalar
  if (!rules) return "";
  if (rules.kind === "array") return checkArray(rules, value);
  return checkScalar(rules, value);
}

/* ---------- 目录 ---------- */
function renderSidebar() {
  const list = $("#sec-list");
  list.innerHTML = "";
  for (const sec of configData.sections) {
    const btn = document.createElement("button");
    btn.className = "sec-item" + (sec.name === activeSection ? " active" : "");
    let badge = "";
    if (sec.entries.some(e => edits.has(sec.name + "." + e.key))) badge = '<span class="badge">●</span>';
    if (sec.entries.some(e => edits.get(sec.name + "." + e.key)?.error)) badge = '<span class="badge err">!</span>';
    btn.innerHTML = escapeHtml("[" + sec.name + "]") + badge;
    btn.onclick = () => { activeSection = sec.name; renderSidebar(); renderEditor(); updatePreviewActiveSection(); scrollPreviewToSection(activeSection); setTab("editor"); };
    list.appendChild(btn);
  }
}
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- 占位符插入 ---------- */
function insertAtCursor(el, text) {
  // 在光标处插入文本（覆盖选区），插入后触发 input 事件走正常编辑流程
  el.focus();
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? start;
  el.setRangeText(text, start, end, "end");
  el.dispatchEvent(new Event("input"));
}

/* ---------- 表单编辑 ---------- */
function renderEditor() {
  currentFocusId = null;
  const sec = configData.sections.find(s => s.name === activeSection);
  const box = $("#editor");
  if (!sec) { box.innerHTML = '<div class="empty">没有可编辑的配置段落</div>'; return; }
  box.innerHTML = "<h2>[" + escapeHtml(sec.name) + "]</h2>" +
    '<div class="hint">共 ' + sec.entries.length + ' 项</div>';
  const isMailTheme = sec.name === "MailTheme" || sec.name.startsWith("MailTheme.");
  for (const entry of sec.entries) {
    const id = sec.name + "." + entry.key;
    const current = edits.has(id) ? edits.get(id).value : entry.value;
    const field = document.createElement("div");
    field.className = "field" + (edits.has(id) ? " changed" : "");
    field.dataset.id = id;
    const label = '<label><span>' + escapeHtml(entry.key) + "</span>" +
      '<span class="type">' + entry.type + "</span>" +
      (entry.secret ? '<span class="secret-tag">敏感</span>' : "") + "</label>";
    const desc = entry.desc ? '<div class="desc">' + escapeHtml(entry.desc) + "</div>" : "";
    const errLine = '<div class="err"></div>';
    let control = "";
    if (entry.type === "boolean") {
      control = '<select><option value="true"' + (current ? " selected" : "") + '>true</option>' +
        '<option value="false"' + (!current ? " selected" : "") + ">false</option></select>";
    } else if (entry.type === "number") {
      control = '<input type="number" step="any" value="' + escapeHtml(String(current)) + '">';
    } else if (entry.type === "array") {
      control = '<input type="text" value="' + escapeHtml(current.join(", ")) + '" placeholder="以英文逗号分隔">';
    } else if (typeof current === "string" && current.includes("\n")) {
      control = "<textarea>" + escapeHtml(current) + "</textarea>";
    } else if (isMailTheme && entry.key === "Context") {
      // 邮件正文强制使用多行文本框
      control = '<textarea class="mail-context">' + escapeHtml(String(current)) + "</textarea>";
    } else {
      control = '<input type="' + (entry.secret ? "password" : "text") + '" value="' + escapeHtml(String(current)) + '">';
    }
    // 邮件模板字段：附加占位符插入按钮
    let chips = "";
    if (isMailTheme && entry.type === "string") {
      chips = '<div class="chips">' + MAIL_PLACEHOLDERS.map(p =>
        '<button type="button" class="chip" data-text="' + p[0] + '" title="插入' + p[1] + '占位符">' + p[0] + "</button>"
      ).join("") + "</div>";
    }
    // 字段预设：数组类型支持一键填充
    const presetKey = sec.name + "." + entry.key;
    if (presetKey === "Altcha.SecretKey") {
      chips += '<div class="chips" style="margin-top:4px;">' +
        '<button type="button" class="chip" onclick="generateAltchaKey()">自动生成密钥</button></div>';
    }
    if (FIELD_PRESETS[presetKey] && entry.type === "array") {
      chips += '<div class="chips" style="margin-top:4px;">' + FIELD_PRESETS[presetKey].map(p =>
        '<button type="button" class="chip preset-chip" data-preset="' + escapeHtml(JSON.stringify(p.values)) + '" title="填充 ' + escapeHtml(p.label) + '">' + escapeHtml(p.label) + "</button>"
      ).join("") + "</div>";
    }
    field.innerHTML = label + desc + chips + control + errLine;
    const input = field.querySelector("input,select,textarea");
    input.addEventListener("input", () => onEdit(sec.name, entry, input.value));
    input.addEventListener("change", () => onEdit(sec.name, entry, input.value));
    input.addEventListener("focus", () => previewFocusLine(sec.name, entry.key));
    input.addEventListener("blur", () => previewBlurLine(sec.name, entry.key));
    field.querySelectorAll(".chip:not(.preset-chip)").forEach(chip =>
      chip.addEventListener("click", () => insertAtCursor(input, chip.dataset.text)));
    field.querySelectorAll(".preset-chip").forEach(chip =>
      chip.addEventListener("click", () => {
        const values = JSON.parse(chip.dataset.preset);
        input.value = values.join(", ");
        input.dispatchEvent(new Event("input"));
      }));
    box.appendChild(field);
  }
}

function onEdit(section, entry, raw) {
  // 输入时：类型转换 + 实时校验 + 更新编辑记录与界面状态
  const id = section + "." + entry.key;
  let value;
  if (entry.type === "boolean") value = raw === "true";
  else if (entry.type === "number") value = raw === "" ? 0 : Number(raw);
  else if (entry.type === "array") {
    const parts = raw.split(",").map(s => s.trim()).filter(s => s !== "");
    const numeric = Array.isArray(entry.value) && entry.value.every(x => typeof x === "number");
    // 数值数组：仅将可解析项转为数字，非法项保留字符串以便实时报错
    value = numeric ? parts.map(p => (p === "-1" || /^-?\d+(\.\d+)?$/.test(p)) ? Number(p) : p) : parts;
  } else value = raw;

  let error = "";
  if (entry.type === "number" && raw === "") error = "该项不能为空";
  else error = checkValue(entry.rules, value);

  if (JSON.stringify(value) === JSON.stringify(original.get(id))) edits.delete(id);
  else edits.set(id, { section, key: entry.key, type: entry.type, value, secret: entry.secret, rules: entry.rules, error });

  // 更新字段外观：橙色=有改动，红色=校验错误
  const field = document.querySelector('.field[data-id="' + CSS.escape(id) + '"]');
  if (field) {
    field.classList.toggle("changed", edits.has(id));
    field.classList.toggle("invalid", Boolean(error));
    const errEl = field.querySelector(".err");
    if (errEl) errEl.textContent = error;
  }
  renderSidebar(); renderPreview(); refreshDirty();
}

/* ---------- 预览（在脱敏原文上打补丁） ---------- */
function patchPreview(text, section, key, serialized) {
  const lines = text.split("\n");
  let inSec = false;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^\s*\[([^\]]+)\]\s*$/);
    if (m) { inSec = m[1].trim() === section; continue; }
    if (!inSec) continue;
    const km = lines[i].match(new RegExp("^(\\s*" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*=\\s*)(.*)$"));
    if (!km) continue;
    const rhs = km[2];
    const triple = rhs.match(/^('''|\"\"\")/);
    let end = i;
    if (triple && rhs.indexOf(triple[1], 3) === -1) {
      for (let j = i + 1; j < lines.length; j++) { end = j; if (lines[j].includes(triple[1])) break; }
    }
    lines.splice(i, end - i + 1, km[1] + serialized);
    return lines.join("\n");
  }
  return text;
}

function stripLeadingComments(text) {
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === "" || t.startsWith("#")) i++;
    else break;
  }
  return lines.slice(i).join("\n");
}

function renderPreview() {
  let text = configData.preview;
  text = stripLeadingComments(text);
  for (const e of edits.values()) {
    const serialized = e.secret ? '"***"' : serialize(e.type, e.value);
    text = patchPreview(text, e.section, e.key, serialized);
  }

  const lines = text.split("\n");
  let html = "";
  let currentSec = null;
  let buffer = "";
  let multilineBuffer = null;  // { key, sec, lines: [] }

  function flush() {
    if (currentSec !== null) {
      const active = currentSec === activeSection ? " active-sec" : "";
      html += '<div class="sec-block' + active + '" data-sec="' + escapeHtml(currentSec) + '">' + buffer + '</div>';
    } else {
      html += buffer;
    }
    buffer = "";
  }

  function flushMultiline() {
    if (!multilineBuffer) return;
    const fullText = multilineBuffer.lines.join("\n");
    const isLong = multilineBuffer.lines.length > 3;
    const displayText = isLong ? multilineBuffer.lines.slice(0, 3).join("\n") : fullText;
    const keyAttr = ' data-key="' + escapeHtml(multilineBuffer.key) + '"';
    const secAttr = ' data-sec="' + escapeHtml(multilineBuffer.sec) + '"';
    const mid = 'ml-' + multilineBuffer.sec.replace(/\./g, "-") + '-' + multilineBuffer.key;
    if (isLong) {
      buffer += '<span class="cfg-line multiline-line"' + secAttr + keyAttr + '>' +
        '<span class="ml-content" id="' + mid + '-short">' + escapeHtml(displayText) + '</span>' +
        '<span class="ml-content" id="' + mid + '-full" style="display:none">' + escapeHtml(fullText) + '</span>' +
        '<button type="button" class="ml-toggle" data-mid="' + mid + '" data-expanded="false">▼ 展开</button>' +
        '</span>';
    } else {
      buffer += '<span class="cfg-line"' + secAttr + keyAttr + '>' + escapeHtml(fullText) + '</span>';
    }
    multilineBuffer = null;
  }

  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    const m = line.match(/^\s*\[([^\]]+)\]\s*$/);
    if (m) {
      flushMultiline();
      flush();
      currentSec = m[1].trim();
      buffer += '<span class="cfg-line sec-title" data-sec="' + escapeHtml(currentSec) + '">' + escapeHtml(line) + '</span>';
      continue;
    }

    // 检测多行字符串开始
    if (!multilineBuffer) {
      const km = line.match(/^(\s*)([^=\s]+)\s*=\s*('''|\"\"\")(.*)$/);
      if (km && currentSec !== null) {
        const quote = km[3];
        const rest = km[4];
        if (!rest.includes(quote)) {
          multilineBuffer = { key: km[2], sec: currentSec, lines: [line], endQuote: quote };
          continue;
        }
        // 单行但用三引号包裹，直接渲染
        const keyAttr = ' data-key="' + escapeHtml(km[2]) + '"';
        buffer += '<span class="cfg-line" data-sec="' + escapeHtml(currentSec) + '"' + keyAttr + '>' + escapeHtml(line) + '</span>';
        continue;
      }
    }

    if (multilineBuffer) {
      multilineBuffer.lines.push(line);
      if (line.includes(multilineBuffer.endQuote)) {
        flushMultiline();
      }
      continue;
    }

    if (currentSec !== null) {
      const km = line.match(/^(\s*)([^=\s]+)\s*=\s*(.*)$/);
      const keyAttr = km ? ' data-key="' + escapeHtml(km[2]) + '"' : "";
      buffer += '<span class="cfg-line" data-sec="' + escapeHtml(currentSec) + '"' + keyAttr + '>' + escapeHtml(line) + '</span>';
    } else {
      buffer += '<span class="cfg-line">' + escapeHtml(line) + '</span>';
    }
  }
  flushMultiline();
  flush();
  $("#preview-pre").innerHTML = html;

  // 绑定多行展开/折叠按钮
  $("#preview-pre").querySelectorAll(".ml-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const mid = btn.dataset.mid;
      const expanded = btn.dataset.expanded === "true";
      const shortEl = $("#" + mid + "-short");
      const fullEl = $("#" + mid + "-full");
      if (expanded) {
        shortEl.style.display = "";
        fullEl.style.display = "none";
        btn.dataset.expanded = "false";
        btn.textContent = "▼ 展开";
      } else {
        shortEl.style.display = "none";
        fullEl.style.display = "";
        btn.dataset.expanded = "true";
        btn.textContent = "▲ 折叠";
      }
    });
  });

  refreshPreviewHighlights();
}

function scrollPreviewToSection(secName) {
  if (!secName) return;
  const block = $("#preview-pre").querySelector('.sec-block[data-sec="' + CSS.escape(secName) + '"]');
  if (block) block.scrollIntoView({ behavior: "smooth", block: "start" });
}

function updatePreviewActiveSection() {
  $("#preview-pre").querySelectorAll(".sec-block").forEach(b =>
    b.classList.toggle("active-sec", b.dataset.sec === activeSection));
}

function refreshPreviewHighlights() {
  const pre = $("#preview-pre");
  pre.querySelectorAll(".focus-line, .valid-line, .invalid-line").forEach(el =>
    el.classList.remove("focus-line", "valid-line", "invalid-line"));
  for (const [id, e] of edits) {
    if (id === currentFocusId) continue;
    const dotIdx = id.indexOf(".");
    const section = id.slice(0, dotIdx);
    const key = id.slice(dotIdx + 1);
    const line = pre.querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
    if (line) line.classList.add(e.error ? "invalid-line" : "valid-line");
  }
  if (currentFocusId) {
    const dotIdx = currentFocusId.indexOf(".");
    const section = currentFocusId.slice(0, dotIdx);
    const key = currentFocusId.slice(dotIdx + 1);
    const line = pre.querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
    if (line) {
      line.classList.remove("valid-line", "invalid-line");
      line.classList.add("focus-line");
    }
  }
}

function previewFocusLine(section, key) {
  currentFocusId = section + "." + key;
  refreshPreviewHighlights();
  const line = $("#preview-pre").querySelector('.cfg-line[data-sec="' + CSS.escape(section) + '"][data-key="' + CSS.escape(key) + '"]');
  if (line) line.scrollIntoView({ behavior: "smooth", block: "center" });
}

function previewBlurLine(section, key) {
  const id = section + "." + key;
  if (currentFocusId === id) currentFocusId = null;
  refreshPreviewHighlights();
}

function generateAltchaKey() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  const hex = Array.from(array)
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
  const sec = configData.sections.find(s => s.name === "Altcha");
  if (!sec) return;
  const entry = sec.entries.find(e => e.key === "SecretKey");
  if (!entry) return;
  const input = document.querySelector('.field[data-id="Altcha.SecretKey"] input');
  if (!input) return;
  input.value = hex;
  input.dispatchEvent(new Event("input"));
}

function refreshDirty() {
  // 有未提交变更 且 全部通过实时校验 时才允许提交
  const dirty = edits.size > 0;
  const errCount = [...edits.values()].filter(e => e.error).length;
  $("#submit-btn").disabled = !dirty || errCount > 0;
  $("#dirty-dot").style.display = dirty ? "inline" : "none";
  $("#err-count").style.display = errCount > 0 ? "inline" : "none";
  $("#err-count").textContent = "⚠ " + errCount + " 项校验错误";
}

$("#submit-btn").addEventListener("click", async () => {
  // 提交前先请求服务端做整份配置校验（含跨键规则，如 SMTP 配对/CORS 通配符）
  try {
    const changes = [...edits.values()].map(e => ({ section: e.section, key: e.key, type: e.type, value: e.value }));
    const result = await api("/api/validate", { method: "POST", body: JSON.stringify({ changes }) });
    if (result.errors && result.errors.length) {
      const first = result.errors[0];
      toast("校验未通过：[" + first.section + "]. " + first.message);
      return;
    }
  } catch (err) {
    toast("校验请求失败：" + err.message);
    return;
  }

  // 校验通过后展示变更确认弹窗
  const body = $("#diff-body");
  body.innerHTML = "";
  const groups = {};
  for (const e of edits.values()) {
    if (!groups[e.section]) groups[e.section] = [];
    groups[e.section].push(e);
  }
  for (const sec of Object.keys(groups).sort()) {
    const group = document.createElement("div");
    group.className = "diff-group";
    group.innerHTML = "<h4>[" + escapeHtml(sec) + "]</h4>";
    for (const e of groups[sec]) {
      const oldV = displayValue(original.get(e.section + "." + e.key), e.secret);
      const newV = displayValue(e.value, e.secret);
      const div = document.createElement("div");
      div.className = "diff-item";
      div.innerHTML = '<div class="k">' + escapeHtml(e.key) + "</div>" +
        '<span class="old">' + escapeHtml(oldV) + "</span>" +
        '<span class="new">' + escapeHtml(newV) + "</span>";
      group.appendChild(div);
    }
    body.appendChild(group);
  }
  $("#diff-modal").style.display = "flex";
});
$("#diff-cancel").addEventListener("click", () => $("#diff-modal").style.display = "none");

$("#diff-confirm").addEventListener("click", async () => {
  $("#diff-modal").style.display = "none";
  try {
    const changes = [...edits.values()].map(e => ({ section: e.section, key: e.key, type: e.type, value: e.value }));
    const result = await api("/api/save", { method: "POST", body: JSON.stringify({ changes }) });
    configData.preview = result.preview;
    edits.clear();
    await loadConfig();
    toast("配置已写入，重启实例后生效");
  } catch (err) {
    toast("提交失败：" + err.message);
  }
});

/* ---------- 页签 / 状态 ---------- */
function setTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
}
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
  setTab(t.dataset.tab);
  if (t.dataset.tab === "catalog") $("#sidebar").scrollIntoView();
  if (t.dataset.tab === "editor") $("#editor").scrollIntoView();
  if (t.dataset.tab === "status") {
    const body = $("#status-body");
    if (edits.size === 0) {
      body.innerHTML = "<p>当前没有未提交的变更。</p>";
    } else {
      const groups = {};
      for (const e of edits.values()) {
        if (!groups[e.section]) groups[e.section] = [];
        groups[e.section].push(e);
      }
      let html = '<p class="status-summary">未提交变更 <b>' + edits.size + '</b> 项</p>';
      for (const sec of Object.keys(groups).sort()) {
        html += '<div class="status-sec"><b>[' + escapeHtml(sec) + ']</b></div>';
        for (const e of groups[sec]) {
          const oldV = displayValue(original.get(e.section + "." + e.key), e.secret);
          const newV = displayValue(e.value, e.secret);
          html += '<p class="status-row"><b>' + escapeHtml(e.key) + '</b>：<span class="old">' + escapeHtml(oldV) +
            '</span> → <span class="new">' + escapeHtml(newV) + '</span>' +
            (e.error ? ' <span class="status-err">（错误）</span>' : '') + '</p>';
        }
      }
      body.innerHTML = html;
    }
    $("#status-modal").style.display = "flex";
  }
}));
$("#status-close").addEventListener("click", () => $("#status-modal").style.display = "none");
document.querySelectorAll(".modal-mask").forEach(m =>
  m.addEventListener("click", (e) => { if (e.target === m) m.style.display = "none"; }));

let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg; el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.style.display = "none", 3200);
}
</script>
</body>
</html>

"""

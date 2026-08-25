# ============================================================================
# 网页配置编辑器（config web-edit / 主菜单 [7] 置顶入口）
# 本文件为源文件，通过 scripts/sync_config_editor.py 同步进 ManagePylai.py
# ============================================================================


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


def _str(desc: str, *, required: bool = False) -> Json:
    rule: Json = {"kind": "string", "desc": desc}
    if required:
        rule["required"] = True
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
    "MailTheme.Register.Context": _str("注册邮件正文（必须包含 %%CaptchaCode%%）", required=True),
    "MailTheme.Bind.Title": _str("绑定邮箱邮件标题", required=True),
    "MailTheme.Bind.Context": _str("绑定邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True),
    "MailTheme.Change.Title": _str("更换邮箱邮件标题", required=True),
    "MailTheme.Change.Context": _str("更换邮箱邮件正文（必须包含 %%CaptchaCode%%）", required=True),
    "MailTheme.PasswordReset.Title": _str("密码重置邮件标题", required=True),
    "MailTheme.PasswordReset.Context": _str("密码重置邮件正文（必须包含 %%CaptchaCode%%）", required=True),

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
    if smtp_port == 465 and str(smtp_security).lower() != "sslconnect":
        issues.append(("Email.Smtp", "Security", "[Email.Smtp].Security：端口 465 为隐式 TLS，必须使用 SslOnConnect"))

    allow_credentials = g("Cors.AllowCredentials", False)
    allowed_origins = g("Cors.AllowedOrigins", [])
    if allow_credentials and "*" in allowed_origins:
        issues.append(("Cors", "AllowedOrigins", "[Cors].AllowedOrigins：AllowCredentials=true 时禁止使用通配符 *"))

    require_https = g("OpenIddict.RequireHttps", False)
    issuer = g("OpenIddict.Issuer", "")
    if require_https and not str(issuer).startswith("https://"):
        issues.append(("OpenIddict", "Issuer", "[OpenIddict].Issuer：RequireHttps=true 时必须使用 https"))

    # 邮件模板正文必须包含验证码占位符
    for theme in ("Register", "Bind", "Change", "PasswordReset"):
        context = g(f"MailTheme.{theme}.Context", "")
        if isinstance(context, str) and context and "%%CaptchaCode%%" not in context:
            issues.append((f"MailTheme.{theme}", "Context", f"[MailTheme.{theme}].Context：正文必须包含占位符 %%CaptchaCode%%"))

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
    for field in ("enum", "min", "max", "required", "noPath", "allowNegOne", "arrayKind", "arrayMin", "arrayMax"):
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

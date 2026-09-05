namespace Pylaios.Features.Config;

public class MainConfig
{
    public ServerConfig Server { get; set; } = new();
    public DatabaseConfig Database { get; set; } = new();
    public RedisConfig Redis { get; set; } = new();
    public EmailConfig Email { get; set; } = new();
    public IdentityConfig Identity { get; set; } = new();
    public CookieConfig Cookie { get; set; } = new();
    public OpenIddictConfig OpenIddict { get; set; } = new();
    public ExternalLoginConfig ExternalLogin { get; set; } = new();
    public LoggingConfig Logging { get; set; } = new();
    public SeedsConfig Seeds { get; set; } = new();
    public InviteCodeConfig InviteCode { get; set; } = new();
    public LoginRateLimitConfig LoginRateLimit { get; set; } = new();
    public TokenCleanupConfig TokenCleanup { get; set; } = new();
    public CorsConfig Cors { get; set; } = new();
    public FrontendConfig Frontend { get; set; } = new();
    public AdminRateLimitConfig AdminRateLimit { get; set; } = new();
    public IpResolutionConfig IpResolution { get; set; } = new();
    public UserTokenConfig UserToken { get; set; } = new();
    public ConfirmationRateLimitConfig ConfirmationRateLimit { get; set; } = new();
    public MfaConfig Mfa { get; set; } = new();
    public DataProtectionConfig DataProtection { get; set; } = new();
    public DeploymentConfig Deployment { get; set; } = new();
    public BackupConfig Backup { get; set; } = new();
    public MailThemeConfig MailTheme { get; set; } = new();
    public AltchaOptions Altcha { get; set; } = new();
}

[ConfigFile("pylai.toml")]
public class ServerConfig
{
    [ConfigRequired]
    [ConfigDescription("服务器监听地址（http://host:port）")]
    public string Url { get; set; } = "http://localhost:5000";

    [ConfigRange(1, 10240)]
    [ConfigDescription("Kestrel 请求体大小上限（MB）")]
    public int MaxRequestBodyMB { get; set; } = 2;

    [ConfigDescription("允许的 HTTP Host 白名单，生产环境禁止使用通配符 *")]
    public string[] AllowedHosts { get; set; } = [];
}

[ConfigFile("pylai.toml")]
public class DatabaseConfig
{
    [ConfigSensitive]
    [ConfigRequired]
    [ConfigDescription("PostgreSQL 连接字符串（含密码，敏感）")]
    public string ConnectionString { get; set; } = "Host=127.0.0.1;Port=5432;Database=postgres;Username=postgres;Password=";
}

[ConfigFile("pylai.toml")]
public class IdentityConfig
{
    [ConfigRange(1, 60)]
    [ConfigDescription("邮件验证码有效期（分钟），注册/密码重置/邮箱绑定统一使用")]
    public int EmailCodeExpireMinutes { get; set; } = 10;
    public PasswordConfig Password { get; set; } = new();
    public LockoutConfig Lockout { get; set; } = new();
}

[ConfigFile("pylai.toml")]
public class PasswordConfig
{
    [ConfigRange(1, 128)]
    [ConfigDescription("密码最小长度")]
    public int RequiredLength { get; set; } = 12;
    [ConfigRange(1, 128)]
    [ConfigDescription("Admin/Max 密码最小长度")]
    public int AdminRequiredLength { get; set; } = 14;
    [ConfigDescription("是否使用 HIBP k-anonymity 检查泄露密码")]
    public bool CheckBreachedPasswords { get; set; } = true;
    [ConfigDescription("密码必须包含数字")]
    public bool RequireDigit { get; set; } = true;
    [ConfigDescription("密码必须包含小写字母")]
    public bool RequireLowercase { get; set; } = false;
    [ConfigDescription("密码必须包含大写字母")]
    public bool RequireUppercase { get; set; } = false;
    [ConfigDescription("密码必须包含非字母数字字符")]
    public bool RequireNonAlphanumeric { get; set; } = false;
}

[ConfigFile("pylai.toml")]
public class LockoutConfig
{
    [ConfigRange(1, 10080)]
    public int DefaultTimeoutMinutes { get; set; } = 5;
    [ConfigRange(1, 100)]
    public int MaxFailedAttempts { get; set; } = 5;
}

[ConfigFile("pylai.toml")]
public class LoginRateLimitConfig
{
    [ConfigRange(1, 1000)]
    [ConfigDescription("同一 IP 登录失败达到阈值后进入递增封禁")]
    public int MaxFailuresPerIp { get; set; } = 10;
    [ConfigNotEmpty]
    [ConfigDescription("递增封禁时长（分钟），-1 为永久封禁")]
    public int[] BanDurationMinutes { get; set; } = [15, 60, 1440, -1];
    [ConfigRange(1, 365)]
    public int CooldownDays { get; set; } = 3;
}

[ConfigFile("pylai.toml")]
public class CookieConfig
{
    [ConfigDescription("认证 Cookie 名称")]
    public string Name { get; set; } = "Pylaios.Auth";
    [ConfigDescription("会话追踪 Cookie 名称")]
    public string SessionName { get; set; } = "Pylaios.Session";
    public bool HttpOnly { get; set; } = true;
    public string SameSite { get; set; } = "Lax";
    public string SecurePolicy { get; set; } = "Always";
    [ConfigRange(1, 365)]
    public int ExpireDays { get; set; } = 14;
    public bool SlidingExpiration { get; set; } = true;
}

[ConfigFile("pylai.toml")]
public class FrontendConfig
{
    [ConfigDescription("前端 SPA 地址")]
    public string Url { get; set; } = "http://localhost:5173";
}

[ConfigFile("pylai.toml")]
public class OpenIddictConfig
{
    public TokenLifetimeConfig AccessToken { get; set; } = new();
    public TokenLifetimeConfig RefreshToken { get; set; } = new() { LifetimeHours = 24 * 7 };
    public TokenLifetimeConfig IdentityToken { get; set; } = new();
    public EndpointsConfig Endpoints { get; set; } = new();
    public GrantsConfig Grants { get; set; } = new();
    public ScopesConfig Scopes { get; set; } = new();
    public CertificatesConfig Certificates { get; set; } = new();
    public SigningKeyEncryptionConfig SigningKeyEncryption { get; set; } = new();
    [ConfigDescription("固定 OIDC Issuer（必须与外部访问地址一致，生产环境必填）")]
    public string Issuer { get; set; } = "http://localhost:5000";
    [ConfigDescription("OpenIddict 传输安全要求（生产默认强制 HTTPS；纯内网 HTTP 部署可设 false）")]
    public bool RequireHttps { get; set; } = true;
}

[ConfigFile("pylai.toml")]
public class SigningKeyEncryptionConfig
{
    [ConfigDescription("签名私钥 KEK 文件；必须位于数据库边界之外")]
    public string KeyFile { get; set; } = "";
}

public class ScopesConfig
{
    public bool OpenId { get; set; } = true;
    public bool ProfileBasic { get; set; } = true;
    public bool ProfileMail { get; set; } = true;
    public bool ProfileRole { get; set; } = true;
    public bool OfflineAccess { get; set; } = true;

    public IEnumerable<string> Enabled()
    {
        if (OpenId) yield return AuthConstants.Scopes.OpenId;
        if (ProfileBasic) yield return AuthConstants.Scopes.ProfileBasic;
        if (ProfileMail) yield return AuthConstants.Scopes.ProfileMail;
        if (ProfileRole) yield return AuthConstants.Scopes.ProfileRole;
        if (OfflineAccess) yield return AuthConstants.Scopes.OfflineAccess;
    }
}

[ConfigFile("pylai.toml")]
public class CertificatesConfig
{
    public CertificateSourceConfig Signing { get; set; } = new();
    public CertificateSourceConfig Encryption { get; set; } = new();
}

[ConfigFile("pylai.toml")]
public class CertificateSourceConfig
{
    [ConfigDescription("PFX 证书文件路径")]
    public string Path { get; set; } = "";
    [ConfigSensitive]
    [ConfigDescription("证书私钥密码")]
    public string Password { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class TokenLifetimeConfig
{
    [ConfigRange(1, 8760)]
    public int LifetimeHours { get; set; } = 1;
    [ConfigRange(1, 3650)]
    public int LifetimeDays { get; set; }
    public bool DisableEncryption { get; set; }
}

[ConfigFile("pylai.toml")]
public class EndpointsConfig
{
    public string Authorize { get; set; } = "/connect/authorize";
    public string Token { get; set; } = "/connect/token";
    public string UserInfo { get; set; } = "/connect/userinfo";
    public string Introspect { get; set; } = "/connect/introspect";
    public string EndSession { get; set; } = "/connect/logout";
}

[ConfigFile("pylai.toml")]
public class GrantsConfig
{
    public bool AuthorizationCode { get; set; } = true;
    public bool RefreshToken { get; set; } = true;
    public bool ClientCredentials { get; set; } = true;
}

[ConfigFile("pylai.toml")]
public class ExternalLoginConfig
{
    public ExternalProviderConfig Facebook { get; set; } = new();
    public ExternalProviderConfig Microsoft { get; set; } = new();
    public ExternalProviderConfig Github { get; set; } = new();
}

[ConfigFile("pylai.toml")]
public class ExternalProviderConfig
{
    [ConfigDescription("Facebook AppId（空即禁用）")]
    public string AppId { get; set; } = "";
    [ConfigDescription("Microsoft/GitHub ClientId（空即禁用）")]
    public string ClientId { get; set; } = "";
    [ConfigSensitive]
    [ConfigDescription("Facebook AppSecret")]
    public string AppSecret { get; set; } = "";
    [ConfigSensitive]
    [ConfigDescription("Microsoft/GitHub ClientSecret")]
    public string ClientSecret { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class LoggingConfig
{
    public string DefaultLevel { get; set; } = "Warning";
    public string MicrosoftAspNetCoreLevel { get; set; } = "Warning";
    public string MicrosoftEntityFrameworkCoreLevel { get; set; } = "Warning";
    public string OpenIddictLevel { get; set; } = "Warning";
    public string SystemNetHttpLevel { get; set; } = "Warning";
    public string PylaiosLevel { get; set; } = "Information";
}

[ConfigFile("pylai.toml")]
public class InviteCodeConfig
{
    [ConfigSensitive]
    [ConfigDescription("邀请码 HMAC pepper；生产环境必须由独立 Secret 注入")]
    public string ServerPepper { get; set; } = "";
    [ConfigRange(1, 1000)]
    public int MaxFailuresPerIp { get; set; } = 20;
    [ConfigRange(1, 8760)]
    public int BanDurationHours { get; set; } = 48;
    [ConfigRange(1, 8760)]
    public int EmailCodeBanDurationHours { get; set; } = 24;
    [ConfigRange(1, 10000)]
    public int UsernameCheckMaxPerHourPerIp { get; set; } = 100;
    [ConfigRange(1, 1000)]
    [ConfigDescription("普通邀请码的默认最大核销次数")]
    public int MaxRedemptions { get; set; } = 10;
    [ConfigRange(1, 8760)]
    [ConfigDescription("新邀请码默认有效期（小时）")]
    public int DefaultLifetimeHours { get; set; } = 168;
    [ConfigDescription("注册是否必须使用邀请码（开启后注册流程不可跳过邀请码）")]
    public bool RequireInviteCode { get; set; } = false;
}

[ConfigFile("pylai.toml")]
public class RedisConfig
{
    public string Host { get; set; } = "127.0.0.1";
    [ConfigRange(1, 65535)]
    public int Port { get; set; } = 6379;
    [ConfigSensitive]
    public string Password { get; set; } = "";
    [ConfigRange(0, 15)]
    public int Database { get; set; } = 0;
    [ConfigRange(1, 60000)]
    public int ConnectTimeoutMs { get; set; } = 5000;
}

[ConfigFile("pylai.toml")]
public class SeedsConfig
{
    public SeedUserConfig DefaultAdmin { get; set; } = new();
    public SeedUserConfig DefaultUser { get; set; } = new();
    public SeedUserConfig DefaultMax { get; set; } = new();
}

[ConfigFile("pylai.toml")]
public class SeedUserConfig
{
    [ConfigDescription("种子账号邮箱（用户名）")]
    public string Email { get; set; } = "";
    [ConfigSensitive]
    [ConfigDescription("种子账号密码（敏感，建议 Secrets.local.toml 覆盖）")]
    public string Password { get; set; } = "";
    [ConfigDescription("种子账号显示名称")]
    public string DisplayName { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class TokenCleanupConfig
{
    [ConfigDescription("OpenIddict 过期 Token 清理任务开关")]
    public bool Enabled { get; set; } = true;
}

[ConfigFile("pylai.toml")]
public class AdminRateLimitConfig
{
    [ConfigRange(1, 100)]
    public int MaxFailuresFirstBan { get; set; } = 5;
    [ConfigRange(1, 86400)]
    public int FirstBanDurationSeconds { get; set; } = 30;
    [ConfigRange(1, 100)]
    public int MaxFailuresSecondBan { get; set; } = 20;
    [ConfigRange(1, 8760)]
    public int SecondBanDurationHours { get; set; } = 24;
}

[ConfigFile("pylai.toml")]
public class CorsConfig
{
    public bool Enabled { get; set; } = true;
    public string[] AllowedOrigins { get; set; } = ["http://localhost:5173"];
    public string[] AllowedMethods { get; set; } = ["GET", "POST", "PUT", "DELETE", "OPTIONS"];
    public string[] AllowedHeaders { get; set; } = ["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"];
    public bool AllowCredentials { get; set; } = true;
}

[ConfigFile("pylai.toml")]
public class IpResolutionConfig
{
    [ConfigDescription("可信代理 IP 列表（仅信任这些来源的 X-Forwarded-For）")]
    public string[] TrustedProxies { get; set; } = [];
    public string[] IpWhitelist { get; set; } = [];
    public string[] TrustedHeaders { get; set; } = ["X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host"];
    public bool ForwardedHeadersEnabled { get; set; }
    [ConfigDescription("可信代理 CIDR 网络（如 10.0.0.0/8）")]
    public string[] TrustedNetworks { get; set; } = [];
}

[ConfigFile("pylai.toml")]
public class UserTokenConfig
{
    [ConfigRange(0, 3650)]
    [ConfigDescription("UserToken 默认有效期（天），生产建议 30-90 天")]
    public int DefaultLifetimeDays { get; set; } = 60;
}

[ConfigFile("pylai.toml")]
public class ConfirmationRateLimitConfig
{
    [ConfigRange(1, 100)]
    [ConfigDescription("特殊功能密码二次验证最大失败次数")]
    public int MaxFailures { get; set; } = 10;
    [ConfigRange(1, 8760)]
    [ConfigDescription("达到上限后账号特殊功能操作锁定小时数")]
    public int BanDurationHours { get; set; } = 24;
}

[ConfigFile("pylai.toml")]
public class MfaConfig
{
    [ConfigDescription("WebAuthn Relying Party ID")]
    public string RelyingPartyId { get; set; } = "localhost";
    [ConfigDescription("WebAuthn 显示名称")]
    public string RelyingPartyName { get; set; } = "Pylaios";
    [ConfigDescription("WebAuthn 允许来源")]
    public string[] Origins { get; set; } = ["http://localhost:5173"];
    [ConfigRange(1, 30)]
    public int ChallengeLifetimeMinutes { get; set; } = 5;
    [ConfigDescription("Admin 及以上角色登录时是否强制要求 MFA（默认关闭，生产环境建议开启）")]
    public bool RequireForAdmin { get; set; } = false;
    [ConfigDescription("Max 角色是否强制使用 WebAuthn（需 HTTPS 环境；HTTP/局域网部署请关闭）")]
    public bool RequireWebAuthnForMax { get; set; } = false;
}

[ConfigFile("pylai.toml")]
public class DataProtectionConfig
{
    [ConfigDescription("ASP.NET Core DataProtection 持久化密钥目录")]
    public string KeyDirectory { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class DeploymentConfig
{
    [ConfigDescription("当前镜像是否包含 bundled Nginx 反向代理")]
    public bool BundledNginx { get; set; }
}

[ConfigFile("pylai.toml")]
public class EmailConfig
{
    public SmtpConfig Smtp { get; set; } = new();
    [ConfigDescription("发件人显示名称")]
    public string FromName { get; set; } = "Pylaios";
    [ConfigDescription("发件人邮箱地址（留空且 Smtp.Host 为空即禁用邮件）")]
    public string FromAddress { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class SmtpConfig
{
    [ConfigDescription("SMTP 服务器地址（留空即禁用邮件）")]
    public string Host { get; set; } = "";
    [ConfigRange(1, 65535)]
    public int Port { get; set; } = 587;
    [ConfigDescription("SMTP 加密方式：None / StartTls / SslOnConnect（465 通常用 SslOnConnect，587 通常用 StartTls）")]
    public string Security { get; set; } = "StartTls";
    public string Username { get; set; } = "";
    [ConfigSensitive]
    public string Password { get; set; } = "";
}

[ConfigFile("pylai.toml")]
public class BackupConfig
{
    [ConfigDescription("数据库备份目录（backup 命令产物，pg_dump 快照）")]
    public string Directory { get; set; } = "backups";
}

[ConfigFile("pylai.toml")]
public class MailThemeConfig
{
    public MailTemplateConfig Register { get; set; } = MailThemeDefaults.Register;
    public MailTemplateConfig Bind { get; set; } = MailThemeDefaults.Bind;
    public MailTemplateConfig Change { get; set; } = MailThemeDefaults.Change;
    public MailTemplateConfig PasswordReset { get; set; } = MailThemeDefaults.PasswordReset;
}

public class MailTemplateConfig
{
    [ConfigNotEmpty]
    [ConfigDescription("邮件主题")]
    public string Title { get; set; } = "";

    [ConfigNotEmpty]
    [ConfigDescription("邮件正文模板；占位符: %%CaptchaCode%%（必填）/ %%Browser%% / %%IPAddress%% / %%ExpireMinutes%%（可选）")]
    public string Context { get; set; } = "";
}

public static class MailThemeDefaults
{
    private static readonly string Tail = """
        ------
        此邮件由系统自动生成并发送，如果不是本人操作，可以选择：
        - 忽略邮件，可能是有人输入了错误的电子邮件地址。
        - 如果频繁收到此邮件，请联系管理员。
        """;

    public static MailTemplateConfig Register { get; } = new()
    {
        Title = "注册 Pylai！",
        Context = $"""
            你正在网页端注册 Pylai 通行证，请仔细核查以下信息，然后输入验证码：

            浏览器：%%Browser%%
            IP地址：%%IPAddress%%

            你的验证码是：%%CaptchaCode%%
            验证码 %%ExpireMinutes%% 分钟内有效，过期后请重新获取。

            Kirsmax(Bot),
            Poeat Team.

            {Tail}
            """
    };

    public static MailTemplateConfig Bind { get; } = new()
    {
        Title = "绑定邮箱",
        Context = $"""
            你正在网页端为 Pylai 通行证绑定邮箱，请仔细核查以下信息，然后输入验证码：

            浏览器：%%Browser%%
            IP地址：%%IPAddress%%

            你的验证码是：%%CaptchaCode%%
            验证码 %%ExpireMinutes%% 分钟内有效，过期后请重新获取。

            Kirsmax(Bot),
            Poeat Team.

            {Tail}
            """
    };

    public static MailTemplateConfig Change { get; } = new()
    {
        Title = "更换邮箱",
        Context = $"""
            你正在网页端更换 Pylai 通行证的邮箱，请仔细核查以下信息，然后输入验证码：

            浏览器：%%Browser%%
            IP地址：%%IPAddress%%

            你的验证码是：%%CaptchaCode%%
            验证码 %%ExpireMinutes%% 分钟内有效，过期后请重新获取。

            Kirsmax(Bot),
            Poeat Team.

            {Tail}
            """
    };

    public static MailTemplateConfig PasswordReset { get; } = new()
    {
        Title = "密码重置",
        Context = $"""
            你正在网页端重置 Pylai 通行证的密码，请仔细核查以下信息，然后输入验证码：

            浏览器：%%Browser%%
            IP地址：%%IPAddress%%

            你的验证码是：%%CaptchaCode%%
            验证码 %%ExpireMinutes%% 分钟内有效，过期后请重新获取。

            Kirsmax(Bot),
            Poeat Team.

            {Tail}
            """
    };
}

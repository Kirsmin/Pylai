using System.Net;
using System.Reflection;
using System.Text.RegularExpressions;

namespace Pylaios.Features.Config;

public static class ConfigValidator
{
    public static void ValidateValues(MainConfig config, string environment, ConfigLoadResult result)
    {
        ValidateServer(config, result);
        ValidateOpenIddictIssuer(config, result, environment);
        ValidateLogging(config, result);
        ValidateCookie(config, result);
        ValidateFrontend(config, result);
        ValidateLoginRateLimit(config, result);
        ValidateIpResolution(config, result);
        ValidateCors(config, result);
        ValidateSmtp(config, result);
        ValidateMfa(config, result);
        ValidateMailTheme(config, result);
        ValidateInviteCodes(config, result, environment);
        ValidateDeployment(config, result);
        if (!environment.Equals("Development", StringComparison.OrdinalIgnoreCase)
            && (config.UserToken.DefaultLifetimeDays is < 1 or > 90))
        {
            result.Errors.Add(new ConfigIssue(FileOf<UserTokenConfig>(), "UserToken.DefaultLifetimeDays", "E005",
                "生产环境 UserToken 默认有效期必须在 1-90 天之间"));
        }

        if (!environment.Equals("Development", StringComparison.OrdinalIgnoreCase))
        {
            if (config.Server.AllowedHosts.Length == 0 || config.Server.AllowedHosts.Contains("*", StringComparer.OrdinalIgnoreCase))
            {
                result.Errors.Add(new ConfigIssue(FileOf<ServerConfig>(), "Server.AllowedHosts", "E004",
                    "生产环境必须配置明确的 AllowedHosts 白名单，禁止使用通配符 *"));
            }

            ValidateCertificate(config.OpenIddict.Certificates.Signing,
                "OpenIddict.Certificates.Signing", FileOf<CertificatesConfig>(), result, optional: true);
            ValidateCertificate(config.OpenIddict.Certificates.Encryption,
                "OpenIddict.Certificates.Encryption", FileOf<CertificatesConfig>(), result,
                optional: false);

            if (string.IsNullOrWhiteSpace(config.DataProtection.KeyDirectory))
            {
                result.Errors.Add(new ConfigIssue(FileOf<DataProtectionConfig>(), "DataProtection.KeyDirectory", "E004",
                    "生产环境必须配置持久化 DataProtection 密钥目录，拒绝使用临时密钥环"));
            }

            if (string.IsNullOrWhiteSpace(config.OpenIddict.Certificates.Signing.Path)
                && string.IsNullOrWhiteSpace(config.OpenIddict.SigningKeyEncryption.KeyFile))
            {
                result.Errors.Add(new ConfigIssue(FileOf<SigningKeyEncryptionConfig>(), "OpenIddict.SigningKeyEncryption.KeyFile", "E004",
                    "数据库托管签名密钥必须配置数据库边界之外的 KEK 文件"));
            }

            if (!string.IsNullOrWhiteSpace(config.OpenIddict.SigningKeyEncryption.KeyFile)
                && !File.Exists(config.OpenIddict.SigningKeyEncryption.KeyFile))
            {
                result.Errors.Add(new ConfigIssue(FileOf<SigningKeyEncryptionConfig>(), "OpenIddict.SigningKeyEncryption.KeyFile", "E007",
                    $"签名 KEK 文件不存在: {config.OpenIddict.SigningKeyEncryption.KeyFile}"));
            }

            if (!config.OpenIddict.RequireHttps
                && config.Cookie.SecurePolicy.Equals("Always", StringComparison.OrdinalIgnoreCase))
            {
                result.Warnings.Add("OpenIddict.RequireHttps=false 且 Cookie.SecurePolicy=Always；HTTP 下认证 Cookie 会被浏览器拒绝，请确认部署架构");
            }
        }
    }

    private static void ValidateServer(MainConfig config, ConfigLoadResult result)
    {
        if (!Uri.TryCreate(config.Server.Url, UriKind.Absolute, out var uri)
            || (uri.Scheme != "http" && uri.Scheme != "https")
            || string.IsNullOrEmpty(uri.Host)
            || !string.IsNullOrEmpty(uri.PathAndQuery.Trim('/')))
        {
            result.Errors.Add(new ConfigIssue(FileOf<ServerConfig>(), "Server.Url", "E006",
                $"Server.Url 不是合法监听地址: {config.Server.Url}（应为 http(s)://host:port）"));
        }
    }

    private static void ValidateOpenIddictIssuer(MainConfig config, ConfigLoadResult result, string environment)
    {
        if (!Uri.TryCreate(config.OpenIddict.Issuer, UriKind.Absolute, out var issuer)
            || (issuer.Scheme != "http" && issuer.Scheme != "https")
            || string.IsNullOrEmpty(issuer.Host)
            || !string.IsNullOrEmpty(issuer.Query)
            || !string.IsNullOrEmpty(issuer.Fragment)
            || !string.IsNullOrEmpty(issuer.PathAndQuery.Trim('/')))
        {
            result.Errors.Add(new ConfigIssue(FileOf<OpenIddictConfig>(), "OpenIddict.Issuer", "E006",
                $"OpenIddict.Issuer 不是合法地址: {config.OpenIddict.Issuer}（应为 http(s)://host[:port]，不带路径）"));
            return;
        }

        if (!environment.Equals("Development", StringComparison.OrdinalIgnoreCase)
            && config.OpenIddict.RequireHttps
            && !issuer.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase))
        {
            result.Errors.Add(new ConfigIssue(FileOf<OpenIddictConfig>(), "OpenIddict.Issuer", "E006",
                "OpenIddict.RequireHttps=true 时 OpenIddict.Issuer 必须使用 https"));
        }
    }

    private static void ValidateLogging(MainConfig config, ConfigLoadResult result)
    {
        ValidateLogLevel(config.Logging.DefaultLevel, "Logging.DefaultLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.MicrosoftAspNetCoreLevel, "Logging.MicrosoftAspNetCoreLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.MicrosoftEntityFrameworkCoreLevel, "Logging.MicrosoftEntityFrameworkCoreLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.OpenIddictLevel, "Logging.OpenIddictLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.SystemNetHttpLevel, "Logging.SystemNetHttpLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.PylaiosLevel, "Logging.PylaiosLevel", FileOf<LoggingConfig>(), result);
    }

    private static void ValidateLogLevel(string value, string path, string file, ConfigLoadResult result)
    {
        if (!Enum.TryParse<Microsoft.Extensions.Logging.LogLevel>(value, ignoreCase: true, out _))
        {
            result.Errors.Add(new ConfigIssue(file, path, "E003",
                $"无效日志级别: {value}（可用: Trace/Debug/Information/Warning/Error/Critical/None）"));
        }
    }

    private static void ValidateCookie(MainConfig config, ConfigLoadResult result)
    {
        if (!Enum.TryParse<Microsoft.AspNetCore.Http.SameSiteMode>(config.Cookie.SameSite, ignoreCase: true, out _))
        {
            result.Errors.Add(new ConfigIssue(FileOf<CookieConfig>(), "Cookie.SameSite", "E003",
                $"无效 SameSite 值: {config.Cookie.SameSite}（可用: Unspecified/None/Lax/Strict）"));
        }

        if (!Enum.TryParse<Microsoft.AspNetCore.Http.CookieSecurePolicy>(config.Cookie.SecurePolicy, ignoreCase: true, out _))
        {
            result.Errors.Add(new ConfigIssue(FileOf<CookieConfig>(), "Cookie.SecurePolicy", "E003",
                $"无效 SecurePolicy 值: {config.Cookie.SecurePolicy}（可用: None/Always/SameAsRequest）"));
        }
    }

    private static void ValidateFrontend(MainConfig config, ConfigLoadResult result)
    {
        if (!Uri.TryCreate(config.Frontend.Url, UriKind.Absolute, out var uri)
            || (uri.Scheme != "http" && uri.Scheme != "https")
            || string.IsNullOrEmpty(uri.Host)
            || !string.IsNullOrEmpty(uri.Query)
            || !string.IsNullOrEmpty(uri.Fragment))
        {
            result.Errors.Add(new ConfigIssue(FileOf<FrontendConfig>(), "Frontend.Url", "E006",
                $"Frontend.Url 不是合法前端地址: {config.Frontend.Url}"));
        }
    }

    private static void ValidateLoginRateLimit(MainConfig config, ConfigLoadResult result)
    {
        var durations = config.LoginRateLimit.BanDurationMinutes;
        if (durations.Length == 0)
        {
            result.Errors.Add(new ConfigIssue(FileOf<LoginRateLimitConfig>(), "LoginRateLimit.BanDurationMinutes", "E004",
                "LoginRateLimit.BanDurationMinutes 不能为空"));
            return;
        }

        for (var i = 0; i < durations.Length; i++)
        {
            var value = durations[i];
            if (value != -1 && value <= 0)
            {
                result.Errors.Add(new ConfigIssue(FileOf<LoginRateLimitConfig>(), "LoginRateLimit.BanDurationMinutes", "E005",
                    $"第 {i + 1} 个封禁时长必须大于 0 或为 -1（永久）"));
            }
        }
    }

    private static void ValidateIpResolution(MainConfig config, ConfigLoadResult result)
    {
        foreach (var proxy in config.IpResolution.TrustedProxies)
        {
            if (!IPAddress.TryParse(proxy, out _))
            {
                result.Errors.Add(new ConfigIssue(FileOf<IpResolutionConfig>(), "IpResolution.TrustedProxies", "E003",
                    $"TrustedProxies 包含无效 IP: {proxy}"));
            }
        }

        foreach (var cidr in config.IpResolution.TrustedNetworks)
        {
            var parts = cidr.Split('/');
            if (parts.Length != 2 || !IPAddress.TryParse(parts[0], out var networkIp) || !int.TryParse(parts[1], out var prefix))
            {
                result.Errors.Add(new ConfigIssue(FileOf<IpResolutionConfig>(), "IpResolution.TrustedNetworks", "E003",
                    $"TrustedNetworks 包含无效 CIDR: {cidr}"));
                continue;
            }

            var maxPrefix = networkIp.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork ? 32 : 128;
            if (prefix < 0 || prefix > maxPrefix)
            {
                result.Errors.Add(new ConfigIssue(FileOf<IpResolutionConfig>(), "IpResolution.TrustedNetworks", "E005",
                    $"CIDR 前缀长度无效: {cidr}"));
            }
        }

        // Cloudflare 场景提示
        var trustedHeaders = config.IpResolution.TrustedHeaders;
        if (config.IpResolution.ForwardedHeadersEnabled && trustedHeaders.Length > 0)
        {
            var hasCfHeader = trustedHeaders.Any(h => h.Equals("CF-Connecting-IP", StringComparison.OrdinalIgnoreCase));
            var hasXff = trustedHeaders.Any(h => h.Equals("X-Forwarded-For", StringComparison.OrdinalIgnoreCase));
            if (hasCfHeader && !hasXff)
            {
                result.Warnings.Add("IpResolution.TrustedHeaders 包含 CF-Connecting-IP 但不包含 X-Forwarded-For；建议同时保留 X-Forwarded-For 作为 Fallback");
            }
        }

        if (config.IpResolution.ForwardedHeadersEnabled && trustedHeaders.Length == 0)
        {
            result.Errors.Add(new ConfigIssue(FileOf<IpResolutionConfig>(), "IpResolution.TrustedHeaders", "E004",
                "ForwardedHeadersEnabled=true 时 TrustedHeaders 不能为空"));
        }
    }

    private static void ValidateCors(MainConfig config, ConfigLoadResult result)
    {
        if (!config.Cors.Enabled)
            return;

        foreach (var origin in config.Cors.AllowedOrigins)
        {
            if (origin == "*" && config.Cors.AllowCredentials)
            {
                result.Errors.Add(new ConfigIssue(FileOf<CorsConfig>(), "Cors.AllowedOrigins", "E006",
                    "AllowCredentials=true 时 CORS 不允许使用通配符 *"));
                continue;
            }

            if (origin == "*")
                continue;

            if (!Uri.TryCreate(origin, UriKind.Absolute, out var uri)
                || (uri.Scheme != "http" && uri.Scheme != "https")
                || string.IsNullOrEmpty(uri.Host))
            {
                result.Errors.Add(new ConfigIssue(FileOf<CorsConfig>(), "Cors.AllowedOrigins", "E006",
                    $"CORS Origin 不合法: {origin}"));
            }
        }
    }

    private static void ValidateSmtp(MainConfig config, ConfigLoadResult result)
    {
        var smtp = config.Email.Smtp;
        var hostEmpty = string.IsNullOrWhiteSpace(smtp.Host);
        var fromEmpty = string.IsNullOrWhiteSpace(config.Email.FromAddress);

        if (hostEmpty && fromEmpty)
        {
            result.Warnings.Add("邮件服务未配置（Email.Smtp.Host / Email.FromAddress），注册/重置密码等验证码邮件不会发送");
            return;
        }

        if (hostEmpty || fromEmpty)
        {
            result.Errors.Add(new ConfigIssue(FileOf<EmailConfig>(), "Email", "E004",
                "Email.Smtp.Host 与 Email.FromAddress 必须同时配置或同时留空"));
        }

        var security = smtp.Security?.Trim();
        var validSecurity = security is not null
            && (security.Equals("None", StringComparison.OrdinalIgnoreCase)
                || security.Equals("StartTls", StringComparison.OrdinalIgnoreCase)
                || security.Equals("SslOnConnect", StringComparison.OrdinalIgnoreCase));
        if (!validSecurity)
        {
            result.Errors.Add(new ConfigIssue(FileOf<SmtpConfig>(), "Email.Smtp.Security", "E003",
                $"无效 SMTP 加密方式: {smtp.Security}（可用: None / StartTls / SslOnConnect）"));
            return;
        }

        if (smtp.Port == 465 && !security!.Equals("SslOnConnect", StringComparison.OrdinalIgnoreCase))
        {
            result.Errors.Add(new ConfigIssue(FileOf<SmtpConfig>(), "Email.Smtp.Security", "E006",
                "端口 465 为 SMTPS/隐式 TLS 端口，Email.Smtp.Security 必须为 SslOnConnect；如需 STARTTLS 请使用 587"));
        }
        else if (smtp.Port == 587 && security!.Equals("SslOnConnect", StringComparison.OrdinalIgnoreCase))
        {
            result.Warnings.Add("端口 587 通常使用 STARTTLS；当前配置为 SslOnConnect，请确认 SMTP 服务端支持隐式 TLS");
        }
        else if (smtp.Port == 25 && security!.Equals("SslOnConnect", StringComparison.OrdinalIgnoreCase))
        {
            result.Warnings.Add("端口 25 通常为明文或 STARTTLS；当前配置为 SslOnConnect，请确认 SMTP 服务端支持");
        }
    }

    private static void ValidateMfa(MainConfig config, ConfigLoadResult result)
    {
        if (string.IsNullOrWhiteSpace(config.Mfa.RelyingPartyId))
        {
            result.Errors.Add(new ConfigIssue(FileOf<MfaConfig>(), "Mfa.RelyingPartyId", "E004",
                "Mfa.RelyingPartyId 不能为空"));
        }

        if (config.Mfa.Origins.Length == 0)
        {
            result.Errors.Add(new ConfigIssue(FileOf<MfaConfig>(), "Mfa.Origins", "E004",
                "Mfa.Origins 不能为空"));
            return;
        }

        foreach (var origin in config.Mfa.Origins)
        {
            if (!Uri.TryCreate(origin, UriKind.Absolute, out var uri)
                || (uri.Scheme != "http" && uri.Scheme != "https")
                || string.IsNullOrEmpty(uri.Host)
                || !string.IsNullOrEmpty(uri.Query)
                || !string.IsNullOrEmpty(uri.Fragment)
                || !string.IsNullOrEmpty(uri.PathAndQuery.Trim('/')))
            {
                result.Errors.Add(new ConfigIssue(FileOf<MfaConfig>(), "Mfa.Origins", "E006",
                    $"WebAuthn Origin 不合法: {origin}（应为 http(s)://host[:port]）"));
            }
        }
    }

    private static void ValidateMailTheme(MainConfig config, ConfigLoadResult result)
    {
        var placeholders = new[] { "%%CaptchaCode%%", "%%Browser%%", "%%IPAddress%%", "%%ExpireMinutes%%" };
        var themes = new (string Path, MailTemplateConfig Theme)[]
        {
            ("MailTheme.Register", config.MailTheme.Register),
            ("MailTheme.Bind", config.MailTheme.Bind),
            ("MailTheme.Change", config.MailTheme.Change),
            ("MailTheme.PasswordReset", config.MailTheme.PasswordReset)
        };

        foreach (var (path, theme) in themes)
        {
            if (string.IsNullOrWhiteSpace(theme.Title))
            {
                result.Errors.Add(new ConfigIssue(FileOf<MailThemeConfig>(), path + ".Title", "E004",
                    $"{path}.Title 不能为空"));
            }

            if (string.IsNullOrWhiteSpace(theme.Context))
            {
                result.Errors.Add(new ConfigIssue(FileOf<MailThemeConfig>(), path + ".Context", "E004",
                    $"{path}.Context 不能为空"));
                continue;
            }

            if (!theme.Context.Contains("%%CaptchaCode%%", StringComparison.Ordinal))
            {
                result.Errors.Add(new ConfigIssue(FileOf<MailThemeConfig>(), path + ".Context", "E004",
                    $"{path}.Context 必须包含占位符 %%CaptchaCode%%"));
            }

            foreach (var token in ExtractPlaceholders(theme.Context))
            {
                if (!placeholders.Contains(token, StringComparer.Ordinal))
                {
                    result.Warnings.Add($"{path}.Context 包含未知占位符 {token}（可用: %%CaptchaCode%% / %%Browser%% / %%IPAddress%% / %%ExpireMinutes%%）");
                }
            }
        }
    }

    private static IEnumerable<string> ExtractPlaceholders(string text)
    {
        foreach (Match match in Regex.Matches(text, @"%%([^%]+)%%"))
            yield return match.Value;
    }

    private static void ValidateInviteCodes(MainConfig config, ConfigLoadResult result, string environment)
    {
        if (!environment.Equals("Development", StringComparison.OrdinalIgnoreCase)
            && string.IsNullOrWhiteSpace(config.InviteCode.ServerPepper))
        {
            result.Errors.Add(new ConfigIssue(FileOf<InviteCodeConfig>(), "InviteCode.ServerPepper", "E004",
                "生产环境必须配置独立的邀请码 HMAC pepper"));
        }

        if (string.IsNullOrWhiteSpace(config.InviteCode.ServerPepper))
            result.Warnings.Add("InviteCode.ServerPepper 未配置；邀请码创建与兑换将被禁用");

        if (config.InviteCode.DefaultLifetimeHours <= 0)
        {
            result.Errors.Add(new ConfigIssue(FileOf<InviteCodeConfig>(), "InviteCode.DefaultLifetimeHours", "E005",
                "邀请码默认有效期必须大于 0 小时"));
        }
    }

    private static void ValidateDeployment(MainConfig config, ConfigLoadResult result)
    {
        if (!config.Deployment.BundledNginx)
            return;

        if (!config.IpResolution.ForwardedHeadersEnabled
            || !config.IpResolution.TrustedProxies.Contains("127.0.0.1", StringComparer.Ordinal)
            || !config.IpResolution.TrustedProxies.Contains("::1", StringComparer.Ordinal)
            || !config.IpResolution.TrustedHeaders.Contains("X-Forwarded-For", StringComparer.OrdinalIgnoreCase)
            || !config.IpResolution.TrustedHeaders.Contains("X-Forwarded-Proto", StringComparer.OrdinalIgnoreCase))
        {
            result.Errors.Add(new ConfigIssue(FileOf<DeploymentConfig>(), "Deployment.BundledNginx", "E004",
                "bundled Nginx 部署必须启用 ForwardedHeaders，并信任 127.0.0.1、::1 的 X-Forwarded-For / X-Forwarded-Proto"));
        }
    }

    private static void ValidateCertificate(
        CertificateSourceConfig cert, string path, string file, ConfigLoadResult result, bool optional)
    {
        if (string.IsNullOrWhiteSpace(cert.Path))
        {
            if (!optional)
            {
                result.Errors.Add(new ConfigIssue(file, path + ".Path", "E004",
                    $"必须配置 {path}.Path"));
            }
            return;
        }

        if (!File.Exists(cert.Path))
        {
            result.Errors.Add(new ConfigIssue(file, path + ".Path", "E007",
                $"证书文件不存在: {cert.Path}"));
            return;
        }

        try
        {
            CertificateLoader.LoadPkcs12(cert.Path, cert.Password);
        }
        catch (Exception ex)
        {
            result.Errors.Add(new ConfigIssue(file, path + ".Path", "E007",
                $"证书无法加载: {ex.Message}"));
        }
    }

    public static string FileOf<T>() where T : class
        => FileOf(typeof(T));

    public static string FileOf(Type type)
    {
        var attr = type.GetCustomAttribute<ConfigFileAttribute>();
        if (attr is not null) return attr.FileName;
        return "pylai.toml";
    }
}

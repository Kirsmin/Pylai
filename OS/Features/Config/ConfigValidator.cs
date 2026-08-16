using System.Net;
using System.Reflection;

namespace Pylaios.Features.Config;

public static class ConfigValidator
{
    public static void ValidateValues(MainConfig config, string environment, ConfigLoadResult result)
    {
        ValidateServer(config, result);
        ValidateLogging(config, result);
        ValidateCookie(config, result);
        ValidateFrontend(config, result);
        ValidateLoginRateLimit(config, result);
        ValidateIpResolution(config, result);
        ValidateCors(config, result);
        ValidateSmtp(config, result);
        ValidateInviteCodes(config, result);

        if (!environment.Equals("Development", StringComparison.OrdinalIgnoreCase))
        {
            ValidateCertificate(config.OpenIddict.Certificates.Signing,
                "OpenIddict.Certificates.Signing", FileOf<CertificatesConfig>(), result, optional: true);
            ValidateCertificate(config.OpenIddict.Certificates.Encryption,
                "OpenIddict.Certificates.Encryption", FileOf<CertificatesConfig>(), result, optional: true);

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

    private static void ValidateLogging(MainConfig config, ConfigLoadResult result)
    {
        ValidateLogLevel(config.Logging.DefaultLevel, "Logging.DefaultLevel", FileOf<LoggingConfig>(), result);
        ValidateLogLevel(config.Logging.MicrosoftAspNetCoreLevel, "Logging.MicrosoftAspNetCoreLevel", FileOf<LoggingConfig>(), result);
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

    private static void ValidateInviteCodes(MainConfig config, ConfigLoadResult result)
    {
        var seen = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (group, codes) in new (string Group, IEnumerable<string> Codes)[]
                 {
                     (AuthConstants.Roles.Normal, config.InviteCode.Gift.Normal),
                     (AuthConstants.Roles.Admin, config.InviteCode.Gift.Admin),
                     (AuthConstants.Roles.Max, config.InviteCode.Gift.Max)
                 })
        {
            foreach (var code in codes)
            {
                if (seen.TryGetValue(code, out var existingGroup))
                {
                    result.Errors.Add(new ConfigIssue(FileOf<InviteCodeConfig>(), "InviteCode.Gift", "E004",
                        $"邀请码 {code} 同时出现在 {existingGroup} 与 {group} 列表中"));
                }
                else
                {
                    seen[code] = group;
                }
            }
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

using System.Diagnostics;
using MailKit.Net.Smtp;
using MailKit.Security;
using MimeKit;
using Pylaios.Features.Config;

namespace Pylaios.Shared;

public enum MailThemeKind { Register, Bind, Change, PasswordReset }

public class EmailSender
{
    private readonly MainConfig _config;
    private readonly EmailConfig _emailConfig;
    private readonly ILogger<EmailSender> _logger;
    private readonly TestModeOptions _testMode;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly IpResolutionService _ipResolver;

    public EmailSender(
        MainConfig config,
        ILogger<EmailSender> logger,
        TestModeOptions testMode,
        IHttpContextAccessor httpContextAccessor,
        IpResolutionService ipResolver)
    {
        _config = config;
        _emailConfig = config.Email;
        _logger = logger;
        _testMode = testMode;
        _httpContextAccessor = httpContextAccessor;
        _ipResolver = ipResolver;
    }

    public Task SendRegisterCodeAsync(User user, string email, string code)
        => SendThemedAsync(MailThemeKind.Register, email, code);

    public Task SendPasswordResetCodeAsync(User user, string email, string resetCode)
        => SendThemedAsync(MailThemeKind.PasswordReset, email, resetCode);

    public Task SendVerificationCodeAsync(MailThemeKind kind, string email, string code)
        => SendThemedAsync(kind, email, code);

    private async Task SendThemedAsync(MailThemeKind kind, string email, string code)
    {
        var theme = kind switch
        {
            MailThemeKind.Register => _config.MailTheme.Register,
            MailThemeKind.Bind => _config.MailTheme.Bind,
            MailThemeKind.Change => _config.MailTheme.Change,
            _ => _config.MailTheme.PasswordReset
        };

        var http = _httpContextAccessor.HttpContext;
        var ip = http is null ? "" : _ipResolver.GetClientIp(http);
        var browser = http?.Request.Headers.UserAgent.ToString() ?? "";

        var body = theme.Context
            .Replace("%%CaptchaCode%%", code)
            .Replace("%%Browser%%", browser)
            .Replace("%%IPAddress%%", ip)
            .Replace("%%ExpireMinutes%%", _config.Identity.EmailCodeExpireMinutes.ToString());

        await SendAsync(email, theme.Title, body);
    }

    private async Task SendAsync(string to, string subject, string body)
    {
        if (_testMode.Enabled)
        {
            _logger.LogDebug("[测试模式] 邮件跳过 → {To} | 主题: {Subject}", to, subject);
            return;
        }

        var smtp = _emailConfig.Smtp;
        if (string.IsNullOrEmpty(smtp.Host) || string.IsNullOrEmpty(_emailConfig.FromAddress))
        {
            _logger.LogWarning("SMTP 未配置，邮件未发送 → {To} | 主题: {Subject}", to, subject);
            return;
        }

        var security = ResolveSecurity(smtp.Security);
        var started = Stopwatch.GetTimestamp();
        try
        {
            _logger.LogInformation(
                "SMTP 发送开始 | 收件人:{To} 主题:{Subject} 发件人:{FromAddress} 服务器:{Host}:{Port} 加密:{Security} 超时:15000ms",
                to, subject, _emailConfig.FromAddress, smtp.Host, smtp.Port, smtp.Security);

            var message = new MimeMessage();
            message.From.Add(new MailboxAddress(_emailConfig.FromName, _emailConfig.FromAddress));
            message.To.Add(MailboxAddress.Parse(to));
            message.Subject = subject;
            message.Body = new TextPart("plain") { Text = body };

            using var client = new SmtpClient();
            client.Timeout = 15000;

            _logger.LogDebug("SMTP 连接中 | 服务器:{Host}:{Port} 加密:{Security}", smtp.Host, smtp.Port, smtp.Security);
            await client.ConnectAsync(smtp.Host, smtp.Port, security);
            _logger.LogDebug("SMTP 连接成功 | 服务器:{Host}:{Port} 耗时:{ElapsedMs}ms",
                smtp.Host, smtp.Port, ElapsedMs(started));

            if (!string.IsNullOrEmpty(smtp.Username))
            {
                _logger.LogDebug("SMTP 认证中 | 用户:{Username} 服务器:{Host}:{Port}", smtp.Username, smtp.Host, smtp.Port);
                await client.AuthenticateAsync(smtp.Username, smtp.Password);
                _logger.LogDebug("SMTP 认证成功 | 用户:{Username} 服务器:{Host}:{Port} 耗时:{ElapsedMs}ms",
                    smtp.Username, smtp.Host, smtp.Port, ElapsedMs(started));
            }

            await client.SendAsync(message);
            await client.DisconnectAsync(true);

            _logger.LogInformation(
                "邮件已发送 | 收件人:{To} 主题:{Subject} 服务器:{Host}:{Port} 加密:{Security} 耗时:{ElapsedMs}ms",
                to, subject, smtp.Host, smtp.Port, smtp.Security, ElapsedMs(started));
        }
        catch (Exception ex)
        {
            _logger.LogError(ex,
                "邮件发送失败 | 收件人:{To} 主题:{Subject} 服务器:{Host}:{Port} 加密:{Security} 耗时:{ElapsedMs}ms",
                to, subject, smtp.Host, smtp.Port, smtp.Security, ElapsedMs(started));
            throw;
        }
    }

    private static SecureSocketOptions ResolveSecurity(string? value)
    {
        return value?.Trim().ToLowerInvariant() switch
        {
            "none" => SecureSocketOptions.None,
            "starttls" => SecureSocketOptions.StartTls,
            "sslonconnect" => SecureSocketOptions.SslOnConnect,
            _ => throw new InvalidOperationException(
                $"无效 SMTP 加密方式: {value}（可用: None / StartTls / SslOnConnect）")
        };
    }

    private static long ElapsedMs(long started) =>
        (long)Stopwatch.GetElapsedTime(started).TotalMilliseconds;
}
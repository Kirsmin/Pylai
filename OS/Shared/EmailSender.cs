using System.Diagnostics;
using MailKit.Net.Smtp;
using MailKit.Security;
using Microsoft.AspNetCore.Identity;
using MimeKit;

namespace Pylaios.Shared;

public class EmailSender : IEmailSender<User>
{
    private readonly EmailConfig _emailConfig;
    private readonly ILogger<EmailSender> _logger;
    private readonly TestModeOptions _testMode;

    public EmailSender(MainConfig config, ILogger<EmailSender> logger, TestModeOptions testMode)
    {
        _emailConfig = config.Email;
        _logger = logger;
        _testMode = testMode;
    }

    public Task SendConfirmationLinkAsync(User user, string email, string confirmationLink)
    {
        var subject = "邮箱验证码";
        var body = $"您的验证码是：{confirmationLink}\n\n有效期 10 分钟。";
        return SendAsync(email, subject, body);
    }

    public Task SendPasswordResetCodeAsync(User user, string email, string resetCode)
    {
        var subject = "密码重置验证码";
        var body = $"您的密码重置验证码是：{resetCode}\n\n有效期 10 分钟。";
        return SendAsync(email, subject, body);
    }

    public Task SendPasswordResetLinkAsync(User user, string email, string resetLink)
    {
        var subject = "密码重置链接";
        var body = $"点击以下链接重置密码：{resetLink}\n\n有效期 10 分钟。";
        return SendAsync(email, subject, body);
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

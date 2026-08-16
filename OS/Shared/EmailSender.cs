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

        if (string.IsNullOrEmpty(_emailConfig.Smtp.Host) || string.IsNullOrEmpty(_emailConfig.FromAddress))
        {
            _logger.LogWarning("SMTP 未配置，邮件未发送 → {To} | 主题: {Subject}", to, subject);
            return;
        }

        try
        {
            var message = new MimeMessage();
            message.From.Add(new MailboxAddress(_emailConfig.FromName, _emailConfig.FromAddress));
            message.To.Add(MailboxAddress.Parse(to));
            message.Subject = subject;
            message.Body = new TextPart("plain") { Text = body };

            using var client = new SmtpClient();
            client.Timeout = 15000;
            var secureSocket = _emailConfig.Smtp.UseSsl ? SecureSocketOptions.StartTls : SecureSocketOptions.None;
            await client.ConnectAsync(_emailConfig.Smtp.Host, _emailConfig.Smtp.Port, secureSocket);

            if (!string.IsNullOrEmpty(_emailConfig.Smtp.Username))
            {
                await client.AuthenticateAsync(_emailConfig.Smtp.Username, _emailConfig.Smtp.Password);
            }

            await client.SendAsync(message);
            await client.DisconnectAsync(true);

            _logger.LogInformation("邮件已发送 → {To} | 主题: {Subject}", to, subject);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "邮件发送失败 → {To} | 主题: {Subject}", to, subject);
        }
    }
}

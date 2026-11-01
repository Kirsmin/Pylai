using System.Threading.Channels;

namespace Pylaios.Features.PasswordReset;

/// <summary>密码重置邮件任务（携带请求上下文，供后台派发后写审计）。</summary>
public record PasswordResetEmailJob(string Email, string Code, Guid Uid, string Ip, string Endpoint, string UserAgent);

/// <summary>
/// 密码重置邮件有界派发队列（§4.4 P2）：容量 100，TryWrite 在已满时立即失败（快速失败），
/// 不再用无界 Task.Run 堆积；派发成功/失败均写审计。
/// </summary>
public class PasswordResetEmailQueue : IHostedService
{
    public const int Capacity = 100;

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<PasswordResetEmailQueue> _logger;
    private readonly Channel<PasswordResetEmailJob> _channel = Channel.CreateBounded<PasswordResetEmailJob>(
        new BoundedChannelOptions(Capacity) { FullMode = BoundedChannelFullMode.Wait });
    private Task? _worker;

    public PasswordResetEmailQueue(IServiceScopeFactory scopeFactory, ILogger<PasswordResetEmailQueue> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    /// <summary>尝试入队；队列已满返回 false（调用方快速失败并审计）。</summary>
    public bool TryEnqueue(PasswordResetEmailJob job) => _channel.Writer.TryWrite(job);

    public Task StartAsync(CancellationToken cancellationToken)
    {
        _worker = Task.Run(() => ProcessAsync(cancellationToken), cancellationToken);
        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        _channel.Writer.TryComplete();
        if (_worker is not null)
            await _worker;
    }

    private async Task ProcessAsync(CancellationToken cancellationToken)
    {
        try
        {
            await foreach (var job in _channel.Reader.ReadAllAsync(cancellationToken))
            {
                try
                {
                    await SendAsync(job);
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    _logger.LogError(ex, "密码重置邮件派发异常 | uid:{Uid}", job.Uid);
                }
            }
        }
        catch (OperationCanceledException) { /* 停机取消 */ }
    }

    private async Task SendAsync(PasswordResetEmailJob job)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var emailSender = scope.ServiceProvider.GetRequiredService<EmailSender>();
        var auditService = scope.ServiceProvider.GetRequiredService<IAuditService>();
        try
        {
            await emailSender.SendPasswordResetCodeAsync(job.Email, job.Code);
            _logger.LogInformation("密码重置邮件已发送 | uid:{Uid}", job.Uid);
            await auditService.LogAsync(BuildAudit(job, AuthConstants.EventTypes.EmailVerificationSent, true, "password-reset"));
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "密码重置邮件发送失败 | uid:{Uid}", job.Uid);
            await auditService.LogAsync(BuildAudit(job, AuthConstants.EventTypes.EmailSendFailed, false, EmailSender.FailureDetails(ex)));
        }
    }

    private static AuditLog BuildAudit(PasswordResetEmailJob job, string eventType, bool success, string? details) => new()
    {
        EventType = eventType,
        UserId = job.Uid.ToString(),
        UserEmail = job.Email,
        IpAddress = job.Ip,
        Endpoint = job.Endpoint,
        Method = "POST",
        UserAgent = job.UserAgent,
        Success = success,
        Details = details
    };
}

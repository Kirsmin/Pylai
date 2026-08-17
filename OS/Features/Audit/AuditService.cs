using System.Text.Json;
using System.Threading.Channels;

namespace Pylaios.Features.Audit;

public interface IAuditService
{
    ValueTask LogAsync(AuditLog entry);
}

public class AuditService : IAuditService, IHostedService
{
    private static readonly TimeSpan[] RetryDelays = [TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(30)];
    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = false };

    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<AuditService> _logger;
    private readonly Channel<AuditLog>? _channel;
    private Task? _worker;

    public AuditService(IServiceScopeFactory scopeFactory, ILogger<AuditService> logger, bool background = true)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
        _channel = background
            ? Channel.CreateBounded<AuditLog>(new BoundedChannelOptions(10000)
            {
                FullMode = BoundedChannelFullMode.Wait
            })
            : null;
    }

    public ValueTask LogAsync(AuditLog entry)
    {
        if (_channel is not null)
            return _channel.Writer.WriteAsync(entry);

        return new ValueTask(WriteBatchWithRetryAsync([entry], CancellationToken.None));
    }

    public Task StartAsync(CancellationToken cancellationToken)
    {
        if (_channel is not null)
            _worker = Task.Run(() => ProcessAsync(cancellationToken), cancellationToken);
        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken cancellationToken)
    {
        if (_channel is null)
            return;
        _channel.Writer.TryComplete();
        if (_worker is not null)
            await _worker;
    }

    private async Task ProcessAsync(CancellationToken cancellationToken)
    {
        var batch = new List<AuditLog>(100);

        while (await _channel!.Reader.WaitToReadAsync(cancellationToken))
        {
            batch.Clear();

            while (batch.Count < 100 && _channel.Reader.TryRead(out var entry))
                batch.Add(entry);

            if (batch.Count == 0)
                continue;

            await WriteBatchWithRetryAsync(batch, cancellationToken);
        }
    }

    private async Task WriteBatchWithRetryAsync(List<AuditLog> batch, CancellationToken cancellationToken)
    {
        for (var attempt = 0; attempt <= RetryDelays.Length; attempt++)
        {
            try
            {
                await using var scope = _scopeFactory.CreateAsyncScope();
                var context = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
                foreach (var entry in batch)
                {
                    entry.Details = SensitiveDataRedactor.Redact(entry.Details);
                    if (entry.Details is { Length: > AuditLog.DetailsMaxLength })
                        entry.Details = entry.Details[..AuditLog.DetailsMaxLength];
                    if (entry.UserAgent is { Length: > AuditLog.UserAgentMaxLength })
                        entry.UserAgent = entry.UserAgent[..AuditLog.UserAgentMaxLength];
                }
                context.AuditLogs.AddRange(batch);
                await context.SaveChangesAsync(cancellationToken);
                return;
            }
            catch (Exception ex) when (ex is ObjectDisposedException)
            {
                _logger.LogWarning(ex, "服务容器已释放，审计日志直接写入文件 fallback（{Count} 条）", batch.Count);
                await WriteFallbackAsync(batch, CancellationToken.None);
                return;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                if (attempt < RetryDelays.Length)
                {
                    _logger.LogWarning(ex,
                        "批量写入审计日志失败（第 {Attempt} 次重试，共 {Count} 条）",
                        attempt + 1, batch.Count);
                    await Task.Delay(RetryDelays[attempt], cancellationToken);
                }
                else
                {

                    _logger.LogError(ex, "批量写入审计日志最终失败（{Count} 条），已写入文件 fallback", batch.Count);
                    await WriteFallbackAsync(batch, cancellationToken);
                }
            }
        }
    }

    private async Task WriteFallbackAsync(List<AuditLog> batch, CancellationToken cancellationToken)
    {
        try
        {
            var dir = Path.Combine(AppContext.BaseDirectory, "Logs");
            Directory.CreateDirectory(dir);
            var file = Path.Combine(dir, $"audit-failed-{DateTimeOffset.UtcNow:yyyyMMdd}.jsonl");

            await using var writer = new StreamWriter(file, append: true);
            foreach (var entry in batch)
            {
                entry.Details = SensitiveDataRedactor.Redact(entry.Details);
                await writer.WriteLineAsync(JsonSerializer.Serialize(entry, JsonOpts));
            }
            await writer.FlushAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "审计日志文件 fallback 写入失败（{Count} 条）", batch.Count);
        }
    }
}

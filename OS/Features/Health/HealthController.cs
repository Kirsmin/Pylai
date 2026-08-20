using MailKit.Net.Smtp;
using MailKit.Security;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using StackExchange.Redis;

namespace Pylaios.Features.Health;

[ApiController]
[Route("health")]
[AllowAnonymous]
public class HealthController : ControllerBase
{
    private readonly ApplicationDbContext _db;
    private readonly IConnectionMultiplexer _redis;
    private readonly MainConfig _config;
    private readonly ILogger<HealthController> _logger;

    public HealthController(
        ApplicationDbContext db,
        IConnectionMultiplexer redis,
        MainConfig config,
        ILogger<HealthController> logger)
    {
        _db = db;
        _redis = redis;
        _config = config;
        _logger = logger;
    }

    [HttpGet("live")]
    public IActionResult Live()
        => Ok(new { status = "alive", timestamp = DateTimeOffset.UtcNow });

    [HttpGet("ready")]
    [HttpGet("")]
    public async Task<IActionResult> Ready()
    {
        var checks = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        try
        {
            await _db.Database.ExecuteSqlRawAsync("SELECT 1");
            checks["database"] = "ok";
        }
        catch (Exception ex)
        {
            checks["database"] = "error";
            _logger.LogWarning(ex, "健康检查：PostgreSQL 不可用");
        }

        try
        {
            await _redis.GetDatabase().PingAsync();
            checks["redis"] = "ok";
        }
        catch (Exception ex)
        {
            checks["redis"] = "error";
            _logger.LogWarning(ex, "健康检查：Redis 不可用");
        }

        if (string.IsNullOrWhiteSpace(_config.Email.Smtp.Host))
        {
            checks["smtp"] = "disabled";
        }
        else
        {
            try
            {
                using var client = new SmtpClient { Timeout = 5000 };
                await client.ConnectAsync(
                    _config.Email.Smtp.Host,
                    _config.Email.Smtp.Port,
                    ResolveSecurity(_config.Email.Smtp.Security));

                if (!string.IsNullOrWhiteSpace(_config.Email.Smtp.Username))
                    await client.AuthenticateAsync(_config.Email.Smtp.Username, _config.Email.Smtp.Password);

                await client.DisconnectAsync(true);
                checks["smtp"] = "ok";
            }
            catch (Exception ex)
            {
                checks["smtp"] = "error";
                _logger.LogWarning(ex, "健康检查：SMTP 不可用");
            }
        }

        var hardHealthy = checks["database"] == "ok" && checks["redis"] == "ok";
        var smtpDegraded = checks["smtp"] == "error";
        var status = !hardHealthy ? "unhealthy" : smtpDegraded ? "degraded" : "healthy";
        var body = new { status, timestamp = DateTimeOffset.UtcNow, checks };

        return hardHealthy ? Ok(body) : StatusCode(StatusCodes.Status503ServiceUnavailable, body);
    }

    private static SecureSocketOptions ResolveSecurity(string? security)
        => security?.Trim().ToLowerInvariant() switch
        {
            "none" => SecureSocketOptions.None,
            "starttls" => SecureSocketOptions.StartTls,
            "sslonconnect" => SecureSocketOptions.SslOnConnect,
            _ => throw new InvalidOperationException(
                $"无效 SMTP 加密方式: {security}（可用: None / StartTls / SslOnConnect）")
        };
}

using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using StackExchange.Redis;

namespace Pylaios.Features.Health;


[ApiController]
public class HealthLiveController : ControllerBase
{
    [HttpGet("/health/live")]
    public IActionResult Live()
        => Ok(new { status = "alive", timestamp = DateTimeOffset.UtcNow });
}


[ApiController]
public class HealthController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<HealthController> _logger;

    public HealthController(ApplicationDbContext context, IConnectionMultiplexer redis, ILogger<HealthController> logger)
    {
        _context = context;
        _redis = redis;
        _logger = logger;
    }

    [HttpGet("/health")]
    [HttpGet("/health/ready")]
    public async Task<IActionResult> Ready()
    {
        var checks = new Dictionary<string, string>();

        try
        {
            await _context.Database.ExecuteSqlRawAsync("SELECT 1");
            checks["database"] = "ok";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "健康检查数据库失败");
            checks["database"] = "error";
        }

        try
        {
            await _redis.GetDatabase().PingAsync();
            checks["redis"] = "ok";
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "健康检查 Redis 失败");
            checks["redis"] = "error";
        }

        var healthy = checks.Values.All(v => v == "ok");
        var body = new
        {
            status = healthy ? "healthy" : "unhealthy",
            timestamp = DateTimeOffset.UtcNow,
            checks
        };
        return healthy ? Ok(body) : StatusCode(503, body);
    }
}

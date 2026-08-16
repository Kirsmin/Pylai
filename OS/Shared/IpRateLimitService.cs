using StackExchange.Redis;

namespace Pylaios.Shared;

public class IpRateLimitService
{
    private readonly IConnectionMultiplexer _redis;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<IpRateLimitService> _logger;

    public IpRateLimitService(IConnectionMultiplexer redis, IpResolutionService ipResolver, ILogger<IpRateLimitService> logger)
    {
        _redis = redis;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    private static RedisKey Key(string action, string ip) => new($"pylaios:rl:{action}:{ip}");

    private const string IncrWithExpireScript =
        "local c = redis.call('INCR', KEYS[1]) " +
        "if c == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end " +
        "return c";

    public async Task<bool> IsRateLimited(string ip, string action, int maxAttempts, TimeSpan window)
    {
        if (_ipResolver.IsWhitelisted(ip))
            return false;

        var db = _redis.GetDatabase();
        var val = await db.StringGetAsync(Key(action, ip));
        if (val.TryParse(out int count) && count >= maxAttempts)
        {
            _logger.LogWarning("IP限流触发 | {Action} | IP:{Ip} | 次数:{Count}/{Max}", action, ip, count, maxAttempts);
            return true;
        }
        return false;
    }

    public async Task RecordAttempt(string ip, string action, TimeSpan window)
    {
        var db = _redis.GetDatabase();
        var key = Key(action, ip);
        await db.ScriptEvaluateAsync(IncrWithExpireScript, [key], [(long)Math.Max(1, window.TotalSeconds)]);
    }
}

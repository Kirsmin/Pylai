using System.Text.Json;
using StackExchange.Redis;

namespace Pylaios.Features.Account;

public enum EmailCodeStatus { Ok, NotFound, Expired, MaxAttempts, WrongCode }

public class EmailCodeResult
{
    public EmailCodeStatus Status { get; init; }
    public int AttemptsRemaining { get; init; }
    public EmailVerificationEntry? Entry { get; init; }
}

public interface IEmailVerificationCodeService
{
    Task<string> CreateAsync(string key, string? email, Guid? userUid = null);
    Task<EmailCodeResult> VerifyAsync(string key, string code);
    Task<EmailVerificationEntry?> PeekAsync(string key);
    Task RemoveAsync(string key);
}

public class EmailVerificationCodeService : IEmailVerificationCodeService
{
    private const int MaxAttempts = 5;

    private static readonly string VerifyScript = """
        if redis.call('EXISTS', KEYS[1]) == 0 then
            return -1
        end
        local attempts = redis.call('INCR', KEYS[2])
        redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
        if attempts > tonumber(ARGV[1]) then
            redis.call('DEL', KEYS[1])
            redis.call('DEL', KEYS[2])
            redis.call('DEL', KEYS[3])
            return -2
        end
        if ARGV[3] == redis.call('GET', KEYS[1]) then
            redis.call('DEL', KEYS[1])
            redis.call('DEL', KEYS[2])
            redis.call('DEL', KEYS[3])
            return 1
        end
        return 0
        """;

    private readonly IRedisStateCache _cache;
    private readonly IDatabase _redis;
    private readonly TimeSpan _codeTtl;

    public EmailVerificationCodeService(IRedisStateCache cache, IConnectionMultiplexer redis, MainConfig config)
    {
        _cache = cache;
        _redis = redis.GetDatabase();
        _codeTtl = TimeSpan.FromMinutes(config.Identity.EmailCodeExpireMinutes);
    }

    public async Task<string> CreateAsync(string key, string? email, Guid? userUid = null)
    {
        var code = AuthHelper.GenerateCode();
        await _cache.SetAsync(key, new EmailVerificationEntry
        {
            Hash = AuthHelper.HashCode(code),
            Email = email,
            UserUid = userUid,
            Expires = DateTimeOffset.UtcNow + _codeTtl
        }, _codeTtl);
        await _redis.StringSetAsync(CodeHashKey(key), AuthHelper.HashCode(code), _codeTtl);
        await _redis.StringSetAsync(AttemptsKey(key), 0, _codeTtl);
        return code;
    }

    public async Task<EmailCodeResult> VerifyAsync(string key, string code)
    {
        var entry = await _cache.GetAsync<EmailVerificationEntry>(key);
        if (entry is null || entry.Expires < DateTimeOffset.UtcNow)
        {
            await RemoveAsync(key);
            return new EmailCodeResult { Status = EmailCodeStatus.NotFound };
        }

        var status = (long)await _redis.ScriptEvaluateAsync(VerifyScript, new RedisKey[]
        {
            CodeHashKey(key),
            AttemptsKey(key),
            _cache.CreateKey(key)
        }, new RedisValue[]
        {
            MaxAttempts,
            (long)_codeTtl.TotalSeconds,
            AuthHelper.HashCode(code)
        });

        return status switch
        {
            1 => new EmailCodeResult { Status = EmailCodeStatus.Ok, Entry = entry },
            -2 => new EmailCodeResult { Status = EmailCodeStatus.MaxAttempts },
            -1 => new EmailCodeResult { Status = EmailCodeStatus.NotFound },
            _ => new EmailCodeResult
            {
                Status = EmailCodeStatus.WrongCode,
                AttemptsRemaining = RemainingAttempts(await _redis.StringGetAsync(AttemptsKey(key)))
            }
        };
    }

    public async Task<EmailVerificationEntry?> PeekAsync(string key)
    {
        var entry = await _cache.GetAsync<EmailVerificationEntry>(key);
        if (entry is null || entry.Expires < DateTimeOffset.UtcNow)
        {
            await RemoveAsync(key);
            return null;
        }
        return entry;
    }

    public async Task RemoveAsync(string key)
    {
        await _cache.RemoveAsync(key);
        await _redis.KeyDeleteAsync(CodeHashKey(key));
        await _redis.KeyDeleteAsync(AttemptsKey(key));
    }

    private static int RemainingAttempts(RedisValue attempts)
        => attempts.TryParse(out long used) ? Math.Max(0, MaxAttempts - (int)used) : 0;

    private static RedisKey AttemptsKey(string key) => new($"pylaios:code-attempts:{key}");
    private static RedisKey CodeHashKey(string key) => new($"pylaios:code-hash:{key}");
}

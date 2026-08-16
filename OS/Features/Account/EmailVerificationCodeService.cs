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
    Task<string> CreateAsync(string key, string? email);
    Task<EmailCodeResult> VerifyAsync(string key, string code);
    Task RemoveAsync(string key);
}

public class EmailVerificationCodeService : IEmailVerificationCodeService
{
    private static readonly TimeSpan CodeTtl = TimeSpan.FromMinutes(10);
    private const int MaxAttempts = 5;

    private readonly IRedisStateCache _cache;
    private readonly IDatabase _redis;

    public EmailVerificationCodeService(IRedisStateCache cache, IConnectionMultiplexer redis)
    {
        _cache = cache;
        _redis = redis.GetDatabase();
    }

    public async Task<string> CreateAsync(string key, string? email)
    {
        var code = AuthHelper.GenerateCode();
        await _cache.SetAsync(key, new EmailVerificationEntry
        {
            Hash = AuthHelper.HashCode(code),
            Email = email,
            Expires = DateTimeOffset.UtcNow.AddMinutes(10)
        }, CodeTtl);
        await _redis.StringSetAsync(AttemptsKey(key), 0, CodeTtl);
        return code;
    }

    public async Task<EmailCodeResult> VerifyAsync(string key, string code)
    {
        var entry = await _cache.GetAsync<EmailVerificationEntry>(key);
        if (entry is null)
            return new EmailCodeResult { Status = EmailCodeStatus.NotFound };

        if (entry.Expires < DateTimeOffset.UtcNow)
        {
            await RemoveAsync(key);
            return new EmailCodeResult { Status = EmailCodeStatus.Expired };
        }

        var attempts = (int)await _redis.StringIncrementAsync(AttemptsKey(key));
        var remaining = Math.Max(0, MaxAttempts - attempts);
        if (attempts > MaxAttempts)
        {
            await RemoveAsync(key);
            return new EmailCodeResult { Status = EmailCodeStatus.MaxAttempts };
        }

        if (!AuthHelper.CodeEquals(entry.Hash, AuthHelper.HashCode(code)))
        {
            return new EmailCodeResult { Status = EmailCodeStatus.WrongCode, AttemptsRemaining = remaining };
        }

        return new EmailCodeResult { Status = EmailCodeStatus.Ok, Entry = entry };
    }

    public async Task RemoveAsync(string key)
    {
        await _cache.RemoveAsync(key);
        await _redis.KeyDeleteAsync(AttemptsKey(key));
    }

    private static RedisKey AttemptsKey(string key) => new($"pylaios:code-attempts:{key}");
}

using System.Text.Json;
using System.Text.Json.Serialization;
using StackExchange.Redis;

namespace Pylaios.Shared;

public interface IRateLimitCacheService
{
    ValueTask<bool> IsBannedAsync(string banType, string ip);
    ValueTask SetBanAsync(string banType, string ip, string banId, DateTimeOffset? banExpiresAt);
    ValueTask ClearBanAsync(string banType, string ip);

    ValueTask<int> IncrementFailureAsync(string failType, string ip);
    ValueTask SetFailureCountAsync(string failType, string ip, int count, DateTimeOffset lastFailureAt);
    ValueTask ClearFailureAsync(string failType, string ip);
}

public class RateLimitCacheService : IRateLimitCacheService
{
    private readonly IDatabase _db;
    private static readonly JsonSerializerOptions JsonOpts = new() { DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull };

    public RateLimitCacheService(IConnectionMultiplexer redis)
    {
        _db = redis.GetDatabase();
    }

    private static RedisKey BanKey(string type, string ip) => new($"pylaios:ban:{type}:{ip}");
    private static RedisKey FailKey(string type, string ip) => new($"pylaios:fail:{type}:{ip}");

    public async ValueTask<bool> IsBannedAsync(string banType, string ip)
    {
        var key = BanKey(banType, ip);
        var json = await _db.StringGetAsync(key);
        if (json.IsNullOrEmpty) return false;

        try
        {
            var entry = JsonSerializer.Deserialize<BanCacheEntry>(json.ToString());
            if (entry?.BanExpiresAt is null) return true;
            if (entry.BanExpiresAt.Value > DateTimeOffset.UtcNow) return true;
            await _db.KeyDeleteAsync(key);
            return false;
        }
        catch
        {
            return false;
        }
    }

    public async ValueTask SetBanAsync(string banType, string ip, string banId, DateTimeOffset? banExpiresAt)
    {
        var entry = new BanCacheEntry { BanId = banId, BanExpiresAt = banExpiresAt };
        var json = JsonSerializer.Serialize(entry, JsonOpts);
        var key = BanKey(banType, ip);

        if (banExpiresAt is not null)
        {
            var ttl = banExpiresAt.Value - DateTimeOffset.UtcNow;
            if (ttl > TimeSpan.Zero)
                await _db.StringSetAsync(key, json, ttl);
            else
                await _db.KeyDeleteAsync(key);
        }
        else
        {
            await _db.StringSetAsync(key, json);
        }
    }

    public async ValueTask ClearBanAsync(string banType, string ip)
    {
        await _db.KeyDeleteAsync(BanKey(banType, ip));
    }

    public async ValueTask<int> IncrementFailureAsync(string failType, string ip)
    {
        var key = FailKey(failType, ip);
        var json = await _db.StringGetAsync(key);

        var entry = json.IsNullOrEmpty ? new FailCacheEntry() :
            JsonSerializer.Deserialize<FailCacheEntry>(json.ToString()) ?? new FailCacheEntry();

        entry.Count++;
        entry.LastFailureAt = DateTimeOffset.UtcNow;

        await _db.StringSetAsync(key, JsonSerializer.Serialize(entry, JsonOpts));
        return entry.Count;
    }

    public async ValueTask SetFailureCountAsync(string failType, string ip, int count, DateTimeOffset lastFailureAt)
    {
        var entry = new FailCacheEntry { Count = count, LastFailureAt = lastFailureAt };
        await _db.StringSetAsync(FailKey(failType, ip), JsonSerializer.Serialize(entry, JsonOpts));
    }

    public async ValueTask ClearFailureAsync(string failType, string ip)
    {
        await _db.KeyDeleteAsync(FailKey(failType, ip));
    }

    private class BanCacheEntry
    {
        [JsonPropertyName("banId")]
        public string? BanId { get; set; }

        [JsonPropertyName("banExpiresAt")]
        public DateTimeOffset? BanExpiresAt { get; set; }
    }

    private class FailCacheEntry
    {
        [JsonPropertyName("count")]
        public int Count { get; set; }

        [JsonPropertyName("lastFailureAt")]
        public DateTimeOffset? LastFailureAt { get; set; }
    }
}

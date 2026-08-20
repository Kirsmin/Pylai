using System.Text.Json;
using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace Pylaios.Shared;

public interface IRedisStateCache
{
    ValueTask<T?> GetAsync<T>(string key);
    ValueTask<T?> TakeAsync<T>(string key);
    ValueTask SetAsync<T>(string key, T value, TimeSpan ttl);
    ValueTask RemoveAsync(string key);
    RedisKey CreateKey(string key);
}

public sealed class RedisStateCache : IRedisStateCache
{
    private readonly IDatabase _db;
    private readonly ILogger<RedisStateCache> _logger;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
    };

    public RedisStateCache(IConnectionMultiplexer redis, ILogger<RedisStateCache> logger)
    {
        _db = redis.GetDatabase();
        _logger = logger;
    }

    private static RedisKey StateKey(string key) => new($"pylaios:state:{key}");
    public RedisKey CreateKey(string key) => StateKey(key);

    public async ValueTask<T?> GetAsync<T>(string key)
    {
        var json = await _db.StringGetAsync(StateKey(key));
        return Deserialize<T>(key, json);
    }

    public async ValueTask<T?> TakeAsync<T>(string key)
    {
        // GETDEL makes one-time state consumption atomic, preventing callback replay races.
        var json = await _db.StringGetDeleteAsync(StateKey(key));
        return Deserialize<T>(key, json);
    }

    private T? Deserialize<T>(string key, RedisValue json)
    {
        if (json.IsNullOrEmpty)
            return default;

        try
        {
            return JsonSerializer.Deserialize<T>(json.ToString(), JsonOpts);
        }
        catch (JsonException ex)
        {
            _logger.LogWarning(ex, "Redis 状态反序列化失败 | Key:{Key}", key);
            return default;
        }
    }

    public async ValueTask SetAsync<T>(string key, T value, TimeSpan ttl)
    {
        var json = JsonSerializer.Serialize(value, JsonOpts);
        await _db.StringSetAsync(StateKey(key), json, ttl);
    }

    public async ValueTask RemoveAsync(string key)
    {
        await _db.KeyDeleteAsync(StateKey(key));
    }
}

using System.Text.Json;
using StackExchange.Redis;

namespace Pylaios.Shared;





public interface IRedisStateCache
{
    ValueTask<T?> GetAsync<T>(string key);
    ValueTask SetAsync<T>(string key, T value, TimeSpan ttl);
    ValueTask RemoveAsync(string key);
}

public class RedisStateCache : IRedisStateCache
{
    private readonly IDatabase _db;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
    };

    public RedisStateCache(IConnectionMultiplexer redis)
    {
        _db = redis.GetDatabase();
    }

    private static RedisKey StateKey(string key) => new($"pylaios:state:{key}");

    public async ValueTask<T?> GetAsync<T>(string key)
    {
        var json = await _db.StringGetAsync(StateKey(key));
        if (json.IsNullOrEmpty)
            return default;

        try
        {
            return JsonSerializer.Deserialize<T>(json.ToString(), JsonOpts);
        }
        catch
        {
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

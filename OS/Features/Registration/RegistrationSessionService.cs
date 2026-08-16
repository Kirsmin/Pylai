
namespace Pylaios.Features.Registration;

public class RegistrationSessionService
{
    private readonly IRedisStateCache _cache;
    private static readonly TimeSpan SessionTimeout = TimeSpan.FromMinutes(30);

    public RegistrationSessionService(IRedisStateCache cache)
    {
        _cache = cache;
    }

    private static string SessionKey(string token) => $"reg:{token}";

    public async Task<string> CreateSessionAsync()
    {
        var token = "Session" + Guid.NewGuid().ToString("N");
        var session = new RegistrationSession();
        await _cache.SetAsync(SessionKey(token), session, SessionTimeout);
        return token;
    }

    public async Task<RegistrationSession?> GetSessionAsync(string? token)
    {
        if (string.IsNullOrEmpty(token))
            return null;
        return await _cache.GetAsync<RegistrationSession>(SessionKey(token));
    }

    public async Task UpdateSessionAsync(string? token, RegistrationSession session)
    {
        if (string.IsNullOrEmpty(token))
            return;
        await _cache.SetAsync(SessionKey(token), session, SessionTimeout);
    }

    public async Task RemoveSessionAsync(string? token)
    {
        if (string.IsNullOrEmpty(token))
            return;
        await _cache.RemoveAsync(SessionKey(token));
    }
}

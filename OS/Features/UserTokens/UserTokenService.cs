using System.Security.Cryptography;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.UserTokens;

public interface IUserTokenService
{
    Task<(UserToken Token, string PlainToken, bool Refreshed)> CreateOrRefreshAsync(User user, int? lifetimeDays);
    Task<UserToken?> GetActiveAsync(Guid userUid);
    Task<List<UserTokenStatusRow>> ListActiveAsync();
    Task<UserTokenStatusRow?> GetStatusAsync(Guid userUid);
    Task<bool> RevokeAsync(Guid userUid);
    Task<UserTokenValidationResult> ValidateAsync(string token, string? ipAddress, string? userAgent = null, string method = "POST", string endpoint = "/");
    Task<(List<UserTokenUsage> Items, int Total)> GetUsageAsync(long tokenId, int skip, int take);
}

public class UserTokenStatusRow
{
    public long Id { get; set; }
    public Guid UserUid { get; set; }
    public string? UserName { get; set; }
    public string? UserDisplayName { get; set; }
    public string TokenPrefix { get; set; } = string.Empty;
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset? RefreshedAt { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
    public DateTimeOffset? LastUsedAt { get; set; }
    public string? LastIpAddress { get; set; }
}

public class UserTokenValidationResult
{
    public bool Valid { get; set; }
    public UserToken? Token { get; set; }
    public User? User { get; set; }
}

public class UserTokenService : IUserTokenService
{
    private const string Prefix = "UserToken";
    private const int KeyLength = 128;

    private readonly ApplicationDbContext _context;
    private readonly MainConfig _config;
    private readonly ILogger<UserTokenService> _logger;

    public UserTokenService(ApplicationDbContext context, MainConfig config, ILogger<UserTokenService> logger)
    {
        _context = context;
        _config = config;
        _logger = logger;
    }

    public async Task<(UserToken Token, string PlainToken, bool Refreshed)> CreateOrRefreshAsync(User user, int? lifetimeDays)
    {
        if (lifetimeDays < 0)
            throw new ArgumentOutOfRangeException(nameof(lifetimeDays), "LifetimeDays 不能为负数。");

        var now = DateTimeOffset.UtcNow;
        var existing = await _context.UserTokens.FirstOrDefaultAsync(t => t.UserUid == user.Uid && t.RevokedAt == null);
        if (existing is not null)
        {
            existing.RevokedAt = now;
        }

        var bytes = RandomNumberGenerator.GetBytes(64);
        var hex = Convert.ToHexStringLower(bytes);
        var plainToken = $"{Prefix}{hex}";

        var expiresAt = ResolveExpiry(lifetimeDays);
        var token = new UserToken
        {
            UserUid = user.Uid,
            TokenHash = AuthHelper.HashCode(plainToken),
            TokenPrefix = hex[..5],
            CreatedAt = now,
            ExpiresAt = expiresAt
        };

        _context.UserTokens.Add(token);
        try
        {
            await _context.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            _context.Entry(token).State = EntityState.Detached;
            var conflict = await _context.UserTokens.FirstOrDefaultAsync(t => t.UserUid == user.Uid && t.RevokedAt == null);
            if (conflict is not null)
                conflict.RevokedAt = now;
            _context.UserTokens.Add(token);
            await _context.SaveChangesAsync();
        }

        _logger.LogInformation("UserToken创建/刷新 | uid:{Uid} | 用户:{Name} | TokenId:{Id} | 过期:{ExpiresAt}",
            user.Uid, user.Name, token.Id, token.ExpiresAt);

        return (token, plainToken, existing is not null);
    }

    public async Task<UserToken?> GetActiveAsync(Guid userUid)
    {
        var now = DateTimeOffset.UtcNow;
        return await _context.UserTokens
            .FirstOrDefaultAsync(t => t.UserUid == userUid && t.RevokedAt == null && (t.ExpiresAt == null || t.ExpiresAt > now));
    }

    public async Task<List<UserTokenStatusRow>> ListActiveAsync()
    {
        var now = DateTimeOffset.UtcNow;
        return await _context.UserTokens
            .Where(t => t.RevokedAt == null && (t.ExpiresAt == null || t.ExpiresAt > now))
            .Join(_context.Users, t => t.UserUid, u => u.Uid, (t, u) => new UserTokenStatusRow
            {
                Id = t.Id,
                UserUid = u.Uid,
                UserName = u.Name,
                UserDisplayName = u.DisplayName,
                TokenPrefix = t.TokenPrefix,
                CreatedAt = t.CreatedAt,
                RefreshedAt = t.RefreshedAt,
                ExpiresAt = t.ExpiresAt,
                LastUsedAt = t.LastUsedAt,
                LastIpAddress = t.LastIpAddress
            })
            .OrderByDescending(t => t.CreatedAt)
            .ToListAsync();
    }

    public async Task<UserTokenStatusRow?> GetStatusAsync(Guid userUid)
    {
        var now = DateTimeOffset.UtcNow;
        var token = await _context.UserTokens
            .FirstOrDefaultAsync(t => t.UserUid == userUid && t.RevokedAt == null && (t.ExpiresAt == null || t.ExpiresAt > now));
        if (token is null)
            return null;

        var user = await _context.Users.FindAsync(userUid);
        return new UserTokenStatusRow
        {
            Id = token.Id,
            UserUid = userUid,
            UserName = user?.Name,
            UserDisplayName = user?.DisplayName,
            TokenPrefix = token.TokenPrefix,
            CreatedAt = token.CreatedAt,
            RefreshedAt = token.RefreshedAt,
            ExpiresAt = token.ExpiresAt,
            LastUsedAt = token.LastUsedAt,
            LastIpAddress = token.LastIpAddress
        };
    }

    public async Task<bool> RevokeAsync(Guid userUid)
    {
        var token = await _context.UserTokens
            .FirstOrDefaultAsync(t => t.UserUid == userUid && t.RevokedAt == null);
        if (token is null)
            return false;

        token.RevokedAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();

        _logger.LogInformation("UserToken吊销 | uid:{Uid} | TokenId:{Id}", userUid, token.Id);
        return true;
    }

    public async Task<UserTokenValidationResult> ValidateAsync(string token, string? ipAddress, string? userAgent = null, string method = "POST", string endpoint = "/")
    {
        var hash = AuthHelper.HashCode(token);
        var entry = await _context.UserTokens
            .FirstOrDefaultAsync(t => t.TokenHash == hash && t.RevokedAt == null);

        if (entry is null)
            return new UserTokenValidationResult { Valid = false };

        if (entry.ExpiresAt is not null && entry.ExpiresAt <= DateTimeOffset.UtcNow)
            return new UserTokenValidationResult { Valid = false };

        var user = await _context.Users.FindAsync(entry.UserUid);
        if (user is null || user.Status != UserStatus.Active)
            return new UserTokenValidationResult { Valid = false };

        var now = DateTimeOffset.UtcNow;
        entry.LastUsedAt = now;
        entry.LastIpAddress = ipAddress;
        _context.UserTokenUsages.Add(new UserTokenUsage
        {
            UserTokenId = entry.Id,
            TokenPrefix = entry.TokenPrefix,
            OccurredAt = now,
            Method = method,
            Endpoint = endpoint,
            IpAddress = ipAddress,
            UserAgent = userAgent is { Length: > 512 } ? userAgent[..512] : userAgent
        });

        try
        {
            await _context.SaveChangesAsync();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "UserToken 使用记录写入失败 | TokenId:{Id}", entry.Id);
        }

        return new UserTokenValidationResult { Valid = true, Token = entry, User = user };
    }

    public async Task<(List<UserTokenUsage> Items, int Total)> GetUsageAsync(long tokenId, int skip, int take)
    {
        var total = await _context.UserTokenUsages.CountAsync(u => u.UserTokenId == tokenId);
        var items = await _context.UserTokenUsages
            .Where(u => u.UserTokenId == tokenId)
            .OrderByDescending(u => u.OccurredAt)
            .Skip(skip).Take(take)
            .ToListAsync();
        return (items, total);
    }

    private DateTimeOffset? ResolveExpiry(int? lifetimeDays)
    {
        if (lifetimeDays is 0)
            return null;

        var days = lifetimeDays ?? _config.UserToken.DefaultLifetimeDays;
        if (days <= 0)
            return null;

        return DateTimeOffset.UtcNow.AddDays(days);
    }
}

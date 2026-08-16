using Cocona;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.UserTokens;

public sealed class UserTokenCommands
{
    private readonly CliCommandContext _ctx;

    public UserTokenCommands(CliCommandContext ctx)
    {
        _ctx = ctx;
    }

    [Command("create", Description = "为指定用户强制生成/刷新 UserToken（旧 Token 立即失效，完整 token 仅打印一次）")]
    public async Task<int> CreateAsync(
        [Argument("uid|name|email")] string target,
        [Option("lifetime-days")] int? lifetimeDays = null,
        [Option("never")] bool never = false)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var days = never ? 0 : lifetimeDays;
        if (days < 0)
            return await CliHelpers.ErrorAsync("--lifetime-days 不能为负数。");
        var (_, plainToken, refreshed) = await _ctx.UserTokens.CreateOrRefreshAsync(user, days);

        await CliHelpers.LogAsync(_ctx, refreshed ? "cli:user-token refresh" : "cli:user-token create", true,
            $"CLI {(refreshed ? "refreshed" : "created")} UserToken for {user.Name} (uid:{user.Uid})",
            userId: user.Uid.ToString(), userEmail: user.Email,
            eventType: refreshed ? AuthConstants.EventTypes.UserTokenRefreshed : AuthConstants.EventTypes.UserTokenCreated);

        return await CliHelpers.OkAsync(new { success = true, uid = user.Uid, refreshed, token = plainToken });
    }

    [Command("show", Description = "查看指定用户的 UserToken 状态")]
    public async Task<int> ShowAsync([Argument("uid|name|email")] string target)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var status = await _ctx.UserTokens.GetStatusAsync(user.Uid);
        if (status is null)
            return await CliHelpers.OkAsync(new { success = true, uid = user.Uid, exists = false });

        return await CliHelpers.OkAsync(new
        {
            success = true,
            uid = user.Uid,
            exists = true,
            tokenPrefix = $"UserToken {status.TokenPrefix}…",
            createdAt = CliHelpers.FormatUtc(status.CreatedAt),
            refreshedAt = status.RefreshedAt.HasValue ? CliHelpers.FormatUtc(status.RefreshedAt.Value) : null,
            expiresAt = status.ExpiresAt.HasValue ? CliHelpers.FormatUtc(status.ExpiresAt.Value) : null,
            lastUsedAt = status.LastUsedAt.HasValue ? CliHelpers.FormatUtc(status.LastUsedAt.Value) : null,
            lastIpAddress = status.LastIpAddress
        });
    }

    [Command("list", Description = "列出所有有效 UserToken")]
    public async Task<int> ListAsync()
    {
        var tokens = await _ctx.UserTokens.ListActiveAsync();
        var list = tokens.Select(t => new
        {
            uid = t.UserUid,
            userName = t.UserName,
            displayName = t.UserDisplayName,
            tokenPrefix = $"UserToken {t.TokenPrefix}…",
            createdAt = CliHelpers.FormatUtc(t.CreatedAt),
            refreshedAt = t.RefreshedAt.HasValue ? CliHelpers.FormatUtc(t.RefreshedAt.Value) : null,
            expiresAt = t.ExpiresAt.HasValue ? CliHelpers.FormatUtc(t.ExpiresAt.Value) : null,
            lastUsedAt = t.LastUsedAt.HasValue ? CliHelpers.FormatUtc(t.LastUsedAt.Value) : null
        });

        return await CliHelpers.OkAsync(new { success = true, tokens = list });
    }

    [Command("usage", Description = "查看指定用户的 UserToken 使用记录")]
    public async Task<int> UsageAsync(
        [Argument("uid|name|email")] string target,
        [Option("skip")] int? skip = null,
        [Option("take")] int? take = null)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var token = await _ctx.UserTokens.GetActiveAsync(user.Uid);
        if (token is null)
            return await CliHelpers.OkAsync(new { success = true, uid = user.Uid, exists = false, usage = Array.Empty<object>(), total = 0 });

        var (items, total) = await _ctx.UserTokens.GetUsageAsync(token.Id, skip ?? 0, take ?? 20);
        var list = items.Select(u => new
        {
            id = u.Id,
            tokenPrefix = $"UserToken {u.TokenPrefix}…",
            occurredAt = CliHelpers.FormatUtc(u.OccurredAt),
            method = u.Method,
            endpoint = u.Endpoint,
            ipAddress = u.IpAddress,
            userAgent = u.UserAgent
        });

        return await CliHelpers.OkAsync(new { success = true, uid = user.Uid, exists = true, usage = list, total });
    }

    [Command("revoke", Description = "吊销指定用户的 UserToken")]
    public async Task<int> RevokeAsync([Argument("uid|name|email")] string target)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var revoked = await _ctx.UserTokens.RevokeAsync(user.Uid);
        if (!revoked)
            return await CliHelpers.ErrorAsync($"用户 {user.Name} 没有有效 UserToken。");

        await CliHelpers.LogAsync(_ctx, "cli:user-token revoke", true,
            $"CLI revoked UserToken for {user.Name} (uid:{user.Uid})",
            userId: user.Uid.ToString(), userEmail: user.Email,
            eventType: AuthConstants.EventTypes.UserTokenRevoked);

        return await CliHelpers.OkAsync(new { success = true, message = $"用户 {user.Name} 的 UserToken 已吊销。" });
    }
}

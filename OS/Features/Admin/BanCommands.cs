using Cocona;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Admin;

public sealed class BanCommands
{
    private readonly CliCommandContext _ctx;
    private readonly ILoginRateLimitService _login;
    private readonly IAdminRateLimitService _admin;
    private readonly IInviteCodeService _invite;
    private readonly IEmailVerificationBlockService _email;
    private readonly IConfirmationRateLimitService _confirm;

    public BanCommands(
        CliCommandContext ctx,
        ILoginRateLimitService login,
        IAdminRateLimitService admin,
        IInviteCodeService invite,
        IEmailVerificationBlockService email,
        IConfirmationRateLimitService confirm)
    {
        _ctx = ctx;
        _login = login;
        _admin = admin;
        _invite = invite;
        _email = email;
        _confirm = confirm;
    }

    [Command("list", Description = "当前活跃封禁（--history 查审计含已解封）")]
    public async Task<int> ListAsync(
        [Option("type")] string? type = null,
        [Option("history")] bool history = false,
        [Option("skip")] int? skip = null,
        [Option("take")] int? take = null)
    {
        if (history)
        {
            var query = _ctx.Db.IpBanAudits.AsNoTracking();
            if (type is not null)
            {
                var historyType = ResolveHistoryType(type);
                if (historyType is null)
                    return await CliHelpers.ErrorAsync($"无效封禁类型: {type}");
                query = query.Where(a => a.BanType == historyType);
            }

            var total = await query.CountAsync();
            var items = await query.OrderByDescending(a => a.BannedAt).Skip(skip ?? 0).Take(take ?? 20)
                .Select(a => new
                {
                    banId = a.BanId,
                    type = a.BanType,
                    ip = a.IpAddress,
                    bannedAt = CliHelpers.FormatUtc(a.BannedAt),
                    banExpiresAt = CliHelpers.FormatUtc(a.BanExpiresAt),
                    unbannedAt = a.UnbannedAt.HasValue ? CliHelpers.FormatUtc(a.UnbannedAt.Value) : (string?)null
                })
                .ToListAsync();

            return await CliHelpers.OkAsync(new { success = true, total, bans = items });
        }

        var list = new List<object>();
        if (type is null or "login") await AddBansAsync<LoginFailure>(list, "login", f => f.BanLevel);
        if (type is null or "invite") await AddBansAsync<InviteCodeFailure>(list, "invite", _ => null);
        if (type is null or "email") await AddBansAsync<EmailVerificationBlock>(list, "email", _ => null);
        if (type is null or "admin") await AddBansAsync<AdminAuthFailure>(list, "admin", _ => null);
        if (type is null or "confirm")
        {
            var confirmBans = await _confirm.GetActiveBansAsync();
            list.AddRange(confirmBans.Select(b => (object)new
            {
                banId = b.BanId,
                type = "confirm",
                userUid = b.UserUid,
                userName = b.UserName,
                displayName = b.DisplayName,
                failureCount = b.FailureCount,
                banLevel = (int?)null,
                expiresAt = b.BanExpiresAt.HasValue ? CliHelpers.FormatUtc(b.BanExpiresAt.Value) : (string?)null
            }));
        }

        var totalCount = list.Count;
        return await CliHelpers.OkAsync(new { success = true, total = totalCount, bans = list.Skip(skip ?? 0).Take(take ?? 20).ToList() });
    }

    private async Task AddBansAsync<T>(List<object> list, string type, Func<T, int?> banLevel)
        where T : class, IIpBanEntry
    {
        var rows = await _ctx.Db.Set<T>().AsNoTracking()
            .Where(f => f.BanId != null && (f.BanExpiresAt == null || f.BanExpiresAt > DateTimeOffset.UtcNow))
            .ToListAsync();
        list.AddRange(rows.Select(f => (object)new
        {
            banId = f.BanId,
            type,
            ip = f.IpAddress,
            failureCount = f.FailureCount,
            banLevel = banLevel(f),
            expiresAt = f.BanExpiresAt.HasValue ? CliHelpers.FormatUtc(f.BanExpiresAt.Value) : (string?)null
        }));
    }

    [Command("show", Description = "按 BanId 查询（含审计记录与当前状态）")]
    public async Task<int> ShowAsync([Argument("banId")] string banId)
    {
        var audit = await _ctx.Db.IpBanAudits.AsNoTracking()
            .Where(a => a.BanId == banId).OrderByDescending(a => a.BannedAt)
            .Select(a => new
            {
                type = a.BanType,
                ip = a.IpAddress,
                bannedAt = CliHelpers.FormatUtc(a.BannedAt),
                banExpiresAt = CliHelpers.FormatUtc(a.BanExpiresAt),
                unbannedAt = a.UnbannedAt.HasValue ? CliHelpers.FormatUtc(a.UnbannedAt.Value) : (string?)null
            })
            .FirstOrDefaultAsync();

        object? current = await FindCurrentAsync<LoginFailure>(banId, "login", f => f.BanLevel)
            ?? await FindCurrentAsync<InviteCodeFailure>(banId, "invite", _ => null)
            ?? await FindCurrentAsync<EmailVerificationBlock>(banId, "email", _ => null)
            ?? await FindCurrentAsync<AdminAuthFailure>(banId, "admin", _ => null);

        if (current is null)
        {
            var confirm = await _confirm.GetActiveBansAsync();
            var c = confirm.FirstOrDefault(b => b.BanId == banId);
            if (c is not null)
            {
                current = new
                {
                    type = "confirm",
                    userUid = c.UserUid,
                    userName = c.UserName,
                    displayName = c.DisplayName,
                    failureCount = c.FailureCount,
                    banLevel = (int?)null,
                    expiresAt = c.BanExpiresAt.HasValue ? CliHelpers.FormatUtc(c.BanExpiresAt.Value) : (string?)null
                };
            }
        }

        if (current is null && audit is null)
            return await CliHelpers.ErrorAsync($"BanId 不存在: {banId}");

        return await CliHelpers.OkAsync(new { success = true, banId, audit, current });
    }

    private static string? ResolveHistoryType(string type) => type switch
    {
        "login" => "Login",
        "invite" => "InviteCode",
        "email" => "EmailVerify",
        "admin" => "AdminAuth",
        _ => null
    };

    private async Task<object?> FindCurrentAsync<T>(string banId, string type, Func<T, int?> banLevel)
        where T : class, IIpBanEntry
    {
        var f = await _ctx.Db.Set<T>().AsNoTracking().FirstOrDefaultAsync(x => x.BanId == banId);
        if (f is null) return null;
        return new
        {
            type,
            ip = f.IpAddress,
            failureCount = f.FailureCount,
            banLevel = banLevel(f),
            expiresAt = f.BanExpiresAt.HasValue ? CliHelpers.FormatUtc(f.BanExpiresAt.Value) : (string?)null
        };
    }

    [Command("revoke", Description = "按 BanId 精准解封（自动识别类型）")]
    public async Task<int> RevokeAsync([Argument("banId")] string banId)
    {
        if (await _login.RevokeByBanIdAsync(banId)
            || await _invite.RevokeByBanIdAsync(banId)
            || await _email.RevokeByBanIdAsync(banId)
            || await _admin.RevokeByBanIdAsync(banId)
            || await _confirm.RevokeByBanIdAsync(banId))
        {
            await CliHelpers.LogAsync(_ctx, "cli:ban revoke", true, $"CLI revoked ban {banId}");
            return await CliHelpers.OkAsync(new { success = true, message = $"已解封 BanId {banId}。" });
        }

        return await CliHelpers.ErrorAsync($"BanId 不存在: {banId}");
    }

    [Command("unban", Description = "按 IP 解封（--type 指定类型，不指定时尝试 login/invite/admin；confirm 为账号级，请用 revoke）")]
    public async Task<int> UnbanAsync(
        [Argument("ip")] string ip,
        [Option("type")] string? type = null)
    {
        if (type is "confirm")
            return await CliHelpers.ErrorAsync("confirm 为账号级封禁，请使用 ban revoke <banId> 解封。");
        if (type is not null && type is not ("login" or "invite" or "email" or "admin"))
            return await CliHelpers.ErrorAsync($"无效封禁类型: {type}");

        var results = new List<object>();

        if (type is null or "login")
            results.Add(new { type = "login", status = await _login.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "invite")
            results.Add(new { type = "invite", status = await _invite.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "email")
            results.Add(new { type = "email", status = await _email.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "admin")
            results.Add(new { type = "admin", status = await _admin.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });

        await CliHelpers.LogAsync(_ctx, "cli:ban unban", true, $"CLI unbanned IP {ip}");
        return await CliHelpers.OkAsync(new { success = true, ip, results });
    }
}

using Cocona;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Users;


public sealed class UserCommands
{
    private readonly CliCommandContext _ctx;
    private readonly IUserAccessRevoker _userAccessRevoker;

    public UserCommands(CliCommandContext ctx, IUserAccessRevoker userAccessRevoker)
    {
        _ctx = ctx;
        _userAccessRevoker = userAccessRevoker;
    }

    [Command("list", Description = "用户列表（可按组/状态过滤、分页）")]
    public async Task<int> ListAsync(
        [Option("group")] string? group = null,
        [Option("status")] string? status = null,
        [Option("skip")] int? skip = null,
        [Option("take")] int? take = null)
    {
        var query = _ctx.Db.Users.AsNoTracking();
        if (!string.IsNullOrEmpty(group)) query = query.Where(u => u.Group == group);
        if (!string.IsNullOrEmpty(status))
        {
            if (!Enum.TryParse<UserStatus>(status, true, out var parsed))
                return await CliHelpers.ErrorAsync($"无效状态: {status}（可用: active/banned/locked/deleted）");
            query = query.Where(u => u.Status == parsed);
        }

        var total = await query.CountAsync();
        var users = await query.OrderByDescending(u => u.RegisterTime)
            .Skip(skip ?? 0).Take(take ?? 20)
            .Select(u => new
            {
                uid = u.Uid,
                name = u.Name,
                displayName = u.DisplayName,
                email = u.Email,
                group = u.Group,
                status = u.Status.ToString(),
                registerTime = CliHelpers.FormatUtc(u.RegisterTime),
                lastLoginAt = u.LastLoginAt.HasValue ? CliHelpers.FormatUtc(u.LastLoginAt.Value) : null
            })
            .ToListAsync();

        return await CliHelpers.OkAsync(new { success = true, total, users });
    }

    [Command("show", Description = "用户详情（含外部登录绑定、活跃会话数）")]
    public async Task<int> ShowAsync([Argument("uid|name|email")] string target)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var logins = await _ctx.Db.UserLogins
            .Where(l => l.UserUid == user.Uid)
            .Select(l => new { provider = l.LoginProvider, boundAt = CliHelpers.FormatUtc(l.CreatedAt) })
            .ToListAsync();
        var activeSessions = await _ctx.Db.UserSessions
            .CountAsync(s => s.UserUid == user.Uid && s.RevokedAt == null && s.ExpiresAt > DateTimeOffset.UtcNow);

        return await CliHelpers.OkAsync(new
        {
            success = true,
            user = new
            {
                uid = user.Uid,
                name = user.Name,
                displayName = user.DisplayName,
                email = user.Email,
                group = user.Group,
                status = user.Status.ToString(),
                registerTime = user.RegisterTime.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                lastLoginAt = user.LastLoginAt.HasValue ? user.LastLoginAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null,
                lockoutEnd = user.LockoutEnd,
                activeSessions,
                externalLogins = logins
            }
        });
    }

    [Command("set-group", Description = "设置用户组（normal/admin/max，变更后吊销全部会话）")]
    public async Task<int> SetGroupAsync(
        [Argument("uid|name")] string target,
        [Argument("group")] string group)
    {
        var targetGroup = group.ToLowerInvariant();
        if (!AuthConstants.Groups.IsValid(targetGroup))
            return await CliHelpers.ErrorAsync($"无效的用户组: {group}（可用: {string.Join("/", AuthConstants.Groups.All)}）");

        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var oldGroup = user.Group;
        if (oldGroup == targetGroup)
            return await CliHelpers.ErrorAsync($"用户 {user.Name} 已在 {targetGroup} 组。");

        user.Group = targetGroup;
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        await CliHelpers.LogAsync(_ctx, "cli:user set-group", true,
            $"CLI set-group {user.Name} (uid:{user.Uid}) {oldGroup} -> {targetGroup}",
            userId: user.Uid.ToString(), userEmail: user.Email);

        return await CliHelpers.OkAsync(new { success = true, message = $"用户 {user.Name} 已从 {oldGroup} 变更到 {targetGroup} 组，其会话已全部吊销。" });
    }

    [Command("set-status", Description = "封禁/解封用户（解封清除锁定，封禁吊销会话）")]
    public async Task<int> SetStatusAsync(
        [Argument("uid|name")] string target,
        [Argument("status")] string status)
    {
        var targetStatus = status.ToLowerInvariant();
        if (targetStatus is not ("active" or "banned"))
            return await CliHelpers.ErrorAsync($"无效状态: {status}（可用: active / banned）");

        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var newStatus = targetStatus == "banned" ? UserStatus.Banned : UserStatus.Active;
        if (user.Status == newStatus)
            return await CliHelpers.ErrorAsync($"用户 {user.Name} 当前状态已是 {targetStatus}。");

        user.Status = newStatus;
        if (newStatus == UserStatus.Active)
        {
            user.LockoutEnd = null;
            user.AccessFailedCount = 0;
            await _ctx.Db.SaveChangesAsync();
        }
        else
        {
            await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);
        }

        await CliHelpers.LogAsync(_ctx, "cli:user set-status", true,
            $"CLI set-status {user.Name} (uid:{user.Uid}) {user.Status} -> {newStatus}",
            userId: user.Uid.ToString(), userEmail: user.Email);

        return await CliHelpers.OkAsync(new { success = true, message = $"用户 {user.Name} 状态已变更为 {targetStatus}。" });
    }

    [Command("reset-password", Description = "重置密码 + 吊销全部会话（密码仅从 stdin 读取）")]
    public async Task<int> ResetPasswordAsync(
        [Argument("uid|name")] string target,
        [Option("password-stdin", Description = "从 stdin 读取新密码（禁止 argv 传参）")] bool passwordStdin)
    {
        if (!passwordStdin)
            return await CliHelpers.ErrorAsync("新密码必须通过 --password-stdin 从 stdin 读取（禁止 argv 传参）");

        var password = CliHelpers.ReadSecretFromStdin();
        if (string.IsNullOrEmpty(password))
            return await CliHelpers.ErrorAsync("新密码不能为空（从 stdin 读取）");

        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        var userManager = _ctx.Services.GetRequiredService<Microsoft.AspNetCore.Identity.UserManager<User>>();
        var passwordErrors = await AuthHelper.ValidatePasswordAsync(userManager, user, password);
        if (passwordErrors.Count > 0)
            return await CliHelpers.ErrorAsync(passwordErrors[0].Description);

        user.PasswordHash = _ctx.PasswordHasher.HashPassword(user, password);
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        await CliHelpers.LogAsync(_ctx, "cli:user reset-password", true,
            $"CLI reset password for uid:{user.Uid} name:{user.Name}",
            userId: user.Uid.ToString(), userEmail: user.Email);

        return await CliHelpers.OkAsync(new { success = true, message = $"已重置用户 {user.Name}（uid:{user.Uid}）的密码。" });
    }
}

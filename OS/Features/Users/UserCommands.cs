using Cocona;
using Microsoft.AspNetCore.Identity;
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

    [Command("create", Description = "创建用户（密码仅从 stdin 读取）")]
    public async Task<int> CreateAsync(
        [Argument("email")] string email,
        [Option("name", Description = "登录名（留空则使用邮箱前缀）")] string? name = null,
        [Option("display-name", Description = "显示名（留空则使用登录名）")] string? displayName = null,
        [Option("group", Description = "用户组（normal/admin/max，默认 normal）")] string group = "normal",
        [Option("password-stdin", Description = "从 stdin 读取密码（禁止 argv 传参）")] bool passwordStdin = false)
    {
        if (!AuthHelper.IsValidEmail(email))
            return await CliHelpers.ErrorAsync("邮箱地址格式不正确。");

        var targetGroup = group.ToLowerInvariant();
        if (!AuthConstants.Groups.IsValid(targetGroup))
            return await CliHelpers.ErrorAsync($"无效的用户组: {group}（可用: {string.Join("/", AuthConstants.Groups.All)}）");

        var normalizedEmail = UsernameNormalizer.Normalize(email);
        var normalizedName = string.IsNullOrEmpty(name) ? normalizedEmail : UsernameNormalizer.Normalize(name);

        var existing = await _ctx.Db.Users.FirstOrDefaultAsync(u =>
            u.Name == normalizedName || (u.NormalizedEmail != null && u.NormalizedEmail == normalizedEmail));
        if (existing is not null)
            return await CliHelpers.ErrorAsync("用户名或邮箱已被占用。");

        string password;
        if (passwordStdin)
        {
            password = CliHelpers.ReadSecretFromStdin() ?? "";
            if (string.IsNullOrEmpty(password))
                return await CliHelpers.ErrorAsync("密码不能为空（从 stdin 读取）");
        }
        else
        {
            password = GeneratePolicyCompliantPassword();
        }

        var user = new User
        {
            Status = UserStatus.Active,
            Name = normalizedName,
            DisplayName = string.IsNullOrEmpty(displayName) ? (name ?? email) : displayName,
            Email = email,
            NormalizedEmail = normalizedEmail,
            Group = targetGroup,
            SecurityStamp = Guid.NewGuid().ToString(),
            RegisterTime = DateTimeOffset.UtcNow
        };

        var userManager = _ctx.Services.GetRequiredService<UserManager<User>>();
        var passwordErrors = await AuthHelper.ValidatePasswordAsync(userManager, user, password);
        if (passwordErrors.Count > 0)
            return await CliHelpers.ErrorAsync(passwordErrors[0].Description);

        user.PasswordHash = _ctx.PasswordHasher.HashPassword(user, password);
        _ctx.Db.Users.Add(user);

        try
        {
            await _ctx.Db.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            return await CliHelpers.ErrorAsync("用户名或邮箱已被占用。");
        }

        await CliHelpers.LogAsync(_ctx, "cli:user create", true,
            $"CLI created user {user.Name} (uid:{user.Uid}) group:{targetGroup}",
            userId: user.Uid.ToString(), userEmail: user.Email);

        var response = new Dictionary<string, object>
        {
            ["success"] = true,
            ["message"] = $"已创建用户 {user.Name}（uid:{user.Uid}）。",
            ["uid"] = user.Uid,
            ["name"] = user.Name,
            ["group"] = targetGroup
        };
        if (!passwordStdin)
            response["generatedPassword"] = password;

        return await CliHelpers.OkAsync(response);
    }

    [Command("delete", Description = "软删除用户（吊销全部会话）")]
    public async Task<int> DeleteAsync([Argument("uid|name|email")] string target)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        if (user.Status == UserStatus.Deleted)
            return await CliHelpers.ErrorAsync($"用户 {user.Name} 已被删除。");

        user.Status = UserStatus.Deleted;
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        await CliHelpers.LogAsync(_ctx, "cli:user delete", true,
            $"CLI deleted user {user.Name} (uid:{user.Uid})",
            userId: user.Uid.ToString(), userEmail: user.Email);

        return await CliHelpers.OkAsync(new { success = true, message = $"用户 {user.Name}（uid:{user.Uid}）已删除。" });
    }

    [Command("revoke-sessions", Description = "强制吊销用户全部活跃会话")]
    public async Task<int> RevokeSessionsAsync([Argument("uid|name|email")] string target)
    {
        var user = await CliHelpers.FindUserAsync(_ctx, target);
        if (user is null)
            return await CliHelpers.ErrorAsync($"用户不存在: {target}");

        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        await CliHelpers.LogAsync(_ctx, "cli:user revoke-sessions", true,
            $"CLI revoked all sessions for {user.Name} (uid:{user.Uid})",
            userId: user.Uid.ToString(), userEmail: user.Email);

        return await CliHelpers.OkAsync(new { success = true, message = $"用户 {user.Name}（uid:{user.Uid}）的全部会话已吊销。" });
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

    private string GeneratePolicyCompliantPassword()
    {
        var opts = _ctx.Services.GetRequiredService<UserManager<User>>().Options.Password;
        var config = _ctx.Config;
        var requiredLength = config.Identity.Password.RequiredLength;
        var length = Math.Max(requiredLength, opts.RequiredLength);
        var requiredCount = 0;
        if (opts.RequireLowercase) requiredCount++;
        if (opts.RequireUppercase) requiredCount++;
        if (opts.RequireDigit) requiredCount++;
        if (opts.RequireNonAlphanumeric) requiredCount++;
        if (length < requiredCount) length = requiredCount;

        const string lower = "abcdefghijklmnopqrstuvwxyz";
        const string upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
        const string digits = "0123456789";
        const string special = "!@#$%^&*()_+-=[]{}|;:,.<>?";

        var passwordChars = new List<char>(length);

        if (opts.RequireLowercase) passwordChars.Add(lower[System.Security.Cryptography.RandomNumberGenerator.GetInt32(lower.Length)]);
        if (opts.RequireUppercase) passwordChars.Add(upper[System.Security.Cryptography.RandomNumberGenerator.GetInt32(upper.Length)]);
        if (opts.RequireDigit) passwordChars.Add(digits[System.Security.Cryptography.RandomNumberGenerator.GetInt32(digits.Length)]);
        if (opts.RequireNonAlphanumeric) passwordChars.Add(special[System.Security.Cryptography.RandomNumberGenerator.GetInt32(special.Length)]);

        var allChars = lower + upper + digits;
        if (opts.RequireNonAlphanumeric) allChars += special;

        while (passwordChars.Count < length)
            passwordChars.Add(allChars[System.Security.Cryptography.RandomNumberGenerator.GetInt32(allChars.Length)]);

        for (var i = passwordChars.Count - 1; i > 0; i--)
        {
            var j = System.Security.Cryptography.RandomNumberGenerator.GetInt32(i + 1);
            (passwordChars[i], passwordChars[j]) = (passwordChars[j], passwordChars[i]);
        }

        return new string(passwordChars.ToArray());
    }
}

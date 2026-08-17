using Cocona;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Registration;

public sealed class InviteCommands
{
    private readonly CliCommandContext _ctx;
    private readonly IInviteCodeService _inviteCodes;

    public InviteCommands(CliCommandContext ctx, IInviteCodeService inviteCodes)
    {
        _ctx = ctx;
        _inviteCodes = inviteCodes;
    }

    [Command("create", Description = "生成一个只显示一次的邀请码")]
    public async Task<int> CreateAsync(
        [Argument(Description = "normal/admin/max")] string group,
        [Option("max-uses", Description = "普通邀请码最大核销次数")] int? maxUses = null,
        [Option("lifetime-hours", Description = "有效期（小时）")] int? lifetimeHours = null)
    {
        group = group.Trim().ToLowerInvariant();
        if (!AuthConstants.Groups.IsValid(group))
            return await CliHelpers.ErrorAsync("用户组必须为 normal、admin 或 max。");

        var max = maxUses ?? _ctx.Config.InviteCode.MaxRedemptions;
        var lifetime = lifetimeHours ?? _ctx.Config.InviteCode.DefaultLifetimeHours;
        if (max <= 0 || lifetime <= 0 || lifetime > 8760)
            return await CliHelpers.ErrorAsync("max-uses 必须大于 0，lifetime-hours 必须在 1-8760 之间。");

        var created = await _inviteCodes.CreateAsync(group, max, lifetime);
        await CliHelpers.LogAsync(_ctx, "cli:invite create", true,
            $"invite created prefix={created.Entity.Prefix} group={created.Entity.Group}");

        return await CliHelpers.OkAsync(new
        {
            success = true,
            id = created.Entity.Id,
            code = created.Code,
            prefix = created.Entity.Prefix,
            group = created.Entity.Group,
            maxUses = created.Entity.MaxRedemptions,
            expiresAt = created.Entity.ExpiresAt,
            warning = "请立即保存，此后无法再次查看完整邀请码。"
        });
    }

    [Command("list", Description = "列出邀请码（仅 Prefix，不返回明文）")]
    public async Task<int> ListAsync(
        [Option("group", Description = "normal/admin/max")] string? group = null)
    {
        var query = _ctx.Db.InviteCodes.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(group))
        {
            group = group.Trim().ToLowerInvariant();
            if (!AuthConstants.Groups.IsValid(group))
                return await CliHelpers.ErrorAsync("用户组必须为 normal、admin 或 max。");
            query = query.Where(c => c.Group == group);
        }

        var codes = await query.OrderBy(c => c.Prefix)
            .Select(c => new
            {
                c.Id,
                c.Prefix,
                c.Group,
                c.Status,
                c.MaxRedemptions,
                c.UsedCount,
                c.ExpiresAt
            })
            .ToListAsync();
        return await CliHelpers.OkAsync(new { success = true, total = codes.Count, codes });
    }

    [Command("revoke", Description = "批量撤销邀请码（不可恢复明文）")]
    public async Task<int> RevokeAsync(
        [Option("ids", Description = "逗号分隔的邀请码 Id")] string ids)
    {
        var parsed = ids.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(x => Guid.TryParse(x, out var id) ? id : (Guid?)null)
            .Where(x => x.HasValue)
            .Select(x => x!.Value)
            .Distinct()
            .ToList();
        if (parsed.Count == 0 || parsed.Count > 1000)
            return await CliHelpers.ErrorAsync("ids 必须为 1-1000 个有效 GUID。");

        var entities = await _ctx.Db.InviteCodes.Where(c => parsed.Contains(c.Id)).ToListAsync();
        foreach (var entity in entities)
            entity.Status = InviteCodeStatus.Revoked;
        await _ctx.Db.SaveChangesAsync();
        await CliHelpers.LogAsync(_ctx, "cli:invite revoke", true, $"invite revoked count={entities.Count}");
        return await CliHelpers.OkAsync(new { success = true, revoked = entities.Count });
    }

    [Command("migrate-legacy", Description = "将旧明文邀请码转换为 HMAC 并删除旧明文字段")]
    public async Task<int> MigrateLegacyAsync()
    {
        var result = await _inviteCodes.MigrateLegacyAsync();
        await CliHelpers.LogAsync(_ctx, "cli:invite migrate-legacy", true,
            $"invite legacy migration migrated={result.Migrated} alreadyMigrated={result.AlreadyMigrated}");
        return await CliHelpers.OkAsync(new
        {
            success = true,
            migrated = result.Migrated,
            alreadyMigrated = result.AlreadyMigrated
        });
    }
}

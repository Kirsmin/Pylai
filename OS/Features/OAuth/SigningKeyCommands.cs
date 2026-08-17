using Cocona;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.OAuth;

public sealed class SigningKeyCommands
{
    private readonly CliCommandContext _ctx;
    private readonly IMfaService _mfa;

    public SigningKeyCommands(CliCommandContext ctx, IMfaService mfa)
    {
        _ctx = ctx;
        _mfa = mfa;
    }

    [Command("status", Description = "查看签名密钥状态")]
    public async Task<int> StatusAsync()
    {
        var keys = await SigningKeyService.GetStatusAsync(_ctx.Db);
        return await CliHelpers.OkAsync(new
        {
            success = true,
            total = keys.Count,
            usable = keys.Count(k => k.UsableNow),
            keys = keys.Select(k => new
            {
                id = k.Id,
                thumbprint = k.Thumbprint,
                createdAt = CliHelpers.FormatUtc(k.CreatedAt),
                expiresAt = CliHelpers.FormatUtc(k.ExpiresAt),
                isActive = k.IsActive,
                isRevoked = k.IsRevoked,
                usableNow = k.UsableNow
            })
        });
    }

    [Command("rotate", Description = "人工轮换签名密钥（需高权限账户 MFA 验证码）")]
    public async Task<int> RotateAsync(
        [Option("rotation-days", Description = "轮换周期（天）")] int rotationDays = 90,
        [Option("validation-days", Description = "旧密钥保留验证天数")] int validationDays = 180,
        [Option("if-empty", Description = "仅当没有可用密钥时创建/轮换")] bool ifEmpty = false,
        [Option("mfa-user", Description = "已配置 MFA 的高权限账户（用户名或邮箱）")] string? mfaUser = null,
        [Option("mfa-code", Description = "该账户 TOTP 验证码")] string? mfaCode = null)
    {
        if (rotationDays < 1 || rotationDays > 3650)
            return await CliHelpers.ErrorAsync("--rotation-days 必须在 1-3650 之间。");
        if (validationDays < 1 || validationDays > 7300)
            return await CliHelpers.ErrorAsync("--validation-days 必须在 1-7300 之间。");

        var status = await SigningKeyService.GetStatusAsync(_ctx.Db);
        if (ifEmpty && status.Any(k => k.UsableNow))
        {
            return await CliHelpers.OkAsync(new { success = true, rotated = false, message = "已有可用签名密钥，无需轮换。" });
        }

        // 初始化空密钥库（--if-empty）不需要 step-up；人工轮换必须有 MFA 验证。
        if (!ifEmpty)
        {
            if (string.IsNullOrWhiteSpace(mfaUser) || string.IsNullOrWhiteSpace(mfaCode))
                return await CliHelpers.ErrorAsync("人工轮换签名密钥必须提供 --mfa-user 与 --mfa-code。");

            var normalized = UsernameNormalizer.Normalize(mfaUser);
            var user = await _ctx.Db.Users.FirstOrDefaultAsync(u =>
                u.Name == normalized || (u.NormalizedEmail != null && u.NormalizedEmail == normalized));
            if (user is null)
                return await CliHelpers.ErrorAsync("MFA 账户不存在。");
            if (AuthConstants.Groups.Rank(user.Group) < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin))
                return await CliHelpers.ErrorAsync("签名密钥轮换必须由 Admin/Max 账户完成 MFA 验证。");
            if (!await _mfa.VerifyTotpAsync(user.Uid, mfaCode))
                return await CliHelpers.ErrorAsync("MFA 验证失败，签名密钥未轮换。");
        }

        var rotated = await SigningKeyService.RotateIfDueAsync(_ctx.Db, _ctx.Config, rotationDays, validationDays);

        await CliHelpers.LogAsync(_ctx, "cli:key rotate", true,
            rotated ? $"签名密钥已轮换 rotationDays={rotationDays} validationDays={validationDays}" : "签名密钥未到期，未轮换",
            eventType: AuthConstants.EventTypes.CliCommand);

        var after = await SigningKeyService.GetStatusAsync(_ctx.Db);
        return await CliHelpers.OkAsync(new
        {
            success = true,
            rotated,
            message = rotated ? "签名密钥已轮换。" : "签名密钥未到期，未轮换。",
            keys = after.Select(k => new { id = k.Id, thumbprint = k.Thumbprint, createdAt = CliHelpers.FormatUtc(k.CreatedAt), usableNow = k.UsableNow })
        });
    }

    [Command("reencrypt", Description = "将数据库中的旧明文 PKCS#12 转为 AES-GCM 信封加密")]
    public async Task<int> ReencryptAsync()
    {
        var result = await SigningKeyService.ReencryptLegacyAsync(_ctx.Db, _ctx.Config);
        await CliHelpers.LogAsync(_ctx, "cli:key reencrypt", true,
            $"signing key reencrypt migrated={result.Migrated} alreadyMigrated={result.AlreadyMigrated}");
        return await CliHelpers.OkAsync(new
        {
            success = true,
            migrated = result.Migrated,
            alreadyMigrated = result.AlreadyMigrated
        });
    }
}

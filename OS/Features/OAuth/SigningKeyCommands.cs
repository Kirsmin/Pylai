using Cocona;

namespace Pylaios.Features.OAuth;

public sealed class SigningKeyCommands
{
    private readonly CliCommandContext _ctx;

    public SigningKeyCommands(CliCommandContext ctx)
    {
        _ctx = ctx;
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

    [Command("rotate", Description = "人工轮换签名密钥（--if-empty 仅无可用密钥时创建）")]
    public async Task<int> RotateAsync(
        [Option("rotation-days", Description = "轮换周期（天）")] int rotationDays = 90,
        [Option("validation-days", Description = "旧密钥保留验证天数")] int validationDays = 180,
        [Option("if-empty", Description = "仅当没有可用密钥时创建/轮换")] bool ifEmpty = false)
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

        var rotated = await SigningKeyService.RotateIfDueAsync(_ctx.Db, rotationDays, validationDays);

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
}

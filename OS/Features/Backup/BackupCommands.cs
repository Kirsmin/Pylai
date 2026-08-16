using Cocona;

namespace Pylaios.Features.Backup;


public sealed class BackupCommands
{
    private readonly CliCommandContext _ctx;
    private readonly BackupService _backup;

    public BackupCommands(CliCommandContext ctx, BackupService backup)
    {
        _ctx = ctx;
        _backup = backup;
    }

    [Command("create", Description = "创建数据库快照（pg_dump -Fc）")]
    public async Task<int> CreateAsync([Argument] string? name = null)
    {
        try
        {
            var path = await _backup.CreateAsync(name);
            await CliHelpers.LogAsync(_ctx, "cli:backup create", true, $"CLI created backup {Path.GetFileName(path)}");
            return await CliHelpers.OkAsync(new
            {
                success = true,
                path,
                name = Path.GetFileName(path),
                message = $"备份已创建: {path}"
            });
        }
        catch (Exception ex)
        {
            return await CliHelpers.ErrorAsync($"创建备份失败: {ex.Message}");
        }
    }

    [Command("list", Description = "列出全部快照（按时间倒序）")]
    public async Task<int> ListAsync()
    {
        var entries = _backup.List().Select(b => new
        {
            name = b.Name,
            sizeBytes = b.SizeBytes,
            sizeMb = Math.Round(b.SizeBytes / 1024.0 / 1024.0, 2),
            createdAt = CliHelpers.FormatUtc(b.CreatedAt)
        });
        return await CliHelpers.OkAsync(new { success = true, directory = _backup.Directory, total = entries.Count(), backups = entries });
    }

    [Command("delete", Description = "删除指定快照")]
    public async Task<int> DeleteAsync([Argument("name")] string name)
    {
        try
        {
            _backup.Delete(name);
            await CliHelpers.LogAsync(_ctx, "cli:backup delete", true, $"CLI deleted backup {name}");
            return await CliHelpers.OkAsync(new { success = true, message = $"备份 {name} 已删除。" });
        }
        catch (Exception ex)
        {
            return await CliHelpers.ErrorAsync(ex.Message);
        }
    }

    [Command("restore", Description = "恢复指定快照（pg_restore --clean；恢复前请先停止 serve）")]
    public async Task<int> RestoreAsync([Argument("name")] string name)
    {
        try
        {
            await _backup.RestoreAsync(name);
            await CliHelpers.LogAsync(_ctx, "cli:backup restore", true, $"CLI restored backup {name}");
            return await CliHelpers.OkAsync(new { success = true, message = $"备份 {name} 已恢复。" });
        }
        catch (Exception ex)
        {
            return await CliHelpers.ErrorAsync($"恢复失败: {ex.Message}");
        }
    }
}

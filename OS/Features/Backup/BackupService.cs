using System.Diagnostics;
using Npgsql;

namespace Pylaios.Features.Backup;






public sealed class BackupService
{
    private readonly string _connectionString;
    private readonly string _directory;

    public BackupService(MainConfig config)
    {
        _connectionString = config.Database.ConnectionString;
        _directory = Path.GetFullPath(config.Backup.Directory);
    }

    public string Directory => _directory;

    public async Task<string> CreateAsync(string? name = null)
    {
        System.IO.Directory.CreateDirectory(_directory);
        var (host, port, username, password, db) = Parse();
        var file = SanitizeName(name ?? $"pylai-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}.dump");
        var target = Path.Combine(_directory, file);

        var args = new List<string>
        {
            "-Fc", "-f", target,
            "-h", host, "-p", port.ToString(), "-U", username,
            db
        };
        var (exit, stderr) = await RunAsync("pg_dump", args, password);
        if (exit != 0)
        {
            if (File.Exists(target)) File.Delete(target);
            throw new InvalidOperationException($"pg_dump 失败 (exit {exit}): {stderr.Trim()}");
        }
        return target;
    }

    public IReadOnlyList<BackupEntry> List()
    {
        if (!System.IO.Directory.Exists(_directory)) return [];
        return System.IO.Directory.GetFiles(_directory, "*.dump")
            .OrderByDescending(File.GetLastWriteTimeUtc)
            .Select(f => new BackupEntry
            {
                Name = Path.GetFileName(f),
                SizeBytes = new FileInfo(f).Length,
                CreatedAt = File.GetLastWriteTimeUtc(f)
            })
            .ToList();
    }

    public void Delete(string name)
    {
        var path = Resolve(name);
        if (!System.IO.File.Exists(path))
            throw new FileNotFoundException($"备份不存在: {name}（可用 backup list 查看）");
        File.Delete(path);
    }

    public async Task RestoreAsync(string name)
    {
        var path = Resolve(name);
        if (!System.IO.File.Exists(path))
            throw new FileNotFoundException($"备份不存在: {name}（可用 backup list 查看）");

        var (host, port, username, password, db) = Parse();
        var args = new List<string>
        {
            "--clean", "--if-exists", "--no-owner",
            "-h", host, "-p", port.ToString(), "-U", username,
            "-d", db, path
        };
        var (exit, stderr) = await RunAsync("pg_restore", args, password);
        if (exit != 0)
            throw new InvalidOperationException($"pg_restore 失败 (exit {exit}): {stderr.Trim()}");
    }

    private string Resolve(string name)
    {
        return Path.Combine(_directory, SanitizeName(name));
    }

    private static string SanitizeName(string name)
    {
        var fileName = name.EndsWith(".dump", StringComparison.OrdinalIgnoreCase) ? name : name + ".dump";
        if (fileName != Path.GetFileName(fileName) || Path.IsPathRooted(fileName) || fileName.Contains('\\'))
            throw new InvalidOperationException($"无效备份名: {name}（仅允许纯文件名）");
        return fileName;
    }

    private (string Host, int Port, string Username, string? Password, string Database) Parse()
    {
        var conn = new NpgsqlConnectionStringBuilder(_connectionString);
        if (string.IsNullOrEmpty(conn.Host))
            throw new InvalidOperationException("[Database].ConnectionString 缺少 Host 参数");
        if (string.IsNullOrEmpty(conn.Username))
            throw new InvalidOperationException("[Database].ConnectionString 缺少 Username 参数");
        if (string.IsNullOrEmpty(conn.Database))
            throw new InvalidOperationException("[Database].ConnectionString 缺少 Database 参数");
        return (conn.Host!, conn.Port, conn.Username!, conn.Password, conn.Database!);
    }

    private static async Task<(int Exit, string Stderr)> RunAsync(string tool, List<string> args, string? password)
    {
        var psi = new ProcessStartInfo(tool)
        {
            RedirectStandardError = true,
            RedirectStandardOutput = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.Environment["PGPASSWORD"] = password ?? "";

        using var process = Process.Start(psi)
            ?? throw new InvalidOperationException($"无法启动 {tool}");
        var stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        return (process.ExitCode, stderr);
    }
}

public sealed class BackupEntry
{
    public required string Name { get; init; }
    public long SizeBytes { get; init; }
    public DateTimeOffset CreatedAt { get; init; }
}

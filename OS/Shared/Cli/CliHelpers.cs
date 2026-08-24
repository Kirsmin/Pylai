using System.Reflection;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared.Cli;

public static class CliHelpers
{

    public static string OutputFormat { get; set; } = "json";


    public static string ConfigPath { get; set; } = "pylai.toml";


    private static readonly JsonSerializerOptions CompactOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    private static readonly JsonSerializerOptions HumanOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };


    public static string SerializeJson(object obj)
        => JsonSerializer.Serialize(obj, OutputFormat == "human" ? HumanOptions : CompactOptions);


    public static string FormatUtc(DateTimeOffset value)
        => value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'");




    public static string? ReadSecretFromStdin()
        => Console.In.ReadLine();

    /// <summary>
    /// 解析配置文件路径：--config flag &gt; PYLAI_CONFIG 环境变量 &gt; 程序根目录/当前目录 pylai.toml。
    /// </summary>
    public static string ResolveConfigPath(string baseDir, string? flag)
    {
        var path = flag ?? Environment.GetEnvironmentVariable("PYLAI_CONFIG");
        if (path is not null)
            return Path.GetFullPath(path, Environment.CurrentDirectory);

        var rootCandidate = Path.Combine(baseDir, "pylai.toml");
        var cwdCandidate = Path.Combine(Environment.CurrentDirectory, "pylai.toml");
        if (File.Exists(rootCandidate)) return rootCandidate;
        if (File.Exists(cwdCandidate)) return cwdCandidate;
        return cwdCandidate;
    }

    public static string VersionInfo()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var v = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.0.0";
        if (v.Contains('+', StringComparison.Ordinal))
            v = v[..v.IndexOf('+')];
        return v;
    }

    public static Task<int> ErrorAsync(string message)
    {
        Console.Error.WriteLine(message);
        Console.Out.WriteLine(SerializeJson(new { success = false, error = message }));
        return Task.FromResult(1);
    }

    public static Task<int> OkAsync(object obj)
    {
        Console.Out.WriteLine(SerializeJson(obj));
        return Task.FromResult(0);
    }


    public static async Task LogAsync(
        CliCommandContext ctx, string endpoint, bool success, string? details = null,
        string? eventType = null, string? userId = null, string? userEmail = null)
    {
        await ctx.Audit.LogAsync(new AuditLog
        {
            EventType = eventType ?? AuthConstants.EventTypes.CliCommand,
            UserId = userId ?? "cli",
            UserEmail = userEmail,
            Endpoint = endpoint,
            Method = "CLI",
            IpAddress = "local",
            Success = success,
            Details = details
        });
    }


    public static async Task<User?> FindUserAsync(CliCommandContext ctx, string uidOrName)
    {
        if (Guid.TryParse(uidOrName, out var uid))
        {
            var byUid = await ctx.Db.Users.FindAsync(uid);
            if (byUid is not null) return byUid;
        }

        var normalized = UsernameNormalizer.Normalize(uidOrName);
        return await ctx.Db.Users.FirstOrDefaultAsync(u =>
            (u.Name == normalized || (u.NormalizedEmail != null && u.NormalizedEmail == normalized))
            && u.Status != UserStatus.Deleted);
    }
}

public sealed class CliUsageException(string message) : Exception(message);

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

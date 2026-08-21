using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using Cocona;
using Microsoft.AspNetCore.Authentication;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Pylaios.Features.Admin;

public static class LocalManageToken
{
    public const string Scheme = "LocalManageToken";
    public const string Prefix = "ManageToken";
    public const string FilePath = "/tmp/pylai-manage-token";

    public static string Hash(string token)
        => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
}

public sealed class LocalManageTokenRecord
{
    public Guid Uid { get; set; }
    public string Name { get; set; } = string.Empty;
    public DateTimeOffset ExpiresAt { get; set; }
    public string TokenHash { get; set; } = string.Empty;
}

public sealed class LocalManageTokenOptions : AuthenticationSchemeOptions { }

public sealed class LocalManageTokenAuthHandler : AuthenticationHandler<LocalManageTokenOptions>
{
    private readonly ApplicationDbContext _db;

    public LocalManageTokenAuthHandler(
        IOptionsMonitor<LocalManageTokenOptions> options,
        ILoggerFactory logger,
        UrlEncoder encoder,
        ApplicationDbContext db)
        : base(options, logger, encoder)
    {
        _db = db;
    }

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var auth = Request.Headers.Authorization.ToString();
        if (!auth.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
            return AuthenticateResult.NoResult();

        var token = auth[7..].Trim();
        if (!token.StartsWith(LocalManageToken.Prefix, StringComparison.Ordinal))
            return AuthenticateResult.NoResult();

        if (Request.Headers.ContainsKey("X-Forwarded-For")
            || Context.Connection.RemoteIpAddress is not { } remoteIp
            || !IPAddress.IsLoopback(remoteIp))
            return AuthenticateResult.Fail("Local manage token only accepts direct loopback requests");

        if (!File.Exists(LocalManageToken.FilePath))
            return AuthenticateResult.Fail("Local manage token unavailable");

        LocalManageTokenRecord? record;
        try
        {
            record = JsonSerializer.Deserialize<LocalManageTokenRecord>(
                await File.ReadAllTextAsync(LocalManageToken.FilePath, Context.RequestAborted));
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            return AuthenticateResult.Fail("Local manage token unavailable");
        }

        if (record is null || record.ExpiresAt <= DateTimeOffset.UtcNow)
            return AuthenticateResult.Fail("Local manage token expired");

        byte[] expected;
        try
        {
            expected = Convert.FromHexString(record.TokenHash);
        }
        catch (FormatException)
        {
            return AuthenticateResult.Fail("Invalid local manage token record");
        }
        var actual = SHA256.HashData(Encoding.UTF8.GetBytes(token));
        if (expected.Length != actual.Length || !CryptographicOperations.FixedTimeEquals(expected, actual))
            return AuthenticateResult.Fail("Invalid local manage token");

        var user = await _db.Users.AsNoTracking()
            .Where(u => u.Uid == record.Uid && u.Group == AuthConstants.Roles.Max && u.Status == UserStatus.Active)
            .Select(u => new { u.Uid, u.Name })
            .FirstOrDefaultAsync(Context.RequestAborted);
        if (user is null)
            return AuthenticateResult.Fail("Local manage token owner is unavailable");

        var claims = new[]
        {
            new Claim(ClaimTypes.NameIdentifier, user.Uid.ToString()),
            new Claim(ClaimTypes.Name, user.Name),
            new Claim(ClaimTypes.Role, AuthConstants.Roles.Max),
            new Claim("auth_scheme", LocalManageToken.Scheme)
        };
        var principal = new ClaimsPrincipal(new ClaimsIdentity(claims, LocalManageToken.Scheme));
        return AuthenticateResult.Success(new AuthenticationTicket(principal, LocalManageToken.Scheme));
    }
}

public sealed class LocalManageTokenCommands
{
    private readonly CliCommandContext _ctx;

    public LocalManageTokenCommands(CliCommandContext ctx)
    {
        _ctx = ctx;
    }

    [Command("issue", Description = "签发 ManagePylai 本机短期管理令牌")]
    public async Task<int> IssueAsync([Option("lifetime-hours")] int lifetimeHours = 12)
    {
        if (lifetimeHours is < 1 or > 24)
            return await CliHelpers.ErrorAsync("--lifetime-hours 必须在 1-24 之间。");

        var user = await _ctx.Db.Users.AsNoTracking()
            .Where(u => u.Group == AuthConstants.Roles.Max && u.Status == UserStatus.Active)
            .OrderBy(u => u.RegisterTime)
            .Select(u => new { u.Uid, u.Name })
            .FirstOrDefaultAsync();
        if (user is null)
            return await CliHelpers.ErrorAsync("没有可用的 Max 账户，无法签发本机管理令牌。");

        var token = LocalManageToken.Prefix + Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
        var expiresAt = DateTimeOffset.UtcNow.AddHours(lifetimeHours);
        var record = new LocalManageTokenRecord
        {
            Uid = user.Uid,
            Name = user.Name,
            ExpiresAt = expiresAt,
            TokenHash = LocalManageToken.Hash(token)
        };

        await File.WriteAllTextAsync(LocalManageToken.FilePath, JsonSerializer.Serialize(record));
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(
                LocalManageToken.FilePath,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.GroupRead | UnixFileMode.OtherRead);
        }

        return await CliHelpers.OkAsync(new
        {
            success = true,
            token,
            expiresAt
        });
    }
}

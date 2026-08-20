using System.Security.Claims;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Pylaios.Shared;

public sealed class PylaiosClaimsPrincipalFactory : UserClaimsPrincipalFactory<User>
{
    public PylaiosClaimsPrincipalFactory(UserManager<User> userManager, IOptions<IdentityOptions> optionsAccessor)
        : base(userManager, optionsAccessor)
    {
    }

    protected override async Task<ClaimsIdentity> GenerateClaimsAsync(User user)
    {
        var identity = await base.GenerateClaimsAsync(user);
        var roles = await UserManager.GetRolesAsync(user);
        foreach (var role in roles)
            identity.AddClaim(new Claim(Options.ClaimsIdentity.RoleClaimType, role));
        return identity;
    }
}

public static class AuthHelper
{
    public static async Task<List<IdentityError>> ValidatePasswordAsync(
        UserManager<User> userManager, User user, string password)
    {
        var errors = new List<IdentityError>();
        foreach (var validator in userManager.PasswordValidators)
        {
            var vr = await validator.ValidateAsync(userManager, user, password);
            if (!vr.Succeeded) errors.AddRange(vr.Errors);
        }
        return errors;
    }

    public static string GenerateCode()
    {
        return RandomNumberGenerator.GetInt32(100000, 1000000).ToString();
    }

    public const string UserTokenPrefix = "UserToken";
    public const int UserTokenKeyLength = 128;

    public static string GenerateOpaqueToken(int bytes = 32)
        => Convert.ToBase64String(RandomNumberGenerator.GetBytes(bytes))
            .Replace('+', '-')
            .Replace('/', '_')
            .TrimEnd('=');

    public static string GenerateUserToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(64);
        var hex = Convert.ToHexStringLower(bytes);
        return $"{UserTokenPrefix}{hex}";
    }

    public static string HashCode(string code)
    {
        var bytes = SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(code));
        return Convert.ToHexStringLower(bytes);
    }

    public static bool CodeEquals(string hash1, string hash2)
    {
        var b1 = Convert.FromHexString(hash1);
        var b2 = Convert.FromHexString(hash2);
        return CryptographicOperations.FixedTimeEquals(b1, b2);
    }

    public static bool IsValidEmail(string email)
    {
        try
        {
            var addr = new System.Net.Mail.MailAddress(email);
            return addr.Address == email;
        }
        catch
        {
            return false;
        }
    }

    private static int _testModeGuardChecked;

    /// <summary>
    /// TestMode 启动门禁：Production 环境下激活 --TestMode 时抛出异常拒绝启动
    /// （验证码会泄露到控制台，属安全风险）；Development 下打印醒目警告。
    /// 启动路径（Program.RunWebAsync）与验证码输出路径（LogCode）都会调用。
    /// </summary>
    public static void EnsureTestModeAllowed(IWebHostEnvironment? env = null)
    {
        // 只校验一次：启动路径与验证码输出路径都会调用，避免重复打印警告。
        if (Interlocked.Exchange(ref _testModeGuardChecked, 1) == 1)
            return;

        var environmentName = env?.EnvironmentName
            ?? Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT")
            ?? Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT")
            ?? "Production";

        if (environmentName.Equals("Development", StringComparison.OrdinalIgnoreCase))
        {
            Console.Error.WriteLine(
                "\x1b[93m⚠️  Pylaios       TestMode 已激活（仅限开发环境）：验证码将输出到控制台，邮件不会实际发送。严禁在生产环境使用 --TestMode\x1b[0m");
            return;
        }

        throw new InvalidOperationException(
            "--TestMode 在生产环境被激活：验证码会输出到控制台，属于安全风险，拒绝启动。请移除 --TestMode 参数。");
    }

    public static void LogCode(this ILogger logger, TestModeOptions testMode, LogLevel level,
        string message, string code, params object?[] args)
    {
        if (!testMode.Enabled)
        {
            logger.Log(level, message, args);
            return;
        }

        // 兜底校验（首次调用时执行一次）：Production 环境拒绝输出验证码，Development 下警告一次。
        EnsureTestModeAllowed();

        // 测试模式：验证码必须输出到控制台，不依赖任何日志级别过滤。
        // 直接写 stderr（与日志同一通道），样式对齐启动横幅（黄色 ⚠️）。
        var formatted = FormatTemplate(message + " | 验证码:" + code, args);
        Console.Error.WriteLine(
            $"\x1b[93m{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  \u26A0\uFE0F  {"Pylaios".PadRight(14)}\x1b[0m {formatted}");
    }

    /// <summary>按出现顺序把结构化模板占位符 {Name} 替换为位置参数（与 logger 位置绑定行为一致）。</summary>
    private static string FormatTemplate(string template, object?[] args)
    {
        if (args.Length == 0) return template;
        var index = 0;
        return Regex.Replace(template, @"\{[^{}]+\}", m =>
            index < args.Length ? args[index++]?.ToString() ?? string.Empty : m.Value);
    }
}

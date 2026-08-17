using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Identity;

namespace Pylaios.Features.Auth;

public sealed class PasswordSecurityValidator : IPasswordValidator<User>
{
    private readonly MainConfig _config;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IWebHostEnvironment _environment;

    public PasswordSecurityValidator(
        MainConfig config,
        IHttpClientFactory httpClientFactory,
        IWebHostEnvironment environment)
    {
        _config = config;
        _httpClientFactory = httpClientFactory;
        _environment = environment;
    }

    public async Task<IdentityResult> ValidateAsync(UserManager<User> manager, User user, string? password)
    {
        if (string.IsNullOrEmpty(password))
            return IdentityResult.Failed(new IdentityError { Code = "PasswordRequired", Description = "密码不能为空。" });

        var minimum = AuthConstants.Groups.Rank(user.Group) >= AuthConstants.Groups.Rank(AuthConstants.Roles.Admin)
            ? _config.Identity.Password.AdminRequiredLength
            : _config.Identity.Password.RequiredLength;
        if (password.Length < minimum)
        {
            return IdentityResult.Failed(new IdentityError
            {
                Code = "PasswordTooShort",
                Description = $"密码长度至少为 {minimum} 个字符。"
            });
        }

        if (!_config.Identity.Password.CheckBreachedPasswords)
            return IdentityResult.Success;

        var hash = Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(password)));
        var prefix = hash[..5];
        var suffix = hash[5..];
        try
        {
            var client = _httpClientFactory.CreateClient("hibp");
            using var response = await client.GetAsync(prefix);
            if (!response.IsSuccessStatusCode)
            {
                if (_environment.IsDevelopment())
                    return IdentityResult.Success;
                return IdentityResult.Failed(new IdentityError
                {
                    Code = "PasswordScreeningUnavailable",
                    Description = "暂时无法完成泄露密码检查，请稍后重试。"
                });
            }

            var body = await response.Content.ReadAsStringAsync();
            var breached = body.Split('\n', StringSplitOptions.RemoveEmptyEntries)
                .Any(line => line.StartsWith(suffix + ":", StringComparison.OrdinalIgnoreCase));
            return breached
                ? IdentityResult.Failed(new IdentityError { Code = "PasswordBreached", Description = "该密码已出现在泄露密码库中，请更换密码。" })
                : IdentityResult.Success;
        }
        catch
        {
            if (_environment.IsDevelopment())
                return IdentityResult.Success;
            return IdentityResult.Failed(new IdentityError
            {
                Code = "PasswordScreeningUnavailable",
                Description = "暂时无法完成泄露密码检查，请稍后重试。"
            });
        }
    }
}

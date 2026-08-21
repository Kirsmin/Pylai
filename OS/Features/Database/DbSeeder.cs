using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Database;






public static class DbSeeder
{
    public static async Task SeedAsync(IServiceProvider serviceProvider, MainConfig config)
    {
        using var scope = serviceProvider.CreateScope();

        var context = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
        var passwordHasher = scope.ServiceProvider.GetRequiredService<IPasswordHasher<User>>();
        var userManager = scope.ServiceProvider.GetRequiredService<UserManager<User>>();

        await SeedUsersAsync(context, passwordHasher, userManager, config);
    }

    private static async Task SeedUsersAsync(
        ApplicationDbContext context,
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        MainConfig config)
    {
        var admin = config.Seeds.DefaultAdmin;
        if (!string.IsNullOrEmpty(admin.Email))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                admin.Email, admin.Password ?? string.Empty, admin.DisplayName,
                AuthConstants.Roles.Admin, config);
        }

        var user = config.Seeds.DefaultUser;
        if (!string.IsNullOrEmpty(user.Email))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                user.Email, user.Password ?? string.Empty, user.DisplayName,
                AuthConstants.Roles.Normal, config);
        }

        var max = config.Seeds.DefaultMax;
        if (!string.IsNullOrEmpty(max.Email))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                max.Email, max.Password ?? string.Empty, max.DisplayName,
                AuthConstants.Roles.Max, config);
        }
    }

    private static async Task CreateUserIfNotExists(
        ApplicationDbContext context,
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        string email,
        string password,
        string displayName,
        string group,
        MainConfig config)
    {
        var normalizedName = UsernameNormalizer.Normalize(email);
        var normalizedEmail = UsernameNormalizer.Normalize(email);

        var existing = await context.Users.FirstOrDefaultAsync(u =>
            u.Name == normalizedName || (u.NormalizedEmail != null && u.NormalizedEmail == normalizedEmail));
        if (existing is not null)
            return;

        var user = new User
        {
            Status = UserStatus.Active,
            Name = normalizedName,
            DisplayName = displayName,
            Email = email,
            NormalizedEmail = normalizedEmail,
            Group = group,
            SecurityStamp = Guid.NewGuid().ToString(),
            RegisterTime = DateTimeOffset.UtcNow
        };

        if (string.IsNullOrEmpty(password))
        {
            const int maxAttempts = 5;
            List<IdentityError>? lastErrors = null;
            string? candidate = null;
            var generated = false;
            for (var attempt = 0; attempt < maxAttempts; attempt++)
            {
                candidate = GeneratePolicyCompliantPassword(userManager, config, group);
                var errors = await AuthHelper.ValidatePasswordAsync(userManager, user, candidate);
                if (errors.Count == 0)
                {
                    password = candidate;
                    generated = true;
                    break;
                }
                lastErrors = errors;
            }
            if (!generated)
            {
                var detail = lastErrors is not null && lastErrors.Count > 0 ? lastErrors[0].Description : "未知原因";
                throw new InvalidOperationException($"种子用户 {email} 自动生成密码失败：{detail}");
            }
            Console.Error.WriteLine($"[DbSeeder] 种子用户 {email} 未提供密码，已自动生成符合当前策略的密码（请在安装脚本输出中查看）。");
        }
        else
        {
            var passwordErrors = await AuthHelper.ValidatePasswordAsync(userManager, user, password);
            if (passwordErrors.Count > 0)
            {
                throw new InvalidOperationException(
                    $"种子用户 {email} 的密码不符合当前策略：{passwordErrors[0].Description}");
            }
        }

        user.PasswordHash = passwordHasher.HashPassword(user, password);

        context.Users.Add(user);
        try
        {
            await context.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            context.Entry(user).State = EntityState.Detached;
        }
    }

    private static string GeneratePolicyCompliantPassword(UserManager<User> userManager, MainConfig config, string group)
    {
        var opts = userManager.Options.Password;
        var isPrivileged = AuthConstants.Groups.Rank(group) >= AuthConstants.Groups.Rank(AuthConstants.Roles.Admin);
        var requiredLength = isPrivileged ? config.Identity.Password.AdminRequiredLength : config.Identity.Password.RequiredLength;
        var length = Math.Max(requiredLength, opts.RequiredLength);
        var requiredCount = 0;
        if (opts.RequireLowercase) requiredCount++;
        if (opts.RequireUppercase) requiredCount++;
        if (opts.RequireDigit) requiredCount++;
        if (opts.RequireNonAlphanumeric) requiredCount++;
        if (length < requiredCount) length = requiredCount;

        const string lower = "abcdefghijklmnopqrstuvwxyz";
        const string upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
        const string digits = "0123456789";
        const string special = "!@#$%^&*()_+-=[]{}|;:,.<>?";

        var passwordChars = new List<char>(length);

        if (opts.RequireLowercase) passwordChars.Add(lower[RandomNumberGenerator.GetInt32(lower.Length)]);
        if (opts.RequireUppercase) passwordChars.Add(upper[RandomNumberGenerator.GetInt32(upper.Length)]);
        if (opts.RequireDigit) passwordChars.Add(digits[RandomNumberGenerator.GetInt32(digits.Length)]);
        if (opts.RequireNonAlphanumeric) passwordChars.Add(special[RandomNumberGenerator.GetInt32(special.Length)]);

        var allChars = lower + upper + digits;
        if (opts.RequireNonAlphanumeric) allChars += special;

        while (passwordChars.Count < length)
            passwordChars.Add(allChars[RandomNumberGenerator.GetInt32(allChars.Length)]);

        for (var i = passwordChars.Count - 1; i > 0; i--)
        {
            var j = RandomNumberGenerator.GetInt32(i + 1);
            (passwordChars[i], passwordChars[j]) = (passwordChars[j], passwordChars[i]);
        }

        return new string(passwordChars.ToArray());
    }
}

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
        if (!string.IsNullOrEmpty(admin.Email) && !string.IsNullOrEmpty(admin.Password))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                admin.Email, admin.Password, admin.DisplayName,
                AuthConstants.Roles.Admin);
        }
        else if (!string.IsNullOrEmpty(admin.Email))
        {
            Console.Error.WriteLine("警告: Seeds.DefaultAdmin.Password 为空，跳过 admin 种子用户创建（请通过 Seeds.local.toml 配置）");
        }

        var user = config.Seeds.DefaultUser;
        if (!string.IsNullOrEmpty(user.Email) && !string.IsNullOrEmpty(user.Password))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                user.Email, user.Password, user.DisplayName,
                AuthConstants.Roles.Normal);
        }
        else if (!string.IsNullOrEmpty(user.Email))
        {
            Console.Error.WriteLine("警告: Seeds.DefaultUser.Password 为空，跳过 normal 种子用户创建（请通过 Seeds.local.toml 配置）");
        }

        var max = config.Seeds.DefaultMax;
        if (!string.IsNullOrEmpty(max.Email) && !string.IsNullOrEmpty(max.Password))
        {
            await CreateUserIfNotExists(context, passwordHasher,
                userManager,
                max.Email, max.Password, max.DisplayName,
                AuthConstants.Roles.Max);
        }
        else if (!string.IsNullOrEmpty(max.Email))
        {
            Console.Error.WriteLine("警告: Seeds.DefaultMax.Password 为空，跳过 max 种子用户创建（请通过 Seeds.local.toml 配置）");
        }
    }

    private static async Task CreateUserIfNotExists(
        ApplicationDbContext context,
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        string email,
        string password,
        string displayName,
        string group)
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

        var passwordErrors = await AuthHelper.ValidatePasswordAsync(userManager, user, password);
        if (passwordErrors.Count > 0)
        {
            throw new InvalidOperationException(
                $"种子用户 {email} 的密码不符合当前策略：{passwordErrors[0].Description}");
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
}

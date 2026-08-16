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

        await SeedUsersAsync(context, passwordHasher, config);
        await SeedInviteCodesAsync(context, config);
    }

    private static async Task SeedInviteCodesAsync(ApplicationDbContext context, MainConfig config)
    {
        var gift = config.InviteCode.Gift;
        var defs = new (string Group, IEnumerable<string> Codes)[]
        {
            (AuthConstants.Roles.Normal, gift.Normal),
            (AuthConstants.Roles.Admin, gift.Admin),
            (AuthConstants.Roles.Max, gift.Max)
        };

        foreach (var (group, codes) in defs)
        {
            foreach (var code in codes)
            {
                if (await context.InviteCodes.AnyAsync(c => c.Code == code))
                    continue;

                context.InviteCodes.Add(new InviteCode
                {
                    Code = code,
                    Group = group,
                    MaxRedemptions = config.InviteCode.MaxRedemptions > 0
                        ? config.InviteCode.MaxRedemptions
                        : 10
                });
            }
        }

        await context.SaveChangesAsync();
    }

    private static async Task SeedUsersAsync(
        ApplicationDbContext context,
        IPasswordHasher<User> passwordHasher,
        MainConfig config)
    {
        var admin = config.Seeds.DefaultAdmin;
        if (!string.IsNullOrEmpty(admin.Email) && !string.IsNullOrEmpty(admin.Password))
        {
            await CreateUserIfNotExists(context, passwordHasher,
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

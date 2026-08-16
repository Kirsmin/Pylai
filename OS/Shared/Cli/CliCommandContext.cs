using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared.Cli;


public sealed class CliCommandContext
{
    public IServiceProvider Services { get; }
    public ApplicationDbContext Db { get; }
    public MainConfig Config { get; }
    public IAuditService Audit { get; }
    public IPasswordHasher<User> PasswordHasher { get; }
    public IUserTokenService UserTokens { get; }
    public IClientService Clients { get; }

    public CliCommandContext(IServiceProvider services)
    {
        Services = services;
        Db = services.GetRequiredService<ApplicationDbContext>();
        Config = services.GetRequiredService<MainConfig>();
        Audit = services.GetRequiredService<IAuditService>();
        PasswordHasher = services.GetRequiredService<IPasswordHasher<User>>();
        UserTokens = services.GetRequiredService<IUserTokenService>();
        Clients = services.GetRequiredService<IClientService>();
    }
}

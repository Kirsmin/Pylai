using System.Net;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Authorization.Policy;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Console;
using OpenIddict.EntityFrameworkCore;
using OpenIddict.Quartz;
using OpenIddict.Server;
using StackExchange.Redis;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Shared;




public static class AppServices
{

    public static IServiceCollection AddPylaios(this IServiceCollection services,
        MainConfig config, IWebHostEnvironment? env = null, bool cliOnly = false)
    {
        services.AddConfigFeature(config);
        services.AddDatabaseFeature(config);
        services.AddOAuthFeature(config, env);
        services.AddAuthFeature(config, env);
        services.AddSharedFeature(config);
        services.AddAuditFeature(!cliOnly);
        services.AddClientsFeature();
        services.AddUserTokensFeature();
        services.AddConfirmationFeature();
        services.AddRegistrationFeature();
        services.AddAdminFeature();
        services.AddBackupFeature(config);
        if (!cliOnly) services.AddApiFeature(config);
        return services;
    }




    public static IServiceCollection AddConfigFeature(this IServiceCollection services, MainConfig config)
    {
        services.AddSingleton(config);
        return services;
    }




    public static IServiceCollection AddDatabaseFeature(this IServiceCollection services, MainConfig config)
    {
        services.AddDbContext<ApplicationDbContext>(options =>
        {
            options.UseNpgsql(config.Database.ConnectionString);
            options.UseOpenIddict();
        });
        return services;
    }




    public static IServiceCollection AddOAuthFeature(this IServiceCollection services,
        MainConfig config, IWebHostEnvironment? env)
    {
        services.AddOpenIddict()
            .AddCore(options =>
            {
                options.UseEntityFrameworkCore()
                       .UseDbContext<ApplicationDbContext>();

                if (env is not null)
                {
                    options.UseQuartz(quartzOptions =>
                    {
                        if (!config.TokenCleanup.Enabled)
                            quartzOptions.DisableTokenPruning();
                    });
                }
            });

        if (env is null)
            return services;

        services.AddOpenIddict()
            .AddServer(options =>
            {
                options.SetAuthorizationEndpointUris(config.OpenIddict.Endpoints.Authorize)
                       .SetTokenEndpointUris(config.OpenIddict.Endpoints.Token)
                       .SetIntrospectionEndpointUris(config.OpenIddict.Endpoints.Introspect)
                       .SetUserInfoEndpointUris(config.OpenIddict.Endpoints.UserInfo)
                       .SetEndSessionEndpointUris(config.OpenIddict.Endpoints.EndSession);

                if (config.OpenIddict.Grants.AuthorizationCode)
                    options.AllowAuthorizationCodeFlow();
                if (config.OpenIddict.Grants.RefreshToken)
                    options.AllowRefreshTokenFlow();
                if (config.OpenIddict.Grants.ClientCredentials)
                    options.AllowClientCredentialsFlow();

                SigningKeyService.ConfigureKeys(options, config, env);

                LoadEncryptionCertificate(options, config, env);

                options.SetRevocationEndpointUris("/connect/revoke");

                var aspNetCoreBuilder = options.UseAspNetCore()
                    .EnableAuthorizationEndpointPassthrough()
                    .EnableTokenEndpointPassthrough()
                    .EnableUserInfoEndpointPassthrough()
                    .EnableEndSessionEndpointPassthrough();

                if (env.IsDevelopment() || !config.OpenIddict.RequireHttps)
                {
                    aspNetCoreBuilder.DisableTransportSecurityRequirement();
                }

                var scopeNames = config.OpenIddict.Scopes.Enabled().ToArray();
                options.RegisterScopes(scopeNames);

                options.SetAccessTokenLifetime(TimeSpan.FromHours(config.OpenIddict.AccessToken.LifetimeHours));

                var refreshDays = config.OpenIddict.RefreshToken.LifetimeDays > 0
                    ? config.OpenIddict.RefreshToken.LifetimeDays
                    : config.OpenIddict.RefreshToken.LifetimeHours / 24;
                options.SetRefreshTokenLifetime(TimeSpan.FromDays(refreshDays));

                options.SetIdentityTokenLifetime(TimeSpan.FromHours(config.OpenIddict.IdentityToken.LifetimeHours));
            })
            .AddValidation(options =>
            {
                options.UseLocalServer();
                options.UseAspNetCore();
            });

        return services;
    }




    public static IServiceCollection AddAuthFeature(this IServiceCollection services,
        MainConfig config, IWebHostEnvironment? env = null)
    {
        services.AddScoped<ILookupNormalizer, PylaiosLookupNormalizer>();

        services.AddIdentityCore<User>(options =>
        {
            options.Password.RequireDigit = config.Identity.Password.RequireDigit;
            options.Password.RequireLowercase = config.Identity.Password.RequireLowercase;
            options.Password.RequireUppercase = config.Identity.Password.RequireUppercase;
            options.Password.RequireNonAlphanumeric = config.Identity.Password.RequireNonAlphanumeric;
            options.Password.RequiredLength = config.Identity.Password.RequiredLength;

            options.Lockout.DefaultLockoutTimeSpan =
                TimeSpan.FromMinutes(config.Identity.Lockout.DefaultTimeoutMinutes);
            options.Lockout.MaxFailedAccessAttempts = config.Identity.Lockout.MaxFailedAttempts;
        })
            .AddUserStore<UserStore>()
            .AddSignInManager()
            .AddDefaultTokenProviders();

        services.AddScoped<IUserClaimsPrincipalFactory<User>, PylaiosClaimsPrincipalFactory>();

        if (env is not null)
        {
            services.ConfigureApplicationCookie(options =>
            {
                options.Cookie.Name = config.Cookie.Name;
                options.Cookie.HttpOnly = config.Cookie.HttpOnly;
                options.Cookie.SameSite = Enum.Parse<SameSiteMode>(config.Cookie.SameSite);
                options.Cookie.SecurePolicy = CookieSecurity.GetPolicy(env, config);
                options.ExpireTimeSpan = TimeSpan.FromDays(config.Cookie.ExpireDays);
                options.SlidingExpiration = config.Cookie.SlidingExpiration;
            });
        }

        services.Configure<IdentityOptions>(options =>
        {
            options.ClaimsIdentity.UserNameClaimType = Claims.Name;
            options.ClaimsIdentity.UserIdClaimType = Claims.Subject;
            options.ClaimsIdentity.RoleClaimType = Claims.Role;
            options.ClaimsIdentity.EmailClaimType = Claims.Email;
        });

        var authBuilder = services.AddAuthentication(options =>
        {
            options.DefaultAuthenticateScheme = IdentityConstants.ApplicationScheme;
            options.DefaultChallengeScheme = IdentityConstants.ApplicationScheme;
        });

        authBuilder.AddCookie(IdentityConstants.ApplicationScheme);

        if (!string.IsNullOrEmpty(config.ExternalLogin.Facebook.AppId))
        {
            authBuilder.AddFacebook(options =>
            {
                options.AppId = config.ExternalLogin.Facebook.AppId;
                options.AppSecret = config.ExternalLogin.Facebook.AppSecret;
            });
        }

        if (!string.IsNullOrEmpty(config.ExternalLogin.Microsoft.ClientId))
        {
            authBuilder.AddMicrosoftAccount(options =>
            {
                options.ClientId = config.ExternalLogin.Microsoft.ClientId;
                options.ClientSecret = config.ExternalLogin.Microsoft.ClientSecret;
            });
        }

        if (!string.IsNullOrEmpty(config.ExternalLogin.Github.ClientId))
        {
            authBuilder.AddGitHub(options =>
            {
                options.ClientId = config.ExternalLogin.Github.ClientId;
                options.ClientSecret = config.ExternalLogin.Github.ClientSecret;
                options.Scope.Add("read:user");
                options.Scope.Add("user:email");
            });
        }

        authBuilder.AddScheme<UserTokenOptions, UserTokenAuthHandler>("UserToken", null);

        services.AddAuthorization(options =>
        {
            options.AddPolicy(AuthConstants.Policies.AuthenticatedApi, policy =>
            {
                policy.AddAuthenticationSchemes(
                    "UserToken",
                    IdentityConstants.ApplicationScheme,
                    "OpenIddict.Validation.AspNetCore");
                policy.RequireAuthenticatedUser();
            });

            options.AddPolicy(AuthConstants.Policies.AdminUserApi, policy =>
            {
                policy.AddAuthenticationSchemes(
                    "UserToken",
                    IdentityConstants.ApplicationScheme,
                    "OpenIddict.Validation.AspNetCore");
                policy.RequireAuthenticatedUser();
                policy.AddRequirements(new UserGroupRequirement(UserGroupRequirementLevel.AdminOrMax));
            });

            options.AddPolicy(AuthConstants.Policies.MaxApi, policy =>
            {
                policy.AddAuthenticationSchemes(
                    "UserToken",
                    IdentityConstants.ApplicationScheme,
                    "OpenIddict.Validation.AspNetCore");
                policy.RequireAuthenticatedUser();
                policy.AddRequirements(new UserGroupRequirement(UserGroupRequirementLevel.Max));
            });
        });

        services.AddScoped<IAuthorizationHandler, UserGroupAuthorizationHandler>();

        services.AddScoped<ILoginRateLimitService, LoginRateLimitService>();
        services.AddScoped<IEmailVerificationCodeService, EmailVerificationCodeService>();
        services.AddScoped<CliCommandContext>();
        services.AddScoped<IAuthorizationMiddlewareResultHandler, AdminAuthorizationMiddlewareResultHandler>();
        return services;
    }




    public static IServiceCollection AddSharedFeature(this IServiceCollection services, MainConfig config)
    {
        services.AddSingleton<IConnectionMultiplexer>(sp =>
        {
            var cfg = config.Redis;
            var options = ConfigurationOptions.Parse($"{cfg.Host}:{cfg.Port},defaultDatabase={cfg.Database},connectTimeout={cfg.ConnectTimeoutMs}");
            if (!string.IsNullOrEmpty(cfg.Password))
                options.Password = cfg.Password;
            return ConnectionMultiplexer.Connect(options);
        });

        services.AddSingleton<IRateLimitCacheService, RateLimitCacheService>();
        services.AddSingleton<IRedisStateCache, RedisStateCache>();
        services.AddSingleton<IpRateLimitService>();
        services.AddSingleton<IpResolutionService>();
        services.AddScoped<IEmailSender<User>, EmailSender>();
        services.AddScoped<IUserAccessRevoker, UserAccessRevoker>();
        return services;
    }




    public static IServiceCollection AddAuditFeature(this IServiceCollection services, bool hosted = true)
    {
        services.AddSingleton<IAuditService>(sp => new AuditService(
            sp.GetRequiredService<IServiceScopeFactory>(),
            sp.GetRequiredService<ILogger<AuditService>>(),
            background: hosted));
        if (hosted)
            services.AddHostedService(sp => (AuditService)sp.GetRequiredService<IAuditService>());
        return services;
    }




    public static IServiceCollection AddClientsFeature(this IServiceCollection services)
    {
        services.AddScoped<IClientService, ClientService>();
        return services;
    }




    public static IServiceCollection AddUserTokensFeature(this IServiceCollection services)
    {
        services.AddScoped<IUserTokenService, UserTokenService>();
        return services;
    }




    public static IServiceCollection AddConfirmationFeature(this IServiceCollection services)
    {
        services.AddHttpContextAccessor();
        services.AddScoped<IConfirmationRateLimitService, ConfirmationRateLimitService>();
        services.AddScoped<ConfirmationGuard>();
        return services;
    }




    public static IServiceCollection AddRegistrationFeature(this IServiceCollection services)
    {
        services.AddScoped<IInviteCodeService, InviteCodeService>();
        services.AddScoped<IEmailVerificationBlockService, EmailVerificationBlockService>();
        services.AddSingleton<RegistrationSessionService>();
        return services;
    }




    public static IServiceCollection AddAdminFeature(this IServiceCollection services)
    {
        services.AddScoped<IAdminRateLimitService, AdminRateLimitService>();
        return services;
    }




    public static IServiceCollection AddBackupFeature(this IServiceCollection services, MainConfig config)
    {
        services.AddSingleton(new BackupService(config));
        return services;
    }




    public static IServiceCollection AddApiFeature(this IServiceCollection services, MainConfig config)
    {
        if (config.Cors.Enabled)
        {
            services.AddCors(options =>
            {
                options.AddPolicy("DefaultCors", policy =>
                {
                    policy.WithOrigins(config.Cors.AllowedOrigins)
                          .WithMethods(config.Cors.AllowedMethods)
                          .WithHeaders(config.Cors.AllowedHeaders)
                          .AllowCredentials();
                });
            });
        }

        services.Configure<Microsoft.AspNetCore.Builder.ForwardedHeadersOptions>(options =>
        {
            if (!config.IpResolution.ForwardedHeadersEnabled)
            {
                options.ForwardedHeaders = Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.None;
                return;
            }

            options.ForwardedHeaders = Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.XForwardedFor
                                      | Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.XForwardedProto
                                      | Microsoft.AspNetCore.HttpOverrides.ForwardedHeaders.XForwardedHost;

            foreach (var proxy in config.IpResolution.TrustedProxies)
            {
                if (IPAddress.TryParse(proxy, out var ip))
                {
                    options.KnownProxies.Add(ip);
                }
                else
                {
                    Console.Error.WriteLine($"{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  Pylaios       [IpResolution].TrustedProxies 忽略无效 IP: {proxy}");
                }
            }

            foreach (var cidr in config.IpResolution.TrustedNetworks)
            {
                var parts = cidr.Split('/');
                if (parts.Length != 2 || !IPAddress.TryParse(parts[0], out var networkIp))
                {
                    Console.Error.WriteLine($"{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  Pylaios       [IpResolution].TrustedNetworks 忽略无效 CIDR: {cidr}");
                    continue;
                }
                if (!int.TryParse(parts[1], out var prefixLength))
                {
                    Console.Error.WriteLine($"{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  Pylaios       [IpResolution].TrustedNetworks 忽略无效 CIDR: {cidr}");
                    continue;
                }
                options.KnownIPNetworks.Add(new System.Net.IPNetwork(networkIp, prefixLength));
            }
        });

        services.AddControllers();
        services.AddOpenApiDocument(settings =>
        {
            settings.Title = "Pylaios Auth Server";
            settings.Version = "v1";
        });
        return services;
    }




    private static void LoadEncryptionCertificate(
        OpenIddictServerBuilder options, MainConfig config, IWebHostEnvironment env)
    {
        if (!env.IsDevelopment())
        {
            var encryption = config.OpenIddict.Certificates.Encryption;
            if (!string.IsNullOrEmpty(encryption.Path))
            {
                options.AddEncryptionCertificate(CertificateLoader.LoadPkcs12(encryption.Path, encryption.Password));
            }
            else
            {
                options.AddEphemeralEncryptionKey();
            }
        }
        else
        {
            if (config.OpenIddict.AccessToken.DisableEncryption)
                options.DisableAccessTokenEncryption();
            else
                options.AddDevelopmentEncryptionCertificate();
        }
    }
}

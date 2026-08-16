using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;

namespace Pylaios.Shared;





public static class CookieSecurity
{
    public static CookieSecurePolicy GetPolicy(IWebHostEnvironment env, MainConfig config)
        => env.IsDevelopment()
            ? CookieSecurePolicy.SameAsRequest
            : Enum.Parse<CookieSecurePolicy>(config.Cookie.SecurePolicy);

    public static bool IsSecure(IWebHostEnvironment env, MainConfig config, HttpContext context)
        => GetPolicy(env, config) switch
        {
            CookieSecurePolicy.Always => true,
            _ => context.Request.IsHttps
        };
}

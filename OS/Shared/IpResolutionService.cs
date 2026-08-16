using Microsoft.AspNetCore.Http;

namespace Pylaios.Shared;




public class IpResolutionService
{
    private readonly IpResolutionConfig _config;
    private readonly HashSet<string> _trustedProxies;
    private readonly HashSet<string> _whitelist;

    public IpResolutionService(MainConfig config)
    {
        _config = config.IpResolution;
        _trustedProxies = new HashSet<string>(_config.TrustedProxies, StringComparer.OrdinalIgnoreCase);
        _whitelist = new HashSet<string>(_config.IpWhitelist, StringComparer.OrdinalIgnoreCase);
    }

    public string GetClientIp(HttpContext context)
    {
        var remoteIp = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";


        if (_trustedProxies.Count > 0 && _trustedProxies.Contains(remoteIp))
        {
            foreach (var headerName in _config.TrustedHeaders)
            {
                var headerValue = context.Request.Headers[headerName].FirstOrDefault();
                if (!string.IsNullOrEmpty(headerValue))
                {
                    var ips = headerValue.Split(',', StringSplitOptions.RemoveEmptyEntries);
                    for (var i = ips.Length - 1; i >= 0; i--)
                    {
                        var candidate = ips[i].Trim();
                        if (candidate.Length == 0)
                            continue;
                        if (!_trustedProxies.Contains(candidate))
                            return candidate;
                    }
                    if (ips.Length > 0 && !string.IsNullOrEmpty(ips[^1].Trim()))
                        return ips[^1].Trim();
                }
            }
        }

        return remoteIp;
    }

    public bool IsWhitelisted(string ip)
    {
        return _whitelist.Count > 0 && _whitelist.Contains(ip);
    }
}

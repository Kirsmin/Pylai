using Microsoft.EntityFrameworkCore;
using System.Net;
using System.Xml;
using System.Xml.Linq;
using OpenIddict.Abstractions;
using static OpenIddict.Abstractions.OpenIddictConstants;
using Pylaios.Features.Database;

namespace Pylaios.Features.Clients;

public interface IClientService
{
    Task<ClientResponse?> GetByIdAsync(string id, CancellationToken ct = default);
    Task<ClientResponse?> GetByClientIdAsync(string clientId, CancellationToken ct = default);
    Task<ClientListResponse> ListAsync(int skip = 0, int take = 20, CancellationToken ct = default);
    Task<ClientResponse> CreateAsync(ClientCreateRequest request, CancellationToken ct = default);
    Task<ClientResponse?> UpdateAsync(string id, ClientUpdateRequest request, CancellationToken ct = default);
    Task<bool> DeleteAsync(string id, CancellationToken ct = default);
    Task<bool> SetDisabledAsync(string id, bool disabled, CancellationToken ct = default);
    Task<bool> UploadLogoAsync(string id, Microsoft.AspNetCore.Http.IFormFile file, CancellationToken ct = default);
    Task<bool> UploadLogoBytesAsync(string id, byte[] bytes, CancellationToken ct = default);
    Task<bool> DeleteLogoAsync(string id, CancellationToken ct = default);
    Task<(byte[]? bytes, string? contentType)?> GetLogoAsync(string id, CancellationToken ct = default);
}

public class ClientService : IClientService
{
    private readonly IOpenIddictApplicationManager _manager;
    private readonly ApplicationDbContext _context;

    private const long MaxLogoSize = 2 * 1024 * 1024;
    private const string SvgContentType = "image/svg+xml";
    private static readonly HashSet<string> AllowedLogoTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        SvgContentType, "image/png"
    };

    private static readonly HashSet<string> SafeSvgElements = new(StringComparer.OrdinalIgnoreCase)
    {
        "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
        "text", "textPath", "tspan", "defs", "linearGradient", "radialGradient", "stop",
        "pattern", "clipPath", "mask", "use", "image", "marker", "symbol", "title", "desc"
    };

    private static readonly HashSet<string> SafeSvgAttributes = new(StringComparer.OrdinalIgnoreCase)
    {
        "d", "x", "y", "cx", "cy", "r", "rx", "ry", "width", "height", "points",
        "viewBox", "transform", "preserveAspectRatio",
        "fill", "fill-rule", "fill-opacity",
        "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit", "stroke-opacity",
        "opacity", "clip-rule",
        "font-size", "font-family", "font-weight", "font-style", "text-anchor",
        "letter-spacing", "word-spacing", "textLength", "lengthAdjust",
        "dominant-baseline", "text-decoration", "startOffset",
        "stop-color", "stop-opacity", "offset",
        "gradientUnits", "gradientTransform", "spreadMethod",
        "patternUnits", "patternTransform", "patternContentUnits",
        "clipPathUnits", "maskUnits", "maskContentUnits",
        "refX", "refY", "markerWidth", "markerHeight", "markerUnits", "orient",
        "id", "version", "href"
    };


    private const string ScopePrefix = "scp:";
    private const string GrantTypePrefix = "gt:";

    private static string ScopePermission(string scope) => ScopePrefix + scope;
    private static string GrantTypePermission(string grantType) => GrantTypePrefix + grantType;

    private static readonly HashSet<string> RequiredPermissions = new()
    {
        Permissions.Endpoints.Authorization,
        Permissions.Endpoints.Token,
        Permissions.Endpoints.EndSession,
        Permissions.ResponseTypes.Code
    };

    public ClientService(IOpenIddictApplicationManager manager, ApplicationDbContext context)
    {
        _manager = manager;
        _context = context;
    }

    public async Task<ClientResponse?> GetByIdAsync(string id, CancellationToken ct = default)
    {
        var app = await _manager.FindByIdAsync(id, ct);
        if (app is null) return null;
        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        return await MapAsync(app, meta, ct);
    }

    public async Task<ClientResponse?> GetByClientIdAsync(string clientId, CancellationToken ct = default)
    {
        var app = await _manager.FindByClientIdAsync(clientId, ct);
        if (app is null) return null;
        var appId = await _manager.GetIdAsync(app, ct);
        var meta = appId is null ? null : await _context.OAuthClientMetadata.FindAsync([appId], ct);
        return await MapAsync(app, meta, ct);
    }

    public async Task<ClientListResponse> ListAsync(int skip = 0, int take = 20, CancellationToken ct = default)
    {
        skip = Math.Max(0, skip);
        take = Math.Clamp(take, 1, 100);

        var total = await _manager.CountAsync(ct);
        var page = new List<object>(take);
        await foreach (var app in _manager.ListAsync(take, skip, ct))
        {
            page.Add(app);
        }

        var appIds = new List<string>();
        foreach (var app in page)
        {
            appIds.Add(await _manager.GetIdAsync(app, ct) ?? string.Empty);
        }

        var metas = await _context.OAuthClientMetadata
            .Where(m => appIds.Contains(m.ApplicationId))
            .ToDictionaryAsync(m => m.ApplicationId, ct);

        var items = new List<ClientResponse>();
        foreach (var app in page)
        {
            var id = await _manager.GetIdAsync(app, ct) ?? string.Empty;
            metas.TryGetValue(id, out var meta);
            items.Add(await MapAsync(app, meta, ct));
        }

        return new ClientListResponse
        {
            Items = items.OrderBy(i => i.ClientId, StringComparer.Ordinal).ToList(),
            Total = total > int.MaxValue ? int.MaxValue : (int)total
        };
    }

    public async Task<ClientResponse> CreateAsync(ClientCreateRequest r, CancellationToken ct = default)
    {
        using var transaction = await _context.Database.BeginTransactionAsync(ct);

        var descriptor = new OpenIddictApplicationDescriptor
        {
            ClientId = r.ClientId,
            ClientSecret = r.ClientSecret,
            DisplayName = r.DisplayName,
            ClientType = string.Equals(r.Type, ClientTypes.Public, StringComparison.OrdinalIgnoreCase)
                ? ClientTypes.Public
                : ClientTypes.Confidential
        };

        foreach (var uri in r.RedirectUris)
            descriptor.RedirectUris.Add(ParseUri(uri));
        foreach (var uri in r.PostLogoutRedirectUris)
            descriptor.PostLogoutRedirectUris.Add(ParseUri(uri));

        var permissions = new HashSet<string>(RequiredPermissions);
        permissions.UnionWith(r.Permissions);
        descriptor.Permissions.UnionWith(permissions);

        foreach (var scope in r.Scopes)
            descriptor.Permissions.Add(ScopePermission(scope));

        foreach (var gt in r.GrantTypes)
            descriptor.Permissions.Add(GrantTypePermission(gt));

        await _manager.CreateAsync(descriptor, ct);
        var app = await _manager.FindByClientIdAsync(r.ClientId, ct);
        var appId = await _manager.GetIdAsync(app!, ct) ?? string.Empty;

        var meta = new OAuthClientMetadata
        {
            ApplicationId = appId,
            Description = r.Description,
            HomepageUrl = r.HomepageUrl,
            IsFajorCertified = r.IsFajorCertified,
            IsDisabled = false
        };
        _context.OAuthClientMetadata.Add(meta);
        await _context.SaveChangesAsync(ct);

        await transaction.CommitAsync(ct);

        return await MapAsync(app!, meta, ct);
    }

    public async Task<ClientResponse?> UpdateAsync(string id, ClientUpdateRequest r, CancellationToken ct = default)
    {
        var app = await _manager.FindByIdAsync(id, ct);
        if (app is null) return null;

        await using var transaction = await _context.Database.BeginTransactionAsync(ct);
        var descriptor = new OpenIddictApplicationDescriptor();
        await _manager.PopulateAsync(descriptor, app, ct);

        if (r.DisplayName is not null)
            descriptor.DisplayName = r.DisplayName;
        if (r.ClientSecret is { Length: > 0 })
            descriptor.ClientSecret = r.ClientSecret;
        if (r.RedirectUris is not null)
        {
            descriptor.RedirectUris.Clear();
            foreach (var uri in r.RedirectUris)
                descriptor.RedirectUris.Add(ParseUri(uri));
        }
        if (r.PostLogoutRedirectUris is not null)
        {
            descriptor.PostLogoutRedirectUris.Clear();
            foreach (var uri in r.PostLogoutRedirectUris)
                descriptor.PostLogoutRedirectUris.Add(ParseUri(uri));
        }

        if (r.Scopes is not null)
        {
            descriptor.Permissions.RemoveWhere(p => p.StartsWith(ScopePrefix));
            foreach (var scope in r.Scopes)
                descriptor.Permissions.Add(ScopePermission(scope));
        }

        if (r.GrantTypes is not null)
        {
            descriptor.Permissions.RemoveWhere(p => p.StartsWith(GrantTypePrefix));
            foreach (var gt in r.GrantTypes)
                descriptor.Permissions.Add(GrantTypePermission(gt));
        }

        if (r.Permissions is not null)
        {
            descriptor.Permissions.RemoveWhere(p => !p.StartsWith(ScopePrefix) && !p.StartsWith(GrantTypePrefix));
            descriptor.Permissions.UnionWith(RequiredPermissions);
            descriptor.Permissions.UnionWith(r.Permissions);
        }

        await _manager.UpdateAsync(app, descriptor, ct);

        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (r.Description is not null || r.HomepageUrl is not null || r.IsFajorCertified.HasValue)
        {
            if (meta is null)
            {
                meta = new OAuthClientMetadata { ApplicationId = id };
                _context.OAuthClientMetadata.Add(meta);
            }
            if (r.Description is not null)
                meta.Description = r.Description;
            if (r.HomepageUrl is not null)
                meta.HomepageUrl = r.HomepageUrl;
            if (r.IsFajorCertified.HasValue)
                meta.IsFajorCertified = r.IsFajorCertified.Value;
        }

        await _context.SaveChangesAsync(ct);
        await transaction.CommitAsync(ct);

        var updated = await _manager.FindByIdAsync(id, ct);
        meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        return await MapAsync(updated!, meta, ct);
    }

    public async Task<bool> DeleteAsync(string id, CancellationToken ct = default)
    {
        var app = await _manager.FindByIdAsync(id, ct);
        if (app is null) return false;

        using var transaction = await _context.Database.BeginTransactionAsync(ct);

        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (meta is not null)
        {
            _context.OAuthClientMetadata.Remove(meta);
        }

        await _manager.DeleteAsync(app, ct);
        await _context.SaveChangesAsync(ct);

        await transaction.CommitAsync(ct);
        return true;
    }

    public async Task<bool> SetDisabledAsync(string id, bool disabled, CancellationToken ct = default)
    {
        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (meta is null)
        {
            var app = await _manager.FindByIdAsync(id, ct);
            if (app is null) return false;

            meta = new OAuthClientMetadata
            {
                ApplicationId = id,
                IsDisabled = disabled
            };
            _context.OAuthClientMetadata.Add(meta);
        }
        else
        {
            meta.IsDisabled = disabled;
        }

        await _context.SaveChangesAsync(ct);
        return true;
    }

    public async Task<bool> UploadLogoAsync(string id, Microsoft.AspNetCore.Http.IFormFile file, CancellationToken ct = default)
    {
        if (file.Length == 0)
            throw new InvalidOperationException("Logo 文件为空。");
        if (file.Length > MaxLogoSize)
            throw new InvalidOperationException($"Logo 文件超过最大限制 {MaxLogoSize / 1024 / 1024}MB。");
        if (!AllowedLogoTypes.Contains(file.ContentType))
            throw new InvalidOperationException($"不支持的 Logo 格式: {file.ContentType}，仅支持 image/svg+xml 和 image/png。");

        using var ms = new MemoryStream();
        await file.CopyToAsync(ms, ct);
        return await UploadLogoBytesAsync(id, ms.ToArray(), ct);
    }


    public async Task<bool> UploadLogoBytesAsync(string id, byte[] bytes, CancellationToken ct = default)
    {
        if (bytes.Length == 0)
            throw new InvalidOperationException("Logo 文件为空。");
        if (bytes.Length > MaxLogoSize)
            throw new InvalidOperationException($"Logo 文件超过最大限制 {MaxLogoSize / 1024 / 1024}MB。");

        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (meta is null)
        {
            var app = await _manager.FindByIdAsync(id, ct);
            if (app is null) return false;

            meta = new OAuthClientMetadata { ApplicationId = id };
            _context.OAuthClientMetadata.Add(meta);
        }


        var actualType = DetectImageType(bytes);
        if (actualType is null)
            throw new InvalidOperationException("Logo 文件内容不是有效的 SVG 或 PNG 图片。");

        if (actualType == SvgContentType)
            bytes = SanitizeSvg(bytes);

        meta.Logo = bytes;
        meta.LogoContentType = actualType;

        await _context.SaveChangesAsync(ct);
        return true;
    }

    private static readonly System.Text.RegularExpressions.Regex UrlRefRegex = new(
        @"url\(\s*['""]?([^'""\)]+)['""]?\s*\)",
        System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.Compiled);

    private static byte[] SanitizeSvg(byte[] bytes)
    {
        try
        {
            var settings = new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                IgnoreComments = true,
                IgnoreProcessingInstructions = true,
                MaxCharactersInDocument = MaxLogoSize
            };

            using var stream = new MemoryStream(bytes);
            using var reader = XmlReader.Create(stream, settings);
            var doc = XDocument.Load(reader);

            var root = doc.Root;
            if (root is null || !root.Name.LocalName.Equals("svg", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Logo SVG 根元素必须是 <svg>。");

            foreach (var element in root.DescendantsAndSelf())
            {
                if (!SafeSvgElements.Contains(element.Name.LocalName))
                    throw new InvalidOperationException($"Logo SVG 包含不允许的元素 <{element.Name.LocalName}>。");

                foreach (var attr in element.Attributes())
                {
                    if (attr.IsNamespaceDeclaration)
                        continue;
                    if (!SafeSvgAttributes.Contains(attr.Name.LocalName))
                        throw new InvalidOperationException($"Logo SVG 包含不允许的属性 {attr.Name.LocalName}。");
                    if (!IsSafeSvgAttributeValue(attr))
                        throw new InvalidOperationException($"Logo SVG 属性 {attr.Name.LocalName} 包含不允许的值。");
                }
            }

            using var output = new MemoryStream();
            using (var writer = XmlWriter.Create(output, new XmlWriterSettings
            {
                Encoding = new System.Text.UTF8Encoding(false),
                Indent = false,
                OmitXmlDeclaration = true
            }))
            {
                doc.Save(writer);
            }
            return output.ToArray();
        }
        catch (InvalidOperationException)
        {
            throw;
        }
        catch (XmlException ex)
        {
            throw new InvalidOperationException($"Logo SVG 内容解析失败，已拒绝: {ex.Message}");
        }
    }

    private static bool IsSafeSvgAttributeValue(XAttribute attr)
    {
        var value = attr.Value.Trim();

        if (attr.Name.LocalName.Equals("href", StringComparison.OrdinalIgnoreCase))
        {
            return value.StartsWith('#')
                || value.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase);
        }

        foreach (System.Text.RegularExpressions.Match match in UrlRefRegex.Matches(value))
        {
            var target = match.Groups[1].Value.Trim();
            if (!target.StartsWith('#') && !target.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase))
                return false;
        }

        return true;
    }

    private static string? DetectImageType(byte[] bytes)
    {

        if (bytes.Length >= 4 && bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4E && bytes[3] == 0x47)
            return "image/png";


        if (bytes.Length > 0 && bytes[0] == (byte)'<')
        {
            var head = System.Text.Encoding.UTF8.GetString(bytes, 0, Math.Min(512, bytes.Length));
            if (head.Contains("<svg", StringComparison.OrdinalIgnoreCase))
                return SvgContentType;
        }

        return null;
    }

    public async Task<bool> DeleteLogoAsync(string id, CancellationToken ct = default)
    {
        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (meta is null) return false;
        if (meta.Logo is null) return false;

        meta.Logo = null;
        meta.LogoContentType = null;
        await _context.SaveChangesAsync(ct);
        return true;
    }

    public async Task<(byte[]? bytes, string? contentType)?> GetLogoAsync(string id, CancellationToken ct = default)
    {
        var meta = await _context.OAuthClientMetadata.FindAsync([id], ct);
        if (meta?.Logo is null) return null;
        return (meta.Logo, meta.LogoContentType);
    }

    private static Uri ParseUri(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
            || (uri.Scheme != "https" && !IsLoopbackUri(uri))
            || string.IsNullOrEmpty(uri.Host))
        {
            throw new InvalidOperationException($"非法 URI: {value}");
        }

        return uri;
    }

    private static bool IsLoopbackUri(Uri uri)
        => uri.Scheme == "http"
            && (uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
                || IPAddress.TryParse(uri.Host, out var ip) && IPAddress.IsLoopback(ip));

    private async Task<ClientResponse> MapAsync(object app, OAuthClientMetadata? meta, CancellationToken ct)
    {
        var permissions = await _manager.GetPermissionsAsync(app, ct);
        var permList = permissions.ToList();

        var scopes = permList
            .Where(p => p.StartsWith(ScopePrefix))
            .Select(p => p[ScopePrefix.Length..])
            .ToList();

        var grantTypes = permList
            .Where(p => p.StartsWith(GrantTypePrefix))
            .Select(p => p[GrantTypePrefix.Length..])
            .ToList();

        var otherPermissions = permList
            .Where(p => !p.StartsWith(ScopePrefix) && !p.StartsWith(GrantTypePrefix))
            .ToList();

        return new ClientResponse
        {
            Id = await _manager.GetIdAsync(app, ct) ?? string.Empty,
            ClientId = await _manager.GetClientIdAsync(app, ct) ?? string.Empty,
            DisplayName = await _manager.GetDisplayNameAsync(app, ct) ?? string.Empty,
            Description = meta?.Description,
            HomepageUrl = meta?.HomepageUrl,
            IsFajorCertified = meta?.IsFajorCertified ?? false,
            IsDisabled = meta?.IsDisabled ?? false,
            HasLogo = meta?.Logo is not null && meta.Logo.Length > 0,
            Type = await _manager.GetClientTypeAsync(app, ct) ?? ClientTypes.Confidential,
            Scopes = scopes,
            RedirectUris = (await _manager.GetRedirectUrisAsync(app, ct)).ToList(),
            PostLogoutRedirectUris = (await _manager.GetPostLogoutRedirectUrisAsync(app, ct)).ToList(),
            GrantTypes = grantTypes,
            Permissions = otherPermissions
        };
    }
}

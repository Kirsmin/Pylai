using Cocona;

namespace Pylaios.Features.Clients;





public sealed class ClientCommands
{
    private readonly CliCommandContext _ctx;

    public ClientCommands(CliCommandContext ctx)
    {
        _ctx = ctx;
    }

    [Command("list", Description = "列出所有客户端（分页）")]
    public async Task<int> ListAsync([Option("skip")] int? skip = null, [Option("take")] int? take = null)
    {
        var result = await _ctx.Clients.ListAsync(skip ?? 0, take ?? 20);
        return await CliHelpers.OkAsync(new { success = true, items = result.Items, total = result.Total });
    }

    [Command("show", Description = "客户端详情")]
    public async Task<int> ShowAsync([Argument("id|clientId")] string id)
    {
        var client = await FindClientAsync(id);
        if (client is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

        return await CliHelpers.OkAsync(new { success = true, client });
    }

    [Command("create", Description = "创建客户端（Secret 仅从 stdin 读取）")]
    public async Task<int> CreateAsync(
        [Argument("clientId")] string clientId,
        [Option("name")] string? name = null,
        [Option("secret-stdin", Description = "从 stdin 读取 client_secret")] bool secretStdin = false,
        [Option("type")] string? type = null,
        [Option("scopes")] string? scopes = null,
        [Option("grant-types")] string? grantTypes = null,
        [Option("redirect-uris")] string? redirectUris = null,
        [Option("post-logout-uris")] string? postLogoutUris = null,
        [Option("description")] string? description = null,
        [Option("homepage")] string? homepage = null,
        [Option("fajor")] bool fajor = false,
        [Option("permissions")] string? permissions = null)
    {
        var secret = secretStdin ? (CliHelpers.ReadSecretFromStdin() ?? "") : "";
        var request = new ClientCreateRequest
        {
            ClientId = clientId,
            DisplayName = name ?? "",
            ClientSecret = secret,
            Description = description,
            HomepageUrl = homepage,
            IsFajorCertified = fajor,
            Type = type ?? "Confidential",
            Scopes = Csv(scopes) ?? ["openid", "profile:basic", "profile:mail", "profile:role", "offline_access"],
            GrantTypes = Csv(grantTypes) ?? ["authorization_code", "refresh_token"],
            RedirectUris = Csv(redirectUris) ?? [],
            PostLogoutRedirectUris = Csv(postLogoutUris) ?? [],
            Permissions = Csv(permissions) ?? []
        };

        var client = await _ctx.Clients.CreateAsync(request);
        await CliHelpers.LogAsync(_ctx, "cli:client create", true,
            $"CLI created client {client.ClientId} (id:{client.Id})",
            eventType: AuthConstants.EventTypes.ClientCreated);

        return await CliHelpers.OkAsync(new { success = true, client });
    }

    [Command("update", Description = "更新客户端（提供即覆盖；--fajor/--no-fajor 三元）")]
    public async Task<int> UpdateAsync(
        [Argument("id|clientId")] string id,
        [Option("name")] string? name = null,
        [Option("secret-stdin", Description = "从 stdin 读取新 client_secret")] bool secretStdin = false,
        [Option("scopes")] string? scopes = null,
        [Option("grant-types")] string? grantTypes = null,
        [Option("redirect-uris")] string? redirectUris = null,
        [Option("post-logout-uris")] string? postLogoutUris = null,
        [Option("description")] string? description = null,
        [Option("homepage")] string? homepage = null,
        [Option("fajor")] bool? fajor = null,
        [Option("no-fajor")] bool? noFajor = null,
        [Option("permissions")] string? permissions = null)
    {
        var client = await FindClientAsync(id);
        if (client is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

        var request = new ClientUpdateRequest
        {
            DisplayName = name,
            ClientSecret = secretStdin ? (CliHelpers.ReadSecretFromStdin() ?? "") : null,
            Description = description,
            HomepageUrl = homepage,
            IsFajorCertified = fajor is true ? true : noFajor is true ? false : null,
            Scopes = Csv(scopes),
            GrantTypes = Csv(grantTypes),
            RedirectUris = Csv(redirectUris),
            PostLogoutRedirectUris = Csv(postLogoutUris),
            Permissions = Csv(permissions)
        };

        var updated = await _ctx.Clients.UpdateAsync(client.Id, request);
        if (updated is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {client.Id}");
        await CliHelpers.LogAsync(_ctx, "cli:client update", true,
            $"CLI updated client {updated.ClientId} (id:{updated.Id})",
            eventType: AuthConstants.EventTypes.ClientUpdated);

        return await CliHelpers.OkAsync(new { success = true, client = updated });
    }

    [Command("delete", Description = "删除客户端")]
    public async Task<int> DeleteAsync([Argument("id|clientId")] string id)
    {
        var client = await FindClientAsync(id);
        if (client is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

        await _ctx.Clients.DeleteAsync(client.Id);
        await CliHelpers.LogAsync(_ctx, "cli:client delete", true,
            $"CLI deleted client {client.ClientId} (id:{client.Id})",
            eventType: AuthConstants.EventTypes.ClientDeleted);

        return await CliHelpers.OkAsync(new { success = true, message = $"客户端 {client.ClientId} 已删除。" });
    }

    [Command("disable", Description = "禁用客户端（立即生效）")]
    public async Task<int> DisableAsync([Argument("id|clientId")] string id)
        => await SetDisabledAsync(id, true);

    [Command("enable", Description = "启用客户端")]
    public async Task<int> EnableAsync([Argument("id|clientId")] string id)
        => await SetDisabledAsync(id, false);

    private async Task<int> SetDisabledAsync(string id, bool disabled)
    {
        var client = await FindClientAsync(id);
        if (client is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

        await _ctx.Clients.SetDisabledAsync(client.Id, disabled);
        await CliHelpers.LogAsync(_ctx, "cli:client " + (disabled ? "disable" : "enable"), true,
            $"CLI {(disabled ? "disabled" : "enabled")} client {client.ClientId} (id:{client.Id})",
            eventType: disabled ? AuthConstants.EventTypes.ClientDisabled : AuthConstants.EventTypes.ClientEnabled);

        return await CliHelpers.OkAsync(new { success = true, message = $"客户端 {client.ClientId} 已{(disabled ? "禁用" : "启用")}。" });
    }

    [Command("logo", Description = "上传客户端 Logo（--delete 删除）")]
    public async Task<int> LogoAsync(
        [Argument("id|clientId")] string id,
        [Argument("file", Description = "Logo 文件路径（--delete 时省略）")] string? file = null,
        [Option("delete", Description = "删除 Logo")] bool delete = false)
    {
        if (delete)
        {
            var client = await FindClientAsync(id);
            if (client is null)
                return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

            var deleted = await _ctx.Clients.DeleteLogoAsync(client.Id);
            if (!deleted)
                return await CliHelpers.ErrorAsync("客户端不存在或没有 Logo。");

            await CliHelpers.LogAsync(_ctx, "cli:client logo delete", true,
                $"CLI deleted logo of client {client.ClientId} (id:{client.Id})",
                eventType: AuthConstants.EventTypes.ClientLogoDeleted);

            return await CliHelpers.OkAsync(new { success = true, message = $"客户端 {client.ClientId} 的 Logo 已删除。" });
        }

        if (string.IsNullOrEmpty(file))
            return await CliHelpers.ErrorAsync("Usage: client logo <id|clientId> <file>  |  client logo --delete <id|clientId>");

        var target = await FindClientAsync(id);
        if (target is null)
            return await CliHelpers.ErrorAsync($"客户端不存在: {id}");

        if (!File.Exists(file))
            return await CliHelpers.ErrorAsync($"Logo 文件不存在: {file}");

        var bytes = await File.ReadAllBytesAsync(file);
        try
        {
            await _ctx.Clients.UploadLogoBytesAsync(target.Id, bytes);
        }
        catch (InvalidOperationException ex)
        {
            return await CliHelpers.ErrorAsync(ex.Message);
        }

        await CliHelpers.LogAsync(_ctx, "cli:client logo upload", true,
            $"CLI uploaded logo of client {target.ClientId} (id:{target.Id})",
            eventType: AuthConstants.EventTypes.ClientLogoUpdated);

        return await CliHelpers.OkAsync(new { success = true, message = $"客户端 {target.ClientId} 的 Logo 已上传。" });
    }


    private async Task<ClientResponse?> FindClientAsync(string idOrClientId)
        => await _ctx.Clients.GetByIdAsync(idOrClientId)
           ?? await _ctx.Clients.GetByClientIdAsync(idOrClientId);

    private static List<string>? Csv(string? value)
        => value is null
            ? null
            : value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
}

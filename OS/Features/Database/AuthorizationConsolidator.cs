using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.EntityFrameworkCore.Models;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.Database;

public sealed class ConsolidationResult
{
    public required string AuthorizationId { get; init; }
    public List<string> PreviousScopes { get; init; } = [];
    public List<string> GrantedScopes { get; init; } = [];
    public List<string> ConsolidatedIds { get; init; } = [];
    public int TokensReassigned { get; init; }
}

public sealed class ConsolidateAllResult
{
    public int GroupsProcessed { get; set; }
    public int AuthorizationsConsolidated { get; set; }
    public int TokensReassigned { get; set; }
}

/// <summary>
/// 授权模型：一个用户对一个客户端只保留一条活跃永久授权，Scope 为可更新的属性（merge 不 replace）。
/// web（consent 流程）与 CLI（consolidate-authorizations）共用。
/// </summary>
public static class AuthorizationConsolidator
{
    public static List<string> NormalizeScopes(IEnumerable<string> scopes) =>
        scopes.Where(s => !string.IsNullOrWhiteSpace(s))
              .Distinct(StringComparer.Ordinal)
              .OrderBy(s => s, StringComparer.Ordinal)
              .ToList();

    public static async Task<List<object>> FindActiveAsync(
        IOpenIddictAuthorizationManager manager, string subject, string clientId)
    {
        var found = new List<(DateTimeOffset? CreatedAt, object Authorization)>();
        await foreach (var auth in manager.FindAsync(subject, clientId, Statuses.Valid, AuthorizationTypes.Permanent, null))
            found.Add((await manager.GetCreationDateAsync(auth), auth));
        return found.OrderBy(t => t.CreatedAt ?? DateTimeOffset.MinValue).Select(t => t.Authorization).ToList();
    }

    /// <summary>
    /// 将同一用户+客户端的活跃永久授权合并为一条：主授权（最早创建）scope 取并集，
    /// 挂旧授权的 token 迁移到主授权，删除重复授权。不负责事务边界。
    /// </summary>
    public static async Task<ConsolidationResult?> ConsolidateAsync(
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictTokenManager tokenManager,
        string subject, string clientId,
        IEnumerable<string>? requestedScopes = null)
    {
        var existing = await FindActiveAsync(authorizationManager, subject, clientId);
        if (existing.Count == 0)
            return null;

        var canonical = existing[0];
        var canonicalId = await authorizationManager.GetIdAsync(canonical)
            ?? throw new InvalidOperationException("授权合并失败：主授权缺少 ID");
        var previous = NormalizeScopes(await authorizationManager.GetScopesAsync(canonical));
        var merged = NormalizeScopes(previous.Concat(requestedScopes ?? previous));

        var consolidatedIds = new List<string>();
        var tokensReassigned = 0;

        foreach (var duplicate in existing.Skip(1))
        {
            var duplicateId = await authorizationManager.GetIdAsync(duplicate)
                ?? throw new InvalidOperationException("授权合并失败：重复授权缺少 ID");
            consolidatedIds.Add(duplicateId);

            await foreach (var token in tokenManager.FindByAuthorizationIdAsync(duplicateId))
            {
                var descriptor = new OpenIddictTokenDescriptor();
                await tokenManager.PopulateAsync(descriptor, token);
                descriptor.AuthorizationId = canonicalId;
                await tokenManager.UpdateAsync(token, descriptor);
                tokensReassigned++;
            }

            await authorizationManager.DeleteAsync(duplicate);
        }

        if (!merged.SequenceEqual(previous))
        {
            var descriptor = new OpenIddictAuthorizationDescriptor();
            await authorizationManager.PopulateAsync(descriptor, canonical);
            descriptor.Scopes.UnionWith(merged);
            await authorizationManager.UpdateAsync(canonical, descriptor);
        }

        return new ConsolidationResult
        {
            AuthorizationId = canonicalId,
            PreviousScopes = previous,
            GrantedScopes = merged,
            ConsolidatedIds = consolidatedIds,
            TokensReassigned = tokensReassigned
        };
    }

    /// <summary>
    /// 全量幂等合并（CLI 用）：仅处理存在重复授权的组合，每批 batchSize 个组合，每组独立事务。
    /// </summary>
    public static async Task<ConsolidateAllResult> ConsolidateAllAsync(
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictTokenManager tokenManager,
        ApplicationDbContext db, int batchSize = 500)
    {
        var result = new ConsolidateAllResult();
        var authorizationSet = db.Set<OpenIddictEntityFrameworkCoreAuthorization>();

        while (true)
        {
            var duplicates = await authorizationSet
                .Where(a => a.Status == Statuses.Valid && a.Type == AuthorizationTypes.Permanent && a.Subject != null)
                .Select(a => new { Subject = a.Subject!, ApplicationId = EF.Property<string>(a, "ApplicationId") })
                .GroupBy(x => new { x.Subject, x.ApplicationId })
                .Where(g => g.Count() > 1)
                .Select(g => new { g.Key.Subject, g.Key.ApplicationId })
                .OrderBy(x => x.Subject).ThenBy(x => x.ApplicationId)
                .Take(batchSize)
                .ToListAsync();

            if (duplicates.Count == 0)
                break;

            foreach (var group in duplicates)
            {
                await using var tx = await db.Database.BeginTransactionAsync();
                var merged = await ConsolidateAsync(authorizationManager, tokenManager, group.Subject, group.ApplicationId);
                if (merged is not null)
                {
                    db.ConsentAuditEvents.Add(new ConsentAuditEvent
                    {
                        Subject = group.Subject,
                        ClientId = group.ApplicationId,
                        Action = ConsentAuditActions.AuthorizationConsolidated,
                        PreviousScopes = ToJson(merged.PreviousScopes),
                        GrantedScopes = ToJson(merged.GrantedScopes),
                        AuthorizationId = merged.AuthorizationId
                    });
                    result.GroupsProcessed++;
                    result.AuthorizationsConsolidated += merged.ConsolidatedIds.Count;
                    result.TokensReassigned += merged.TokensReassigned;
                    await db.SaveChangesAsync();
                }
                await tx.CommitAsync();
            }
        }

        return result;
    }

    public static string? ToJson(List<string> scopes) =>
        scopes.Count == 0 ? null : System.Text.Json.JsonSerializer.Serialize(scopes);
}

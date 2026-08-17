using System.Data;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;

namespace Pylaios.Features.Registration;

public interface IInviteCodeService
{
    Task<InviteCodeCreateResult> CreateAsync(string group, int maxRedemptions, int lifetimeHours);
    Task<InviteCodeMigrationResult> MigrateLegacyAsync();
    Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress);
    Task<InviteRedeemResult> RedeemAsync(string code, User user, string ipAddress, bool revokeExistingAccess = false);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByIpAsync(string ipAddress);
}

public sealed class InviteCodeService : IpBanServiceBase<InviteCodeFailure>, IInviteCodeService
{
    private const string Alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*+-_";
    private const int CodeLength = 10;

    private readonly InviteCodeConfig _config;
    private readonly IUserAccessRevoker _userAccessRevoker;

    public InviteCodeService(
        ApplicationDbContext context,
        MainConfig config,
        IRateLimitCacheService cache,
        IpResolutionService ipResolver,
        ILogger<InviteCodeService> logger,
        IUserAccessRevoker userAccessRevoker)
        : base(context, cache, ipResolver, logger)
    {
        _config = config.InviteCode;
        _userAccessRevoker = userAccessRevoker;
    }

    protected override string BanType => "invite";
    protected override string BanAuditType => "InviteCode";
    protected override string BanIdPrefix => "BlockInvite";

    protected override bool ShouldBan(InviteCodeFailure entity)
        => entity.FailureCount >= _config.MaxFailuresPerIp;

    protected override TimeSpan? GetBanDuration(InviteCodeFailure entity)
        => TimeSpan.FromHours(_config.BanDurationHours);

    protected override InviteCodeFailure CreateEntry(string ipAddress, DateTimeOffset now)
        => new() { IpAddress = ipAddress, FailureCount = 1, LastFailureAt = now };

    public async Task<InviteCodeCreateResult> CreateAsync(string group, int maxRedemptions, int lifetimeHours)
    {
        EnsurePepper();

        var effectiveMax = AuthConstants.Groups.Rank(group) >= AuthConstants.Groups.Rank(AuthConstants.Roles.Admin)
            ? 1
            : maxRedemptions;
        var expiresAt = DateTimeOffset.UtcNow.AddHours(lifetimeHours);

        for (var attempt = 0; attempt < 5; attempt++)
        {
            var code = GenerateCode();
            var entity = new InviteCode
            {
                Id = Guid.NewGuid(),
                CodeHash = HashCode(code),
                Prefix = code[..3],
                Group = group,
                MaxRedemptions = effectiveMax,
                Status = InviteCodeStatus.Active,
                ExpiresAt = expiresAt
            };

            _context.InviteCodes.Add(entity);
            try
            {
                await _context.SaveChangesAsync();
                return new InviteCodeCreateResult(entity, code);
            }
            catch (DbUpdateException ex) when (ex.IsUniqueViolation())
            {
                _context.Entry(entity).State = EntityState.Detached;
            }
        }

        throw new InvalidOperationException("无法生成唯一邀请码，请稍后重试。");
    }

    public async Task<InviteCodeMigrationResult> MigrateLegacyAsync()
    {
        EnsurePepper();

        var connection = _context.Database.GetDbConnection();
        if (connection.State != ConnectionState.Open)
            await connection.OpenAsync();

        var legacy = new List<(Guid Id, string Code)>();
        await using (var read = connection.CreateCommand())
        {
            read.CommandText = "SELECT \"Id\", \"Code\" FROM \"InviteCodes\"";
            try
            {
                await using var reader = await read.ExecuteReaderAsync();
                while (await reader.ReadAsync())
                    legacy.Add((reader.GetGuid(0), reader.GetString(1)));
            }
            catch (PostgresException ex) when (ex.SqlState == "42703")
            {
                return new InviteCodeMigrationResult(0, true);
            }
        }

        var placeholders = legacy.Where(x => Regex.IsMatch(x.Code, "^(NORMAL|ADMIN|MAX)-[0-9]+$", RegexOptions.IgnoreCase)).ToList();
        if (placeholders.Count > 0)
            throw new InvalidOperationException("检测到 legacy placeholder 邀请码，请先清理后重试，拒绝继续启动。");

        await using var tx = await _context.Database.BeginTransactionAsync();
        foreach (var item in legacy)
        {
            await using var update = connection.CreateCommand();
            update.Transaction = tx.GetDbTransaction();
            update.CommandText = "UPDATE \"InviteCodes\" SET \"CodeHash\" = @hash, \"Prefix\" = @prefix WHERE \"Id\" = @id";
            AddParameter(update, "hash", HashCode(item.Code));
            AddParameter(update, "prefix", PrefixOf(item.Code));
            AddParameter(update, "id", item.Id);
            await update.ExecuteNonQueryAsync();
        }

        await _context.Database.ExecuteSqlRawAsync("ALTER TABLE \"InviteCodes\" DROP COLUMN IF EXISTS \"Code\"");
        await _context.Database.ExecuteSqlRawAsync("ALTER TABLE \"InviteCodes\" ALTER COLUMN \"CodeHash\" SET NOT NULL");
        await _context.Database.ExecuteSqlRawAsync("ALTER TABLE \"InviteCodes\" ALTER COLUMN \"Prefix\" SET NOT NULL");
        await tx.CommitAsync();
        return new InviteCodeMigrationResult(legacy.Count, false);
    }

    public async Task<InviteRedeemResult> RedeemAsync(
        string code, User user, string ipAddress, bool revokeExistingAccess = false)
    {
        var prefix = PrefixOf(code);
        var (inviteBanned, _) = await IsIpBannedAsync(ipAddress);
        if (inviteBanned)
        {
            _logger.LogWarning("IP已封禁(邀请码) | {Ip}", ipAddress);
            return new InviteRedeemResult { IpBanned = true, Prefix = prefix };
        }

        if (string.IsNullOrWhiteSpace(_config.ServerPepper))
            return new InviteRedeemResult { ApiError = true, Prefix = prefix, Message = "邀请码服务暂不可用，请稍后重试。" };

        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                var result = await RedeemCoreAsync(code.Trim(), user, revokeExistingAccess, prefix);
                if (!result.Allowed)
                    await RecordFailureAsync(ipAddress);
                return result;
            }
            catch (PostgresException ex) when (ex.SqlState == "40001" && attempt == 0)
            {
                _logger.LogWarning("邀请码核销串行化冲突，重试 | uid:{Uid} | prefix:{Prefix}", user.Uid, prefix);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "邀请码核销异常 | prefix:{Prefix} | uid:{Uid}", prefix, user.Uid);
                return new InviteRedeemResult
                {
                    ApiError = true,
                    Prefix = prefix,
                    Message = "邀请码服务暂不可用，请稍后重试。"
                };
            }
        }

        return new InviteRedeemResult
        {
            ApiError = true,
            Prefix = prefix,
            Message = "邀请码服务暂不可用，请稍后重试。"
        };
    }

    private async Task<InviteRedeemResult> RedeemCoreAsync(
        string code, User user, bool revokeExistingAccess, string prefix)
    {
        await using var tx = await _context.Database.BeginTransactionAsync(IsolationLevel.Serializable);

        var entity = await _context.InviteCodes.FirstOrDefaultAsync(c => c.CodeHash == HashCode(code));
        if (entity is null
            || entity.Status != InviteCodeStatus.Active
            || entity.ExpiresAt <= DateTimeOffset.UtcNow
            || entity.UsedCount >= entity.MaxRedemptions
            || entity.UsedBy.Contains(user.Uid.ToString()))
        {
            return InviteRedeemResult.Failure(prefix);
        }

        if (revokeExistingAccess && AuthConstants.Groups.Rank(entity.Group) <= AuthConstants.Groups.Rank(user.Group))
            return InviteRedeemResult.Failure(prefix);

        entity.UsedCount++;
        entity.UsedBy.Add(user.Uid.ToString());
        user.Group = entity.Group;

        if (revokeExistingAccess)
            await _userAccessRevoker.RevokeUserAccessAsync(user.Uid, revokeUserToken: true, manageTransaction: false);

        await _context.SaveChangesAsync();
        await tx.CommitAsync();

        _logger.LogInformation("邀请码核销并提权 | prefix:{Prefix} | uid:{Uid} | 组:{Group}", prefix, user.Uid, entity.Group);
        return InviteRedeemResult.Success(entity.Group, prefix);
    }

    public string HashCode(string code)
    {
        EnsurePepper();
        var key = Encoding.UTF8.GetBytes(_config.ServerPepper);
        var value = Encoding.UTF8.GetBytes(code);
        return Convert.ToHexStringLower(HMACSHA256.HashData(key, value));
    }

    private static string GenerateCode()
    {
        var chars = new char[CodeLength];
        for (var i = 0; i < chars.Length; i++)
            chars[i] = Alphabet[RandomNumberGenerator.GetInt32(Alphabet.Length)];
        return new string(chars);
    }

    private static string PrefixOf(string? code)
    {
        var value = code?.Trim() ?? string.Empty;
        return value.Length <= 3 ? value : value[..3];
    }

    private void EnsurePepper()
    {
        if (string.IsNullOrWhiteSpace(_config.ServerPepper))
            throw new InvalidOperationException("InviteCode.ServerPepper 未配置。");
    }

    private static void AddParameter(System.Data.Common.DbCommand command, string name, object value)
    {
        var parameter = command.CreateParameter();
        parameter.ParameterName = name;
        parameter.Value = value;
        command.Parameters.Add(parameter);
    }
}

public sealed record InviteCodeCreateResult(InviteCode Entity, string Code);

public sealed record InviteCodeMigrationResult(int Migrated, bool AlreadyMigrated);

public sealed class InviteRedeemResult
{
    public bool IpBanned { get; init; }
    public bool ApiError { get; init; }
    public string Message { get; init; } = "invalid_or_expired";
    public string? NewGroup { get; init; }
    public string Prefix { get; init; } = string.Empty;

    public static InviteRedeemResult Success(string group, string prefix)
        => new() { Allowed = true, NewGroup = group, Prefix = prefix, Message = string.Empty };

    public static InviteRedeemResult Failure(string prefix)
        => new() { Allowed = false, Prefix = prefix, Message = "invalid_or_expired" };

    public bool Allowed { get; init; }
}

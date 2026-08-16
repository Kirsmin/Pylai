using System.Data;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Pylaios.Features.Registration;

public interface IInviteCodeService
{
    Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress);
    Task<InviteRedeemResult> RedeemAsync(string code, User user, string ipAddress, bool revokeExistingAccess = false);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByIpAsync(string ipAddress);
}

public class InviteCodeService : IpBanServiceBase<InviteCodeFailure>, IInviteCodeService
{
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

    public async Task<InviteRedeemResult> RedeemAsync(
        string code, User user, string ipAddress, bool revokeExistingAccess = false)
    {
        var (inviteBanned, _) = await IsIpBannedAsync(ipAddress);
        if (inviteBanned)
        {
            _logger.LogWarning("IP已封禁(邀请码) | {Ip}", ipAddress);
            return new InviteRedeemResult { IpBanned = true };
        }

        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                var result = await RedeemCoreAsync(code, user, revokeExistingAccess);
                if (!result.Allowed)
                    await RecordFailureAsync(ipAddress);
                return result;
            }
            catch (PostgresException ex) when (ex.SqlState == "40001" && attempt == 0)
            {
                _logger.LogWarning("邀请码核销串行化冲突，重试 | uid:{Uid} | code:{Code}", user.Uid, code);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "邀请码核销异常 | code:{Code} | uid:{Uid}", code, user.Uid);
                return new InviteRedeemResult
                {
                    ApiError = true,
                    Message = "邀请码服务暂不可用，请稍后重试。"
                };
            }
        }

        return new InviteRedeemResult
        {
            ApiError = true,
            Message = "邀请码服务暂不可用，请稍后重试。"
        };
    }

    private async Task<InviteRedeemResult> RedeemCoreAsync(string code, User user, bool revokeExistingAccess)
    {
        await using var tx = await _context.Database.BeginTransactionAsync(IsolationLevel.Serializable);

        var entity = await _context.InviteCodes.FirstOrDefaultAsync(c => c.Code == code);
        if (entity is null)
            return InviteRedeemResult.Failure("邀请码不存在。");

        if (entity.UsedBy.Contains(user.Uid.ToString()))
            return InviteRedeemResult.Failure("你已使用过此邀请码，无需重复提交。");

        if (entity.UsedCount >= entity.MaxRedemptions)
            return InviteRedeemResult.Failure("邀请码核销次数已达上限。");

        if (revokeExistingAccess && AuthConstants.Groups.Rank(entity.Group) <= AuthConstants.Groups.Rank(user.Group))
            return InviteRedeemResult.Failure("当前用户组不低于邀请码目标组，未核销邀请码。");

        entity.UsedCount++;
        entity.UsedBy.Add(user.Uid.ToString());

        user.Group = entity.Group;

        if (revokeExistingAccess)
            await _userAccessRevoker.RevokeUserAccessAsync(user.Uid, revokeUserToken: true, manageTransaction: false);

        await _context.SaveChangesAsync();
        await tx.CommitAsync();

        _logger.LogInformation("邀请码核销并提权 | code:{Code} | uid:{Uid} | 组:{Group}", code, user.Uid, entity.Group);
        return InviteRedeemResult.Success(entity.Group);
    }
}

public class InviteRedeemResult
{
    public bool IpBanned { get; init; }
    public bool ApiError { get; init; }
    public string Message { get; init; } = string.Empty;
    public string? NewGroup { get; init; }

    public static InviteRedeemResult Success(string group)
        => new() { Allowed = true, NewGroup = group };

    public static InviteRedeemResult Failure(string message)
        => new() { Allowed = false, Message = message };

    public bool Allowed { get; init; }
}

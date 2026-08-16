using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Account;


public class EmailVerificationEntry
{
    public string Hash { get; set; } = string.Empty;
    public string? Email { get; set; }
    public int Attempts { get; set; }
    public DateTimeOffset Expires { get; set; }
}




public class ChangePasswordRequest
{
    [Required]
    public string CurrentPassword { get; set; } = string.Empty;

    [Required]
    [StringLength(100, MinimumLength = 6)]
    public string NewPassword { get; set; } = string.Empty;
}

public class PasswordResponse : ApiResponse
{
    public int? AttemptsRemaining { get; set; }
}

public class BindEmailRequest
{
    [Required]
    public string CurrentPassword { get; set; } = string.Empty;

    [Required]
    public string Email { get; set; } = string.Empty;
}

public class ChangeEmailRequest
{
    [Required]
    public string NewEmail { get; set; } = string.Empty;
}

public class EmailCodeRequest
{
    [Required]
    public string Code { get; set; } = string.Empty;
}

public class EmailCodeResponse : ApiResponse
{
    public bool Sent { get; set; }
    public string? VerifiedEmail { get; set; }
    public string? PendingEmail { get; set; }
    public int? AttemptsRemaining { get; set; }
}

public class AccountRedeemRequest
{
    public string InviteCode { get; set; } = string.Empty;
}

public class AccountRedeemResponse : ApiResponse
{
    public string? NewGroup { get; set; }
}




public class AuthorizedAppItem
{
    public string Id { get; set; } = string.Empty;
    public string ClientId { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? LogoUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public string? HomepageUrl { get; set; }
    public string AuthorizedAt { get; set; } = string.Empty;
    public List<ScopeInfo> Scopes { get; set; } = [];
}

public class AuthorizedAppListResponse : ApiResponse
{
    public List<AuthorizedAppItem> Apps { get; set; } = [];
}

public class AuthorizedAppRevokeResponse : ApiResponse
{
}

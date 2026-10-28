using System.ComponentModel.DataAnnotations;

using Fido2NetLib;

namespace Pylaios.Features.Auth;

public sealed class MfaVerifyRequest
{
    [Required]
    public string TransactionId { get; set; } = string.Empty;
    [Required]
    public string Code { get; set; } = string.Empty;
}

public sealed class MfaEnrollmentRequest
{
    public string? TransactionId { get; set; }
}

public sealed class MfaEnrollmentConfirmRequest
{
    [Required]
    public string EnrollmentId { get; set; } = string.Empty;
    [Required]
    public string Code { get; set; } = string.Empty;
}

public sealed class MfaWebAuthnRequest
{
    [Required]
    public string TransactionId { get; set; } = string.Empty;
    [Required]
    public AuthenticatorAssertionRawResponse Response { get; set; } = new();
}

public sealed class MfaStatusResponse : ApiResponse
{
    public bool Required { get; set; }
    public bool TotpEnabled { get; set; }
    public int WebAuthnCount { get; set; }
    public bool StepUpSatisfied { get; set; }
}

public sealed class MfaWebAuthnRegistrationRequest
{
    public string? TransactionId { get; set; }
    [Required]
    public string RegistrationId { get; set; } = string.Empty;
    [StringLength(64)]
    public string? Name { get; set; }
    [Required]
    public AuthenticatorAttestationRawResponse Response { get; set; } = new();
}

/// <summary>
/// WebAuthn 凭据列表项：仅暴露管理所需的最小字段，禁止包含 CredentialId/PublicKey/SignCount。
/// </summary>
public sealed class MfaWebAuthnCredentialItem
{
    public long Id { get; set; }
    public string? Name { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset? LastUsedAt { get; set; }
    public string[] Transports { get; set; } = [];
}

public sealed class MfaWebAuthnCredentialListResponse : ApiResponse
{
    public MfaWebAuthnCredentialItem[] Credentials { get; set; } = [];
}

public sealed class MfaWebAuthnCredentialRenameRequest
{
    [StringLength(64)]
    public string? Name { get; set; }
}

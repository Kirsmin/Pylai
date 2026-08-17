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
    [Required]
    public AuthenticatorAttestationRawResponse Response { get; set; } = new();
}

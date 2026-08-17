using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.PasswordReset;

public class ForgotPasswordRequest
{
    [Required]
    public string Email { get; set; } = string.Empty;
}

public class ResetPasswordRequest
{
    [Required]
    public string TransactionId { get; set; } = string.Empty;

    [Required]
    public string Code { get; set; } = string.Empty;

    [Required]
    [StringLength(128, MinimumLength = 12)]
    public string NewPassword { get; set; } = string.Empty;
}

public class ForgotPasswordResponse : ApiResponse
{
    public string TransactionId { get; set; } = string.Empty;
}

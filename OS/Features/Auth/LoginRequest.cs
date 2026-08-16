using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Auth;

public class LoginRequest
{
    [Required]
    public string UsernameOrEmail { get; set; } = string.Empty;

    [Required]
    public string Password { get; set; } = string.Empty;

    public bool RememberMe { get; set; }
}

public class LoginResponse : ApiResponse
{
    public Guid? Uid { get; set; }
    public string? Name { get; set; }
    public string? DisplayName { get; set; }
    public string? Group { get; set; }
    public string? Email { get; set; }
    public bool LockedOut { get; set; }
    public string? LockoutRemaining { get; set; }
    public string? BanId { get; set; }
}

public class PasswordPolicyResponse : ApiResponse
{
    public int MinLength { get; set; }
    public bool RequireDigit { get; set; }
    public bool RequireLowercase { get; set; }
    public bool RequireUppercase { get; set; }
    public bool RequireNonAlphanumeric { get; set; }
}

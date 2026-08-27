namespace Pylaios.Features.Registration;

public class RegisterInitRequest
{
    public AltchaPayload? Altcha { get; set; }
}

public class RegisterInitResponse : ApiResponse
{
    public string SessionToken { get; set; } = string.Empty;
    public bool IpBanned { get; set; }
}

public class SendEmailCodeRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
}

public class SendEmailCodeResponse : ApiResponse
{
    public int? ChangesRemaining { get; set; }
}

public class VerifyEmailRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string Code { get; set; } = string.Empty;
}

public class VerifyEmailResponse : ApiResponse
{
}

public class ChangeRegistrationEmailRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string NewEmail { get; set; } = string.Empty;
}

public class ChangeRegistrationEmailResponse : ApiResponse
{
    public int? ChangesRemaining { get; set; }
}

public class UsernameCheckRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string Username { get; set; } = string.Empty;
}

public class UsernameCheckResponse : ApiResponse
{
    public string? NormalizedName { get; set; }
    public string? DisplayName { get; set; }
}

public class CreateAccountRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string Password { get; set; } = string.Empty;
}

public class CreateAccountResponse : ApiResponse
{
    public Guid? Uid { get; set; }
    public string? Name { get; set; }
    public string? DisplayName { get; set; }
    public string? Group { get; set; }
}

public class InviteCodeRedeemRequest
{
    public string SessionToken { get; set; } = string.Empty;
    public string? InviteCode { get; set; }
}

public class InviteCodeRedeemResponse : ApiResponse
{
    public string? NewGroup { get; set; }
    public bool Skipped { get; set; }
}

public class ExternalLoginRequest
{
    public string Provider { get; set; } = string.Empty;
}

public class RegisterCompleteRequest
{
    public string SessionToken { get; set; } = string.Empty;
}

public class RegisterCompleteResponse : ApiResponse
{
    public bool Completed { get; set; }
}

public class RegistrationStatusResponse : ApiResponse
{
    public int Step { get; set; }
    public string? InviteCodeType { get; set; }
    public string? NormalizedName { get; set; }
    public string? DisplayName { get; set; }
    public bool AccountCreated { get; set; }
    public string? PendingEmail { get; set; }
    public int EmailCodeAttempts { get; set; }
    public int EmailChangeCount { get; set; }
    public bool Completed { get; set; }
}

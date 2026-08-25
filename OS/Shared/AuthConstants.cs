namespace Pylaios.Shared;

public static class AuthConstants
{
    public static class Roles
    {
        public const string Admin = "admin";
        public const string Normal = "normal";
        public const string Max = "max";
    }

    public static class Groups
    {
        public static readonly string[] All = [Roles.Normal, Roles.Admin, Roles.Max];
        public static bool IsValid(string? group) => group is not null && All.Contains(group);
        public static int Rank(string? group) => group?.ToLowerInvariant() switch
        {
            Roles.Normal => 0,
            Roles.Admin => 1,
            Roles.Max => 2,
            _ => -1
        };
    }

    public static class Policies
    {
        public const string AuthenticatedApi = "AuthenticatedApi";
        public const string AdminUserApi = "AdminUserApi";
        public const string MaxApi = "MaxApi";
    }

    public static class EventTypes
    {
        public const string Login = "Login";
        public const string LoginFailure = "LoginFailure";
        public const string LoginLockedOut = "LoginLockedOut";
        public const string LoginIpBanned = "LoginIpBanned";
        public const string PasswordReset = "PasswordReset";
        public const string ExternalLoginBound = "ExternalLoginBound";
        public const string ExternalLoginSignedIn = "ExternalLoginSignedIn";
        public const string ExternalLoginUnbound = "ExternalLoginUnbound";
        public const string ConsentApproved = "ConsentApproved";
        public const string ConsentDenied = "ConsentDenied";
        public const string AuthorizationRevoked = "AuthorizationRevoked";

        public const string ClientCreated = "ClientCreated";
        public const string ClientUpdated = "ClientUpdated";
        public const string ClientDeleted = "ClientDeleted";
        public const string ClientDisabled = "ClientDisabled";
        public const string ClientEnabled = "ClientEnabled";
        public const string ClientLogoUpdated = "ClientLogoUpdated";
        public const string ClientLogoDeleted = "ClientLogoDeleted";

        public const string TokenIssued = "TokenIssued";
        public const string TokenRefreshed = "TokenRefreshed";
        public const string ClientCredentialsToken = "ClientCredentialsToken";
        public const string TokenRequest = "TokenRequest";
        public const string Authorize = "Authorize";
        public const string AuthorizeRedirect = "AuthorizeRedirect";
        public const string Logout = "Logout";
        public const string UserInfo = "UserInfo";
        public const string Introspect = "Introspect";
        public const string Revoke = "Revoke";
        public const string Discovery = "Discovery";
        public const string ApiCall = "ApiCall";

        public const string InviteCodeRedeemed = "InviteCodeRedeemed";
        public const string InviteCodeRedeemFailed = "InviteCodeRedeemFailed";
        public const string RegisterStarted = "RegisterStarted";
        public const string RegisterCompleted = "RegisterCompleted";
        public const string EmailVerificationSent = "EmailVerificationSent";
        public const string EmailVerificationFailed = "EmailVerificationFailed";
        public const string EmailVerificationSuccess = "EmailVerificationSuccess";
        public const string EmailVerificationExpired = "EmailVerificationExpired";
        public const string EmailVerificationMaxAttempts = "EmailVerificationMaxAttempts";
        public const string EmailVerificationIpBanned = "EmailVerificationIpBanned";
        public const string EmailChanged = "EmailChanged";
        public const string CliCommand = "CliCommand";
        public const string UserTokenCreated = "UserTokenCreated";
        public const string UserTokenRefreshed = "UserTokenRefreshed";
        public const string UserTokenRevoked = "UserTokenRevoked";
        public const string UserTokenQueried = "UserTokenQueried";
        public const string ConfirmationSucceeded = "ConfirmationSucceeded";
        public const string ConfirmationFailed = "ConfirmationFailed";
        public const string MfaStepUpSkipped = "MfaStepUpSkipped";
        public const string InviteCodeCreated = "InviteCodeCreated";
        public const string InviteCodeUpdated = "InviteCodeUpdated";
        public const string InviteCodeDeleted = "InviteCodeDeleted";
        public const string InviteCodeRevoked = "InviteCodeRevoked";
        public const string AdminUserUpdated = "AdminUserUpdated";
        public const string AdminUserDeleted = "AdminUserDeleted";
        public const string SessionsRevokedAll = "SessionsRevokedAll";
        public const string AdminAuthFailed = "AdminAuthFailed";
        public const string AdminResetPassword = "AdminResetPassword";
        public const string AdminIpUnbanned = "AdminIpUnbanned";
        public const string UserCreated = "UserCreated";
        public const string SettingsChanged = "SettingsChanged";
    }

    public static class Scopes
    {
        public const string OpenId = "openid";
        public const string ProfileBasic = "profile:basic";
        public const string ProfileMail = "profile:mail";
        public const string ProfileRole = "profile:role";
        public const string OfflineAccess = "offline_access";
    }
}

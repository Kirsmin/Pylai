using System.Security.Cryptography;
using System.Text;
using Fido2NetLib;
using Fido2NetLib.Objects;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Auth;

public sealed class MfaLoginRequirement
{
    public bool Required { get; init; }
    public bool SetupRequired { get; init; }
    public string? TransactionId { get; init; }
    public string[] Methods { get; init; } = [];

    public static MfaLoginRequirement NotRequired { get; } = new();
}

public sealed class MfaLoginState
{
    public Guid UserUid { get; set; }
    public bool RememberMe { get; set; }
    public string IpAddress { get; set; } = string.Empty;
}

public sealed class MfaTotpEnrollment
{
    public Guid UserUid { get; set; }
    public string Secret { get; set; } = string.Empty;
    public string? LoginTransactionId { get; set; }
}

public sealed class MfaWebAuthnState
{
    public Guid UserUid { get; set; }
    public string OptionsJson { get; set; } = string.Empty;
    public string? LoginTransactionId { get; set; }
}

public interface IMfaService
{
    Task<MfaLoginRequirement> BeginLoginAsync(User user, bool rememberMe, string ipAddress);
    ValueTask<MfaLoginState?> GetLoginStateAsync(string transactionId);
    ValueTask RemoveLoginStateAsync(string transactionId);
    Task<bool> VerifyTotpAsync(Guid userUid, string code);
    Task<(string EnrollmentId, string Secret, string Uri, string? LoginTransactionId)> BeginTotpEnrollmentAsync(Guid userUid, string? loginTransactionId);
    Task<(bool Success, string? LoginTransactionId)> ConfirmTotpEnrollmentAsync(string enrollmentId, string code);
    Task<(string RegistrationId, CredentialCreateOptions Options)> BeginWebAuthnRegistrationAsync(Guid userUid, string? loginTransactionId);
    Task<bool> CompleteWebAuthnRegistrationAsync(Guid userUid, string registrationId, AuthenticatorAttestationRawResponse response);
    Task<AssertionOptions> BeginWebAuthnAssertionAsync(string transactionId);
    Task<bool> VerifyWebAuthnAssertionAsync(string transactionId, AuthenticatorAssertionRawResponse response);
    Task<MfaLoginRequirement> BeginStepUpAsync(User user);
    ValueTask<MfaLoginState?> GetStepUpStateAsync(string transactionId);
    ValueTask RemoveStepUpStateAsync(string transactionId);
    Task<bool> VerifyStepUpTotpAsync(string transactionId, string code);
    Task<AssertionOptions> BeginStepUpWebAuthnAssertionAsync(string transactionId);
    Task<bool> VerifyStepUpWebAuthnAssertionAsync(string transactionId, AuthenticatorAssertionRawResponse response);
    Task MarkStepUpVerifiedAsync(string credentialKey);
    Task<bool> HasCredentialStepUpVerifiedAsync(string credentialKey);
    Task<bool> HasRecentStepUpAsync(Guid userUid);
}

public sealed class MfaService : IMfaService
{
    private static readonly TimeSpan StateTtl = TimeSpan.FromMinutes(5);
    private const string LoginPrefix = "mfa:login:";
    private const string StepUpPrefix = "mfa:stepup:";
    private const string TotpPrefix = "mfa:totp:";
    private const string RegistrationPrefix = "mfa:registration:";
    private const string AssertionPrefix = "mfa:assertion:";
    private const string StepUpAssertionPrefix = "mfa:stepup-assertion:";
    public const string StepUpVerifiedPrefix = "mfa:verified:";
    private const string Base32Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

    private readonly ApplicationDbContext _context;
    private readonly IRedisStateCache _cache;
    private readonly IDataProtector _protector;
    private readonly IFido2 _fido2;
    private readonly MfaConfig _config;

    public MfaService(
        ApplicationDbContext context,
        IRedisStateCache cache,
        IDataProtectionProvider dataProtection,
        IFido2 fido2,
        MainConfig config)
    {
        _context = context;
        _cache = cache;
        _protector = dataProtection.CreateProtector("Pylaios.Mfa.Totp.v1");
        _fido2 = fido2;
        _config = config.Mfa;
    }

    public async Task<MfaLoginRequirement> BeginLoginAsync(User user, bool rememberMe, string ipAddress)
    {
        var rank = AuthConstants.Groups.Rank(user.Group);
        var adminMfaRequired = rank >= AuthConstants.Groups.Rank(AuthConstants.Roles.Admin)
            && _config.RequireForAdmin;
        var maxWebAuthnRequired = rank >= AuthConstants.Groups.Rank(AuthConstants.Roles.Max)
            && _config.RequireWebAuthnForMax;
        if (rank < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin)
            || (!adminMfaRequired && !maxWebAuthnRequired))
            return MfaLoginRequirement.NotRequired;

        var settings = await _context.UserMfaSettings.AsNoTracking().FirstOrDefaultAsync(x => x.UserUid == user.Uid);
        var hasTotp = settings?.TotpEnabled == true && !string.IsNullOrWhiteSpace(settings.EncryptedTotpSecret);
        var hasWebAuthn = await _context.WebAuthnCredentials.AnyAsync(x => x.UserUid == user.Uid);
        var maxRequiresWebAuthn = rank >= AuthConstants.Groups.Rank(AuthConstants.Roles.Max)
            && _config.RequireWebAuthnForMax;
        var availableMethods = maxRequiresWebAuthn
            ? (hasWebAuthn ? ["webauthn"] : Array.Empty<string>())
            : new[] { hasTotp ? "totp" : null, hasWebAuthn ? "webauthn" : null }
                .Where(x => x is not null)
                .Cast<string>()
                .ToArray();
        var methods = availableMethods.Length > 0
            ? availableMethods
            : maxRequiresWebAuthn ? ["webauthn"] : ["totp", "webauthn"];

        var transactionId = AuthHelper.GenerateOpaqueToken();
        await _cache.SetAsync(LoginPrefix + transactionId, new MfaLoginState
        {
            UserUid = user.Uid,
            RememberMe = rememberMe,
            IpAddress = ipAddress
        }, StateTtl);

        return new MfaLoginRequirement
        {
            Required = true,
            SetupRequired = availableMethods.Length == 0,
            TransactionId = transactionId,
            Methods = methods
        };
    }

    public ValueTask<MfaLoginState?> GetLoginStateAsync(string transactionId)
        => _cache.GetAsync<MfaLoginState>(LoginPrefix + transactionId);

    public ValueTask RemoveLoginStateAsync(string transactionId)
        => _cache.RemoveAsync(LoginPrefix + transactionId);

    public async Task<bool> HasRecentStepUpAsync(Guid userUid)
    {
        var settings = await _context.UserMfaSettings.AsNoTracking().FirstOrDefaultAsync(x => x.UserUid == userUid);
        return settings?.LastVerifiedAt is { } verified
            && verified >= DateTimeOffset.UtcNow.AddMinutes(-_config.ChallengeLifetimeMinutes);
    }

    public async Task MarkStepUpVerifiedAsync(string credentialKey)
        => await _cache.SetAsync(StepUpVerifiedPrefix + credentialKey, true,
            TimeSpan.FromMinutes(_config.ChallengeLifetimeMinutes));

    public async Task<bool> HasCredentialStepUpVerifiedAsync(string credentialKey)
        => await _cache.GetAsync<bool>(StepUpVerifiedPrefix + credentialKey);

    public async Task<MfaLoginRequirement> BeginStepUpAsync(User user)
    {
        var settings = await _context.UserMfaSettings.AsNoTracking().FirstOrDefaultAsync(x => x.UserUid == user.Uid);
        var hasTotp = settings?.TotpEnabled == true && !string.IsNullOrWhiteSpace(settings.EncryptedTotpSecret);
        var hasWebAuthn = await _context.WebAuthnCredentials.AnyAsync(x => x.UserUid == user.Uid);
        var methods = new[] { hasTotp ? "totp" : null, hasWebAuthn ? "webauthn" : null }
            .Where(x => x is not null)
            .Cast<string>()
            .ToArray();
        if (methods.Length == 0)
            throw new InvalidOperationException("账户尚未配置可用的 MFA 方法。");

        var transactionId = AuthHelper.GenerateOpaqueToken();
        await _cache.SetAsync(StepUpPrefix + transactionId, new MfaLoginState
        {
            UserUid = user.Uid,
            RememberMe = false,
            IpAddress = string.Empty
        }, StateTtl);
        return new MfaLoginRequirement { Required = true, TransactionId = transactionId, Methods = methods };
    }

    public ValueTask<MfaLoginState?> GetStepUpStateAsync(string transactionId)
        => _cache.GetAsync<MfaLoginState>(StepUpPrefix + transactionId);

    public ValueTask RemoveStepUpStateAsync(string transactionId)
        => _cache.RemoveAsync(StepUpPrefix + transactionId);

    public async Task<bool> VerifyStepUpTotpAsync(string transactionId, string code)
    {
        var state = await GetStepUpStateAsync(transactionId);
        return state is not null && await VerifyTotpAsync(state.UserUid, code);
    }

    public async Task<bool> VerifyTotpAsync(Guid userUid, string code)
    {
        var settings = await _context.UserMfaSettings.FirstOrDefaultAsync(x => x.UserUid == userUid);
        if (settings?.TotpEnabled != true || string.IsNullOrWhiteSpace(settings.EncryptedTotpSecret))
            return false;

        var secret = _protector.Unprotect(settings.EncryptedTotpSecret);
        var matchedCounter = VerifyTotp(secret, code, DateTimeOffset.UtcNow);
        if (matchedCounter is null)
            return false;
        if (settings.LastTotpCounter.HasValue && matchedCounter.Value <= settings.LastTotpCounter.Value)
            return false;

        settings.LastTotpCounter = matchedCounter;
        settings.LastVerifiedAt = DateTimeOffset.UtcNow;
        settings.UpdatedAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<(string EnrollmentId, string Secret, string Uri, string? LoginTransactionId)> BeginTotpEnrollmentAsync(
        Guid userUid, string? loginTransactionId)
    {
        var secret = GenerateBase32Secret();
        var enrollmentId = AuthHelper.GenerateOpaqueToken();
        var user = await _context.Users.AsNoTracking().FirstOrDefaultAsync(x => x.Uid == userUid)
            ?? throw new InvalidOperationException("用户不存在。");
        var label = Uri.EscapeDataString(user.Email ?? user.Name);
        var uri = $"otpauth://totp/Pylaios:{label}?secret={secret}&issuer=Pylaios&algorithm=SHA1&digits=6&period=30";
        await _cache.SetAsync(TotpPrefix + enrollmentId, new MfaTotpEnrollment
        {
            UserUid = userUid,
            Secret = secret,
            LoginTransactionId = loginTransactionId
        }, StateTtl);
        return (enrollmentId, secret, uri, loginTransactionId);
    }

    public async Task<(bool Success, string? LoginTransactionId)> ConfirmTotpEnrollmentAsync(string enrollmentId, string code)
    {
        var enrollment = await _cache.GetAsync<MfaTotpEnrollment>(TotpPrefix + enrollmentId);
        if (enrollment is null || VerifyTotp(enrollment.Secret, code, DateTimeOffset.UtcNow) is null)
            return (false, null);

        var settings = await _context.UserMfaSettings.FirstOrDefaultAsync(x => x.UserUid == enrollment.UserUid);
        if (settings is null)
        {
            settings = new UserMfaSettings { UserUid = enrollment.UserUid };
            _context.UserMfaSettings.Add(settings);
        }
        settings.EncryptedTotpSecret = _protector.Protect(enrollment.Secret);
        settings.TotpEnabled = true;
        settings.LastVerifiedAt = DateTimeOffset.UtcNow;
        settings.UpdatedAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();
        await _cache.RemoveAsync(TotpPrefix + enrollmentId);
        return (true, enrollment.LoginTransactionId);
    }

    public async Task<(string RegistrationId, CredentialCreateOptions Options)> BeginWebAuthnRegistrationAsync(Guid userUid, string? loginTransactionId)
    {
        var user = await _context.Users.AsNoTracking().FirstOrDefaultAsync(x => x.Uid == userUid)
            ?? throw new InvalidOperationException("用户不存在。");
        var existing = await _context.WebAuthnCredentials.AsNoTracking()
            .Where(x => x.UserUid == userUid)
            .Select(x => new PublicKeyCredentialDescriptor(x.CredentialId))
            .ToListAsync();
        var options = _fido2.RequestNewCredential(new RequestNewCredentialParams
        {
            User = new Fido2User
            {
                DisplayName = user.DisplayName ?? user.Name,
                Name = user.Name,
                Id = user.Uid.ToByteArray()
            },
            ExcludeCredentials = existing,
            AuthenticatorSelection = new AuthenticatorSelection
            {
                UserVerification = UserVerificationRequirement.Required,
                ResidentKey = ResidentKeyRequirement.Required
            },
            AttestationPreference = AttestationConveyancePreference.None
        });
        var stateKey = AuthHelper.GenerateOpaqueToken();
        await _cache.SetAsync(RegistrationPrefix + stateKey, new MfaWebAuthnState
        {
            UserUid = userUid,
            OptionsJson = options.ToJson(),
            LoginTransactionId = loginTransactionId
        }, StateTtl);
        return (stateKey, options);
    }

    public async Task<bool> CompleteWebAuthnRegistrationAsync(
        Guid userUid, string registrationId, AuthenticatorAttestationRawResponse response)
    {
        var state = await _cache.GetAsync<MfaWebAuthnState>(RegistrationPrefix + registrationId);
        if (state is null || state.UserUid != userUid)
            return false;
        var options = CredentialCreateOptions.FromJson(state.OptionsJson);
        var credential = await _fido2.MakeNewCredentialAsync(new MakeNewCredentialParams
        {
            AttestationResponse = response,
            OriginalOptions = options,
            IsCredentialIdUniqueToUserCallback = async (args, _) =>
                !await _context.WebAuthnCredentials.AnyAsync(x => x.CredentialId == args.CredentialId)
        });
        _context.WebAuthnCredentials.Add(new WebAuthnCredential
        {
            UserUid = userUid,
            CredentialId = credential.Id,
            PublicKey = credential.PublicKey,
            SignCount = credential.SignCount,
            CreatedAt = DateTimeOffset.UtcNow
        });
        await _context.SaveChangesAsync();
        await _cache.RemoveAsync(RegistrationPrefix + registrationId);
        return true;
    }

    public async Task<AssertionOptions> BeginStepUpWebAuthnAssertionAsync(string transactionId)
    {
        var state = await GetStepUpStateAsync(transactionId)
            ?? throw new InvalidOperationException("MFA step-up 事务无效或已过期。");
        var credentials = await _context.WebAuthnCredentials.AsNoTracking()
            .Where(x => x.UserUid == state.UserUid)
            .Select(x => new PublicKeyCredentialDescriptor(x.CredentialId))
            .ToListAsync();
        var options = _fido2.GetAssertionOptions(new GetAssertionOptionsParams
        {
            AllowedCredentials = credentials,
            UserVerification = UserVerificationRequirement.Required
        });
        await _cache.SetAsync(StepUpAssertionPrefix + transactionId, new MfaWebAuthnState
        {
            UserUid = state.UserUid,
            OptionsJson = options.ToJson(),
            LoginTransactionId = transactionId
        }, StateTtl);
        return options;
    }

    public async Task<bool> VerifyStepUpWebAuthnAssertionAsync(string transactionId, AuthenticatorAssertionRawResponse response)
    {
        var state = await _cache.GetAsync<MfaWebAuthnState>(StepUpAssertionPrefix + transactionId);
        if (state is null)
            return false;
        var credential = await _context.WebAuthnCredentials.FirstOrDefaultAsync(x => x.CredentialId == response.RawId);
        if (credential is null || credential.UserUid != state.UserUid)
            return false;
        var result = await _fido2.MakeAssertionAsync(new MakeAssertionParams
        {
            AssertionResponse = response,
            OriginalOptions = AssertionOptions.FromJson(state.OptionsJson),
            StoredPublicKey = credential.PublicKey,
            StoredSignatureCounter = credential.SignCount,
            IsUserHandleOwnerOfCredentialIdCallback = (args, _) =>
                Task.FromResult(args.UserHandle is null || credential.UserUid == state.UserUid)
        });
        credential.SignCount = result.SignCount;
        credential.LastUsedAt = DateTimeOffset.UtcNow;
        var settings = await _context.UserMfaSettings.FirstOrDefaultAsync(x => x.UserUid == credential.UserUid);
        if (settings is not null)
        {
            settings.LastVerifiedAt = DateTimeOffset.UtcNow;
            settings.UpdatedAt = DateTimeOffset.UtcNow;
        }
        await _context.SaveChangesAsync();
        await _cache.RemoveAsync(StepUpAssertionPrefix + transactionId);
        await _cache.RemoveAsync(StepUpPrefix + transactionId);
        return true;
    }

    public async Task<AssertionOptions> BeginWebAuthnAssertionAsync(string transactionId)
    {
        var login = await GetLoginStateAsync(transactionId)
            ?? throw new InvalidOperationException("MFA 事务无效或已过期。");
        var credentials = await _context.WebAuthnCredentials.AsNoTracking()
            .Where(x => x.UserUid == login.UserUid)
            .Select(x => new PublicKeyCredentialDescriptor(x.CredentialId))
            .ToListAsync();
        var options = _fido2.GetAssertionOptions(new GetAssertionOptionsParams
        {
            AllowedCredentials = credentials,
            UserVerification = UserVerificationRequirement.Required
        });
        await _cache.SetAsync(AssertionPrefix + transactionId, new MfaWebAuthnState
        {
            UserUid = login.UserUid,
            OptionsJson = options.ToJson(),
            LoginTransactionId = transactionId
        }, StateTtl);
        return options;
    }

    public async Task<bool> VerifyWebAuthnAssertionAsync(string transactionId, AuthenticatorAssertionRawResponse response)
    {
        var state = await _cache.GetAsync<MfaWebAuthnState>(AssertionPrefix + transactionId);
        if (state is null)
            return false;
        var credential = await _context.WebAuthnCredentials.FirstOrDefaultAsync(x => x.CredentialId == response.RawId);
        if (credential is null || credential.UserUid != state.UserUid)
            return false;
        var result = await _fido2.MakeAssertionAsync(new MakeAssertionParams
        {
            AssertionResponse = response,
            OriginalOptions = AssertionOptions.FromJson(state.OptionsJson),
            StoredPublicKey = credential.PublicKey,
            StoredSignatureCounter = credential.SignCount,
            IsUserHandleOwnerOfCredentialIdCallback = (args, _) =>
                Task.FromResult(args.UserHandle is null || credential.UserUid == state.UserUid)
        });
        credential.SignCount = result.SignCount;
        credential.LastUsedAt = DateTimeOffset.UtcNow;
        var settings = await _context.UserMfaSettings.FirstOrDefaultAsync(x => x.UserUid == credential.UserUid);
        if (settings is not null)
        {
            settings.LastVerifiedAt = DateTimeOffset.UtcNow;
            settings.UpdatedAt = DateTimeOffset.UtcNow;
        }
        await _context.SaveChangesAsync();
        await _cache.RemoveAsync(AssertionPrefix + transactionId);
        return true;
    }

    private static string GenerateBase32Secret()
    {
        var bytes = RandomNumberGenerator.GetBytes(20);
        var result = new StringBuilder(32);
        var buffer = 0;
        var bits = 0;
        foreach (var value in bytes)
        {
            buffer = (buffer << 8) | value;
            bits += 8;
            while (bits >= 5)
            {
                bits -= 5;
                result.Append(Base32Alphabet[(buffer >> bits) & 31]);
            }
        }
        if (bits > 0)
            result.Append(Base32Alphabet[(buffer << (5 - bits)) & 31]);
        return result.ToString();
    }

    private static long? VerifyTotp(string secret, string code, DateTimeOffset now)
    {
        if (code.Length != 6 || !int.TryParse(code, out _))
            return null;
        var key = DecodeBase32(secret);
        var counter = now.ToUnixTimeSeconds() / 30;
        for (long offset = -1; offset <= 1; offset++)
        {
            var expected = GenerateTotp(key, counter + offset);
            if (CryptographicOperations.FixedTimeEquals(
                    Encoding.ASCII.GetBytes(expected), Encoding.ASCII.GetBytes(code)))
                return counter + offset;
        }
        return null;
    }

    private static string GenerateTotp(byte[] key, long counter)
    {
        Span<byte> data = stackalloc byte[8];
        System.Buffers.Binary.BinaryPrimitives.WriteInt64BigEndian(data, counter);
        var hash = HMACSHA1.HashData(key, data);
        var offset = hash[^1] & 0x0f;
        var value = ((hash[offset] & 0x7f) << 24)
            | (hash[offset + 1] << 16)
            | (hash[offset + 2] << 8)
            | hash[offset + 3];
        return (value % 1_000_000).ToString("D6");
    }

    private static byte[] DecodeBase32(string value)
    {
        var output = new List<byte>();
        var buffer = 0;
        var bits = 0;
        foreach (var character in value.TrimEnd('=').ToUpperInvariant())
        {
            var index = Base32Alphabet.IndexOf(character);
            if (index < 0) throw new FormatException("无效的 TOTP secret。");
            buffer = (buffer << 5) | index;
            bits += 5;
            if (bits >= 8)
            {
                bits -= 8;
                output.Add((byte)((buffer >> bits) & 0xff));
            }
        }
        return output.ToArray();
    }
}

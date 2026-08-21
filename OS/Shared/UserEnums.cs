namespace Pylaios.Shared;

public enum UserStatus
{
    Active,
    Banned,
    Locked,
    Deleted
}

public static class UserStatusParser
{
    public static bool TryParse(string? value, out UserStatus status)
    {
        status = UserStatus.Active;
        if (string.IsNullOrWhiteSpace(value)) return false;
        return value.Trim().ToLowerInvariant() switch
        {
            "active" or "正常" => Set(UserStatus.Active, out status),
            "banned" or "封禁" => Set(UserStatus.Banned, out status),
            "locked" or "锁定" => Set(UserStatus.Locked, out status),
            "deleted" or "已删除" => Set(UserStatus.Deleted, out status),
            _ => false
        };
    }

    private static bool Set(UserStatus value, out UserStatus status)
    {
        status = value;
        return true;
    }
}

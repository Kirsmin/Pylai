namespace Pylaios.Shared;

public class ApiResponse
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public string? ErrorCode { get; set; }

    public static ApiResponse Ok() => new() { Success = true };

    public static ApiResponse Fail(string error, string? errorCode = null) => new()
    {
        Success = false,
        Error = error,
        ErrorCode = errorCode
    };
}

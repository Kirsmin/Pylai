namespace Pylaios.Shared;

public class ApiResponse
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public string? ErrorCode { get; set; }
}

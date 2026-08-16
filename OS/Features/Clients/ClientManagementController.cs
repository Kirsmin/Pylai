using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Clients;

[ApiController]
[Route("api/clients")]
[Authorize(Policy = AuthConstants.Policies.MaxApi)]
public class ClientManagementController : ControllerBase
{
    private readonly IClientService _clientService;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<ClientManagementController> _logger;

    public ClientManagementController(IClientService clientService, IAuditService auditService, IpResolutionService ipResolver, ILogger<ClientManagementController> logger)
    {
        _clientService = clientService;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] int skip = 0, [FromQuery] int take = 20)
    {
        var result = await _clientService.ListAsync(Math.Max(0, skip), Math.Clamp(take, 1, 100));
        return Ok(result);
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(string id)
    {
        var client = await _clientService.GetByIdAsync(id);
        if (client is null)
            return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
        return Ok(client);
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] ClientCreateRequest request)
    {
        if (TryValidateCreate(request, out var validationError))
            return BadRequest(new ApiResponse { Success = false, Error = validationError, ErrorCode = "invalid_request" });

        try
        {
            var client = await _clientService.CreateAsync(request);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientCreated,
                null, null, true, $"ClientId: {request.ClientId}, DisplayName: {request.DisplayName}");
            _logger.LogInformation("客户端创建 | ClientId:{ClientId}", request.ClientId);
            return CreatedAtAction(nameof(GetById), new { id = client.Id }, client);
        }
        catch (InvalidOperationException ex)
        {
            return Conflict(new ApiResponse { Success = false, Error = ex.Message, ErrorCode = "invalid_request" });
        }
        catch (OpenIddict.Abstractions.OpenIddictExceptions.ValidationException ex)
        {
            return Conflict(new ApiResponse { Success = false, Error = ex.Message, ErrorCode = "invalid_request" });
        }
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(string id, [FromBody] ClientUpdateRequest request)
    {
        if (TryValidateUpdate(request, out var validationError))
            return BadRequest(new ApiResponse { Success = false, Error = validationError, ErrorCode = "invalid_request" });

        try
        {
            var client = await _clientService.UpdateAsync(id, request);
            if (client is null)
                return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientUpdated,
                null, null, true, $"Updated client {id}");
            _logger.LogInformation("客户端更新 | Id:{Id}", id);
            return Ok(client);
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new ApiResponse { Success = false, Error = ex.Message, ErrorCode = "invalid_request" });
        }
        catch (OpenIddict.Abstractions.OpenIddictExceptions.ValidationException ex)
        {
            return BadRequest(new ApiResponse { Success = false, Error = ex.Message, ErrorCode = "invalid_request" });
        }
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(string id)
    {
        var deleted = await _clientService.DeleteAsync(id);
        if (!deleted)
            return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientDeleted,
            null, null, true, $"Deleted client {id}");
        _logger.LogInformation("客户端删除 | Id:{Id}", id);
        return NoContent();
    }

    [HttpPatch("{id}/disable")]
    public async Task<IActionResult> Disable(string id)
    {
        var result = await _clientService.SetDisabledAsync(id, true);
        if (!result)
            return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientDisabled,
            null, null, true, $"Disabled client {id}");
        _logger.LogInformation("客户端禁用 | Id:{Id}", id);
        return NoContent();
    }

    [HttpPatch("{id}/enable")]
    public async Task<IActionResult> Enable(string id)
    {
        var result = await _clientService.SetDisabledAsync(id, false);
        if (!result)
            return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientEnabled,
            null, null, true, $"Enabled client {id}");
        _logger.LogInformation("客户端启用 | Id:{Id}", id);
        return NoContent();
    }

    [HttpGet("{id}/logo")]
    [AllowAnonymous]
    public async Task<IActionResult> GetLogo(string id)
    {
        var logo = await _clientService.GetLogoAsync(id);
        if (logo is null)
            return NotFound();
        var (bytes, contentType) = logo.Value;
        if (bytes is null)
            return NotFound();
        Response.Headers["X-Content-Type-Options"] = "nosniff";
        return File(bytes, contentType ?? "application/octet-stream");
    }

    [HttpPut("{id}/logo")]
    [RequestSizeLimit(2L * 1024L * 1024L)]
    public async Task<IActionResult> UploadLogo(string id, IFormFile file)
    {
        if (file is null || file.Length == 0)
            return BadRequest(new ApiResponse { Success = false, Error = "请选择要上传的 Logo 文件。", ErrorCode = "invalid_request" });
        try
        {
            var result = await _clientService.UploadLogoAsync(id, file);
            if (!result)
                return NotFound(new ApiResponse { Success = false, Error = "客户端不存在。", ErrorCode = "not_found" });
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientLogoUpdated,
                null, null, true, $"Updated logo for client {id}");
            _logger.LogInformation("客户端 Logo 上传 | Id:{Id}", id);
            return NoContent();
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new ApiResponse { Success = false, Error = ex.Message, ErrorCode = "invalid_request" });
        }
    }

    [HttpDelete("{id}/logo")]
    public async Task<IActionResult> DeleteLogo(string id)
    {
        var result = await _clientService.DeleteLogoAsync(id);
        if (!result)
            return NotFound(new ApiResponse { Success = false, Error = "客户端不存在或没有 Logo。", ErrorCode = "not_found" });
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ClientLogoDeleted,
            null, null, true, $"Deleted logo for client {id}");
        _logger.LogInformation("客户端 Logo 删除 | Id:{Id}", id);
        return NoContent();
    }

    private static bool TryValidateCreate(ClientCreateRequest request, out string error)
    {
        error = string.Empty;
        var clientId = request.ClientId?.Trim() ?? string.Empty;
        if (clientId.Length is < 1 or > 128) { error = "ClientId 不能为空且不能超过 128 字符。"; return true; }
        if (string.IsNullOrWhiteSpace(request.DisplayName)) { error = "DisplayName 不能为空。"; return true; }
        if (!string.Equals(request.Type, "Confidential", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(request.Type, "Public", StringComparison.OrdinalIgnoreCase))
        {
            error = "Type 仅支持 Confidential 或 Public。"; return true;
        }
        if (request.Scopes is null || request.Scopes.Count == 0) { error = "Scopes 不能为空。"; return true; }
        if (request.GrantTypes is null || request.GrantTypes.Count == 0) { error = "GrantTypes 不能为空。"; return true; }

        return ValidateUris(request.RedirectUris ?? [], "RedirectUris", out error)
            || ValidateUris(request.PostLogoutRedirectUris ?? [], "PostLogoutRedirectUris", out error);
    }

    private static bool TryValidateUpdate(ClientUpdateRequest request, out string error)
    {
        error = string.Empty;
        if (request.RedirectUris is not null
            && ValidateUris(request.RedirectUris, "RedirectUris", out error))
            return true;
        if (request.PostLogoutRedirectUris is not null
            && ValidateUris(request.PostLogoutRedirectUris, "PostLogoutRedirectUris", out error))
            return true;
        return false;
    }

    private static bool ValidateUris(IEnumerable<string> uris, string field, out string error)
    {
        error = string.Empty;
        foreach (var value in uris)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
                || (uri.Scheme != "http" && uri.Scheme != "https")
                || string.IsNullOrEmpty(uri.Host))
            {
                error = $"{field} 包含非法 URI: {value}";
                return true;
            }
        }

        return false;
    }
}

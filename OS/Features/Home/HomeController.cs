using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Home;

[ApiController]
[Route("")]
public class HomeController : Controller
{
    private readonly ApplicationDbContext _context;

    public HomeController(ApplicationDbContext context)
    {
        _context = context;
    }

    [HttpGet("/")]
    public async Task<IActionResult> Index()
    {
        if (User.Identity?.IsAuthenticated ?? false)
        {
            var user = await this.GetCurrentUserAsync(_context);

            return Ok(new
            {
                authenticated = true,
                name = User.Identity.Name,
                displayName = user?.DisplayName ?? User.Identity.Name
            });
        }

        return Unauthorized(new { authenticated = false });
    }

    [HttpGet("/error")]
    [ApiExplorerSettings(IgnoreApi = true)]
    public IActionResult Error()
    {
        return Problem(
            detail: "An unexpected error occurred.",
            statusCode: 500,
            title: "Server Error");
    }
}

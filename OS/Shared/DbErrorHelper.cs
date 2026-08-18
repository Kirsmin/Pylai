using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public static class DbErrorHelper
{
    public static string? SqlState(this Exception exception)
    {
        for (var current = exception; current is not null; current = current.InnerException)
        {
            if (current is Npgsql.PostgresException { SqlState: var state })
                return state;
        }

        return null;
    }

    public static bool IsUniqueViolation(this Exception exception)
        => exception.SqlState() == "23505";
}

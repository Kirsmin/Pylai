using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public static class DbErrorHelper
{
    public static bool IsUniqueViolation(this Exception exception)
    {
        for (var current = exception; current is not null; current = current.InnerException)
        {
            if (current is Npgsql.PostgresException { SqlState: "23505" })
                return true;
        }

        return false;
    }
}

from django.contrib.auth.hashers import Argon2PasswordHasher


class ApplicationArgon2PasswordHasher(Argon2PasswordHasher):
    """Argon2id above OWASP's 19 MiB/t=2/p=1 minimum, bounded per login.

    One lane avoids oversubscribing small shared-CPU instances. Each active hash
    uses about 32 MiB; include that in the Gunicorn worker/concurrency budget.
    """
    time_cost = 2
    memory_cost = 32768  # KiB, not bytes or a logarithmic exponent.
    parallelism = 1

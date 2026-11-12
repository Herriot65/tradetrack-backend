# Response-time investigation

The browser's sign-in loading state awaits `POST /api/auth/login/`. The login
response already includes the user, so navigation must not wait for a second
profile request or for the journal list. There is no fixed five-second UI timer.
Connection failures/502/503/504 retain the existing bounded recovery retries.

Every API response now includes `Server-Timing: app;dur=<milliseconds>`.
Processing times of at least one second also emit a server warning with the
method, route pattern, status and duration, excluding user input and credentials.
The header measures Django processing, including authentication and database
work. It excludes browser/network time, worker queueing and platform startup.
Compare this value with the login request's Timing tab in browser DevTools to
locate the remaining deployed delay. A slow first request followed by fast warm
requests can indicate hosting startup; confirm with platform logs before changing
hosting. Compare application/database regions and database query timings when
server processing remains slow. Do not reduce password hashing cost to hide it.

Database connections are reused for up to 600 seconds with health checks for both
`DATABASE_URL` and individual `POSTGRES_*` configurations. `DB_CONN_MAX_AGE` can
adjust this value (use `0` for environments that require per-request connections).
The URL configuration previously reused connections; the individual settings did
not. These settings target the existing synchronous WSGI/Gunicorn deployment.
Iterators avoid Django's result cache. Named server-side cursors default to
disabled for compatibility with transaction poolers. Direct PostgreSQL deployments
can set `DB_DISABLE_SERVER_SIDE_CURSORS=False` to enable server-side streaming.

The dashboard summary now uses one conditional aggregate plus a narrow streamed
PnL query for drawdown: two queries instead of nine. Win/loss distribution uses
one aggregate instead of three. Explicit status overrides, BE thresholds and open
positions retain their existing semantics. Equity, career and timing calculations
stream only the fields they use. No database migrations are required.

Run the backend suite against an isolated database:

```sh
DATABASE_URL=sqlite:////tmp/tradetrack-performance.sqlite3 python -m pytest -q
```

`tests/test_performance.py` enforces query budgets, checks mixed automatic/manual
statuses, and verifies login works even when the browser supplies a stale bearer
token. It also checks the timing header. Local SQLite timings do not establish
production network or PostgreSQL latency. In this environment default password
verification initially had a five-sample median of about 162 ms. Later production
measurements are documented below.

## Authentication changes after the production benchmark

The successful-login benchmark on 2026-11-12 recorded six empty-account dashboard
loads of 3.09–3.84 seconds (median 3.50 seconds), with 2.57–3.10 seconds inside the
login endpoint. These are GitHub-runner measurements, not a phone/network SLA.

New password hashes use Argon2id with 32 MiB of memory, two passes and one lane.
This exceeds OWASP's minimum Argon2id profile of 19 MiB/t=2/p=1, while bounding
hash memory and avoiding eight hashing threads on small shared-CPU machines.
Existing PBKDF2 and other supported Django hashes remain verifiable. Django
upgrades the stored hash only after a successful password check. That first
legacy login still pays the old verification cost, the new encoding cost and
one password UPDATE; subsequent logins use Argon2id. No password reset or data
migration is required. Do not remove the legacy hashers from the settings list.

A local seven-sample verification benchmark measured PBKDF2 at 170.5 ms versus
Argon2id at 45.9 ms. Production improvement must be measured after deployment:

```sh
python manage.py benchmark_password_hashers --samples 7
```

This command uses synthetic passwords, does not query or change user accounts,
and reports both wall time and hashing-thread CPU time. The parameters follow
[Django's Argon2 integration](https://docs.djangoproject.com/en/6.0/topics/auth/passwords/#using-argon2-with-django)
and [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#argon2id).

Login responses now expose the following `Server-Timing` phases alongside `app`:

- `db_connect`: establishing a connection if one is not already open.
- `user_lookup`: account lookup, including any per-request health check.
- `password`: verification or unknown-user dummy hashing. Includes encoding and
  saving the replacement hash during a one-time legacy upgrade.
- `password_cpu`: CPU consumed on the hashing thread during that same phase.
  A large wall/CPU gap can indicate scheduling or CPU quota pressure; during a
  legacy upgrade it also includes waiting for the password UPDATE.
- `session`: JWT creation, token persistence and user serialization, on success.

The backend follows Django ModelBackend's inactive-account and unknown-user
behavior and returns generic credential rejections. Headers contain durations
only. Login responses explicitly disallow caching, and CORS exposes the timing
header for browser diagnostics. Connection and query phase timings include
application-to-database round trips; database execution statistics alone do not.

Budget about 32 MiB per concurrent Argon2 operation plus the Python application's
normal memory. Keep the existing worker count unless host memory and concurrency
measurements justify a change. Persistent workers, same-region API/database
placement, and separate AI/background workers remain deployment considerations.

For rollback, keep argon2-cffi installed and keep
`users.hashers.ApplicationArgon2PasswordHasher` in `PASSWORD_HASHERS` so upgraded
accounts remain readable. Returning PBKDF2 to the first position changes future
hashing policy; removing Argon2 support would lock out upgraded accounts.

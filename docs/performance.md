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
verification had a five-sample median of about 162 ms; the reported five-second
production delay has not been reproduced against a deployed session.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TraderTrackAnalytics is a Django REST Framework API for tracking and analyzing trading activity. It supports multi-user trading journals, per-journal asset/tag catalogs, trade management, and analytics.

## Development Setup

**Start the database:**
```bash
docker-compose up -d
```

**Activate the virtual environment (Windows):**
```bash
venv\Scripts\activate
```

**Run the dev server:**
```bash
python manage.py runserver
```

**Apply migrations:**
```bash
python manage.py migrate
python manage.py makemigrations  # after model changes
```

**Environment:** Copy `.env.example` to `.env` before first run.

**Reset the database** (required after the Workspace → Journal refactor):
```bash
docker-compose down -v && docker-compose up -d
python manage.py migrate
```

## Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_trade_api.py

# With coverage
pytest --cov=core --cov=users
```

Test factories live in `tests/factories.py` (Factory Boy). Use them for all test data — don't create model instances directly.

## Architecture

### Apps

- **`users/`** — Custom email-based User model, JWT auth endpoints (register, login, logout, me, token refresh). A default `Journal` named "Main" is auto-created for each user via `users/signals.py`.
- **`core/`** — Journal, catalog models, Trade, and analytics. All trade data is scoped to a journal owned by the authenticated user.
- **`config/`** — Django project settings and root URL config.

### Key Design Patterns

**Multi-tenancy via journals:** Every `Trade` belongs to a `Journal`. Ownership is enforced at the view layer by filtering all querysets to `journal__user=request.user`. The `IsJournalOwner` permission class (`core/permissions.py`) provides object-level checks for journal CRUD.

**Per-journal catalogs:** `Asset`, `EmotionTag`, `MistakeTag`, and `SetupTag` are scoped to a journal. FKs from Trade to catalog items use `on_delete=PROTECT`. When a catalog item is deleted via the API and is referenced by a trade, it is auto-archived (`is_archived=True`) instead of hard-deleted.

**Analytics are computed in `core/services.py`**, not in views or models. Functions receive a queryset of trades and return computed dicts. "Closed" trades are those with `exit_datetime` and `pnl_r` both set.

**Status is nullable on Trade.** `null` means auto-derive: `pnl_r > 0` → WIN, `< 0` → LOSS, `= 0` → BE, `exit_datetime is null` → OPEN. OPEN cannot be manually set.

**Trade filtering** is handled by `core/filters.py`. Trades support filtering by `side`, `status`, `trend_direction`, `session`, and entry datetime range, plus full-text search on `asset__symbol` and `notes`.

### Data Model Summary

- `User` — email-based auth, no username field
- `Journal` — integer PK, unique per (user, name), fields: journal_type, starting_capital, currency, break_even_method
- `Asset`, `EmotionTag`, `MistakeTag`, `SetupTag` — per-journal catalogs with `is_archived` soft-delete
- `Trade` — FK to Journal, FK to Asset, FK to SetupTag, M2M to EmotionTag and MistakeTag; pnl_r and status are nullable
- `TradeEmotion`, `TradeMistake` — explicit M2M through tables
- `TradeScreenshot` — stores `image_url` (Supabase public URL) + `uploaded_at`; no binary data in DB

### API Structure

All routes are scoped to a journal under `/api/journals/`:

- `/api/auth/` — authentication endpoints
- `/api/journals/` — journal CRUD
- `/api/journals/{id}/assets/` — asset catalog CRUD
- `/api/journals/{id}/emotion-tags/` — emotion tag catalog CRUD
- `/api/journals/{id}/mistake-tags/` — mistake tag catalog CRUD
- `/api/journals/{id}/setup-tags/` — setup tag catalog CRUD
- `/api/journals/{id}/trades/` — trade CRUD (paginated, filterable)
- `/api/journals/{id}/dashboard/summary/` — aggregate stats
- `/api/journals/{id}/analytics/equity-curve/` — equity curve by period
- `/api/journals/{id}/analytics/win-loss-distribution/` — win/loss counts
- `/api/journals/{id}/analytics/pnl-by-setup/` — P&L grouped by setup tag
- `/api/journals/{id}/analytics/career/` — year summaries and monthly heatmap

### Trade API Write/Read Contract

**Write** (create/update) uses flat ID fields: `asset_id`, `setup_id`, `emotion_ids[]`, `mistake_ids[]`

**Read** (list/retrieve) returns expanded nested objects: `asset: {id, symbol}`, `setup: {id, label}`, `emotions: [{id, label}]`, `mistakes: [{id, label}]`

### Auth

JWT via `djangorestframework-simplejwt`. Access tokens expire in 15 minutes; refresh tokens in 7 days with rotation and blacklisting enabled. CORS is configured for `localhost:5173` (expected frontend dev server).

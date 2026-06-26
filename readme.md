# TraderTrack Analytics — Backend

Django REST Framework API for tracking and analyzing trading activity. Supports multi-user trading journals, per-journal asset/tag catalogs, trade management, MT5 HTML import, and a full analytics suite.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 6 + Django REST Framework |
| Database | PostgreSQL 16 (Docker) |
| Auth | JWT via `djangorestframework-simplejwt` |
| Import | BeautifulSoup4 (MT5 HTML parsing) |
| Tests | pytest + pytest-django + Factory Boy |

---

## Quick Start

### Prerequisites
- Python 3.12+
- Docker & Docker Compose

### 1. Clone and set up the environment

```bash
git clone <repo-url>
cd traderTrackAnalytics

cp .env.example .env
# Edit .env if needed (defaults work for local dev)

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 2. Start the database

```bash
docker-compose up -d
```

### 3. Run migrations and start the server

```bash
python manage.py migrate
python manage.py runserver
```

The API is available at `http://localhost:8000/api/`.

---

## Environment Variables

Copy `.env.example` to `.env`. All variables have local-dev defaults.

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | `django-insecure-dev-only-change-me` | Django secret key — **change in production** |
| `POSTGRES_DB` | `tradertrack` | Database name |
| `POSTGRES_USER` | `tradertrack` | Database user |
| `POSTGRES_PASSWORD` | `tradertrack` | Database password |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |

---

## Running Tests

```bash
# All tests
pytest

# Single file
pytest tests/test_trade_api.py

# With coverage
pytest --cov=core --cov=users
```

Test factories live in `tests/factories.py` (Factory Boy). Use them for all test data.

---

## Architecture

### Apps

- **`users/`** — Custom email-based `User` model. JWT auth endpoints (register, login, logout, token refresh, me). A default `Journal` named "Main" is auto-created for each new user via `users/signals.py`.
- **`core/`** — Journals, catalog models, trades, MT5 import, and analytics. All trade data is scoped to a journal owned by the authenticated user.
- **`config/`** — Django project settings and root URL config.

### Key Design Patterns

**Multi-tenancy via journals** — Every `Trade` belongs to a `Journal`. Ownership is enforced at the view layer by filtering all querysets to `journal__user=request.user`.

**Per-journal catalogs** — `Asset`, `EmotionTag`, `MistakeTag`, and `SetupTag` are scoped to a journal. When a catalog item is deleted and is referenced by a trade, it is auto-archived (`is_archived=True`) instead of hard-deleted.

**Analytics computed in `core/services.py`** — Never in views or models. Functions receive a queryset of trades and return computed dicts.

**Break-even threshold** — Every analytics classification (WIN / LOSS / BE) respects the journal's `break_even_value` and `break_even_method` settings. Both "ratio" (pnl_r units) and "profit" (monetary, converted via `starting_capital`) methods are supported.

**Status is nullable on Trade** — `null` means auto-derive: `pnl_r > threshold` → WIN, `< -threshold` → LOSS, within threshold → BE, no exit → OPEN. OPEN cannot be set manually.

---

## Data Model

```
User
└── Journal (unique per user+name)
    ├── Asset          (symbol catalog, per journal)
    ├── EmotionTag     (per journal)
    ├── MistakeTag     (per journal)
    ├── SetupTag       (per journal)
    ├── Trade          (FK → Asset, SetupTag; M2M → EmotionTag, MistakeTag)
    │   └── TradeScreenshot
    └── ImportBatch
        └── TradeImport (one per imported trade; stores raw_profit for recomputation)
```

---

## API Reference

### Authentication — `/api/auth/`

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/auth/register/` | Create account |
| POST | `/api/auth/login/` | Obtain access + refresh tokens |
| POST | `/api/auth/logout/` | Blacklist refresh token |
| POST | `/api/auth/token/refresh/` | Rotate refresh token |
| GET | `/api/auth/me/` | Current user profile |

JWT tokens: access expires in **2 days**, refresh in **7 days** (with rotation and blacklisting).

---

### Journals — `/api/journals/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/journals/` | List user's journals |
| POST | `/api/journals/` | Create journal |
| GET | `/api/journals/{id}/` | Journal detail |
| PATCH | `/api/journals/{id}/` | Update journal settings |
| DELETE | `/api/journals/{id}/` | Delete journal |

**Journal fields:**

| Field | Type | Notes |
|---|---|---|
| `name` | string | Unique per user |
| `journal_type` | `"trading"` \| `"backtest"` | |
| `starting_capital` | decimal | Required for pnl_r computation. Changing this **automatically recomputes `pnl_r`** for all imported trades. |
| `currency` | string | Display only (e.g. `"USD"`) |
| `break_even_method` | `"ratio"` \| `"profit"` | How `break_even_value` is interpreted |
| `break_even_value` | decimal | Trades within this threshold are classified as BE in all analytics |

---

### Catalog endpoints (per journal)

All follow the same pattern under `/api/journals/{id}/`:

| Resource | List/Create | Detail |
|---|---|---|
| Assets | `assets/` | `assets/{pk}/` |
| Emotion tags | `emotion-tags/` | `emotion-tags/{pk}/` |
| Mistake tags | `mistake-tags/` | `mistake-tags/{pk}/` |
| Setup tags | `setup-tags/` | `setup-tags/{pk}/` |

DELETE auto-archives instead of hard-deleting when the item is referenced by a trade.

---

### Trades — `/api/journals/{id}/trades/`

| Method | Endpoint | Description |
|---|---|---|
| GET | `trades/` | List trades (paginated, filterable) |
| POST | `trades/` | Create trade |
| GET | `trades/{pk}/` | Trade detail |
| PATCH | `trades/{pk}/` | Update trade |
| DELETE | `trades/{pk}/` | Delete trade |

**Write** (create/update) uses flat ID fields: `asset_id`, `setup_id`, `emotion_ids[]`, `mistake_ids[]`.  
**Read** (list/retrieve) returns expanded nested objects: `asset: {id, symbol}`, `setup: {id, label}`, etc.

**Filters:** `side`, `status`, `trend_direction`, `session`, `entry_datetime` range.  
**Search:** `asset__symbol`, `notes`.  
**Ordering:** `entry_datetime`, `created_at`, `pnl_r`.

---

### MT5 Import — `/api/journals/{id}/imports/mt5/`

```
POST /api/journals/{id}/imports/mt5/
Content-Type: multipart/form-data
Body: file=<MT5 HTML report>
```

Accepts an MT5 HTML account statement or history report.

**Supported formats:**
- UTF-16 LE encoded single-table reports (standard Deriv/MT5 "Save as Report")
- UTF-8 encoded multi-table legacy exports

**How it works:**
1. Parses the HTML (Deals section preferred; Positions section as fallback)
2. Pairs entry/exit deals using FIFO per symbol
3. Handles `in/out` reversal deals (closes the existing position, opens a new one)
4. Imports unmatched `in` deals as open trades (no `exit_datetime`)
5. Deduplicates by `(journal, source, external_id)` — safe to re-import the same file
6. `pnl_r` = `raw_profit / starting_capital × 100` (stored; recomputed if capital changes)

**Response:**

```json
{
  "success": true,
  "import_id": 1,
  "format_detected": "deals",
  "raw_rows_found": 110,
  "rows_parsed": 54,
  "trades_created": 52,
  "trades_skipped": 2,
  "trades_failed": 0,
  "failures": [],
  "warnings": []
}
```

---

### Analytics

All analytics endpoints are under `/api/journals/{id}/` and require authentication. The break-even threshold from journal settings is applied automatically to every classification.

#### Dashboard summary

```
GET /api/journals/{id}/dashboard/summary/
```

```json
{
  "has_data": true,
  "total_trades": 54,
  "win_rate": 62.5,
  "total_r": 18.4,
  "profit_factor": 2.1,
  "max_drawdown_r": 3.2,
  "average_r": 0.34
}
```

#### Equity curve

```
GET /api/journals/{id}/analytics/equity-curve/?period=weekly
```

`period`: `weekly` (default) | `monthly` | `yearly`

```json
[{"date": "2024-01-01", "equity_r": 4.2}, ...]
```

#### Win/loss distribution

```
GET /api/journals/{id}/analytics/win-loss-distribution/
```

```json
{"has_data": true, "wins": 34, "losses": 16, "break_even": 4}
```

#### P&L by setup

```
GET /api/journals/{id}/analytics/pnl-by-setup/
```

```json
[{"setup": "ICT BOS", "total_r": 8.4}, ...]
```

#### Career

```
GET /api/journals/{id}/analytics/career/
```

Top-level fields are all-time stats. Each `yearSummaries` entry contains the same KPI fields scoped to that year.

```json
{
  "has_data": true,
  "years": [2024, 2023],
  "total_trades": 120,
  "max_win_streak": 8,
  "max_loss_streak": 4,
  "avg_consecutive_wins": 2.5,
  "avg_consecutive_losses": 1.3,
  "expectancy": 0.42,
  "avg_win_r": 1.85,
  "avg_loss_r": -0.90,
  "max_drawdown": 6.4,
  "yearSummaries": [
    {
      "year": 2024,
      "total_r": 10.5,
      "total_trades": 54,
      "win_rate": 62.5,
      "max_win_streak": 5,
      "max_loss_streak": 3,
      "avg_consecutive_wins": 2.1,
      "avg_consecutive_losses": 1.2,
      "expectancy": 0.44,
      "avg_win_r": 1.90,
      "avg_loss_r": -0.88,
      "max_drawdown": 3.2
    }
  ],
  "heatmap": {
    "2024": {"0": 1.2, "1": -0.5, ...}
  }
}
```

`heatmap` months are 0-indexed (0 = January).

#### Performance by day

```
GET /api/journals/{id}/analytics/performance-by-day/?tz=Africa/Douala
```

Always returns all 7 weekdays (Mon→Sun). `?tz=` accepts any IANA timezone name (default: `UTC`).

```json
[
  {"day": "Monday", "day_index": 0, "trade_count": 12, "win_count": 8, "win_rate": 66.67, "total_r": 4.2},
  ...
]
```

`day_index` is 0=Monday … 6=Sunday.

#### Performance by hour

```
GET /api/journals/{id}/analytics/performance-by-hour/?tz=America/New_York
```

Returns only hours with at least one trade, sorted 0→23. `?tz=` same as above.

```json
[
  {"hour": 9, "trade_count": 11, "win_count": 7, "win_rate": 63.64, "total_r": 3.85},
  ...
]
```

---

## Project Structure

```
traderTrackAnalytics/
├── config/               # Django settings & root URLs
├── users/                # Custom User model, JWT auth, signal (auto-create journal)
├── core/
│   ├── models.py         # Journal, Asset, Tag, Trade, ImportBatch, TradeImport
│   ├── serializers.py    # DRF serializers
│   ├── views.py          # API views
│   ├── urls.py           # URL routing
│   ├── services.py       # All analytics logic
│   ├── filters.py        # Trade filtering
│   ├── permissions.py    # IsJournalOwner
│   ├── pagination.py     # JournalPagination
│   └── importers/
│       └── mt5/
│           ├── parser.py   # HTML → raw rows
│           ├── mapper.py   # Raw rows → trade dicts
│           └── importer.py # Persist + dedup
├── tests/
│   ├── factories.py
│   ├── test_auth_workspaces.py
│   ├── test_trade_model.py
│   ├── test_trade_api.py
│   ├── test_analytics.py
│   └── test_mt5_import.py
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

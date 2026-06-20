# Backend Report — TraderTrackAnalytics

_Generated: 2026-06-20_

---

## 1. Stack

| Layer | Technology |
|-------|-----------|
| Framework | Django 6.0 + Django REST Framework |
| Database | PostgreSQL (Docker) |
| Auth | JWT via `djangorestframework-simplejwt` |
| Filtering | `django-filter` |
| Testing | pytest + Factory Boy |
| Language | Python 3.x |

---

## 2. Apps

### `users/`
Custom auth layer. No changes from the original setup.

- **`User`** model — email-based (no username), `AbstractBaseUser` + `PermissionsMixin`
- **Signal** (`users/signals.py`) — creates a default `Journal` named "Main" on registration
- **Endpoints** — register, login, logout, me, token refresh

### `core/`
All business logic: journals, catalog entities, trades, and analytics.

---

## 3. Data Model

### 3.1 Journal
Top-level container. Replaces the old `Workspace` model.

| Field | Type | Notes |
|-------|------|-------|
| `id` | integer (auto PK) | replaces old UUID PK |
| `user` | FK → User | |
| `name` | CharField(255) | unique per user |
| `journal_type` | `"trading" \| "backtest"` | |
| `starting_capital` | DecimalField | default 0 |
| `currency` | CharField(10) | default "USD" |
| `break_even_method` | `"ratio" \| "profit"` | default "ratio" |
| `created_at` / `updated_at` | DateTimeField | |

**Constraint:** `unique_journal_name_per_user`

---

### 3.2 Catalog Models
Four per-journal catalogs. All follow the same pattern: journal FK, soft-delete via `is_archived`, and `PROTECT` on the Trade FK so referenced items cannot be hard-deleted.

#### Asset
```
id, journal (FK), symbol (CharField 20, uppercased on save), name (CharField 100), is_archived
```
Constraint: `unique_asset_symbol_per_journal`

#### EmotionTag
```
id, journal (FK), label (CharField 50), is_archived
```

#### MistakeTag
```
id, journal (FK), label (CharField 50), is_archived
```

#### SetupTag
```
id, journal (FK), label (CharField 100), is_archived
```

---

### 3.3 Trade
Core entity. Owns references to all catalog items.

#### Execution fields
| Field | Type | Notes |
|-------|------|-------|
| `journal` | FK → Journal | `CASCADE` |
| `asset` | FK → Asset | `PROTECT` |
| `side` | `"BUY" \| "SELL"` | |
| `entry_datetime` | DateTimeField | required |
| `exit_datetime` | DateTimeField | nullable — null = open |
| `risk_percent` | DecimalField(5,2) | nullable |
| `pnl_r` | DecimalField(8,2) | nullable — R-multiple |
| `commission` | DecimalField(10,2) | nullable |
| `swap` | DecimalField(10,2) | nullable |

#### Context fields
| Field | Type | Notes |
|-------|------|-------|
| `opportunity_timeframe` | CharField(10) | nullable, free text |
| `entry_timeframe` | CharField(10) | nullable, free text |
| `trend_direction` | `"BULLISH" \| "BEARISH" \| "RANGE"` | nullable |
| `setup` | FK → SetupTag | `PROTECT`, nullable |
| `session` | CharField(50) | nullable, free text |

#### Psychology fields
| Field | Type | Notes |
|-------|------|-------|
| `emotions` | M2M → EmotionTag | via `TradeEmotion` |
| `mistakes` | M2M → MistakeTag | via `TradeMistake`, optional |
| `notes` | TextField | nullable |

#### Status
| Field | Type | Notes |
|-------|------|-------|
| `status` | `"WIN" \| "LOSS" \| "BE" \| null` | null = auto-derive |

**Derivation rule (frontend + analytics both use this):**
- `exit_datetime is null` → OPEN (not stored; derived display value)
- `pnl_r > 0` → WIN
- `pnl_r < 0` → LOSS
- `pnl_r == 0` → BE
- Explicit `status` field overrides derivation permanently once set

**Model validation (`clean()`):** rejects `exit_datetime <= entry_datetime`

**DB indexes:** `(journal, entry_datetime)`, `(journal, status)`, `(journal, asset)`

---

### 3.4 Through Tables
| Model | Fields |
|-------|--------|
| `TradeEmotion` | `trade` FK, `emotion` FK, unique_together |
| `TradeMistake` | `trade` FK, `mistake` FK, unique_together |

---

### 3.5 TradeScreenshot
Image uploads linked to a trade. `ImageField` stored under `media/trade_screenshots/`.

---

## 4. API Endpoints

Base prefix: `/api/`

### Auth (`/api/auth/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register/` | Create user (auto-creates default Journal) |
| POST | `/api/auth/login/` | Returns `{access, refresh, user}` |
| GET | `/api/auth/me/` | Current user object |
| POST | `/api/auth/logout/` | Blacklists refresh token |
| POST | `/api/auth/refresh/` | Returns new access token |

---

### Journals (`/api/journals/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/journals/` | List user's journals |
| POST | `/api/journals/` | Create journal |
| GET | `/api/journals/{id}/` | Retrieve journal |
| PATCH | `/api/journals/{id}/` | Update journal |
| DELETE | `/api/journals/{id}/` | Delete journal + all its trades |

**Create body:**
```json
{
  "name": "Main Account",
  "journal_type": "trading",
  "starting_capital": "10000.00",
  "currency": "USD",
  "break_even_method": "ratio"
}
```

---

### Catalog CRUD
Same pattern for all four types. Replace `{catalog}` with `assets`, `emotion-tags`, `mistake-tags`, or `setup-tags`.

| Method | Path | Body |
|--------|------|------|
| GET | `/api/journals/{id}/{catalog}/` | — |
| POST | `/api/journals/{id}/{catalog}/` | `{symbol}` or `{label}` |
| PATCH | `/api/journals/{id}/{catalog}/{itemId}/` | `{symbol}` or `{label}` |
| DELETE | `/api/journals/{id}/{catalog}/{itemId}/` | — |

**DELETE behavior:** if the item is referenced by any trade (`PROTECT` FK), it is auto-archived (`is_archived=true`) and returned with HTTP 200. Otherwise deleted and returns HTTP 204.

**Asset response:**
```json
{ "id": 1, "symbol": "EURUSD", "name": "", "is_archived": false }
```

**Tag response (emotion / mistake / setup):**
```json
{ "id": 3, "label": "Calm", "is_archived": false }
```

---

### Trades
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/journals/{id}/trades/` | Paginated, filterable |
| POST | `/api/journals/{id}/trades/` | |
| GET | `/api/journals/{id}/trades/{tradeId}/` | |
| PATCH | `/api/journals/{id}/trades/{tradeId}/` | |
| DELETE | `/api/journals/{id}/trades/{tradeId}/` | |

**List query parameters:**
| Param | Notes |
|-------|-------|
| `page` | Page number (default 1) |
| `page_size` | Items per page (default 20, max 100) |
| `ordering` | e.g. `-entry_datetime`, `pnl_r` |
| `status` | `WIN`, `LOSS`, `BE` |
| `side` | `BUY`, `SELL` |
| `trend_direction` | `BULLISH`, `BEARISH`, `RANGE` |
| `session` | free text |
| `entry_datetime__gte` / `entry_datetime__lte` | ISO 8601 |
| `search` | full-text on `asset__symbol`, `notes` |

**Write (create/update) request body:**
```json
{
  "asset_id": 1,
  "side": "BUY",
  "entry_datetime": "2025-06-12T09:30:00Z",
  "exit_datetime": "2025-06-12T14:00:00Z",
  "risk_percent": "1.00",
  "pnl_r": "1.50",
  "commission": "0.00",
  "swap": "0.00",
  "opportunity_timeframe": "D1",
  "entry_timeframe": "H4",
  "trend_direction": "BULLISH",
  "setup_id": 1,
  "session": "London",
  "status": null,
  "emotion_ids": [1, 2],
  "mistake_ids": [],
  "notes": "Clean setup."
}
```

**Read response (catalog fields expanded):**
```json
{
  "id": 30,
  "asset": { "id": 1, "symbol": "EURUSD" },
  "side": "BUY",
  "entry_datetime": "2025-06-12T09:30:00Z",
  "exit_datetime": "2025-06-12T14:00:00Z",
  "risk_percent": "1.00",
  "pnl_r": "1.50",
  "commission": "0.00",
  "swap": "0.00",
  "opportunity_timeframe": "D1",
  "entry_timeframe": "H4",
  "trend_direction": "BULLISH",
  "setup": { "id": 1, "label": "Break of Structure" },
  "session": "London",
  "status": null,
  "emotions": [{ "id": 1, "label": "Calm" }],
  "mistakes": [],
  "notes": "Clean setup.",
  "created_at": "2025-06-12T09:30:00Z",
  "updated_at": "2025-06-12T14:05:00Z"
}
```

**List response envelope:**
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/journals/1/trades/?page=2",
  "previous": null,
  "results": [ ... ]
}
```

---

### Analytics
All analytics are scoped to the journal and operate only on **closed trades** (both `exit_datetime` and `pnl_r` set).

| Endpoint | Response shape |
|----------|---------------|
| `GET /api/journals/{id}/dashboard/summary/` | `{total_trades, win_rate, total_r, profit_factor, max_drawdown_r, average_r}` |
| `GET /api/journals/{id}/analytics/equity-curve/?period=weekly\|monthly\|yearly` | `[{date, equity_r}]` cumulative |
| `GET /api/journals/{id}/analytics/win-loss-distribution/` | `{wins, losses, break_even}` |
| `GET /api/journals/{id}/analytics/pnl-by-setup/` | `[{setup, total_r}]` sorted descending |
| `GET /api/journals/{id}/analytics/career/` | `{yearSummaries, heatmap, years}` |

**Dashboard example:**
```json
{ "total_trades": 30, "win_rate": 60.71, "total_r": 26.0, "profit_factor": 3.6, "max_drawdown_r": -1.0, "average_r": 0.93 }
```

**Career example:**
```json
{
  "yearSummaries": [{ "year": 2025, "total_r": 14.5, "total_trades": 20, "win_rate": 60.0 }],
  "heatmap": { "2025": { "0": 1.5, "2": 3.0 } },
  "years": [2025]
}
```

---

## 5. Auth Details

- JWT Bearer tokens via `Authorization: Bearer <token>` header
- Access token lifetime: **15 minutes**
- Refresh token lifetime: **7 days** with rotation and blacklisting
- CORS allowed origin: `http://localhost:5173`

---

## 6. Key Implementation Notes

### Catalog soft-delete
FKs from Trade → Asset/SetupTag use `on_delete=PROTECT`. The API `destroy()` method catches `ProtectedError` and sets `is_archived=True` instead, returning the updated object.

### Trade write/read split
`TradeSerializer` exposes `*_id` write-only fields and nested `*` read-only fields for catalog relations. M2M relations (`emotion_ids`, `mistake_ids`) are handled via explicit `.set()` calls in `create()` and `update()`.

### Status derivation
The stored `status` field only accepts `WIN`, `LOSS`, `BE`, or `null`. The value `OPEN` is never stored — analytics and the frontend derive it from `exit_datetime is null`. Attempting to POST `"status": "OPEN"` returns a 400 error.

### Analytics win/loss counting
Since `status` can be null, the services check both the stored value and the pnl_r-derived value:
```
WIN  ← status="WIN"  OR (status=null AND pnl_r > 0)
LOSS ← status="LOSS" OR (status=null AND pnl_r < 0)
BE   ← status="BE"   OR (status=null AND pnl_r = 0)
```

### Pagination
Custom `JournalPagination` class supports `page_size` query param (default 20, max 100).

---

## 7. File Map

| File | Purpose |
|------|---------|
| `config/settings.py` | DB, JWT, CORS, REST config |
| `config/urls.py` | Root URL routing |
| `users/models.py` | Custom email-based User |
| `users/serializers.py` | Register + User serializers |
| `users/views.py` | Auth views |
| `users/signals.py` | Auto-creates default Journal on registration |
| `core/models.py` | Journal, Asset, EmotionTag, MistakeTag, SetupTag, Trade, through tables, TradeScreenshot |
| `core/serializers.py` | JournalSerializer, catalog serializers, TradeSerializer |
| `core/views.py` | JournalViewSet, catalog views, trade views, analytics views |
| `core/urls.py` | All API routes |
| `core/filters.py` | TradeFilter (django-filter) |
| `core/services.py` | Analytics computation (dashboard, equity curve, distribution, pnl-by-setup, career) |
| `core/permissions.py` | IsJournalOwner |
| `core/pagination.py` | JournalPagination (page_size support) |
| `core/admin.py` | Django admin registrations |
| `core/migrations/0001_initial.py` | Full schema (fresh after refactor) |
| `tests/factories.py` | UserFactory, JournalFactory, AssetFactory, EmotionTagFactory, MistakeTagFactory, SetupTagFactory, TradeFactory |
| `tests/test_trade_api.py` | Trade + journal + catalog endpoint tests |
| `tests/test_analytics.py` | Analytics endpoint tests |
| `tests/test_auth_workspaces.py` | Registration + default journal creation tests |
| `tests/test_trade_model.py` | Model validation tests |

---

## 8. Known Gaps (Not Yet Implemented)

| Gap | Notes |
|-----|-------|
| Trade notes sections / screenshots | `notesSections` (3-section rich-note blobs with images) — frontend stores locally, no API endpoint yet |
| `break_even_method` backend derivation | Field is persisted and returned but the backend does not yet branch on it when computing BE status |
| Catalog sync from localStorage defaults | Frontend default catalog items are in localStorage; migration to API-backed catalogs requires a one-time seeding step |
| `TradeScreenshot` upload endpoint | Model exists, no DRF endpoint exposed |

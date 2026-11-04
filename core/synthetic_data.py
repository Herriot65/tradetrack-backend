from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from .models import (
    Asset,
    EmotionTag,
    MistakeTag,
    SetupTag,
    Trade,
    TradeEmotion,
    TradeMistake,
)

_ASSETS = [
    ("EURUSD", "Euro / US Dollar"),
    ("GBPUSD", "British Pound / US Dollar"),
    ("USDJPY", "US Dollar / Japanese Yen"),
    ("AUDUSD", "Australian Dollar / US Dollar"),
    ("USDCAD", "US Dollar / Canadian Dollar"),
    ("XAUUSD", "Gold / US Dollar"),
    ("GBPJPY", "British Pound / Japanese Yen"),
    ("NAS100", "Nasdaq 100"),
    ("US30", "Dow Jones 30"),
    ("GER40", "DAX 40"),
]

_SETUPS = [
    "Break of Structure",
    "Order Block",
    "Fair Value Gap",
    "Liquidity Grab",
    "Supply & Demand Zone",
    "Trendline Bounce",
    "Support / Resistance",
    "Breaker Block",
]

_EMOTIONS = [
    "Calm",
    "Confident",
    "Anxious",
    "Fearful",
    "FOMO",
    "Disciplined",
    "Impatient",
    "Excited",
    "Frustrated",
    "Neutral",
]

_MISTAKES = [
    "Chased entry",
    "Moved SL",
    "FOMO trade",
    "Overtraded",
    "Ignored plan",
    "Poor risk sizing",
    "Exited too early",
]

_SESSIONS = {
    "London": (7, 11),
    "New York": (12, 16),
    "Asia": (0, 5),
}

_TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"]

_NOTES = [
    "Waited for confirmation before entering.",
    "Clean setup, followed the plan.",
    "Entry was a little early but managed risk.",
    "Took partials at the first target.",
    "Market was choppy — should have stayed out.",
    "Good execution and patience.",
    "Moved stop too soon.",
    "Let the trade run to the planned target.",
    None,
]


def _dec(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def _catalog(model, journal, values, field, defaults_by_value=None):
    objects, created_ids = [], []
    for value in values:
        lookup = {field: value}
        defaults = (defaults_by_value or {}).get(value, {})
        obj, created = model.objects.get_or_create(
            journal=journal, defaults=defaults, **lookup
        )
        if not created and obj.is_archived:
            obj.is_archived = False
            obj.save(update_fields=["is_archived"])
        objects.append(obj)
        if created:
            created_ids.append(obj.pk)
    return objects, created_ids


def _entry_datetime(day, rng):
    session = rng.choices(
        ["London", "New York", "Asia"], weights=[45, 40, 15], k=1
    )[0]
    start, end = _SESSIONS[session]
    hour = rng.randint(start, end)
    minute = rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
    return timezone.make_aware(datetime.combine(day, time(hour, minute))), session


def _pnl_r(rng) -> Decimal:
    roll = rng.random()
    if roll < 0.09:
        return Decimal("0.00")
    if roll < 0.63:
        return _dec(rng.triangular(0.30, 4.20, 1.25))
    return -_dec(rng.triangular(0.20, 1.60, 0.70))


def generate_synthetic_trades(journal, *, months=18, seed=None):
    rng = random.Random(seed if seed is not None else f"tradetrack:{journal.pk}")

    assets, asset_ids = _catalog(
        Asset,
        journal,
        [symbol for symbol, _ in _ASSETS],
        "symbol",
        {symbol: {"name": name} for symbol, name in _ASSETS},
    )
    setups, setup_ids = _catalog(SetupTag, journal, _SETUPS, "label")
    emotions, emotion_ids = _catalog(EmotionTag, journal, _EMOTIONS, "label")
    mistakes, mistake_ids = _catalog(MistakeTag, journal, _MISTAKES, "label")

    today = timezone.localdate()
    start_day = today - timedelta(days=months * 30)
    end_day = today - timedelta(days=1)
    trades = []
    emotion_links = []
    mistake_links = []
    capital_basis = (
        journal.starting_capital
        if journal.starting_capital and journal.starting_capital > 0
        else None
    )

    def add_trade(**values):
        trade = Trade(journal=journal, is_synthetic=True, **values)
        trade.capital_basis = capital_basis
        if capital_basis is not None and trade.risk_percent is not None:
            trade.risk_amount = (
                capital_basis * trade.risk_percent / Decimal("100")
            ).quantize(Decimal("0.000001"))
        if trade.risk_amount is not None and trade.pnl_r is not None:
            trade.pnl_amount = (trade.risk_amount * trade.pnl_r).quantize(
                Decimal("0.000001")
            )
        trades.append(trade)
        return trade

    day = start_day
    while day <= end_day:
        if day.weekday() < 5:
            trades_today = rng.choices([0, 1, 2, 3], weights=[50, 32, 14, 4], k=1)[0]
            for _ in range(trades_today):
                entry_datetime, session = _entry_datetime(day, rng)
                pnl_r = _pnl_r(rng)
                holding_minutes = rng.choice([15, 30, 45, 60, 90, 120, 180, 240, 360])
                exit_datetime = entry_datetime + timedelta(minutes=holding_minutes)

                trade = add_trade(
                    asset=rng.choice(assets),
                    side=rng.choice([Trade.Side.BUY, Trade.Side.SELL]),
                    entry_datetime=entry_datetime,
                    exit_datetime=exit_datetime,
                    risk_percent=rng.choice(
                        [Decimal("0.50"), Decimal("0.75"), Decimal("1.00"),
                         Decimal("1.50"), Decimal("2.00")]
                    ),
                    pnl_r=pnl_r,
                    commission=_dec(rng.uniform(0.50, 4.50)),
                    swap=_dec(rng.uniform(-1.50, 0.50)),
                    opportunity_timeframe=rng.choice(_TIMEFRAMES),
                    entry_timeframe=rng.choice(_TIMEFRAMES[:3]),
                    trend_direction=rng.choice(Trade.TrendDirection.values),
                    setup=rng.choice(setups),
                    session=session,
                    notes=rng.choice(_NOTES),
                )
                emotion_links.extend(
                    (trade, emotion)
                    for emotion in rng.sample(emotions, rng.choice([0, 1, 1, 2, 3]))
                )
                if rng.random() < 0.30:
                    mistake_links.extend(
                        (trade, mistake)
                        for mistake in rng.sample(mistakes, rng.choice([1, 1, 2]))
                    )
        day += timedelta(days=1)

    open_days = [end_day - timedelta(days=offset) for offset in range(1, 8)]
    for day in [d for d in open_days if d.weekday() < 5][:3]:
        entry_datetime, session = _entry_datetime(day, rng)
        trade = add_trade(
            asset=rng.choice(assets),
            side=rng.choice([Trade.Side.BUY, Trade.Side.SELL]),
            entry_datetime=entry_datetime,
            exit_datetime=None,
            risk_percent=Decimal("1.00"),
            pnl_r=None,
            commission=_dec(rng.uniform(0.50, 4.50)),
            opportunity_timeframe=rng.choice(_TIMEFRAMES),
            entry_timeframe=rng.choice(_TIMEFRAMES[:3]),
            trend_direction=rng.choice(Trade.TrendDirection.values),
            setup=rng.choice(setups),
            session=session,
            notes="Open position from sample data.",
        )
        emotion_links.extend(
            (trade, emotion)
            for emotion in rng.sample(emotions, rng.choice([0, 1, 2]))
        )

    # Keep generation inside the existing transaction while reducing hundreds
    # of per-row writes to a handful of bulk inserts on hosted databases.
    Trade.objects.bulk_create(trades, batch_size=500)
    TradeEmotion.objects.bulk_create(
        [TradeEmotion(trade_id=trade.pk, emotion_id=emotion.pk) for trade, emotion in emotion_links],
        batch_size=1000,
    )
    TradeMistake.objects.bulk_create(
        [TradeMistake(trade_id=trade.pk, mistake_id=mistake.pk) for trade, mistake in mistake_links],
        batch_size=1000,
    )

    return {
        "trades_created": len(trades),
        "catalog_ids": {
            "assets": asset_ids,
            "setups": setup_ids,
            "emotions": emotion_ids,
            "mistakes": mistake_ids,
        },
    }


def remove_synthetic_trades(journal) -> int:
    catalog_ids = journal.synthetic_catalog_ids or {}

    synthetic_trades = Trade.objects.filter(journal=journal, is_synthetic=True)
    deleted = synthetic_trades.count()
    synthetic_trades.delete()

    remaining = Trade.objects.filter(journal=journal)
    asset_ids_in_use = set(remaining.values_list("asset_id", flat=True))
    setup_ids_in_use = set(
        remaining.exclude(setup__isnull=True).values_list("setup_id", flat=True)
    )
    emotion_ids_in_use = set(
        TradeEmotion.objects.filter(trade__journal=journal).values_list(
            "emotion_id", flat=True
        )
    )
    mistake_ids_in_use = set(
        TradeMistake.objects.filter(trade__journal=journal).values_list(
            "mistake_id", flat=True
        )
    )

    Asset.objects.filter(
        journal=journal, pk__in=catalog_ids.get("assets", [])
    ).exclude(pk__in=asset_ids_in_use).delete()
    SetupTag.objects.filter(
        journal=journal, pk__in=catalog_ids.get("setups", [])
    ).exclude(pk__in=setup_ids_in_use).delete()
    EmotionTag.objects.filter(
        journal=journal, pk__in=catalog_ids.get("emotions", [])
    ).exclude(pk__in=emotion_ids_in_use).delete()
    MistakeTag.objects.filter(
        journal=journal, pk__in=catalog_ids.get("mistakes", [])
    ).exclude(pk__in=mistake_ids_in_use).delete()

    journal.synthetic_catalog_ids = {}
    journal.save(update_fields=["synthetic_catalog_ids"])

    return deleted

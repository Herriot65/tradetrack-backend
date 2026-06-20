from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Literal

from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Coalesce

from .models import Trade

Period = Literal["weekly", "monthly", "yearly"]

_SENTINEL = object()


def _number(value: Decimal | int | float | None) -> float:
    return round(float(value or 0), 2)


def _closed_trades(queryset: QuerySet[Trade]) -> QuerySet[Trade]:
    """Trades that have been closed (exit recorded and pnl_r set)."""
    return queryset.filter(exit_datetime__isnull=False, pnl_r__isnull=False)


def _effective_win(qs: QuerySet[Trade]) -> QuerySet[Trade]:
    return qs.filter(Q(status="WIN") | (Q(status__isnull=True) & Q(pnl_r__gt=0)))


def _effective_loss(qs: QuerySet[Trade]) -> QuerySet[Trade]:
    return qs.filter(Q(status="LOSS") | (Q(status__isnull=True) & Q(pnl_r__lt=0)))


def _effective_be(qs: QuerySet[Trade]) -> QuerySet[Trade]:
    return qs.filter(Q(status="BE") | (Q(status__isnull=True) & Q(pnl_r=0)))


def calculate_max_drawdown(trades: Iterable[Trade]) -> Decimal:
    peak = Decimal("0")
    cumulative = Decimal("0")
    max_drawdown = Decimal("0")

    for trade in trades:
        cumulative += trade.pnl_r or Decimal("0")
        if cumulative > peak:
            peak = cumulative
        drawdown = cumulative - peak
        if drawdown < max_drawdown:
            max_drawdown = drawdown

    return max_drawdown


def get_dashboard_summary(queryset: QuerySet[Trade]) -> dict[str, float | int | None]:
    total_trades = queryset.count()  # ALL trades — open and closed

    if total_trades == 0:
        return {
            "has_data": False,
            "total_trades": 0,
            "win_rate": 0.0,
            "total_r": 0.0,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
            "average_r": 0.0,
        }

    closed = _closed_trades(queryset)
    closed_count = closed.count()
    wins = _effective_win(closed).count()
    losses = _effective_loss(closed).count()
    break_even = _effective_be(closed).count()

    aggregates = closed.aggregate(total_r=Coalesce(Sum("pnl_r"), Decimal("0")))
    gross_profit = closed.filter(pnl_r__gt=0).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]
    gross_loss = closed.filter(pnl_r__lt=0).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]

    total_r = aggregates["total_r"]
    denominator = wins + losses + break_even
    win_rate = (wins / denominator * 100) if denominator else 0
    average_r = (total_r / closed_count) if closed_count else Decimal("0")  # closed trades only
    profit_factor = None if gross_loss == 0 else abs(gross_profit / gross_loss)
    ordered_trades = closed.order_by("entry_datetime", "id")

    return {
        "has_data": True,
        "total_trades": total_trades,
        "win_rate": _number(win_rate),
        "total_r": _number(total_r),
        "profit_factor": None if profit_factor is None else _number(profit_factor),
        "max_drawdown_r": _number(calculate_max_drawdown(ordered_trades)),
        "average_r": _number(average_r),
    }


def _period_start(value: date, period: Period) -> date:
    if period == "yearly":
        return value.replace(month=1, day=1)
    if period == "monthly":
        return value.replace(day=1)
    return value.fromisocalendar(value.isocalendar().year, value.isocalendar().week, 1)


def get_equity_curve(queryset: QuerySet[Trade], period: Period = "weekly") -> list[dict[str, str | float]]:
    closed = _closed_trades(queryset).order_by("entry_datetime", "id")
    cumulative_by_period: dict[date, Decimal] = {}
    cumulative = Decimal("0")

    for trade in closed:
        cumulative += trade.pnl_r or Decimal("0")
        bucket = _period_start(trade.entry_datetime.date(), period)
        cumulative_by_period[bucket] = cumulative

    return [
        {"date": bucket.isoformat(), "equity_r": _number(equity)}
        for bucket, equity in sorted(cumulative_by_period.items())
    ]


def get_win_loss_distribution(queryset: QuerySet[Trade]) -> dict[str, int]:
    closed = _closed_trades(queryset)
    wins = _effective_win(closed).count()
    losses = _effective_loss(closed).count()
    break_even = _effective_be(closed).count()
    return {
        "has_data": wins + losses + break_even > 0,
        "wins": wins,
        "losses": losses,
        "break_even": break_even,
    }


def get_pnl_by_setup(queryset: QuerySet[Trade]) -> list[dict[str, str | float]]:
    rows = (
        _closed_trades(queryset)
        .filter(setup__isnull=False)
        .values("setup__label")
        .annotate(total_r=Coalesce(Sum("pnl_r"), Decimal("0")))
        .order_by("-total_r", "setup__label")
    )
    return [{"setup": row["setup__label"], "total_r": _number(row["total_r"])} for row in rows]


def get_career_data(queryset: QuerySet[Trade]) -> dict:
    # Total trade count per year — ALL trades (open + closed)
    all_counts: dict[int, int] = {
        row["entry_datetime__year"]: row["count"]
        for row in queryset.values("entry_datetime__year").annotate(count=Count("id"))
    }

    # Financial metrics from closed trades only
    closed = _closed_trades(queryset).order_by("entry_datetime")

    year_financials: dict[int, dict] = defaultdict(
        lambda: {"total_r": Decimal("0"), "closed_count": 0, "wins": 0}
    )
    heatmap: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    for trade in closed.values("entry_datetime", "pnl_r", "status"):
        year = trade["entry_datetime"].year
        month = trade["entry_datetime"].month - 1  # 0-indexed for frontend
        pnl = trade["pnl_r"] or Decimal("0")

        year_financials[year]["total_r"] += pnl
        year_financials[year]["closed_count"] += 1

        effective_status = trade["status"]
        if effective_status is None:
            effective_status = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")
        if effective_status == "WIN":
            year_financials[year]["wins"] += 1

        heatmap[year][month] = round(heatmap[year][month] + float(pnl), 2)

    years = sorted(set(all_counts.keys()) | set(year_financials.keys()), reverse=True)
    year_summaries = []
    for year in years:
        financials = year_financials[year]
        closed_count = financials["closed_count"]
        win_rate = round(financials["wins"] / closed_count * 100, 2) if closed_count else 0.0
        year_summaries.append({
            "year": year,
            "total_r": _number(financials["total_r"]),
            "total_trades": all_counts.get(year, 0),  # ALL trades in that year
            "win_rate": win_rate,                      # closed trades only
        })

    return {
        "has_data": len(years) > 0,
        "yearSummaries": year_summaries,
        "heatmap": {str(year): dict(months) for year, months in heatmap.items()},
        "years": years,
    }

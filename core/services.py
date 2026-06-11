from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Literal

from django.db.models import QuerySet, Sum
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from .models import Trade, Workspace

Period = Literal["weekly", "monthly", "yearly"]


def get_user_workspace(user, workspace_id) -> Workspace:
    if not workspace_id:
        raise ValidationError({"workspace_id": "This query parameter is required."})

    try:
        return Workspace.objects.get(id=workspace_id, user=user)
    except (Workspace.DoesNotExist, ValueError):
        raise ValidationError({"workspace_id": "Invalid workspace for the authenticated user."})


def _number(value: Decimal | int | float | None) -> float:
    return round(float(value or 0), 2)


def _closed_trades(queryset: QuerySet[Trade]) -> QuerySet[Trade]:
    return queryset.exclude(status=Trade.Status.OPEN)


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
    closed = _closed_trades(queryset)
    total_trades = closed.count()
    wins = closed.filter(status=Trade.Status.WIN).count()
    losses = closed.filter(status=Trade.Status.LOSS).count()
    break_even = closed.filter(status=Trade.Status.BE).count()

    aggregates = closed.aggregate(total_r=Coalesce(Sum("pnl_r"), Decimal("0")))
    gross_profit = closed.filter(pnl_r__gt=0).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]
    gross_loss = closed.filter(pnl_r__lt=0).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]

    total_r = aggregates["total_r"]
    denominator = wins + losses + break_even
    win_rate = (wins / denominator * 100) if denominator else 0
    average_r = (total_r / total_trades) if total_trades else Decimal("0")
    profit_factor = None if gross_loss == 0 else abs(gross_profit / gross_loss)
    ordered_trades = closed.order_by("entry_datetime", "id")

    return {
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
    return {
        "wins": closed.filter(status=Trade.Status.WIN).count(),
        "losses": closed.filter(status=Trade.Status.LOSS).count(),
        "break_even": closed.filter(status=Trade.Status.BE).count(),
    }


def get_pnl_by_setup(queryset: QuerySet[Trade]) -> list[dict[str, str | float]]:
    rows = (
        _closed_trades(queryset)
        .values("setup")
        .annotate(total_r=Coalesce(Sum("pnl_r"), Decimal("0")))
        .order_by("-total_r", "setup")
    )
    return [{"setup": row["setup"], "total_r": _number(row["total_r"])} for row in rows]

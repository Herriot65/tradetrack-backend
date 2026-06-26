from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Literal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Coalesce

from .models import Trade, TradeImport

if TYPE_CHECKING:
    from .models import Journal

Period = Literal["weekly", "monthly", "yearly"]

_SENTINEL = object()


def _number(value: Decimal | int | float | None) -> float:
    return round(float(value or 0), 2)


def _closed_trades(queryset: QuerySet[Trade]) -> QuerySet[Trade]:
    """Trades that have been closed (exit recorded and pnl_r set)."""
    return queryset.filter(exit_datetime__isnull=False, pnl_r__isnull=False)


def be_threshold_r(journal: Journal) -> Decimal:
    """
    Convert journal break-even settings to a pnl_r threshold.

    "ratio"  method → threshold is already in pnl_r units (use as-is).
    "profit" method → convert the monetary threshold to pnl_r percentage
                      using starting_capital so all downstream code stays uniform.

    Returns 0 when no meaningful threshold is set.
    """
    be_value = journal.break_even_value or Decimal("0")
    if be_value <= 0:
        return Decimal("0")
    if journal.break_even_method == "profit":
        capital = journal.starting_capital or Decimal("0")
        if capital <= 0:
            return Decimal("0")
        return (be_value / capital * Decimal("100")).quantize(Decimal("0.01"))
    return be_value  # "ratio" — already in pnl_r units


def _auto_status(pnl: Decimal, threshold: Decimal) -> str:
    """Derive WIN / LOSS / BE from pnl_r when the trade has no explicit status."""
    if threshold > 0 and abs(pnl) <= threshold:
        return "BE"
    return "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BE")


def _effective_win(qs: QuerySet[Trade], threshold: Decimal = Decimal("0")) -> QuerySet[Trade]:
    if threshold > 0:
        return qs.filter(Q(status="WIN") | (Q(status__isnull=True) & Q(pnl_r__gt=threshold)))
    return qs.filter(Q(status="WIN") | (Q(status__isnull=True) & Q(pnl_r__gt=0)))


def _effective_loss(qs: QuerySet[Trade], threshold: Decimal = Decimal("0")) -> QuerySet[Trade]:
    if threshold > 0:
        return qs.filter(Q(status="LOSS") | (Q(status__isnull=True) & Q(pnl_r__lt=-threshold)))
    return qs.filter(Q(status="LOSS") | (Q(status__isnull=True) & Q(pnl_r__lt=0)))


def _effective_be(qs: QuerySet[Trade], threshold: Decimal = Decimal("0")) -> QuerySet[Trade]:
    if threshold > 0:
        return qs.filter(
            Q(status="BE") | (Q(status__isnull=True) & Q(pnl_r__gte=-threshold) & Q(pnl_r__lte=threshold))
        )
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


def get_dashboard_summary(
    queryset: QuerySet[Trade], threshold: Decimal = Decimal("0")
) -> dict[str, float | int | None]:
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
    wins = _effective_win(closed, threshold).count()
    losses = _effective_loss(closed, threshold).count()
    break_even = _effective_be(closed, threshold).count()

    aggregates = closed.aggregate(total_r=Coalesce(Sum("pnl_r"), Decimal("0")))
    gross_profit = _effective_win(closed, threshold).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]
    gross_loss = _effective_loss(closed, threshold).aggregate(total=Coalesce(Sum("pnl_r"), Decimal("0")))["total"]

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


def get_win_loss_distribution(
    queryset: QuerySet[Trade], threshold: Decimal = Decimal("0")
) -> dict[str, int]:
    closed = _closed_trades(queryset)
    wins = _effective_win(closed, threshold).count()
    losses = _effective_loss(closed, threshold).count()
    break_even = _effective_be(closed, threshold).count()
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


def _empty_kpi_state() -> dict:
    return {
        "current_win_streak": 0,
        "current_loss_streak": 0,
        "win_streaks": [],
        "loss_streaks": [],
        "sum_win_r": Decimal("0"),
        "sum_loss_r": Decimal("0"),
        "total_r": Decimal("0"),
        "win_count": 0,
        "loss_count": 0,
        "closed_count": 0,
        "cumulative_pnl": Decimal("0"),
        "peak": Decimal("0"),
        "max_drawdown": Decimal("0"),
    }


def _flush_kpi_state(s: dict) -> None:
    """Flush any trailing streak into the streak lists."""
    if s["current_win_streak"] > 0:
        s["win_streaks"].append(s["current_win_streak"])
        s["current_win_streak"] = 0
    if s["current_loss_streak"] > 0:
        s["loss_streaks"].append(s["current_loss_streak"])
        s["current_loss_streak"] = 0


def _kpi_from_state(s: dict) -> dict:
    """Derive the KPI summary dict from a fully-flushed state dict."""
    ws = s["win_streaks"]
    ls = s["loss_streaks"]
    wc = s["win_count"]
    lc = s["loss_count"]
    cc = s["closed_count"]
    return {
        "max_win_streak":        max(ws) if ws else 0,
        "max_loss_streak":       max(ls) if ls else 0,
        "avg_consecutive_wins":  round(sum(ws) / len(ws), 2) if ws else 0.0,
        "avg_consecutive_losses":round(sum(ls) / len(ls), 2) if ls else 0.0,
        "avg_win_r":             _number(s["sum_win_r"] / wc) if wc else 0.0,
        "avg_loss_r":            _number(s["sum_loss_r"] / lc) if lc else 0.0,
        "expectancy":            _number((s["sum_win_r"] + s["sum_loss_r"]) / cc) if cc else 0.0,
        "max_drawdown":          _number(s["max_drawdown"]),
    }


def _update_kpi_state(s: dict, pnl: Decimal, effective_status: str) -> None:
    """Apply one trade result to a KPI state dict (global or per-year)."""
    s["closed_count"] += 1
    s["total_r"] += pnl

    if effective_status == "WIN":
        s["sum_win_r"] += pnl
        s["win_count"] += 1
        s["current_win_streak"] += 1
        if s["current_loss_streak"] > 0:
            s["loss_streaks"].append(s["current_loss_streak"])
            s["current_loss_streak"] = 0
    elif effective_status == "LOSS":
        s["sum_loss_r"] += pnl
        s["loss_count"] += 1
        s["current_loss_streak"] += 1
        if s["current_win_streak"] > 0:
            s["win_streaks"].append(s["current_win_streak"])
            s["current_win_streak"] = 0
    else:  # BE — ends both streaks
        if s["current_win_streak"] > 0:
            s["win_streaks"].append(s["current_win_streak"])
            s["current_win_streak"] = 0
        if s["current_loss_streak"] > 0:
            s["loss_streaks"].append(s["current_loss_streak"])
            s["current_loss_streak"] = 0

    s["cumulative_pnl"] += pnl
    if s["cumulative_pnl"] > s["peak"]:
        s["peak"] = s["cumulative_pnl"]
    drawdown = s["peak"] - s["cumulative_pnl"]
    if drawdown > s["max_drawdown"]:
        s["max_drawdown"] = drawdown


def get_career_data(queryset: QuerySet[Trade], threshold: Decimal = Decimal("0")) -> dict:
    # Total trade count per year — ALL trades (open + closed)
    all_counts: dict[int, int] = {
        row["entry_datetime__year"]: row["count"]
        for row in queryset.values("entry_datetime__year").annotate(count=Count("id"))
    }

    closed = _closed_trades(queryset).order_by("entry_datetime")

    year_wins: dict[int, int] = defaultdict(int)
    heatmap: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    # One state dict for all-time, one per year
    global_state = _empty_kpi_state()
    year_states: dict[int, dict] = defaultdict(_empty_kpi_state)

    for trade in closed.values("entry_datetime", "pnl_r", "status"):
        year = trade["entry_datetime"].year
        month = trade["entry_datetime"].month - 1  # 0-indexed for frontend
        pnl = trade["pnl_r"] or Decimal("0")

        effective_status = trade["status"] or _auto_status(pnl, threshold)

        if effective_status == "WIN":
            year_wins[year] += 1

        heatmap[year][month] = round(heatmap[year][month] + float(pnl), 2)

        _update_kpi_state(global_state, pnl, effective_status)
        _update_kpi_state(year_states[year], pnl, effective_status)

    _flush_kpi_state(global_state)
    for s in year_states.values():
        _flush_kpi_state(s)

    global_kpis = _kpi_from_state(global_state)

    years = sorted(set(all_counts.keys()) | set(year_states.keys()), reverse=True)
    year_summaries = []
    for year in years:
        ys = year_states[year]
        cc = ys["closed_count"]
        wins = year_wins[year]
        win_rate = round(wins / cc * 100, 2) if cc else 0.0
        year_kpis = _kpi_from_state(ys)
        year_summaries.append({
            "year":         year,
            "total_r":      _number(ys["total_r"]),
            "total_trades": all_counts.get(year, 0),
            "win_rate":     win_rate,
            **year_kpis,
        })

    return {
        "has_data":    len(years) > 0,
        "yearSummaries": year_summaries,
        "heatmap":     {str(year): dict(months) for year, months in heatmap.items()},
        "years":       years,
        "total_trades": sum(all_counts.values()),
        **global_kpis,
    }


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_UTC = ZoneInfo("UTC")


def get_performance_by_day(
    queryset: QuerySet[Trade], tz: ZoneInfo = _UTC, threshold: Decimal = Decimal("0")
) -> list[dict]:
    """
    Returns one entry per weekday (Mon–Sun), always 7 items, sorted Mon→Sun.
    Days with no trades have trade_count=0 and all metrics at 0.
    entry_datetime is converted to `tz` before grouping.
    """
    closed = _closed_trades(queryset)
    groups: dict[int, dict] = {
        i: {"trade_count": 0, "win_count": 0, "total_r": Decimal("0")}
        for i in range(7)
    }

    for trade in closed.values("entry_datetime", "pnl_r", "status"):
        day = trade["entry_datetime"].astimezone(tz).weekday()  # 0=Mon, 6=Sun
        pnl = trade["pnl_r"] or Decimal("0")
        groups[day]["trade_count"] += 1
        groups[day]["total_r"] += pnl

        if (trade["status"] or _auto_status(pnl, threshold)) == "WIN":
            groups[day]["win_count"] += 1

    result = []
    for day_index, data in groups.items():
        count = data["trade_count"]
        win_rate = round(data["win_count"] / count * 100, 2) if count else 0.0
        result.append({
            "day": _WEEKDAYS[day_index],
            "day_index": day_index,
            "trade_count": count,
            "win_count": data["win_count"],
            "win_rate": win_rate,
            "total_r": _number(data["total_r"]),
        })

    return result


def get_performance_by_hour(
    queryset: QuerySet[Trade], tz: ZoneInfo = _UTC, threshold: Decimal = Decimal("0")
) -> list[dict]:
    """
    Returns one entry per hour that has at least one closed trade, sorted 0→23.
    entry_datetime is converted to `tz` before grouping.
    """
    closed = _closed_trades(queryset)
    groups: dict[int, dict] = defaultdict(
        lambda: {"trade_count": 0, "win_count": 0, "total_r": Decimal("0")}
    )

    for trade in closed.values("entry_datetime", "pnl_r", "status"):
        hour = trade["entry_datetime"].astimezone(tz).hour
        pnl = trade["pnl_r"] or Decimal("0")
        groups[hour]["trade_count"] += 1
        groups[hour]["total_r"] += pnl

        if (trade["status"] or _auto_status(pnl, threshold)) == "WIN":
            groups[hour]["win_count"] += 1

    result = []
    for hour in sorted(groups.keys()):
        data = groups[hour]
        count = data["trade_count"]
        win_rate = round(data["win_count"] / count * 100, 2) if count else 0.0
        result.append({
            "hour": hour,
            "trade_count": count,
            "win_count": data["win_count"],
            "win_rate": win_rate,
            "total_r": _number(data["total_r"]),
        })

    return result


@transaction.atomic
def recompute_imported_pnl(journal: Journal) -> int:
    """
    Recompute pnl_r for every imported trade when starting_capital changes.

    Only trades with a TradeImport record and a non-null raw_profit are touched.
    Manually created trades are never modified.

    Returns the number of trades updated.
    """
    capital = journal.starting_capital
    trade_imports = (
        TradeImport.objects
        .filter(journal=journal, raw_profit__isnull=False)
        .select_related("trade")
    )

    trades_to_update = []
    for ti in trade_imports:
        if capital and capital > 0:
            new_pnl_r = (ti.raw_profit / capital * Decimal("100")).quantize(Decimal("0.01"))
        else:
            new_pnl_r = None
        ti.trade.pnl_r = new_pnl_r
        trades_to_update.append(ti.trade)

    if trades_to_update:
        Trade.objects.bulk_update(trades_to_update, ["pnl_r"])

    return len(trades_to_update)

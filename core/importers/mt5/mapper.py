"""
MT5 → TraderTrack trade schema mapper.

Responsibility: convert raw MT5 row data into Trade-compatible dicts.
No database access. No HTML parsing. Pure data transformation.

Field mapping notes:
  MT5 type (buy/sell) + direction (in/out) → Trade.side (BUY/SELL)
  MT5 profit                                → TradeImport.raw_profit + Trade.pnl_r (as % of capital)
  MT5 commission (sum of entry + exit)      → Trade.commission
  MT5 swap                                  → Trade.swap
  MT5 open_time / entry deal time           → Trade.entry_datetime
  MT5 close_time / exit deal time           → Trade.exit_datetime
  MT5 symbol                                → Asset.symbol (auto-created per journal)
  MT5 ticket / entry deal #                 → TradeImport.external_id (dedup key)

Fields with no schema equivalent (stored in Trade.notes):
  volume / lot size, entry price, exit price, SL, TP, magic number, order #
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional


_MT5_DATETIME_FORMATS = [
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
]


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    for fmt in _MT5_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", value.strip())
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _sum_decimals(*values: Optional[str]) -> Optional[Decimal]:
    total = Decimal("0")
    has_any = False
    for v in values:
        d = _parse_decimal(v)
        if d is not None:
            total += d
            has_any = True
    return total if has_any else None


def _detect_side(trade_type: str) -> str:
    """Map MT5 deal/type string to Trade.Side value."""
    t = trade_type.lower()
    if "buy" in t:
        return "BUY"
    if "sell" in t:
        return "SELL"
    return "BUY"  # fallback — will be visible in notes


def _build_notes(fields: dict) -> str:
    """Build a human-readable MT5 metadata string for Trade.notes."""
    parts = ["[MT5 Import]"]
    order_map = [
        ("Ticket", "ticket"),
        ("Volume", "volume"),
        ("Entry", "open_price"),
        ("Exit", "close_price"),
        ("SL", "sl"),
        ("TP", "tp"),
        ("Magic", "magic"),
        ("Comment", "comment"),
        ("Raw Profit", "raw_profit_str"),
    ]
    detail_parts = []
    for label, key in order_map:
        val = fields.get(key)
        if val:
            detail_parts.append(f"{label}: {val}")
    if detail_parts:
        parts.append(" | ".join(detail_parts))
    return "\n".join(parts)


def map_statement_rows(positions: list[dict], starting_capital: Decimal) -> list[dict]:
    """
    Map statement-format rows (each row = complete trade) to Trade-compatible dicts.

    Returns list of dicts with keys:
      symbol, side, entry_datetime, exit_datetime, commission, swap,
      pnl_r, notes, external_id, raw_profit
    """
    results = []
    for pos in positions:
        entry_dt = _parse_dt(pos.get("open_time"))
        exit_dt = _parse_dt(pos.get("close_time"))

        if not entry_dt:
            continue  # cannot create a trade without entry datetime

        side = _detect_side(pos.get("type", ""))
        raw_profit = _parse_decimal(pos.get("profit"))
        commission = _sum_decimals(pos.get("commission"), pos.get("taxes"))
        swap = _parse_decimal(pos.get("swap"))
        pnl_r = _compute_pnl_percent(raw_profit, starting_capital)

        external_id = pos.get("ticket") or ""

        notes = _build_notes({
            "ticket":         pos.get("ticket"),
            "volume":         pos.get("size"),
            "open_price":     pos.get("open_price"),
            "close_price":    pos.get("close_price"),
            "sl":             pos.get("sl"),
            "tp":             pos.get("tp"),
            "comment":        pos.get("comment"),
            "raw_profit_str": str(raw_profit) if raw_profit is not None else None,
        })

        results.append({
            "symbol":          pos.get("symbol", "").upper(),
            "side":            side,
            "entry_datetime":  entry_dt,
            "exit_datetime":   exit_dt,
            "commission":      commission,
            "swap":            swap,
            "pnl_r":           pnl_r,
            "notes":           notes,
            "external_id":     external_id,
            "raw_profit":      raw_profit,
        })

    return results


def map_deal_rows(deals: list[dict], starting_capital: Decimal) -> tuple[list[dict], list[dict]]:
    """
    Map deals-format rows (separate entry/exit rows) to Trade-compatible dicts.

    Deals are paired FIFO per symbol:
    - "in"     deal → entry
    - "out"    deal → exit (paired with oldest open "in" for same symbol)
    - "in/out" deal → reversal: closes existing position + opens a new one

    Unmatched "in" deals at the end are imported as open trades (no exit).

    Returns (trades, warnings) where warnings describe any skipped/unusual deals.
    """
    sorted_deals = sorted(deals, key=lambda d: d.get("time") or "")

    open_positions: dict[str, list[dict]] = defaultdict(list)
    results: list[dict] = []
    warnings: list[dict] = []

    def _close_position(entry_deal: dict, exit_deal: dict, symbol: str) -> None:
        entry_dt = _parse_dt(entry_deal.get("time"))
        if not entry_dt:
            warnings.append({
                "type": "missing_entry_datetime",
                "symbol": symbol,
                "deal": entry_deal.get("deal", "?"),
                "reason": f"Could not parse entry datetime for {symbol} deal {entry_deal.get('deal','?')}",
            })
            return
        exit_dt = _parse_dt(exit_deal.get("time"))
        side = _detect_side(entry_deal.get("type", ""))
        raw_profit = _parse_decimal(exit_deal.get("profit"))
        commission = _sum_decimals(entry_deal.get("commission"), exit_deal.get("commission"))
        swap = _parse_decimal(exit_deal.get("swap"))
        pnl_r = _compute_pnl_percent(raw_profit, starting_capital)
        external_id = entry_deal.get("deal") or entry_deal.get("order") or ""
        notes = _build_notes({
            "ticket":         entry_deal.get("deal"),
            "volume":         entry_deal.get("volume"),
            "open_price":     entry_deal.get("price"),
            "close_price":    exit_deal.get("price"),
            "comment":        exit_deal.get("comment") or entry_deal.get("comment"),
            "raw_profit_str": str(raw_profit) if raw_profit is not None else None,
        })
        results.append({
            "symbol":         symbol,
            "side":           side,
            "entry_datetime": entry_dt,
            "exit_datetime":  exit_dt,
            "commission":     commission,
            "swap":           swap,
            "pnl_r":          pnl_r,
            "notes":          notes,
            "external_id":    external_id,
            "raw_profit":     raw_profit,
        })

    for deal in sorted_deals:
        direction = deal.get("direction", "")
        symbol = deal.get("symbol", "").upper()

        if direction == "in":
            open_positions[symbol].append(deal)

        elif direction == "out":
            if not open_positions[symbol]:
                warnings.append({
                    "type": "unmatched_exit",
                    "symbol": symbol,
                    "deal": deal.get("deal", "?"),
                    "reason": f"Exit deal for {symbol} has no matching entry deal",
                })
                continue
            entry_deal = open_positions[symbol].pop(0)
            _close_position(entry_deal, deal, symbol)

        elif direction == "in/out":
            # Reversal: closes the current open position, then opens a new one.
            # The reversal deal's profit = P&L of the position being closed.
            if open_positions[symbol]:
                entry_deal = open_positions[symbol].pop(0)
                _close_position(entry_deal, deal, symbol)
            # The reversal deal also opens a new position — push it as a new entry.
            # Zero out commission on the new entry so it is not double-counted when closed.
            new_entry = dict(deal)
            new_entry["commission"] = "0"
            open_positions[symbol].append(new_entry)

    # Remaining open positions have no exit deal yet — import them as open trades.
    for symbol, open_list in open_positions.items():
        for entry_deal in open_list:
            entry_dt = _parse_dt(entry_deal.get("time"))
            if not entry_dt:
                warnings.append({
                    "type": "missing_entry_datetime",
                    "symbol": symbol,
                    "deal": entry_deal.get("deal", "?"),
                    "reason": f"Open position for {symbol}: could not parse entry datetime",
                })
                continue
            side = _detect_side(entry_deal.get("type", ""))
            commission = _parse_decimal(entry_deal.get("commission"))
            external_id = entry_deal.get("deal") or entry_deal.get("order") or ""
            notes = _build_notes({
                "ticket":     entry_deal.get("deal"),
                "volume":     entry_deal.get("volume"),
                "open_price": entry_deal.get("price"),
                "comment":    entry_deal.get("comment"),
            })
            results.append({
                "symbol":         symbol,
                "side":           side,
                "entry_datetime": entry_dt,
                "exit_datetime":  None,
                "commission":     commission,
                "swap":           None,
                "pnl_r":          None,
                "notes":          notes,
                "external_id":    external_id,
                "raw_profit":     None,
            })

    return results, warnings


def _compute_pnl_percent(raw_profit: Optional[Decimal], starting_capital: Decimal) -> Optional[Decimal]:
    """
    Temporary Phase 1 rule:
    pnl_r = (raw_profit / starting_capital) * 100

    Returns None if profit is unknown or capital is zero/negative.
    """
    if raw_profit is None:
        return None
    if not starting_capital or starting_capital <= 0:
        return None
    result = (raw_profit / starting_capital) * Decimal("100")
    return result.quantize(Decimal("0.01"))

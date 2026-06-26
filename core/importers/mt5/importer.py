"""
MT5 HTML import orchestrator.

Flow:
  1. Receive uploaded file + journal context
  2. Parse HTML → raw rows  (parser)
  3. Map raw rows → trade dicts  (mapper)
  4. Persist trades with dedup   (this module)
  5. Return import summary
"""

from __future__ import annotations

from decimal import Decimal
from typing import BinaryIO

from django.db import transaction

from core.models import Asset, ImportBatch, Journal, Trade, TradeImport

from .mapper import map_deal_rows, map_statement_rows
from .parser import MT5ParseError, parse_mt5_html


SOURCE = "mt5_html"


class ImportResult:
    def __init__(self, batch: ImportBatch, failures: list[dict]):
        self.batch = batch
        self.failures = failures

    def to_dict(self) -> dict:
        return {
            "success": True,
            "import_id": self.batch.pk,
            "source": self.batch.source,
            "filename": self.batch.filename,
            "format_detected": self.batch.format_detected,
            "raw_rows_found": self.batch.raw_rows_found,
            "rows_parsed": self.batch.rows_parsed,
            "trades_created": self.batch.trades_created,
            "trades_skipped": self.batch.trades_skipped,
            "trades_failed": self.batch.trades_failed,
            "failures": self.failures,
        }


def import_mt5_html(journal: Journal, file: BinaryIO, filename: str = "") -> dict:
    """
    Top-level entry point called by the view.

    Reads the uploaded file, parses it, maps rows to trades, persists them,
    and returns a summary dict suitable for an API response.
    """
    try:
        content = file.read()
    except Exception as exc:
        return {"success": False, "error": f"Could not read uploaded file: {exc}"}

    # --- Parse ---
    try:
        parsed = parse_mt5_html(content)
    except MT5ParseError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": f"Unexpected parse error: {exc}"}

    fmt = parsed["format"]
    starting_capital = journal.starting_capital or Decimal("0")

    # --- Map ---
    mapper_warnings: list[dict] = []
    if fmt == "statement":
        raw_rows = parsed["positions"]
        mapped_trades = map_statement_rows(raw_rows, starting_capital)
    else:  # deals
        raw_rows = parsed["deals"]
        mapped_trades, mapper_warnings = map_deal_rows(raw_rows, starting_capital)

    rows_parsed = len(mapped_trades)

    # --- Persist ---
    result = _persist(
        journal=journal,
        mapped_trades=mapped_trades,
        filename=filename,
        rows_parsed=rows_parsed,
        fmt=fmt,
        raw_rows_found=len(raw_rows),
    )
    response = result.to_dict()
    if mapper_warnings:
        response["warnings"] = mapper_warnings
    if parsed.get("_debug"):
        response["_debug"] = parsed["_debug"]
    return response


@transaction.atomic
def _persist(
    journal: Journal,
    mapped_trades: list[dict],
    filename: str,
    rows_parsed: int,
    fmt: str = "",
    raw_rows_found: int = 0,
) -> ImportResult:
    """
    Persist mapped trade dicts into the database.

    Dedup rule: (journal, source="mt5_html", external_id) must be unique.
    Trades whose external_id already exists in TradeImport are skipped.
    """
    batch = ImportBatch.objects.create(
        journal=journal,
        source=SOURCE,
        filename=filename or "",
        format_detected=fmt,
        raw_rows_found=raw_rows_found,
        rows_parsed=rows_parsed,
    )

    created = 0
    skipped = 0
    failed = 0
    failures: list[dict] = []

    # Pre-load existing external_ids for this journal+source to avoid per-row queries
    existing_ids: set[str] = set(
        TradeImport.objects.filter(journal=journal, source=SOURCE)
        .values_list("external_id", flat=True)
    )

    for row in mapped_trades:
        external_id = row.get("external_id", "")

        # --- Dedup check ---
        if external_id and external_id in existing_ids:
            skipped += 1
            continue

        # --- Validate minimum required fields ---
        if not row.get("symbol"):
            failed += 1
            failures.append({"external_id": external_id, "error": "Missing symbol"})
            continue

        if not row.get("entry_datetime"):
            failed += 1
            failures.append({"external_id": external_id or row.get("symbol", "?"), "error": "Missing entry datetime"})
            continue

        try:
            # --- Get or create Asset ---
            symbol = row["symbol"].upper()
            asset, _ = Asset.objects.get_or_create(
                journal=journal,
                symbol=symbol,
                defaults={"name": symbol},
            )

            # --- Create Trade ---
            trade = Trade.objects.create(
                journal=journal,
                asset=asset,
                side=row["side"],
                entry_datetime=row["entry_datetime"],
                exit_datetime=row.get("exit_datetime"),
                commission=row.get("commission"),
                swap=row.get("swap"),
                pnl_r=row.get("pnl_r"),
                notes=row.get("notes"),
                # risk_percent intentionally null — not computable from MT5 HTML in Phase 1
            )

            # --- Create TradeImport record (for dedup + traceability) ---
            raw_profit = row.get("raw_profit")
            TradeImport.objects.create(
                trade=trade,
                batch=batch,
                journal=journal,
                source=SOURCE,
                external_id=external_id,
                raw_profit=raw_profit,
                raw_data={k: str(v) if v is not None else None for k, v in row.items()
                          if k not in ("entry_datetime", "exit_datetime")},
            )

            if external_id:
                existing_ids.add(external_id)

            created += 1

        except Exception as exc:
            failed += 1
            failures.append({"external_id": external_id or "?", "error": str(exc)})

    batch.trades_created = created
    batch.trades_skipped = skipped
    batch.trades_failed = failed
    batch.save(update_fields=["trades_created", "trades_skipped", "trades_failed"])

    return ImportResult(batch=batch, failures=failures)

"""
MT5 HTML report parser.

Responsibility: extract raw row data from MT5 HTML files only.
No business logic, no schema mapping, no PnL calculations here.

Supports two structural variants:

  Variant A — "Sectioned" (real MT5 broker reports, e.g. Deriv):
    - Single <table> with section headers: <th colspan="N"><b>Deals</b></th>
    - UTF-16 LE encoded (common from MT5 terminal "Save as Report")
    - Deals section is the authoritative source (Direction=in/out for pairing)
    - Positions section is secondary fallback

  Variant B — "Legacy" (simpler exports, older MT4/MT5, test fixtures):
    - Separate tables per section, or a single table with column headers in row 0
    - UTF-8 encoded
    - Column headers identified by keyword scoring
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag


class MT5ParseError(Exception):
    pass


_NON_TRADE_TYPES = {"balance", "credit", "deposit", "withdrawal", "correction"}
_SECTION_NAMES = {"deals", "positions", "orders"}

# Keywords for legacy column-scanning fallback
_DEALS_KEYWORDS = {"time", "deal", "symbol", "type", "direction", "volume", "price", "commission", "swap", "profit"}
_STATEMENT_KEYWORDS = {"open time", "ticket", "type", "size", "item", "price", "s/l", "t/p", "close time", "swap", "profit"}


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _decode(raw: bytes) -> str:
    """
    Decode raw bytes to string, handling UTF-16 LE (standard MT5 report encoding).
    MT5 "Save as Report" generates UTF-16 LE HTML with or without a BOM.
    """
    # Explicit BOM: 0xFF 0xFE = UTF-16 LE, 0xFE 0xFF = UTF-16 BE
    if raw[:2] == b'\xff\xfe':
        return raw.decode('utf-16-le', errors='replace').lstrip('﻿')
    if raw[:2] == b'\xfe\xff':
        return raw.decode('utf-16-be', errors='replace').lstrip('﻿')
    # Heuristic: UTF-16 LE without BOM — ASCII chars have 0x00 as second byte
    if len(raw) >= 8 and raw[1] == 0 and raw[3] == 0 and raw[5] == 0:
        return raw.decode('utf-16-le', errors='replace')
    # UTF-8 (test fixtures, other formats)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', errors='replace')


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _cell(cells: list[Tag], headers: list[str], name: str, nth: int = 0) -> Optional[str]:
    """Return text of the nth cell whose column header matches name."""
    indices = [i for i, h in enumerate(headers) if h == name]
    try:
        idx = indices[nth]
        text = cells[idx].get_text(strip=True)
        return text if text else None
    except IndexError:
        return None


# ---------------------------------------------------------------------------
# Variant A: Sectioned single-table parsing (real MT5 broker reports)
# ---------------------------------------------------------------------------

def _find_main_table(soup: BeautifulSoup) -> Optional[Tag]:
    """
    Find the table that contains MT5 section headers (Deals / Positions / Orders).
    Falls back to the largest table if no section header is found.
    """
    for table in soup.find_all("table"):
        for th in table.find_all("th"):
            if _norm(th.get_text()) in _SECTION_NAMES:
                return table
    tables = soup.find_all("table")
    return max(tables, key=lambda t: len(t.find_all("tr"))) if tables else None


def _find_section(all_rows: list[Tag], section_name: str) -> tuple[list[str], list[Tag]]:
    """
    Locate a named section inside a flat list of table rows.

    MT5 layout inside one table:
      <tr><th colspan="N"><b>Deals</b></th></tr>   ← section header row
      <tr><td>Time</td><td>Deal</td>...</tr>         ← column header row
      <tr bgcolor="...">...</tr>                     ← data rows
      ...
      <tr><th colspan="N"><b>Orders</b></th></tr>   ← next section (stop)

    Returns (column_header_names, data_row_tags).
    """
    name_lower = section_name.lower()
    section_start = -1

    for i, row in enumerate(all_rows):
        if any(_norm(th.get_text()) == name_lower for th in row.find_all("th")):
            section_start = i
            break

    if section_start < 0 or section_start + 1 >= len(all_rows):
        return [], []

    col_hdr_row = all_rows[section_start + 1]
    headers = [_norm(c.get_text()) for c in col_hdr_row.find_all(["th", "td"])]

    data_rows: list[Tag] = []
    for row in all_rows[section_start + 2:]:
        if any(_norm(th.get_text()) in _SECTION_NAMES for th in row.find_all("th")):
            break
        if row.find_all(["td", "th"]):
            data_rows.append(row)

    return headers, data_rows


def _parse_deals_rows_debug(headers: list[str], rows: list[Tag]) -> dict:
    """Return diagnostic counters for why rows were filtered in _parse_deals_rows."""
    total = 0
    skipped_no_cells = 0
    skipped_non_trade = 0
    skipped_no_symbol = 0
    sample_types: list[str] = []
    sample_symbols: list[str] = []

    for row in rows:
        cells = row.find_all("td")
        if not cells:
            skipped_no_cells += 1
            continue
        total += 1
        deal_type = (_cell(cells, headers, "type") or "").lower()
        if len(sample_types) < 5 and deal_type:
            sample_types.append(deal_type)
        if deal_type in _NON_TRADE_TYPES:
            skipped_non_trade += 1
            continue
        symbol = _cell(cells, headers, "symbol")
        if symbol and len(sample_symbols) < 5:
            sample_symbols.append(symbol)
        if not symbol:
            skipped_no_symbol += 1

    return {
        "headers": headers,
        "total_rows_with_cells": total,
        "skipped_no_cells": skipped_no_cells,
        "skipped_non_trade_type": skipped_non_trade,
        "skipped_no_symbol": skipped_no_symbol,
        "sample_types": list(dict.fromkeys(sample_types)),
        "sample_symbols": list(dict.fromkeys(sample_symbols)),
    }


def _parse_deals_rows(headers: list[str], rows: list[Tag]) -> list[dict]:
    """
    Parse deal rows extracted from a Deals section.

    Deals section column structure (real MT5):
      Time | Deal | Symbol | Type | Direction | Volume | Price | Order
      | [Cost — class="hidden", always empty, skip] | Commission | Fee
      | Swap | Profit | Balance | Comment

    The hidden Cost column is included in the headers list with text "cost" (or "").
    Column-name-based lookup (_cell) is unaffected by it — it simply finds the
    right column by name regardless of index offsets.
    """
    results = []
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        deal_type = (_cell(cells, headers, "type") or "").lower()
        if deal_type in _NON_TRADE_TYPES:
            continue

        symbol = _cell(cells, headers, "symbol")
        if not symbol:
            continue

        results.append({
            "time":       _cell(cells, headers, "time"),
            "deal":       _cell(cells, headers, "deal"),
            "symbol":     symbol.upper().strip(),
            "type":       deal_type,
            "direction":  (_cell(cells, headers, "direction") or "").lower(),
            "volume":     _cell(cells, headers, "volume"),
            "price":      _cell(cells, headers, "price"),
            "order":      _cell(cells, headers, "order"),
            "commission": _cell(cells, headers, "commission"),
            "swap":       _cell(cells, headers, "swap"),
            "profit":     _cell(cells, headers, "profit"),
            "balance":    _cell(cells, headers, "balance"),
            "comment":    _cell(cells, headers, "comment"),
        })
    return results


def _parse_positions_rows(headers: list[str], rows: list[Tag]) -> list[dict]:
    """
    Parse position rows from a Positions section or a legacy statement table.

    Handles two column naming conventions:
      Sectioned (real MT5):  "time" appears twice (open + close), "symbol", "position"
      Legacy (MT4/statement): "open time", "close time", "item" for symbol, "ticket"

    MT5 sectioned positions also use a <td class="hidden" colspan="8"> spacer
    between open and close sides. We use column-name lookup for all fields to
    avoid index-offset issues from that spacer.
    """
    # Pre-compute indices for ambiguous duplicate column names
    time_indices = [i for i, h in enumerate(headers) if h == "time"]
    price_indices = [i for i, h in enumerate(headers) if h == "price"]

    results = []
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue

        def nth_cell(idx_list: list[int], n: int) -> Optional[str]:
            try:
                text = cells[idx_list[n]].get_text(strip=True)
                return text if text else None
            except IndexError:
                return None

        ticket = (
            _cell(cells, headers, "position")
            or _cell(cells, headers, "ticket")
            or _cell(cells, headers, "order")
            or _cell(cells, headers, "#")
        )
        if not ticket:
            continue

        trade_type = (_cell(cells, headers, "type") or "").lower()
        if trade_type in _NON_TRADE_TYPES:
            continue

        # Symbol: "symbol" in sectioned format, "item" in legacy MT4 format
        symbol = _cell(cells, headers, "symbol") or _cell(cells, headers, "item")
        if not symbol:
            continue

        # Open time: "time" (first occurrence) in sectioned, "open time" in legacy
        open_time = nth_cell(time_indices, 0) if time_indices else _cell(cells, headers, "open time")
        # Close time: "time" (second occurrence) in sectioned, "close time" in legacy
        close_time = nth_cell(time_indices, 1) if len(time_indices) > 1 else _cell(cells, headers, "close time")

        results.append({
            "open_time":   open_time,
            "ticket":      ticket,
            "type":        trade_type,
            "size":        _cell(cells, headers, "volume") or _cell(cells, headers, "size"),
            "symbol":      symbol.upper().strip(),
            "open_price":  nth_cell(price_indices, 0),
            "sl":          _cell(cells, headers, "s/l"),
            "tp":          _cell(cells, headers, "t/p"),
            "close_time":  close_time,
            "close_price": nth_cell(price_indices, 1),
            "commission":  _cell(cells, headers, "commission"),
            "swap":        _cell(cells, headers, "swap"),
            "profit":      _cell(cells, headers, "profit"),
            "comment":     _cell(cells, headers, "comment"),
        })
    return results


def _try_section_parse(soup: BeautifulSoup) -> Optional[dict]:
    """
    Parse using section headers (Deals / Positions).
    Returns a result dict, or None if no section headers are found.
    """
    table = _find_main_table(soup)
    if not table:
        return None
    all_rows = table.find_all("tr")

    # Primary: Deals (most complete, authoritative)
    hdrs, rows = _find_section(all_rows, "Deals")
    if hdrs and rows and "direction" in hdrs:
        deals = _parse_deals_rows(hdrs, rows)
        result: dict = {"format": "deals", "deals": deals}
        if not deals:
            result["_debug"] = _parse_deals_rows_debug(hdrs, rows)
        return result

    # Secondary: Positions
    hdrs, rows = _find_section(all_rows, "Positions")
    if hdrs and rows:
        return {"format": "statement", "positions": _parse_positions_rows(hdrs, rows)}

    return None


# ---------------------------------------------------------------------------
# Variant B: Legacy column-scanning (simple exports, test fixtures)
# ---------------------------------------------------------------------------

def _best_header_row(table: Tag) -> tuple[list[str], int]:
    """
    Scan the first several rows of a table and return (headers, row_index) for
    the row that best matches known MT5 column keywords.
    Handles section-title rows (e.g. a single "Deals" colspan cell) that appear
    before the real column header row in some export formats.
    """
    all_keywords = _DEALS_KEYWORDS | _STATEMENT_KEYWORDS
    best_score, best_headers, best_idx = -1, [], 0

    for idx, row in enumerate(table.find_all("tr")[:8]):
        cells = row.find_all(["th", "td"])
        if len(cells) < 3:
            continue
        hdrs = [_norm(c.get_text()) for c in cells]
        score = sum(1 for k in all_keywords if k in set(hdrs))
        if score > best_score:
            best_score, best_headers, best_idx = score, hdrs, idx

    return best_headers, best_idx


def _score(headers: list[str], keywords: set[str]) -> int:
    h_set = set(headers)
    return sum(1 for k in keywords if k in h_set)


def _try_legacy_parse(soup: BeautifulSoup) -> dict:
    """
    Legacy fallback: rank all tables by keyword match, parse the best one.
    Used for simpler HTML that has no section headers.
    """
    tables = soup.find_all("table")
    if not tables:
        raise MT5ParseError("No tables found in the HTML document.")

    best_deals = (0, None, 0)
    best_statement = (0, None, 0)

    for table in tables:
        hdrs, hdr_idx = _best_header_row(table)
        ds = _score(hdrs, _DEALS_KEYWORDS)
        ss = _score(hdrs, _STATEMENT_KEYWORDS)
        if ds > best_deals[0]:
            best_deals = (ds, table, hdr_idx)
        if ss > best_statement[0]:
            best_statement = (ss, table, hdr_idx)

    THRESHOLD = 5

    if best_statement[0] >= THRESHOLD:
        hdrs, hdr_idx = _best_header_row(best_statement[1])
        if "close time" in hdrs:
            rows = best_statement[1].find_all("tr")
            headers = [_norm(c.get_text()) for c in rows[hdr_idx].find_all(["th", "td"])]
            return {"format": "statement", "positions": _parse_positions_rows(headers, rows[hdr_idx + 1:])}

    if best_deals[0] >= THRESHOLD:
        hdrs, hdr_idx = _best_header_row(best_deals[1])
        if "direction" in hdrs:
            rows = best_deals[1].find_all("tr")
            headers = [_norm(c.get_text()) for c in rows[hdr_idx].find_all(["th", "td"])]
            return {"format": "deals", "deals": _parse_deals_rows(headers, rows[hdr_idx + 1:])}

    raise MT5ParseError(
        "Could not identify a valid MT5 trade history table. "
        "Please export an MT5 Account Statement or trading history as HTML."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_mt5_html(html_content: str | bytes) -> dict:
    """
    Parse an MT5 HTML report and return raw extracted data.

    Handles:
    - UTF-16 LE encoding (standard MT5 terminal output)
    - Single-table HTML with Deals/Positions/Orders section headers
    - Multi-table HTML where each section is a separate table
    - Section-title rows before column header rows

    Returns a dict with:
      format   : "deals" | "statement"
      deals    : list[dict]   (present when format == "deals")
      positions: list[dict]   (present when format == "statement")
    """
    if isinstance(html_content, bytes):
        html_content = _decode(html_content)

    soup = BeautifulSoup(html_content, "html.parser")

    # Try section-based parsing first (handles real MT5 reports)
    result = _try_section_parse(soup)
    if result is not None:
        return result

    # Fall back to column-scanning (handles simpler formats and test fixtures)
    return _try_legacy_parse(soup)

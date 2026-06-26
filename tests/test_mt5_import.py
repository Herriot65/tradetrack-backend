"""
Tests for MT5 HTML import: parser, mapper, and API endpoint.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.importers.mt5.mapper import map_deal_rows, map_statement_rows, _compute_pnl_percent
from core.importers.mt5.parser import MT5ParseError, parse_mt5_html
from core.models import ImportBatch, Trade, TradeImport

from tests.factories import JournalFactory, UserFactory


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

DEALS_HTML = """
<html><body>
<table>
<tr>
  <td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
  <td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>
  <td>Profit</td><td>Balance</td><td>Comment</td>
</tr>
<tr>
  <td>2024.01.01 00:00:00</td><td>1</td><td></td>
  <td>balance</td><td></td><td>0.00</td><td>0.00</td><td>1</td>
  <td>0.00</td><td>0.00</td><td>10000.00</td><td>10000.00</td><td>Initial deposit</td>
</tr>
<tr>
  <td>2024.01.02 09:00:00</td><td>1001</td><td>EURUSD</td>
  <td>buy</td><td>in</td><td>0.10</td><td>1.08500</td><td>5001</td>
  <td>-0.70</td><td>0.00</td><td>0.00</td><td>10000.00</td><td>entry signal</td>
</tr>
<tr>
  <td>2024.01.02 10:30:00</td><td>1002</td><td>EURUSD</td>
  <td>sell</td><td>out</td><td>0.10</td><td>1.08700</td><td>5002</td>
  <td>-0.70</td><td>0.00</td><td>20.00</td><td>10019.60</td><td></td>
</tr>
<tr>
  <td>2024.01.03 08:00:00</td><td>1003</td><td>GBPUSD</td>
  <td>sell</td><td>in</td><td>0.05</td><td>1.27000</td><td>5003</td>
  <td>-0.50</td><td>0.00</td><td>0.00</td><td>10019.60</td><td></td>
</tr>
<tr>
  <td>2024.01.03 11:00:00</td><td>1004</td><td>GBPUSD</td>
  <td>buy</td><td>out</td><td>0.05</td><td>1.26500</td><td>5004</td>
  <td>-0.50</td><td>-1.20</td><td>25.00</td><td>10043.90</td><td></td>
</tr>
</table>
</body></html>
"""

STATEMENT_HTML = """
<html><body>
<table>
<tr>
  <td>Open Time</td><td>Ticket</td><td>Type</td><td>Size</td><td>Item</td>
  <td>Price</td><td>S/L</td><td>T/P</td><td>Close Time</td><td>Price</td>
  <td>Commission</td><td>Taxes</td><td>Swap</td><td>Profit</td>
</tr>
<tr>
  <td>2024.03.10 09:00:00</td><td>2001</td><td>buy</td><td>0.10</td><td>EURUSD</td>
  <td>1.08500</td><td>1.08000</td><td>1.09500</td><td>2024.03.10 14:00:00</td><td>1.09200</td>
  <td>-1.40</td><td>0.00</td><td>0.00</td><td>70.00</td>
</tr>
<tr>
  <td>2024.03.11 10:00:00</td><td>2002</td><td>sell</td><td>0.20</td><td>GBPUSD</td>
  <td>1.27000</td><td>1.27500</td><td>1.26000</td><td>2024.03.11 15:30:00</td><td>1.26800</td>
  <td>-2.00</td><td>0.00</td><td>-0.50</td><td>40.00</td>
</tr>
</table>
</body></html>
"""

BAD_HTML = "<html><body><p>No trade tables here.</p></body></html>"

# ---------------------------------------------------------------------------
# Fixtures that match the ACTUAL Deriv/MT5 file structure:
# - Single <table> with all sections
# - <th colspan="N"><b>SectionName</b></th> section headers
# - Deals columns include hidden "Cost" column and a "Fee" column
# ---------------------------------------------------------------------------

# UTF-16 LE version of the single-table sectioned format (what Deriv MT5 generates)
_REAL_MT5_HTML_UTF8 = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">
<html>
<head><meta http-equiv="Content-Type" content="text/html; charset=UTF-16"></head>
<body>
<div align="center">
<table border="1">
  <!-- Account header rows -->
  <tr><th>Name</th><th>HERRIOT DEO GRATIAS DAGOUDI</th></tr>
  <tr><th>Account</th><th>140299951</th></tr>

  <!-- Positions section -->
  <tr><th colspan="14"><b>Positions</b></th></tr>
  <tr><td>Time</td><td>Position</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S/L</td><td>T/P</td><td>Time</td><td>Price</td><td>Commission</td><td>Swap</td><td>Profit</td><td></td></tr>
  <tr bgcolor="#FFFFFF"><td>2024.01.02 09:00:00</td><td>7001</td><td>EURUSD</td><td>buy</td><td>0.10</td><td>1.08500</td><td>1.08000</td><td>1.09500</td><td>2024.01.02 14:00:00</td><td>1.09200</td><td>-1.40</td><td>0.00</td><td>70.00</td><td></td></tr>

  <!-- Orders section -->
  <tr><th colspan="14"><b>Orders</b></th></tr>
  <tr><td>Open Time</td><td>Order</td><td>Symbol</td><td>Type</td><td>Volume</td><td>Price</td><td>S/L</td><td>T/P</td><td>Time</td><td>State</td><td>Comment</td><td></td><td></td><td></td></tr>

  <!-- Deals section — authoritative source -->
  <tr><th colspan="15"><b>Deals</b></th></tr>
  <tr>
    <td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
    <td>Volume</td><td>Price</td><td>Order</td><td>Cost</td>
    <td>Commission</td><td>Fee</td><td>Swap</td><td>Profit</td><td>Balance</td><td>Comment</td>
  </tr>
  <!-- Balance deposit — should be skipped -->
  <tr bgcolor="#FFFFFF"><td>2024.01.01 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td>0.00</td><td>0.00</td><td>1</td><td></td><td>0.00</td><td>0.00</td><td>0.00</td><td>10000.00</td><td>10000.00</td><td>R-initial</td></tr>
  <!-- Entry deal: buy EURUSD -->
  <tr bgcolor="#F7F7F7"><td>2024.03.10 09:00:00</td><td>3001</td><td>EURUSD</td><td>buy</td><td>in</td><td>0.10</td><td>1.08500</td><td>5001</td><td></td><td>-0.70</td><td>0.00</td><td>0.00</td><td>0.00</td><td>10000.00</td><td>entry</td></tr>
  <!-- Exit deal: close EURUSD long -->
  <tr bgcolor="#FFFFFF"><td>2024.03.10 14:00:00</td><td>3002</td><td>EURUSD</td><td>sell</td><td>out</td><td>0.10</td><td>1.09200</td><td>5002</td><td></td><td>-0.70</td><td>0.00</td><td>0.00</td><td>70.00</td><td>10069.60</td><td></td></tr>
  <!-- Entry deal: sell GBPUSD -->
  <tr bgcolor="#F7F7F7"><td>2024.03.11 10:00:00</td><td>3003</td><td>GBPUSD</td><td>sell</td><td>in</td><td>0.20</td><td>1.27000</td><td>5003</td><td></td><td>-1.00</td><td>0.00</td><td>0.00</td><td>0.00</td><td>10069.60</td><td></td></tr>
  <!-- Exit deal: close GBPUSD short -->
  <tr bgcolor="#FFFFFF"><td>2024.03.11 15:30:00</td><td>3004</td><td>GBPUSD</td><td>buy</td><td>out</td><td>0.20</td><td>1.26800</td><td>5004</td><td></td><td>-1.00</td><td>0.00</td><td>-0.50</td><td>40.00</td><td>10108.10</td><td></td></tr>
  <!-- Totals row — should be skipped -->
  <tr align="right"><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>-3.40</td><td>0.00</td><td>-0.50</td><td>110.00</td><td></td><td></td></tr>
</table>
</div>
</body>
</html>"""

REAL_MT5_HTML_UTF16 = _REAL_MT5_HTML_UTF8.encode("utf-16-le")
REAL_MT5_HTML_UTF16_BOM = b'\xff\xfe' + _REAL_MT5_HTML_UTF8.encode("utf-16-le")

# Real MT5 reports prepend a colspan section-title row ("Deals") before the column headers.
# This fixture tests that the parser skips that title row and finds the real headers.
DEALS_HTML_WITH_SECTION_TITLE = """
<html><body>
<table>
<tr><td colspan="13"><b>Deals</b></td></tr>
<tr>
  <td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
  <td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>
  <td>Profit</td><td>Balance</td><td>Comment</td>
</tr>
<tr>
  <td>2024.01.01 00:00:00</td><td>1</td><td></td>
  <td>balance</td><td></td><td>0.00</td><td>0.00</td><td>1</td>
  <td>0.00</td><td>0.00</td><td>10000.00</td><td>10000.00</td><td>Initial deposit</td>
</tr>
<tr>
  <td>2024.02.01 09:00:00</td><td>2001</td><td>EURUSD</td>
  <td>buy</td><td>in</td><td>0.10</td><td>1.08500</td><td>9001</td>
  <td>-0.70</td><td>0.00</td><td>0.00</td><td>10000.00</td><td></td>
</tr>
<tr>
  <td>2024.02.01 11:00:00</td><td>2002</td><td>EURUSD</td>
  <td>sell</td><td>out</td><td>0.10</td><td>1.09000</td><td>9002</td>
  <td>-0.70</td><td>0.00</td><td>50.00</td><td>10049.60</td><td></td>
</tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMT5Parser:
    def test_parse_deals_format(self):
        result = parse_mt5_html(DEALS_HTML)
        assert result["format"] == "deals"
        deals = result["deals"]
        # Balance row should be excluded
        assert all(d["symbol"] for d in deals)
        assert len(deals) == 4

    def test_deals_fields(self):
        result = parse_mt5_html(DEALS_HTML)
        entry = result["deals"][0]
        assert entry["symbol"] == "EURUSD"
        assert entry["type"] == "buy"
        assert entry["direction"] == "in"
        assert entry["deal"] == "1001"
        assert entry["commission"] == "-0.70"

    def test_parse_statement_format(self):
        result = parse_mt5_html(STATEMENT_HTML)
        assert result["format"] == "statement"
        positions = result["positions"]
        assert len(positions) == 2

    def test_statement_fields(self):
        result = parse_mt5_html(STATEMENT_HTML)
        pos = result["positions"][0]
        assert pos["symbol"] == "EURUSD"
        assert pos["type"] == "buy"
        assert pos["ticket"] == "2001"
        assert pos["open_price"] == "1.08500"
        assert pos["close_price"] == "1.09200"
        assert pos["sl"] == "1.08000"
        assert pos["tp"] == "1.09500"
        assert pos["profit"] == "70.00"

    def test_bad_html_raises(self):
        with pytest.raises(MT5ParseError):
            parse_mt5_html(BAD_HTML)

    def test_accepts_bytes(self):
        result = parse_mt5_html(DEALS_HTML.encode())
        assert result["format"] == "deals"

    def test_section_title_row_before_headers(self):
        """Parser must skip the single-cell 'Deals' colspan row and find real column headers."""
        result = parse_mt5_html(DEALS_HTML_WITH_SECTION_TITLE)
        assert result["format"] == "deals"
        deals = result["deals"]
        assert len(deals) == 2  # balance row excluded, 1 entry + 1 exit
        assert deals[0]["symbol"] == "EURUSD"
        assert deals[0]["direction"] == "in"

    # --- Real MT5 single-table sectioned format (Deriv broker) ---

    def test_real_mt5_single_table_section_parse(self):
        """Parser finds the Deals section inside a single table with multiple sections."""
        result = parse_mt5_html(_REAL_MT5_HTML_UTF8)
        assert result["format"] == "deals"
        deals = result["deals"]
        # 4 trade deals (2 entry + 2 exit), balance row excluded, totals row excluded
        assert len(deals) == 4
        assert all(d["symbol"] in {"EURUSD", "GBPUSD"} for d in deals)

    def test_real_mt5_deals_have_correct_direction(self):
        result = parse_mt5_html(_REAL_MT5_HTML_UTF8)
        directions = [d["direction"] for d in result["deals"]]
        assert directions.count("in") == 2
        assert directions.count("out") == 2

    def test_real_mt5_balance_rows_excluded(self):
        result = parse_mt5_html(_REAL_MT5_HTML_UTF8)
        assert all(d["type"] != "balance" for d in result["deals"])

    def test_real_mt5_totals_row_excluded(self):
        """Row with align='right' (totals) must be skipped."""
        result = parse_mt5_html(_REAL_MT5_HTML_UTF8)
        # If totals row were included it would have no symbol, but verify count is right
        assert len(result["deals"]) == 4

    def test_hidden_cost_column_does_not_break_commission(self):
        """The hidden 'Cost' column between Order and Commission must not shift other fields."""
        result = parse_mt5_html(_REAL_MT5_HTML_UTF8)
        eurusd_entry = next(d for d in result["deals"] if d["symbol"] == "EURUSD" and d["direction"] == "in")
        assert eurusd_entry["commission"] == "-0.70"

    def test_utf16_le_without_bom(self):
        """Parser must handle UTF-16 LE bytes without a BOM (common in MT5 exports)."""
        result = parse_mt5_html(REAL_MT5_HTML_UTF16)
        assert result["format"] == "deals"
        assert len(result["deals"]) == 4

    def test_utf16_le_with_bom(self):
        """Parser must handle UTF-16 LE bytes with the standard 0xFF 0xFE BOM."""
        result = parse_mt5_html(REAL_MT5_HTML_UTF16_BOM)
        assert result["format"] == "deals"
        assert len(result["deals"]) == 4


# ---------------------------------------------------------------------------
# Mapper tests
# ---------------------------------------------------------------------------

class TestMapper:
    def test_pnl_percent_calculation(self):
        profit = Decimal("245")
        capital = Decimal("10000")
        result = _compute_pnl_percent(profit, capital)
        assert result == Decimal("2.45")

    def test_pnl_percent_zero_capital(self):
        assert _compute_pnl_percent(Decimal("100"), Decimal("0")) is None

    def test_pnl_percent_none_profit(self):
        assert _compute_pnl_percent(None, Decimal("10000")) is None

    def test_map_statement_rows(self):
        parsed = parse_mt5_html(STATEMENT_HTML)
        trades = map_statement_rows(parsed["positions"], Decimal("10000"))
        assert len(trades) == 2

        t = trades[0]
        assert t["symbol"] == "EURUSD"
        assert t["side"] == "BUY"
        assert t["pnl_r"] == Decimal("0.70")  # 70/10000 * 100
        assert t["commission"] == Decimal("-1.40")
        assert t["external_id"] == "2001"

        t2 = trades[1]
        assert t2["side"] == "SELL"
        assert t2["swap"] == Decimal("-0.50")

    def test_map_deal_rows_pairs_correctly(self):
        parsed = parse_mt5_html(DEALS_HTML)
        trades, warnings = map_deal_rows(parsed["deals"], Decimal("10000"))
        assert len(trades) == 2
        assert warnings == []

        eurusd = next(t for t in trades if t["symbol"] == "EURUSD")
        assert eurusd["side"] == "BUY"
        assert eurusd["pnl_r"] == Decimal("0.20")  # 20/10000*100
        assert eurusd["commission"] == Decimal("-1.40")  # entry -0.70 + exit -0.70
        assert eurusd["external_id"] == "1001"  # entry deal #

        gbpusd = next(t for t in trades if t["symbol"] == "GBPUSD")
        assert gbpusd["side"] == "SELL"
        assert gbpusd["pnl_r"] == Decimal("0.25")  # 25/10000*100
        assert gbpusd["swap"] == Decimal("-1.20")

    def test_notes_contain_mt5_metadata(self):
        parsed = parse_mt5_html(STATEMENT_HTML)
        trades = map_statement_rows(parsed["positions"], Decimal("10000"))
        assert "[MT5 Import]" in trades[0]["notes"]
        assert "Entry: 1.08500" in trades[0]["notes"]

    def test_raw_profit_stored(self):
        parsed = parse_mt5_html(DEALS_HTML)
        trades, _ = map_deal_rows(parsed["deals"], Decimal("10000"))
        eurusd = next(t for t in trades if t["symbol"] == "EURUSD")
        assert eurusd["raw_profit"] == Decimal("20.00")

    def test_open_position_imported_as_open_trade(self):
        """An 'in' deal with no matching 'out' must be imported as an open trade."""
        html = """<html><body><table>
        <tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
            <td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>
            <td>Profit</td><td>Balance</td><td>Comment</td></tr>
        <tr><td>2024.06.01 09:00:00</td><td>9001</td><td>EURUSD</td><td>buy</td><td>in</td>
            <td>0.10</td><td>1.08500</td><td>5001</td><td>-0.70</td><td>0.00</td>
            <td>0.00</td><td>10000.00</td><td></td></tr>
        </table></body></html>"""
        parsed = parse_mt5_html(html)
        trades, warnings = map_deal_rows(parsed["deals"], Decimal("10000"))
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "EURUSD"
        assert t["side"] == "BUY"
        assert t["exit_datetime"] is None
        assert t["pnl_r"] is None
        assert t["external_id"] == "9001"
        assert warnings == []

    def test_reversal_in_out_deal_creates_two_trades(self):
        """An 'in/out' deal closes the existing position and opens a new one."""
        html = """<html><body><table>
        <tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
            <td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>
            <td>Profit</td><td>Balance</td><td>Comment</td></tr>
        <!-- Open a buy -->
        <tr><td>2024.06.01 09:00:00</td><td>8001</td><td>EURUSD</td><td>buy</td><td>in</td>
            <td>0.10</td><td>1.08000</td><td>5001</td><td>-0.70</td><td>0.00</td>
            <td>0.00</td><td>10000.00</td><td></td></tr>
        <!-- Reversal: close buy and open sell -->
        <tr><td>2024.06.01 11:00:00</td><td>8002</td><td>EURUSD</td><td>sell</td><td>in/out</td>
            <td>0.10</td><td>1.08500</td><td>5002</td><td>-0.70</td><td>0.00</td>
            <td>50.00</td><td>10049.60</td><td>reversal</td></tr>
        <!-- Close the sell opened by the reversal -->
        <tr><td>2024.06.01 14:00:00</td><td>8003</td><td>EURUSD</td><td>buy</td><td>out</td>
            <td>0.10</td><td>1.08200</td><td>5003</td><td>-0.70</td><td>0.00</td>
            <td>30.00</td><td>10079.60</td><td></td></tr>
        </table></body></html>"""
        parsed = parse_mt5_html(html)
        trades, warnings = map_deal_rows(parsed["deals"], Decimal("10000"))
        assert len(trades) == 2
        assert warnings == []

        first = next(t for t in trades if t["external_id"] == "8001")
        assert first["side"] == "BUY"
        assert first["pnl_r"] == Decimal("0.50")  # 50/10000*100
        assert first["exit_datetime"] is not None

        second = next(t for t in trades if t["external_id"] == "8002")
        assert second["side"] == "SELL"
        assert second["pnl_r"] == Decimal("0.30")  # 30/10000*100

    def test_unmatched_exit_generates_warning(self):
        """An 'out' deal with no matching 'in' must emit a warning and not crash."""
        html = """<html><body><table>
        <tr><td>Time</td><td>Deal</td><td>Symbol</td><td>Type</td><td>Direction</td>
            <td>Volume</td><td>Price</td><td>Order</td><td>Commission</td><td>Swap</td>
            <td>Profit</td><td>Balance</td><td>Comment</td></tr>
        <tr><td>2024.06.01 14:00:00</td><td>7777</td><td>EURUSD</td><td>sell</td><td>out</td>
            <td>0.10</td><td>1.09000</td><td>5005</td><td>-0.70</td><td>0.00</td>
            <td>50.00</td><td>10050.00</td><td></td></tr>
        </table></body></html>"""
        parsed = parse_mt5_html(html)
        trades, warnings = map_deal_rows(parsed["deals"], Decimal("10000"))
        assert len(trades) == 0
        assert len(warnings) == 1
        assert warnings[0]["type"] == "unmatched_exit"
        assert warnings[0]["symbol"] == "EURUSD"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMT5ImportEndpoint:
    def setup_method(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.journal = JournalFactory(user=self.user, starting_capital=Decimal("10000"))
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/journals/{self.journal.pk}/imports/mt5/"

    def _upload(self, html: str, filename: str = "report.html"):
        file = io.BytesIO(html.encode())
        file.name = filename
        return self.client.post(
            self.url,
            {"file": file},
            format="multipart",
        )

    def test_deals_import_success(self):
        response = self._upload(DEALS_HTML)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["trades_created"] == 2
        assert data["trades_skipped"] == 0
        assert data["rows_parsed"] == 2

    def test_statement_import_success(self):
        response = self._upload(STATEMENT_HTML)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["trades_created"] == 2

    def test_trades_created_in_db(self):
        self._upload(DEALS_HTML)
        assert Trade.objects.filter(journal=self.journal).count() == 2

    def test_pnl_stored_as_percent(self):
        self._upload(DEALS_HTML)
        eurusd = Trade.objects.get(journal=self.journal, asset__symbol="EURUSD")
        assert eurusd.pnl_r == Decimal("0.20")

    def test_import_batch_recorded(self):
        self._upload(DEALS_HTML)
        batch = ImportBatch.objects.get(journal=self.journal)
        assert batch.source == "mt5_html"
        assert batch.trades_created == 2

    def test_trade_import_records_created(self):
        self._upload(DEALS_HTML)
        assert TradeImport.objects.filter(journal=self.journal).count() == 2

    def test_raw_profit_stored_in_trade_import(self):
        self._upload(DEALS_HTML)
        ti = TradeImport.objects.get(journal=self.journal, external_id="1001")
        assert ti.raw_profit == Decimal("20.00")

    def test_dedup_on_reimport(self):
        self._upload(DEALS_HTML)
        response = self._upload(DEALS_HTML)
        data = response.json()
        assert data["trades_skipped"] == 2
        assert data["trades_created"] == 0
        assert Trade.objects.filter(journal=self.journal).count() == 2

    def test_no_file_returns_400(self):
        response = self.client.post(self.url, {}, format="multipart")
        assert response.status_code == 400

    def test_wrong_file_type_returns_400(self):
        file = io.BytesIO(b"some,csv,data")
        file.name = "report.csv"
        response = self.client.post(self.url, {"file": file}, format="multipart")
        assert response.status_code == 400

    def test_bad_html_returns_422(self):
        response = self._upload(BAD_HTML)
        assert response.status_code == 422
        assert response.json()["success"] is False

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self._upload(DEALS_HTML)
        assert response.status_code == 401

    def test_wrong_journal_returns_404(self):
        other_url = f"/api/journals/99999/imports/mt5/"
        response = self._upload(DEALS_HTML)
        # Posting to own journal succeeds — just verify 404 on nonexistent
        bad_response = self.client.post(
            other_url,
            {"file": io.BytesIO(DEALS_HTML.encode())},
            format="multipart",
        )
        assert bad_response.status_code == 404

    def test_zero_capital_returns_400(self):
        self.journal.starting_capital = Decimal("0")
        self.journal.save()
        response = self._upload(DEALS_HTML)
        assert response.status_code == 400
        assert "starting capital" in response.json()["error"].lower()

    def test_assets_auto_created(self):
        self._upload(DEALS_HTML)
        from core.models import Asset
        symbols = set(Asset.objects.filter(journal=self.journal).values_list("symbol", flat=True))
        assert "EURUSD" in symbols
        assert "GBPUSD" in symbols

    def test_filename_stored_in_batch(self):
        self._upload(DEALS_HTML, filename="my_statement.html")
        batch = ImportBatch.objects.get(journal=self.journal)
        assert batch.filename == "my_statement.html"

    def test_pnl_recomputed_when_capital_changes(self):
        """Patching starting_capital must recompute pnl_r for all imported trades."""
        # Import with capital=10000: EURUSD profit=20 → pnl_r=0.20, GBPUSD profit=25 → pnl_r=0.25
        self._upload(DEALS_HTML)

        # Halve the capital via API PATCH
        url = f"/api/journals/{self.journal.pk}/"
        self.client.patch(url, {"starting_capital": "5000.00"}, format="json")

        eurusd = Trade.objects.get(journal=self.journal, asset__symbol="EURUSD")
        gbpusd = Trade.objects.get(journal=self.journal, asset__symbol="GBPUSD")
        # 20 / 5000 * 100 = 0.40, 25 / 5000 * 100 = 0.50
        assert eurusd.pnl_r == Decimal("0.40")
        assert gbpusd.pnl_r == Decimal("0.50")

    def test_pnl_not_recomputed_when_other_settings_change(self):
        """Patching non-capital fields must leave pnl_r untouched."""
        self._upload(DEALS_HTML)

        url = f"/api/journals/{self.journal.pk}/"
        self.client.patch(url, {"currency": "EUR", "name": "Renamed"}, format="json")

        eurusd = Trade.objects.get(journal=self.journal, asset__symbol="EURUSD")
        assert eurusd.pnl_r == Decimal("0.20")  # unchanged

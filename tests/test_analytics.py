from decimal import Decimal
from datetime import datetime, timezone

import pytest
from rest_framework.test import APIClient

from tests.factories import JournalFactory, SetupTagFactory, TradeFactory, UserFactory


def dt(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def journal(user):
    return JournalFactory(user=user)


@pytest.fixture
def client(user):
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
def test_dashboard_summary_calculations(client, user, journal):
    TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("2.00"), entry_datetime=dt("2026-06-01T10:00:00Z"), exit_datetime=dt("2026-06-01T11:00:00Z"))
    TradeFactory(journal=journal, status="LOSS", pnl_r=Decimal("-1.00"), entry_datetime=dt("2026-06-02T10:00:00Z"), exit_datetime=dt("2026-06-02T11:00:00Z"))
    TradeFactory(journal=journal, status="BE", pnl_r=Decimal("0.00"), entry_datetime=dt("2026-06-03T10:00:00Z"), exit_datetime=dt("2026-06-03T11:00:00Z"))
    # Open trade (no exit_datetime) — excluded from analytics
    TradeFactory(journal=journal, pnl_r=Decimal("5.00"), exit_datetime=None, entry_datetime=dt("2026-06-04T10:00:00Z"))
    # Different journal — excluded
    TradeFactory(status="WIN", pnl_r=Decimal("99.00"))

    response = client.get(f"/api/journals/{journal.id}/dashboard/summary/")

    assert response.status_code == 200
    assert response.data == {
        "has_data": True,
        "total_trades": 4,  # 3 closed + 1 open
        "win_rate": 33.33,
        "total_r": 1.0,
        "profit_factor": 2.0,
        "max_drawdown_r": -1.0,
        "average_r": 0.33,
    }


@pytest.mark.django_db
def test_profit_factor_is_none_when_no_losses(client, user, journal):
    TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("2.00"))

    response = client.get(f"/api/journals/{journal.id}/dashboard/summary/")

    assert response.status_code == 200
    assert response.data["has_data"] is True
    assert response.data["profit_factor"] is None


@pytest.mark.django_db
def test_equity_curve_uses_cumulative_pnl_by_period(client, user, journal):
    TradeFactory(journal=journal, pnl_r=Decimal("2.00"), entry_datetime=dt("2026-06-01T10:00:00Z"), exit_datetime=dt("2026-06-01T11:00:00Z"))
    TradeFactory(journal=journal, pnl_r=Decimal("-0.50"), entry_datetime=dt("2026-06-03T10:00:00Z"), exit_datetime=dt("2026-06-03T11:00:00Z"))
    TradeFactory(journal=journal, pnl_r=Decimal("1.00"), entry_datetime=dt("2026-06-08T10:00:00Z"), exit_datetime=dt("2026-06-08T11:00:00Z"))

    response = client.get(f"/api/journals/{journal.id}/analytics/equity-curve/?period=weekly")

    assert response.status_code == 200
    assert response.data == [
        {"date": "2026-06-01", "equity_r": 1.5},
        {"date": "2026-06-08", "equity_r": 2.5},
    ]


@pytest.mark.django_db
def test_win_loss_distribution(client, user, journal):
    TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("1.00"))
    TradeFactory(journal=journal, status="LOSS", pnl_r=Decimal("-1.00"))
    TradeFactory(journal=journal, status="BE", pnl_r=Decimal("0.00"))
    # Open trade — excluded
    TradeFactory(journal=journal, exit_datetime=None, pnl_r=None)

    response = client.get(f"/api/journals/{journal.id}/analytics/win-loss-distribution/")

    assert response.status_code == 200
    assert response.data == {"has_data": True, "wins": 1, "losses": 1, "break_even": 1}


@pytest.mark.django_db
def test_pnl_by_setup_aggregation(client, user, journal):
    pullback = SetupTagFactory(journal=journal, label="Pullback")
    breakout = SetupTagFactory(journal=journal, label="Breakout")

    TradeFactory(journal=journal, setup=pullback, pnl_r=Decimal("2.00"))
    TradeFactory(journal=journal, setup=pullback, pnl_r=Decimal("-0.50"))
    TradeFactory(journal=journal, setup=breakout, pnl_r=Decimal("-1.00"))
    # Different journal — excluded
    TradeFactory(pnl_r=Decimal("99.00"))

    response = client.get(f"/api/journals/{journal.id}/analytics/pnl-by-setup/")

    assert response.status_code == 200
    assert response.data == [
        {"setup": "Pullback", "total_r": 1.5},
        {"setup": "Breakout", "total_r": -1.0},
    ]


@pytest.mark.django_db
def test_analytics_return_has_data_false_when_no_trades(client, user, journal):
    # Journal exists but has no trades at all
    summary = client.get(f"/api/journals/{journal.id}/dashboard/summary/")
    assert summary.status_code == 200
    assert summary.data["has_data"] is False
    assert summary.data["total_trades"] == 0

    dist = client.get(f"/api/journals/{journal.id}/analytics/win-loss-distribution/")
    assert dist.status_code == 200
    assert dist.data["has_data"] is False

    curve = client.get(f"/api/journals/{journal.id}/analytics/equity-curve/")
    assert curve.status_code == 200
    assert curve.data == []

    pnl = client.get(f"/api/journals/{journal.id}/analytics/pnl-by-setup/")
    assert pnl.status_code == 200
    assert pnl.data == []

    career = client.get(f"/api/journals/{journal.id}/analytics/career/")
    assert career.status_code == 200
    assert career.data["has_data"] is False
    assert career.data["years"] == []


@pytest.mark.django_db
def test_career_data_structure(client, user, journal):
    TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("2.00"), entry_datetime=dt("2025-03-15T10:00:00Z"), exit_datetime=dt("2025-03-15T11:00:00Z"))
    TradeFactory(journal=journal, status="LOSS", pnl_r=Decimal("-1.00"), entry_datetime=dt("2025-06-10T10:00:00Z"), exit_datetime=dt("2025-06-10T11:00:00Z"))

    response = client.get(f"/api/journals/{journal.id}/analytics/career/")

    assert response.status_code == 200
    data = response.data
    assert data["has_data"] is True
    assert "yearSummaries" in data
    assert "heatmap" in data
    assert "years" in data
    assert 2025 in data["years"]
    assert data["yearSummaries"][0]["year"] == 2025
    assert data["yearSummaries"][0]["total_r"] == 1.0

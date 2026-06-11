from decimal import Decimal
from datetime import datetime, timezone

import pytest
from rest_framework.test import APIClient

from core.models import Trade
from tests.factories import TradeFactory, UserFactory, WorkspaceFactory


def dt(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def workspace(user):
    return user.workspaces.get(name="Main")


@pytest.fixture
def client(user):
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


@pytest.mark.django_db
def test_dashboard_summary_calculations(client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.WIN, pnl_r=Decimal("2.00"), entry_datetime=dt("2026-06-01T10:00:00Z"))
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.LOSS, pnl_r=Decimal("-1.00"), entry_datetime=dt("2026-06-02T10:00:00Z"))
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.BE, pnl_r=Decimal("0.00"), entry_datetime=dt("2026-06-03T10:00:00Z"))
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.OPEN, pnl_r=Decimal("5.00"), entry_datetime=dt("2026-06-04T10:00:00Z"))
    other_workspace = WorkspaceFactory(user=user, name="Personal")
    TradeFactory(owner=user, workspace=other_workspace, status=Trade.Status.WIN, pnl_r=Decimal("99.00"))

    response = client.get(f"/api/dashboard/summary/?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data == {
        "total_trades": 3,
        "win_rate": 33.33,
        "total_r": 1.0,
        "profit_factor": 2.0,
        "max_drawdown_r": -1.0,
        "average_r": 0.33,
    }


@pytest.mark.django_db
def test_profit_factor_is_none_when_no_losses(client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.WIN, pnl_r=Decimal("2.00"))

    response = client.get(f"/api/dashboard/summary/?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data["profit_factor"] is None


@pytest.mark.django_db
def test_equity_curve_uses_cumulative_pnl_by_period(client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.WIN, pnl_r=Decimal("2.00"), entry_datetime=dt("2026-06-01T10:00:00Z"))
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.LOSS, pnl_r=Decimal("-0.50"), entry_datetime=dt("2026-06-03T10:00:00Z"))
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.WIN, pnl_r=Decimal("1.00"), entry_datetime=dt("2026-06-08T10:00:00Z"))

    response = client.get(f"/api/analytics/equity-curve/?workspace_id={workspace.id}&period=weekly")

    assert response.status_code == 200
    assert response.data == [
        {"date": "2026-06-01", "equity_r": 1.5},
        {"date": "2026-06-08", "equity_r": 2.5},
    ]


@pytest.mark.django_db
def test_win_loss_distribution(client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.WIN)
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.LOSS)
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.BE)
    TradeFactory(owner=user, workspace=workspace, status=Trade.Status.OPEN)

    response = client.get(f"/api/analytics/win-loss-distribution/?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data == {"wins": 1, "losses": 1, "break_even": 1}


@pytest.mark.django_db
def test_pnl_by_setup_aggregation(client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, setup="Pullback", status=Trade.Status.WIN, pnl_r=Decimal("2.00"))
    TradeFactory(owner=user, workspace=workspace, setup="Pullback", status=Trade.Status.LOSS, pnl_r=Decimal("-0.50"))
    TradeFactory(owner=user, workspace=workspace, setup="Breakout", status=Trade.Status.LOSS, pnl_r=Decimal("-1.00"))
    TradeFactory(setup="Pullback", status=Trade.Status.WIN, pnl_r=Decimal("99.00"))

    response = client.get(f"/api/analytics/pnl-by-setup/?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data == [
        {"setup": "Pullback", "total_r": 1.5},
        {"setup": "Breakout", "total_r": -1.0},
    ]

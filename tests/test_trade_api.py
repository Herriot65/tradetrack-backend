from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from core.models import Trade
from tests.factories import TradeFactory, UserFactory, WorkspaceFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def workspace(user):
    return user.workspaces.get(name="Main")


@pytest.fixture
def authenticated_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


def trade_payload(workspace, **overrides):
    payload = {
        "workspace": str(workspace.id),
        "asset": "GBPUSD",
        "trend_direction": Trade.TrendDirection.BULLISH,
        "opportunity_timeframe": Trade.Timeframe.H4,
        "entry_timeframe": Trade.Timeframe.M15,
        "setup": "Breakout",
        "session": Trade.Session.LONDON,
        "side": Trade.Side.BUY,
        "status": Trade.Status.WIN,
        "entry_datetime": "2026-06-01T10:00:00Z",
        "exit_datetime": "2026-06-01T11:00:00Z",
        "risk_percent": "1.00",
        "pnl_r": "2.00",
        "emotion": "Focused",
        "notes": "Clean entry",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_trade_assigns_authenticated_owner_and_workspace(authenticated_client, user, workspace):
    response = authenticated_client.post("/api/trades/", trade_payload(workspace), format="json")

    assert response.status_code == 201
    trade = Trade.objects.get(id=response.data["id"])
    assert trade.owner == user
    assert trade.workspace == workspace


@pytest.mark.django_db
def test_list_trades_only_returns_requested_workspace_trades(authenticated_client, user, workspace):
    other_workspace = WorkspaceFactory(user=user, name="FTMO")
    own_trade = TradeFactory(owner=user, workspace=workspace, asset="EURUSD")
    TradeFactory(owner=user, workspace=other_workspace, asset="GBPUSD")
    TradeFactory(asset="USDJPY")

    response = authenticated_client.get(f"/api/trades/?workspace_id={workspace.id}")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == own_trade.id


@pytest.mark.django_db
def test_list_trades_requires_workspace_id(authenticated_client):
    response = authenticated_client.get("/api/trades/")

    assert response.status_code == 400
    assert "workspace_id" in response.data


@pytest.mark.django_db
def test_user_cannot_retrieve_another_users_trade(authenticated_client, workspace):
    other_trade = TradeFactory()

    response = authenticated_client.get(f"/api/trades/{other_trade.id}/?workspace_id={workspace.id}")

    assert response.status_code == 404


@pytest.mark.django_db
def test_user_cannot_use_another_users_workspace(authenticated_client):
    other_workspace = WorkspaceFactory()

    response = authenticated_client.get(f"/api/trades/?workspace_id={other_workspace.id}")

    assert response.status_code == 400
    assert "workspace_id" in response.data


@pytest.mark.django_db
def test_update_rejects_invalid_exit_datetime(authenticated_client, user, workspace):
    trade = TradeFactory(owner=user, workspace=workspace)

    response = authenticated_client.patch(
        f"/api/trades/{trade.id}/?workspace_id={workspace.id}",
        {"exit_datetime": "2026-05-01T09:00:00Z", "entry_datetime": "2026-05-01T10:00:00Z"},
        format="json",
    )

    assert response.status_code == 400
    assert "exit_datetime" in response.data


@pytest.mark.django_db
def test_trade_filtering_search_and_ordering(authenticated_client, user, workspace):
    TradeFactory(owner=user, workspace=workspace, asset="EURUSD", setup="Pullback", pnl_r=Decimal("1.00"))
    expected = TradeFactory(owner=user, workspace=workspace, asset="GBPUSD", setup="Breakout", pnl_r=Decimal("3.00"))

    response = authenticated_client.get(
        f"/api/trades/?workspace_id={workspace.id}&asset=GBPUSD&search=Breakout&ordering=-pnl_r"
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == expected.id


@pytest.mark.django_db
def test_workspace_crud_is_user_scoped(authenticated_client, user):
    response = authenticated_client.post("/api/workspaces/", {"name": "FTMO", "description": "Challenge"}, format="json")

    assert response.status_code == 201
    workspace_id = response.data["id"]

    detail = authenticated_client.get(f"/api/workspaces/{workspace_id}/")
    assert detail.status_code == 200
    assert detail.data["name"] == "FTMO"

    other_workspace = WorkspaceFactory()
    other_detail = authenticated_client.get(f"/api/workspaces/{other_workspace.id}/")
    assert other_detail.status_code == 404

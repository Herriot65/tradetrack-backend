from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from core.models import Asset, Trade
from tests.factories import AssetFactory, JournalFactory, TradeFactory, UserFactory


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
def test_enable_generates_synthetic_trades(client, journal):
    response = client.post(f"/api/journals/{journal.id}/synthetic-data/")

    assert response.status_code == 201
    assert response.data["enabled"] is True
    assert response.data["trades_created"] > 0

    journal.refresh_from_db()
    assert journal.synthetic_data_enabled is True
    assert journal.trades.filter(is_synthetic=True).exists()
    assert journal.trades.filter(is_synthetic=False).count() == 0


@pytest.mark.django_db
def test_enable_is_blocked_when_journal_has_trades(client, journal):
    TradeFactory(journal=journal, pnl_r=Decimal("1.00"))

    response = client.post(f"/api/journals/{journal.id}/synthetic-data/")

    assert response.status_code == 400
    assert "no existing trades" in response.data["error"]
    assert not journal.trades.filter(is_synthetic=True).exists()


@pytest.mark.django_db
def test_disable_removes_synthetic_trades_and_catalog(client, journal):
    client.post(f"/api/journals/{journal.id}/synthetic-data/")
    assert Trade.objects.filter(journal=journal, is_synthetic=True).exists()
    assert Asset.objects.filter(journal=journal).exists()

    response = client.delete(f"/api/journals/{journal.id}/synthetic-data/")

    assert response.status_code == 200
    assert response.data["enabled"] is False
    assert not Trade.objects.filter(journal=journal).exists()
    assert not Asset.objects.filter(journal=journal).exists()

    journal.refresh_from_db()
    assert journal.synthetic_data_enabled is False
    assert journal.synthetic_catalog_ids == {}

    status_response = client.get(f"/api/journals/{journal.id}/synthetic-data/")
    assert status_response.data == {
        "enabled": False,
        "trade_count": 0,
        "can_enable": True,
    }


@pytest.mark.django_db
def test_disable_keeps_real_trades_added_while_enabled(client, journal):
    client.post(f"/api/journals/{journal.id}/synthetic-data/")

    real_asset = AssetFactory(journal=journal, symbol="REALPAIR")
    real_trade = TradeFactory(journal=journal, asset=real_asset, pnl_r=Decimal("2.00"))

    client.delete(f"/api/journals/{journal.id}/synthetic-data/")

    assert Trade.objects.filter(journal=journal).count() == 1
    assert Trade.objects.filter(pk=real_trade.pk).exists()

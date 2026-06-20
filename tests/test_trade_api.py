from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from core.models import Trade
from tests.factories import AssetFactory, EmotionTagFactory, JournalFactory, MistakeTagFactory, SetupTagFactory, TradeFactory, UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def journal(user):
    return JournalFactory(user=user)


@pytest.fixture
def authenticated_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


def trade_payload(journal, **overrides):
    asset = AssetFactory(journal=journal, symbol="GBPUSD")
    emotion = EmotionTagFactory(journal=journal, label="Focused")
    payload = {
        "asset_id": asset.id,
        "side": "BUY",
        "entry_datetime": "2026-06-01T10:00:00Z",
        "exit_datetime": "2026-06-01T11:00:00Z",
        "risk_percent": "1.00",
        "pnl_r": "2.00",
        "emotion_ids": [emotion.id],
        "mistake_ids": [],
        "notes": "Clean entry",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_trade_assigns_correct_journal(authenticated_client, user, journal):
    response = authenticated_client.post(
        f"/api/journals/{journal.id}/trades/", trade_payload(journal), format="json"
    )

    assert response.status_code == 201
    trade = Trade.objects.get(id=response.data["id"])
    assert trade.journal == journal


@pytest.mark.django_db
def test_list_trades_scoped_to_journal(authenticated_client, user, journal):
    other_journal = JournalFactory(user=user, name="FTMO")
    own_trade = TradeFactory(journal=journal)
    TradeFactory(journal=other_journal)
    TradeFactory()  # different user entirely

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == own_trade.id


@pytest.mark.django_db
def test_list_trades_returns_paginated_response(authenticated_client, user, journal):
    TradeFactory.create_batch(3, journal=journal)

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/")

    assert response.status_code == 200
    assert "count" in response.data
    assert "results" in response.data


@pytest.mark.django_db
def test_user_cannot_access_another_users_journal(authenticated_client):
    other_journal = JournalFactory()

    response = authenticated_client.get(f"/api/journals/{other_journal.id}/trades/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_user_cannot_retrieve_another_users_trade(authenticated_client, user, journal):
    other_trade = TradeFactory()

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/{other_trade.id}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_update_rejects_invalid_exit_datetime(authenticated_client, user, journal):
    trade = TradeFactory(journal=journal)

    response = authenticated_client.patch(
        f"/api/journals/{journal.id}/trades/{trade.id}/",
        {"exit_datetime": "2026-05-01T09:00:00Z", "entry_datetime": "2026-05-01T10:00:00Z"},
        format="json",
    )

    assert response.status_code == 400
    assert "exit_datetime" in response.data


@pytest.mark.django_db
def test_trade_response_includes_nested_asset_and_emotions(authenticated_client, user, journal):
    asset = AssetFactory(journal=journal, symbol="EURUSD")
    emotion = EmotionTagFactory(journal=journal, label="Calm")
    trade = TradeFactory(journal=journal, asset=asset, emotions=[emotion])

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/{trade.id}/")

    assert response.status_code == 200
    assert response.data["asset"] == {"id": asset.id, "symbol": "EURUSD"}
    assert {"id": emotion.id, "label": "Calm"} in response.data["emotions"]


@pytest.mark.django_db
def test_trade_search_by_asset_symbol(authenticated_client, user, journal):
    eur_asset = AssetFactory(journal=journal, symbol="EURUSD")
    gbp_asset = AssetFactory(journal=journal, symbol="GBPUSD")
    expected = TradeFactory(journal=journal, asset=eur_asset, pnl_r=Decimal("1.00"))
    TradeFactory(journal=journal, asset=gbp_asset, pnl_r=Decimal("2.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/?search=EURUSD")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == expected.id


@pytest.mark.django_db
def test_trade_filter_by_status(authenticated_client, user, journal):
    win_trade = TradeFactory(journal=journal, status="WIN", pnl_r=Decimal("2.00"))
    TradeFactory(journal=journal, status="LOSS", pnl_r=Decimal("-1.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/trades/?status=WIN")

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == win_trade.id


@pytest.mark.django_db
def test_journal_crud_is_user_scoped(authenticated_client, user):
    response = authenticated_client.post(
        "/api/journals/",
        {
            "name": "FTMO",
            "journal_type": "trading",
            "starting_capital": "10000.00",
            "currency": "USD",
            "break_even_method": "ratio",
        },
        format="json",
    )

    assert response.status_code == 201
    journal_id = response.data["id"]

    detail = authenticated_client.get(f"/api/journals/{journal_id}/")
    assert detail.status_code == 200
    assert detail.data["name"] == "FTMO"

    other_journal = JournalFactory()
    other_detail = authenticated_client.get(f"/api/journals/{other_journal.id}/")
    assert other_detail.status_code == 404


@pytest.mark.django_db
def test_catalog_asset_crud(authenticated_client, user, journal):
    response = authenticated_client.post(
        f"/api/journals/{journal.id}/assets/", {"symbol": "eurusd", "name": "Euro"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["symbol"] == "EURUSD"

    asset_id = response.data["id"]
    patch = authenticated_client.patch(
        f"/api/journals/{journal.id}/assets/{asset_id}/", {"symbol": "GBPUSD"}, format="json"
    )
    assert patch.status_code == 200
    assert patch.data["symbol"] == "GBPUSD"


@pytest.mark.django_db
def test_catalog_asset_delete_archives_when_referenced(authenticated_client, user, journal):
    asset = AssetFactory(journal=journal, symbol="EURUSD")
    TradeFactory(journal=journal, asset=asset)

    response = authenticated_client.delete(f"/api/journals/{journal.id}/assets/{asset.id}/")

    assert response.status_code == 200
    asset.refresh_from_db()
    assert asset.is_archived is True


@pytest.mark.django_db
def test_setup_tag_pnl_grouping(authenticated_client, user, journal):
    setup = SetupTagFactory(journal=journal, label="Breakout")
    TradeFactory(journal=journal, setup=setup, pnl_r=Decimal("3.00"))
    TradeFactory(journal=journal, setup=setup, pnl_r=Decimal("-1.00"))

    response = authenticated_client.get(f"/api/journals/{journal.id}/analytics/pnl-by-setup/")

    assert response.status_code == 200
    assert response.data == [{"setup": "Breakout", "total_r": 2.0}]

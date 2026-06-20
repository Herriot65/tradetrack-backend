from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.factories import AssetFactory, JournalFactory, TradeFactory, UserFactory


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def journal(user):
    return JournalFactory(user=user)


@pytest.mark.django_db
def test_trade_rejects_exit_before_entry(user, journal):
    asset = AssetFactory(journal=journal)
    entry = timezone.now()
    trade = TradeFactory.build(
        journal=journal,
        asset=asset,
        entry_datetime=entry,
        exit_datetime=entry - timezone.timedelta(minutes=1),
    )

    with pytest.raises(ValidationError) as exc:
        trade.full_clean()

    assert "exit_datetime" in exc.value.message_dict


@pytest.mark.django_db
def test_trade_allows_null_pnl_r(user, journal):
    trade = TradeFactory(journal=journal, pnl_r=None, exit_datetime=None)
    trade.full_clean()


@pytest.mark.django_db
def test_trade_allows_negative_zero_and_positive_pnl_r(user, journal):
    for pnl_r in (Decimal("-1.25"), Decimal("0.00"), Decimal("2.50")):
        trade = TradeFactory(journal=journal, pnl_r=pnl_r)
        trade.full_clean()


@pytest.mark.django_db
def test_asset_symbol_uppercased_on_save(journal):
    asset = AssetFactory(journal=journal, symbol="eurusd")
    assert asset.symbol == "EURUSD"


@pytest.mark.django_db
def test_trade_status_null_by_default(journal):
    trade = TradeFactory(journal=journal)
    assert trade.status is None

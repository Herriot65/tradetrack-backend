from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.factories import TradeFactory, UserFactory


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def workspace(user):
    return user.workspaces.get(name="Main")


@pytest.mark.django_db
def test_trade_rejects_exit_before_entry(user, workspace):
    entry = timezone.now()
    trade = TradeFactory.build(
        owner=user,
        workspace=workspace,
        entry_datetime=entry,
        exit_datetime=entry - timezone.timedelta(minutes=1),
    )

    with pytest.raises(ValidationError) as exc:
        trade.full_clean()

    assert "exit_datetime" in exc.value.message_dict


@pytest.mark.django_db
def test_trade_rejects_non_positive_risk_percent(user, workspace):
    trade = TradeFactory.build(owner=user, workspace=workspace, risk_percent=Decimal("0.00"))

    with pytest.raises(ValidationError) as exc:
        trade.full_clean()

    assert "risk_percent" in exc.value.message_dict


@pytest.mark.django_db
def test_trade_allows_negative_zero_and_positive_pnl_r(user, workspace):
    for pnl_r in (Decimal("-1.25"), Decimal("0.00"), Decimal("2.50")):
        trade = TradeFactory.build(owner=user, workspace=workspace, pnl_r=pnl_r)
        trade.full_clean()

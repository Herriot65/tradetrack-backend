from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Trade, Workspace


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = "Test"
    last_name = "User"

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        password = extracted or "testpass123"
        self.set_password(password)
        if create:
            self.save(update_fields=["password"])


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Workspace {n}")
    description = ""


class TradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Trade

    owner = factory.SubFactory(UserFactory)
    workspace = factory.LazyAttribute(
        lambda trade: Workspace.objects.filter(user=trade.owner, name="Main").first()
        or WorkspaceFactory(user=trade.owner, name="Main")
    )
    asset = "EURUSD"
    trend_direction = Trade.TrendDirection.BULLISH
    opportunity_timeframe = Trade.Timeframe.H4
    entry_timeframe = Trade.Timeframe.M15
    setup = "Pullback"
    session = Trade.Session.LONDON
    side = Trade.Side.BUY
    status = Trade.Status.WIN
    entry_datetime = factory.LazyFunction(timezone.now)
    exit_datetime = factory.LazyAttribute(lambda trade: trade.entry_datetime + timezone.timedelta(hours=1))
    risk_percent = Decimal("1.00")
    pnl_r = Decimal("1.00")
    emotion = "Calm"
    notes = "Followed plan"

from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade


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


class JournalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Journal

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Journal {n}")
    journal_type = "trading"
    starting_capital = Decimal("10000.00")
    currency = "USD"
    break_even_method = "ratio"


class AssetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Asset

    journal = factory.SubFactory(JournalFactory)
    symbol = factory.Sequence(lambda n: f"PAIR{n:02d}")
    name = ""
    is_archived = False


class EmotionTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmotionTag

    journal = factory.SubFactory(JournalFactory)
    label = factory.Sequence(lambda n: f"Emotion {n}")
    is_archived = False


class MistakeTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MistakeTag

    journal = factory.SubFactory(JournalFactory)
    label = factory.Sequence(lambda n: f"Mistake {n}")
    is_archived = False


class SetupTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SetupTag

    journal = factory.SubFactory(JournalFactory)
    label = factory.Sequence(lambda n: f"Setup {n}")
    is_archived = False


class TradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Trade
        skip_postgeneration_save = True

    journal = factory.SubFactory(JournalFactory)
    asset = factory.SubFactory(AssetFactory, journal=factory.SelfAttribute("..journal"))
    side = Trade.Side.BUY
    entry_datetime = factory.LazyFunction(timezone.now)
    exit_datetime = factory.LazyAttribute(lambda t: t.entry_datetime + timezone.timedelta(hours=1))
    risk_percent = Decimal("1.00")
    pnl_r = Decimal("1.00")
    status = None
    notes = "Followed plan"

    @factory.post_generation
    def emotions(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            self.emotions.set(extracted)
        else:
            emotion = EmotionTagFactory(journal=self.journal)
            self.emotions.add(emotion)

    @factory.post_generation
    def mistakes(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.mistakes.set(extracted)

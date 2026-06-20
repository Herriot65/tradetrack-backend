import django_filters

from .models import Trade


class TradeFilter(django_filters.FilterSet):
    entry_datetime__gte = django_filters.IsoDateTimeFilter(field_name="entry_datetime", lookup_expr="gte")
    entry_datetime__lte = django_filters.IsoDateTimeFilter(field_name="entry_datetime", lookup_expr="lte")

    class Meta:
        model = Trade
        fields = (
            "side",
            "status",
            "trend_direction",
            "session",
            "entry_datetime__gte",
            "entry_datetime__lte",
        )

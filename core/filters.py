import django_filters
from django.db.models import F
from rest_framework import filters as drf_filters

from .models import Trade
from .services import filter_trade_status
from django_filters.rest_framework import DjangoFilterBackend


class TradeOrderingFilter(drf_filters.OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        expressions = []
        for field in ordering:
            descending = field.startswith("-")
            name = field[1:] if descending else field
            if name in {"pnl_r", "pnl_amount", "pnl_percent", "display_pnl_r"}:
                expressions.append(F(name).desc(nulls_last=True) if descending else F(name).asc(nulls_last=True))
            else:
                expressions.append(field)
        return queryset.order_by(*expressions)


class JournalTradeFilterBackend(DjangoFilterBackend):
    def get_filterset_kwargs(self, request, queryset, view):
        return {**super().get_filterset_kwargs(request, queryset, view), "journal": view.get_journal()}


class TradeFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=[(value, value) for value in ["OPEN", "WIN", "LOSS", "BE"]], method="filter_status")
    asset = django_filters.NumberFilter(field_name="asset_id")
    setup = django_filters.NumberFilter(field_name="setup_id")

    def __init__(self, *args, journal=None, **kwargs):
        self.journal = journal
        super().__init__(*args, **kwargs)

    def filter_status(self, queryset, name, value):
        return filter_trade_status(queryset, value, self.journal)

    entry_datetime__gte = django_filters.IsoDateTimeFilter(field_name="entry_datetime", lookup_expr="gte")
    entry_datetime__lte = django_filters.IsoDateTimeFilter(field_name="entry_datetime", lookup_expr="lte")

    class Meta:
        model = Trade
        fields = (
            "asset",
            "setup",
            "side",
            "status",
            "trend_direction",
            "session",
            "entry_datetime__gte",
            "entry_datetime__lte",
        )

from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import TradeFilter
from .models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade
from .pagination import JournalPagination
from .permissions import IsJournalOwner
from .serializers import (
    AssetSerializer,
    EmotionTagSerializer,
    JournalSerializer,
    MistakeTagSerializer,
    SetupTagSerializer,
    TradeSerializer,
)
from .services import (
    get_career_data,
    get_dashboard_summary,
    get_equity_curve,
    get_pnl_by_setup,
    get_win_loss_distribution,
)


class JournalViewSet(viewsets.ModelViewSet):
    serializer_class = JournalSerializer
    permission_classes = [IsAuthenticated, IsJournalOwner]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Journal.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class JournalScopedMixin:
    """Resolves and validates the journal from URL kwargs, scoped to the request user."""

    def get_journal(self) -> Journal:
        if not hasattr(self, "_journal"):
            self._journal = get_object_or_404(
                Journal, pk=self.kwargs["journal_id"], user=self.request.user
            )
        return self._journal


class CatalogListCreateView(JournalScopedMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    model = None

    def get_queryset(self):
        return self.model.objects.filter(journal=self.get_journal())

    def perform_create(self, serializer):
        serializer.save(journal=self.get_journal())


class CatalogDetailView(JournalScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    model = None
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return self.model.objects.filter(journal=self.get_journal())

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ProtectedError:
            instance.is_archived = True
            instance.save(update_fields=["is_archived"])
            serializer = self.get_serializer(instance)
            return Response(serializer.data)


class AssetListCreateView(CatalogListCreateView):
    serializer_class = AssetSerializer
    model = Asset


class AssetDetailView(CatalogDetailView):
    serializer_class = AssetSerializer
    model = Asset


class EmotionTagListCreateView(CatalogListCreateView):
    serializer_class = EmotionTagSerializer
    model = EmotionTag


class EmotionTagDetailView(CatalogDetailView):
    serializer_class = EmotionTagSerializer
    model = EmotionTag


class MistakeTagListCreateView(CatalogListCreateView):
    serializer_class = MistakeTagSerializer
    model = MistakeTag


class MistakeTagDetailView(CatalogDetailView):
    serializer_class = MistakeTagSerializer
    model = MistakeTag


class SetupTagListCreateView(CatalogListCreateView):
    serializer_class = SetupTagSerializer
    model = SetupTag


class SetupTagDetailView(CatalogDetailView):
    serializer_class = SetupTagSerializer
    model = SetupTag


class TradeListCreateView(JournalScopedMixin, generics.ListCreateAPIView):
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = JournalPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TradeFilter
    search_fields = ["asset__symbol", "notes"]
    ordering_fields = ["entry_datetime", "created_at", "pnl_r"]
    ordering = ["-entry_datetime"]

    def get_queryset(self):
        return (
            Trade.objects.filter(journal=self.get_journal())
            .select_related("asset", "setup")
            .prefetch_related("emotions", "mistakes")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["journal"] = self.get_journal()
        return context

    def perform_create(self, serializer):
        serializer.save(journal=self.get_journal())


class TradeDetailView(JournalScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return (
            Trade.objects.filter(journal=self.get_journal())
            .select_related("asset", "setup")
            .prefetch_related("emotions", "mistakes")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["journal"] = self.get_journal()
        return context


class _AnalyticsBase(JournalScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get_trade_queryset(self):
        return Trade.objects.filter(journal=self.get_journal())


class DashboardSummaryView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_dashboard_summary(self.get_trade_queryset()))


class EquityCurveView(_AnalyticsBase):
    allowed_periods = {"weekly", "monthly", "yearly"}

    def get(self, request, journal_id):
        period = request.query_params.get("period", "weekly")
        if period not in self.allowed_periods:
            period = "weekly"
        return Response(get_equity_curve(self.get_trade_queryset(), period=period))


class WinLossDistributionView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_win_loss_distribution(self.get_trade_queryset()))


class PnlBySetupView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_pnl_by_setup(self.get_trade_queryset()))


class CareerView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_career_data(self.get_trade_queryset()))

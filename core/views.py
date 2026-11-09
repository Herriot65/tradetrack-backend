from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction, IntegrityError
from django.db.models import ProtectedError, Case, When, F, Value, FloatField, ExpressionWrapper
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, status, viewsets, serializers
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import TradeFilter, JournalTradeFilterBackend, TradeOrderingFilter
from .models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade, TradeScreenshot, TradeCustomField
from .pagination import JournalPagination, TradePagination
from .permissions import IsJournalOwner
from .serializers import (
    AssetSerializer,
    EmotionTagSerializer,
    JournalSerializer,
    MistakeTagSerializer,
    SetupTagSerializer,
    TradeScreenshotSerializer,
    TradeSerializer,
    AnalyticsTradeSerializer,
    TradeCustomFieldSerializer,
)
from .services import (
    be_threshold_r,
    get_career_data,
    get_dashboard_summary,
    get_equity_curve,
    get_performance_by_day,
    get_performance_by_hour,
    get_pnl_by_setup,
    get_win_loss_distribution,
    recompute_imported_pnl,
)
from .synthetic_data import generate_synthetic_trades, remove_synthetic_trades


class JournalViewSet(viewsets.ModelViewSet):
    serializer_class = JournalSerializer
    permission_classes = [IsAuthenticated, IsJournalOwner]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Journal.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        old_capital = serializer.instance.starting_capital
        journal = serializer.save()
        if journal.starting_capital != old_capital:
            recompute_imported_pnl(journal)

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.trades.all().delete()
            instance.delete()


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


class TradeCustomFieldListCreateView(CatalogListCreateView):
    serializer_class = TradeCustomFieldSerializer
    model = TradeCustomField
    pagination_class = None

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "journal": self.get_journal()}

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save(journal=self.get_journal())
        except IntegrityError:
            raise serializers.ValidationError({"label": "A field with this name already exists in this section."})


class TradeCustomFieldDeleteView(JournalScopedMixin, generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TradeCustomFieldSerializer

    def get_queryset(self):
        return TradeCustomField.objects.filter(journal=self.get_journal())

    def perform_destroy(self, instance):
        with transaction.atomic():
            for trade in Trade.objects.select_for_update().filter(journal=instance.journal):
                values = dict(trade.custom_fields or {})
                if str(instance.pk) in values:
                    del values[str(instance.pk)]
                    trade.custom_fields = values
                    trade.save(update_fields=["custom_fields"])
            instance.delete()


class TradeListCreateView(JournalScopedMixin, generics.ListCreateAPIView):
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = TradePagination
    filter_backends = [JournalTradeFilterBackend, filters.SearchFilter, TradeOrderingFilter]
    filterset_class = TradeFilter
    search_fields = ["asset__symbol", "notes"]
    ordering_fields = ["entry_datetime", "created_at", "pnl_r", "pnl_amount", "pnl_percent", "display_pnl_r", "asset__symbol", "id"]
    ordering = ["-entry_datetime", "-id"]

    def get_serializer_class(self):
        if self.request.method == "GET" and self.request.query_params.get("compact") == "1":
            return AnalyticsTradeSerializer
        return TradeSerializer

    def get_queryset(self):
        queryset = (
            Trade.objects.filter(journal=self.get_journal())
            .annotate(
                pnl_percent=Case(When(capital_basis__gt=0, then=ExpressionWrapper(F("pnl_amount") * Value(100.0) / F("capital_basis"), output_field=FloatField())), default=Value(None), output_field=FloatField()),
                display_pnl_r=Case(When(risk_amount__gt=0, then=ExpressionWrapper(F("pnl_amount") * Value(1.0) / F("risk_amount"), output_field=FloatField())), When(pnl_amount__isnull=False, then=Value(None)), default=F("pnl_r"), output_field=FloatField()),
            )
            .select_related("asset", "setup")
            .prefetch_related("emotions", "mistakes")
        )

        if self.request.method == "GET" and self.request.query_params.get("compact") == "1":
            return queryset.defer("notes", "notes_document", "custom_fields")
        return queryset.prefetch_related("screenshots")

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
            .prefetch_related("emotions", "mistakes", "screenshots")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["journal"] = self.get_journal()
        return context


class _AnalyticsBase(JournalScopedMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get_trade_queryset(self):
        return Trade.objects.filter(journal=self.get_journal())

    def get_be_threshold(self):
        return be_threshold_r(self.get_journal())


class DashboardSummaryView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_dashboard_summary(self.get_trade_queryset(), self.get_be_threshold()))


class EquityCurveView(_AnalyticsBase):
    allowed_periods = {"weekly", "monthly", "yearly"}

    def get(self, request, journal_id):
        period = request.query_params.get("period", "weekly")
        if period not in self.allowed_periods:
            period = "weekly"
        return Response(get_equity_curve(self.get_trade_queryset(), period=period))


class WinLossDistributionView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_win_loss_distribution(self.get_trade_queryset(), self.get_be_threshold()))


class PnlBySetupView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_pnl_by_setup(self.get_trade_queryset()))


class CareerView(_AnalyticsBase):
    def get(self, request, journal_id):
        return Response(get_career_data(self.get_trade_queryset(), self.get_be_threshold()))


def _parse_tz(request) -> tuple[ZoneInfo, str | None]:
    """Return (ZoneInfo, error_message). error_message is None on success."""
    tz_name = request.query_params.get("tz", request.user.timezone or "UTC")
    try:
        return ZoneInfo(tz_name), None
    except (ZoneInfoNotFoundError, KeyError):
        return None, f"Unknown timezone: '{tz_name}'. Use an IANA name such as 'America/New_York'."


class PerformanceByDayView(_AnalyticsBase):
    def get(self, request, journal_id):
        tz, err = _parse_tz(request)
        if err:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(get_performance_by_day(self.get_trade_queryset(), tz=tz, threshold=self.get_be_threshold()))


class PerformanceByHourView(_AnalyticsBase):
    def get(self, request, journal_id):
        tz, err = _parse_tz(request)
        if err:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(get_performance_by_hour(self.get_trade_queryset(), tz=tz, threshold=self.get_be_threshold()))


class SyntheticDataView(JournalScopedMixin, APIView):
    """
    GET    — report whether synthetic data is enabled and can be enabled
    POST   — generate synthetic trades (only when the journal has no trades)
    DELETE — remove synthetic trades and the catalog records they created
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, journal_id):
        journal = self.get_journal()
        trade_count = journal.trades.count()
        return Response(
            {
                "enabled": journal.synthetic_data_enabled,
                "trade_count": trade_count,
                "can_enable": trade_count == 0,
            }
        )

    def post(self, request, journal_id):
        journal = self.get_journal()

        if journal.synthetic_data_enabled:
            return Response(
                {
                    "enabled": True,
                    "trade_count": journal.trades.count(),
                    "trades_created": 0,
                }
            )

        if journal.trades.exists():
            return Response(
                {
                    "success": False,
                    "error": (
                        "Synthetic data can only be enabled on a journal with no "
                        "existing trades."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            result = generate_synthetic_trades(journal)
            journal.synthetic_data_enabled = True
            journal.synthetic_catalog_ids = result["catalog_ids"]
            journal.save(
                update_fields=["synthetic_data_enabled", "synthetic_catalog_ids"]
            )

        return Response(
            {
                "enabled": True,
                "trade_count": result["trades_created"],
                "trades_created": result["trades_created"],
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, journal_id):
        journal = self.get_journal()

        with transaction.atomic():
            deleted = remove_synthetic_trades(journal)
            journal.synthetic_data_enabled = False
            journal.save(update_fields=["synthetic_data_enabled"])

        return Response({"enabled": False, "trades_deleted": deleted})


class TradeScreenshotView(JournalScopedMixin, APIView):
    """
    GET  /api/journals/{journal_id}/trades/{trade_id}/screenshots/  — list screenshots
    POST /api/journals/{journal_id}/trades/{trade_id}/screenshots/  — upload a screenshot
    DELETE /api/journals/{journal_id}/trades/{trade_id}/screenshots/{pk}/  — delete a screenshot
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    def _get_trade(self, trade_id):
        return get_object_or_404(Trade, pk=trade_id, journal=self.get_journal())

    def get(self, request, journal_id, trade_id):
        trade = self._get_trade(trade_id)
        screenshots = trade.screenshots.all()
        return Response(TradeScreenshotSerializer(screenshots, many=True).data)

    def post(self, request, journal_id, trade_id):
        from .supabase_client import upload_screenshot

        trade = self._get_trade(trade_id)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file provided. Send the image as 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        metadata = TradeScreenshotSerializer(data={"display_width": request.data.get("display_width", 100)})
        metadata.is_valid(raise_exception=True)
        try:
            image_url = upload_screenshot(trade.pk, file_obj)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"error": f"Upload failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        section = request.data.get("section") or None
        screenshot = TradeScreenshot.objects.create(trade=trade, image_url=image_url, section=section, display_width=metadata.validated_data.get("display_width", 100))
        return Response(TradeScreenshotSerializer(screenshot).data, status=status.HTTP_201_CREATED)

    def patch(self, request, journal_id, trade_id, pk):
        trade = self._get_trade(trade_id)
        screenshot = get_object_or_404(TradeScreenshot, pk=pk, trade=trade)
        serializer = TradeScreenshotSerializer(screenshot, data={key: request.data[key] for key in ("display_width", "section") if key in request.data}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, journal_id, trade_id, pk):
        from .supabase_client import delete_screenshot

        trade = self._get_trade(trade_id)
        screenshot = get_object_or_404(TradeScreenshot, pk=pk, trade=trade)

        try:
            delete_screenshot(screenshot.image_url)
        except Exception:
            pass  # best-effort; still remove DB record

        screenshot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MT5ImportView(JournalScopedMixin, APIView):
    """
    POST /api/journals/{journal_id}/imports/mt5/

    Accepts a multipart/form-data upload with field "file" containing an MT5 HTML report.
    Parses, maps, and persists trades into the specified journal.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, journal_id):
        journal = self.get_journal()

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response(
                {"success": False, "error": "No file provided. Send the MT5 HTML report as 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = uploaded.content_type or ""
        if not (
            "html" in content_type.lower()
            or uploaded.name.lower().endswith((".html", ".htm"))
        ):
            return Response(
                {"success": False, "error": "Uploaded file must be an HTML file (.html or .htm)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if journal.starting_capital <= 0:
            return Response(
                {
                    "success": False,
                    "error": (
                        "Journal starting capital must be greater than 0 to compute trade performance. "
                        "Update the journal's starting capital first."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .importers.mt5.importer import import_mt5_html

        result = import_mt5_html(
            journal=journal,
            file=uploaded,
            filename=uploaded.name,
        )

        http_status = status.HTTP_200_OK if result.get("success") else status.HTTP_422_UNPROCESSABLE_ENTITY
        return Response(result, status=http_status)

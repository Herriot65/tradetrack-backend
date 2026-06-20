from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AssetDetailView,
    AssetListCreateView,
    CareerView,
    DashboardSummaryView,
    EmotionTagDetailView,
    EmotionTagListCreateView,
    EquityCurveView,
    JournalViewSet,
    MistakeTagDetailView,
    MistakeTagListCreateView,
    PnlBySetupView,
    SetupTagDetailView,
    SetupTagListCreateView,
    TradeDetailView,
    TradeListCreateView,
    WinLossDistributionView,
)

router = DefaultRouter()
router.register("journals", JournalViewSet, basename="journal")

journal_nested = [
    path("assets/", AssetListCreateView.as_view(), name="journal-assets"),
    path("assets/<int:pk>/", AssetDetailView.as_view(), name="journal-asset-detail"),
    path("emotion-tags/", EmotionTagListCreateView.as_view(), name="journal-emotion-tags"),
    path("emotion-tags/<int:pk>/", EmotionTagDetailView.as_view(), name="journal-emotion-tag-detail"),
    path("mistake-tags/", MistakeTagListCreateView.as_view(), name="journal-mistake-tags"),
    path("mistake-tags/<int:pk>/", MistakeTagDetailView.as_view(), name="journal-mistake-tag-detail"),
    path("setup-tags/", SetupTagListCreateView.as_view(), name="journal-setup-tags"),
    path("setup-tags/<int:pk>/", SetupTagDetailView.as_view(), name="journal-setup-tag-detail"),
    path("trades/", TradeListCreateView.as_view(), name="journal-trades"),
    path("trades/<int:pk>/", TradeDetailView.as_view(), name="journal-trade-detail"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="journal-dashboard-summary"),
    path("analytics/equity-curve/", EquityCurveView.as_view(), name="journal-equity-curve"),
    path("analytics/win-loss-distribution/", WinLossDistributionView.as_view(), name="journal-win-loss"),
    path("analytics/pnl-by-setup/", PnlBySetupView.as_view(), name="journal-pnl-by-setup"),
    path("analytics/career/", CareerView.as_view(), name="journal-career"),
]

urlpatterns = router.urls + [
    path("journals/<int:journal_id>/", include(journal_nested)),
]

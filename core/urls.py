from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DashboardSummaryView,
    EquityCurveView,
    PnlBySetupView,
    TradeViewSet,
    WinLossDistributionView,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register("workspaces", WorkspaceViewSet, basename="workspace")
router.register("trades", TradeViewSet, basename="trade")

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/trades/",
        TradeViewSet.as_view({"get": "list", "post": "create"}),
        name="workspace-trade-list",
    ),
    path(
        "workspaces/<uuid:workspace_id>/trades/<int:pk>/",
        TradeViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="workspace-trade-detail",
    ),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("analytics/equity-curve/", EquityCurveView.as_view(), name="equity-curve"),
    path("analytics/win-loss-distribution/", WinLossDistributionView.as_view(), name="win-loss-distribution"),
    path("analytics/pnl-by-setup/", PnlBySetupView.as_view(), name="pnl-by-setup"),
]

urlpatterns += router.urls

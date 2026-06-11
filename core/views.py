from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from .filters import TradeFilter
from .models import Trade, Workspace
from .permissions import IsOwner
from .serializers import TradeSerializer, WorkspaceSerializer
from .services import (
    get_user_workspace,
    get_dashboard_summary,
    get_equity_curve,
    get_pnl_by_setup,
    get_win_loss_distribution,
)


class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Workspace.objects.filter(user=self.request.user)

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)


class WorkspaceTradeQuerysetMixin:
    workspace_lookup_kwarg = "workspace_id"

    def get_workspace_id(self):
        return self.kwargs.get(self.workspace_lookup_kwarg) or self.request.query_params.get("workspace_id")

    def get_workspace(self):
        return get_user_workspace(self.request.user, self.get_workspace_id())

    def get_queryset(self):
        workspace = self.get_workspace()
        return (
            Trade.objects.filter(owner=self.request.user, workspace=workspace)
            .select_related("owner", "workspace")
            .prefetch_related("screenshots")
        )


class TradeViewSet(WorkspaceTradeQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TradeFilter
    search_fields = ["asset", "setup", "notes"]
    ordering_fields = ["entry_datetime", "created_at", "pnl_r"]
    ordering = ["-entry_datetime", "-created_at"]

    def perform_create(self, serializer) -> None:
        workspace_id = self.kwargs.get(self.workspace_lookup_kwarg) or self.request.data.get("workspace")
        workspace = get_user_workspace(self.request.user, workspace_id)
        serializer.save(owner=self.request.user, workspace=workspace)


class DashboardSummaryView(WorkspaceTradeQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(get_dashboard_summary(self.get_queryset()))


class EquityCurveView(WorkspaceTradeQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]
    allowed_periods = {"weekly", "monthly", "yearly"}

    def get(self, request):
        period = request.query_params.get("period", "weekly")
        if period not in self.allowed_periods:
            period = "weekly"
        return Response(get_equity_curve(self.get_queryset(), period=period))


class WinLossDistributionView(WorkspaceTradeQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(get_win_loss_distribution(self.get_queryset()))


class PnlBySetupView(WorkspaceTradeQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(get_pnl_by_setup(self.get_queryset()))

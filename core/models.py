import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspaces")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_workspace_name_per_user"),
        ]

    def __str__(self) -> str:
        return self.name


class Trade(models.Model):
    class TrendDirection(models.TextChoices):
        BULLISH = "BULLISH", "Bullish"
        BEARISH = "BEARISH", "Bearish"
        RANGE = "RANGE", "Range"

    class Timeframe(models.TextChoices):
        MN = "MN", "Monthly"
        W1 = "W1", "Weekly"
        D1 = "D1", "Daily"
        H4 = "H4", "4 Hour"
        H1 = "H1", "1 Hour"
        M15 = "M15", "15 Minute"
        M5 = "M5", "5 Minute"

    class Session(models.TextChoices):
        ASIA = "ASIA", "Asia"
        LONDON = "LONDON", "London"
        NEW_YORK = "NEW_YORK", "New York"

    class Side(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        WIN = "WIN", "Win"
        LOSS = "LOSS", "Loss"
        BE = "BE", "Break even"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trades")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="trades")
    asset = models.CharField(max_length=50)
    trend_direction = models.CharField(max_length=20, choices=TrendDirection.choices)
    opportunity_timeframe = models.CharField(max_length=5, choices=Timeframe.choices)
    entry_timeframe = models.CharField(max_length=5, choices=Timeframe.choices)
    setup = models.CharField(max_length=100)
    session = models.CharField(max_length=20, choices=Session.choices)
    side = models.CharField(max_length=10, choices=Side.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    entry_datetime = models.DateTimeField()
    exit_datetime = models.DateTimeField(null=True, blank=True)
    risk_percent = models.DecimalField(max_digits=5, decimal_places=2)
    pnl_r = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    emotion = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_datetime", "-created_at"]
        indexes = [
            models.Index(fields=["workspace", "entry_datetime"]),
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["owner", "entry_datetime"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "asset"]),
        ]

    def clean(self) -> None:
        errors = {}
        if self.exit_datetime and self.exit_datetime < self.entry_datetime:
            errors["exit_datetime"] = "Exit datetime must be greater than or equal to entry datetime."
        if self.risk_percent is not None and self.risk_percent <= 0:
            errors["risk_percent"] = "Risk percent must be greater than zero."
        if self.workspace_id and self.owner_id and self.workspace.user_id != self.owner_id:
            errors["workspace"] = "Workspace must belong to the trade owner."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.asset} {self.side} {self.entry_datetime:%Y-%m-%d}"


class TradeScreenshot(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="screenshots")
    image = models.ImageField(upload_to="trade_screenshots/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"Screenshot for trade {self.trade_id}"

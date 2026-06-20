from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Journal(models.Model):
    JOURNAL_TYPE_CHOICES = [("trading", "Trading"), ("backtest", "Backtest")]
    BREAK_EVEN_METHOD_CHOICES = [("ratio", "Ratio"), ("profit", "Profit")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="journals")
    name = models.CharField(max_length=255)
    journal_type = models.CharField(max_length=20, choices=JOURNAL_TYPE_CHOICES, default="trading")
    starting_capital = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0"))
    currency = models.CharField(max_length=10, default="USD")
    break_even_method = models.CharField(max_length=10, choices=BREAK_EVEN_METHOD_CHOICES, default="ratio")
    break_even_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_journal_name_per_user"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.email})"


class Asset(models.Model):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="assets")
    symbol = models.CharField(max_length=20)
    name = models.CharField(max_length=100, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["symbol"]
        constraints = [
            models.UniqueConstraint(fields=["journal", "symbol"], name="unique_asset_symbol_per_journal"),
        ]

    def save(self, *args, **kwargs):
        self.symbol = self.symbol.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.symbol


class EmotionTag(models.Model):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="emotion_tags")
    label = models.CharField(max_length=50)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class MistakeTag(models.Model):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="mistake_tags")
    label = models.CharField(max_length=50)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class SetupTag(models.Model):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="setup_tags")
    label = models.CharField(max_length=100)
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class Trade(models.Model):
    class TrendDirection(models.TextChoices):
        BULLISH = "BULLISH", "Bullish"
        BEARISH = "BEARISH", "Bearish"
        RANGE = "RANGE", "Range"

    class Side(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    class Status(models.TextChoices):
        WIN = "WIN", "Win"
        LOSS = "LOSS", "Loss"
        BE = "BE", "Break Even"

    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="trades")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="trades")
    side = models.CharField(max_length=10, choices=Side.choices)
    entry_datetime = models.DateTimeField()
    exit_datetime = models.DateTimeField(null=True, blank=True)
    risk_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    pnl_r = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    commission = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    swap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    opportunity_timeframe = models.CharField(max_length=10, null=True, blank=True)
    entry_timeframe = models.CharField(max_length=10, null=True, blank=True)
    trend_direction = models.CharField(max_length=20, choices=TrendDirection.choices, null=True, blank=True)
    setup = models.ForeignKey(SetupTag, on_delete=models.PROTECT, null=True, blank=True, related_name="trades")
    session = models.CharField(max_length=50, null=True, blank=True)

    emotions = models.ManyToManyField(EmotionTag, through="TradeEmotion")
    mistakes = models.ManyToManyField(MistakeTag, through="TradeMistake", blank=True)

    # null = auto-derive (pnl_r > 0 → WIN, < 0 → LOSS, == 0 → BE, no exit → OPEN)
    status = models.CharField(max_length=10, choices=Status.choices, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        errors = {}
        if self.exit_datetime and self.entry_datetime and self.exit_datetime <= self.entry_datetime:
            errors["exit_datetime"] = "Exit datetime must be after entry datetime."
        if errors:
            raise ValidationError(errors)

    class Meta:
        ordering = ["-entry_datetime", "-created_at"]
        indexes = [
            models.Index(fields=["journal", "entry_datetime"]),
            models.Index(fields=["journal", "status"]),
            models.Index(fields=["journal", "asset"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset.symbol} {self.side} {self.entry_datetime:%Y-%m-%d}"


class TradeEmotion(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE)
    emotion = models.ForeignKey(EmotionTag, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("trade", "emotion")]


class TradeMistake(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE)
    mistake = models.ForeignKey(MistakeTag, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("trade", "mistake")]


class TradeScreenshot(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="screenshots")
    image = models.ImageField(upload_to="trade_screenshots/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"Screenshot for trade {self.trade_id}"

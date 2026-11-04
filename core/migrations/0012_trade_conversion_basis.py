from decimal import Decimal
from django.db import migrations, models


def snapshot_existing(apps, schema_editor):
    Trade = apps.get_model("core", "Trade")
    TradeImport = apps.get_model("core", "TradeImport")
    profits = dict(TradeImport.objects.filter(raw_profit__isnull=False).values_list("trade_id", "raw_profit"))
    for trade in Trade.objects.select_related("journal").iterator():
        capital = trade.journal.starting_capital
        trade.capital_basis = capital if capital > 0 else None
        trade.risk_amount = (capital * trade.risk_percent / 100).quantize(Decimal("0.000001")) if capital > 0 and trade.risk_percent is not None else None
        trade.pnl_amount = profits.get(trade.pk)
        if trade.pnl_amount is None and trade.risk_amount and trade.pnl_r is not None:
            trade.pnl_amount = (trade.risk_amount * trade.pnl_r).quantize(Decimal("0.000001"))
        trade.save(update_fields=["capital_basis", "risk_amount", "pnl_amount"])


class Migration(migrations.Migration):
    dependencies = [("core", "0011_decimal_trade_score")]
    operations = [
        migrations.AddField(model_name="journal", name="display_unit", field=models.CharField(max_length=3, choices=[("R", "R"), ("USD", "$"), ("PCT", "%")], default="R")),
        *[migrations.AddField(model_name="trade", name=name, field=models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)) for name in ["capital_basis", "risk_amount", "pnl_amount"]],
        migrations.RunPython(snapshot_existing, migrations.RunPython.noop),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0012_trade_conversion_basis")]
    operations = [
        migrations.AlterField(model_name="trade", name="risk_percent", field=models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)),
        migrations.AlterField(model_name="trade", name="pnl_r", field=models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)),
    ]

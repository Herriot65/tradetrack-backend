from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0010_trade_custom_fields")]
    operations = [migrations.AlterField(model_name="trade", name="trade_score", field=models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(10)]))]

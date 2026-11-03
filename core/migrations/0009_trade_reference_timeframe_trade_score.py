from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0008_synthetic_data")]

    operations = [
        migrations.AddField(
            model_name="trade",
            name="reference_timeframe",
            field=models.CharField(max_length=10, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="trade_score",
            field=models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(10)]),
        ),
        migrations.AddConstraint(
            model_name="trade",
            constraint=models.CheckConstraint(
                condition=models.Q(trade_score__isnull=True) | (models.Q(trade_score__gte=0) & models.Q(trade_score__lte=10)),
                name="trade_score_between_0_and_10",
            ),
        ),
    ]

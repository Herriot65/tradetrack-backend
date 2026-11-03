from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_tradescreenshot_section"),
    ]

    operations = [
        migrations.AddField(
            model_name="journal",
            name="synthetic_data_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="journal",
            name="synthetic_catalog_ids",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="trade",
            name="is_synthetic",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]

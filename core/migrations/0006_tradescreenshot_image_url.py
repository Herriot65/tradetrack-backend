from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_increase_asset_symbol_max_length"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradescreenshot",
            name="image",
        ),
        migrations.AddField(
            model_name="tradescreenshot",
            name="image_url",
            field=models.URLField(max_length=2000, default=""),
            preserve_default=False,
        ),
    ]

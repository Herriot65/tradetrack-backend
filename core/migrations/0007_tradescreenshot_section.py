from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_tradescreenshot_image_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradescreenshot",
            name="section",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]

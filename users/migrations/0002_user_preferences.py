from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]
    operations = [
        migrations.AddField(model_name="user", name="timezone", field=models.CharField(max_length=100, blank=True, default="")),
        migrations.AddField(model_name="user", name="rating_style", field=models.CharField(max_length=10, choices=[("score", "Score"), ("stars", "Stars")], default="score")),
    ]

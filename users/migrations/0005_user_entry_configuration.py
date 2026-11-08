from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0004_user_theme")]
    operations = [migrations.AddField(model_name="user", name="entry_configuration", field=models.JSONField(default=dict, blank=True))]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0003_user_google_sub")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
                default="system",
                max_length=6,
            ),
        ),
    ]

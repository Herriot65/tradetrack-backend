# Generated manually to backfill existing trades into per-user default workspaces.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_default_workspaces(apps, schema_editor):
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(user_app_label, user_model_name)
    Workspace = apps.get_model("core", "Workspace")

    for user in User.objects.all():
        Workspace.objects.get_or_create(
            user=user,
            name="Main",
            defaults={"description": "Default workspace"},
        )


def assign_existing_trades(apps, schema_editor):
    Trade = apps.get_model("core", "Trade")
    Workspace = apps.get_model("core", "Workspace")

    for trade in Trade.objects.filter(workspace__isnull=True).select_related("owner"):
        workspace, _ = Workspace.objects.get_or_create(
            user=trade.owner,
            name="Main",
            defaults={"description": "Default workspace"},
        )
        trade.workspace = workspace
        trade.save(update_fields=["workspace"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workspaces", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["name", "created_at"],
                "constraints": [
                    models.UniqueConstraint(fields=("user", "name"), name="unique_workspace_name_per_user"),
                ],
            },
        ),
        migrations.AddField(
            model_name="trade",
            name="workspace",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="trades",
                to="core.workspace",
            ),
        ),
        migrations.RunPython(create_default_workspaces, migrations.RunPython.noop),
        migrations.RunPython(assign_existing_trades, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="trade",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="trades",
                to="core.workspace",
            ),
        ),
        migrations.AddIndex(
            model_name="trade",
            index=models.Index(fields=["workspace", "entry_datetime"], name="core_trade_workspa_d074f5_idx"),
        ),
        migrations.AddIndex(
            model_name="trade",
            index=models.Index(fields=["workspace", "status"], name="core_trade_workspa_286246_idx"),
        ),
    ]

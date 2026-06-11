from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_workspace(sender, instance, created, **kwargs) -> None:
    if not created:
        return

    from core.models import Workspace

    Workspace.objects.get_or_create(user=instance, name="Main", defaults={"description": "Default workspace"})

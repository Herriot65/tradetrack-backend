from django.core.management.base import BaseCommand
from django.utils import timezone
from core.coach_api import run_task
from core.models import CoachTask


class Command(BaseCommand):
    help = "Run due AI coaching tasks. Invoke every minute from a cron job or scheduler."

    def handle(self, *args, **options):
        now = timezone.now()
        ids = list(CoachTask.objects.filter(enabled=True, next_run_at__lte=now).order_by("next_run_at").values_list("id", flat=True)[:100])
        for task_id in ids:
            try:
                run = run_task(task_id, scheduled=True, now=timezone.now())
                if run:
                    self.stdout.write(f"Task {task_id}: {run.status}")
            except CoachTask.DoesNotExist:
                continue

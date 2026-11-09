from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .coach import SECTIONS, CoachUnavailable, generate_reply
from .coach_schedule import next_occurrence
from .models import CoachTask, CoachTaskRun, Journal


class CoachThrottle(UserRateThrottle):
    rate = "30/hour"
    scope = "coach"


class ConfigurationSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=["day", "week", "month", "custom"], default="week")
    timezone = serializers.CharField(max_length=64, default="UTC")
    detail = serializers.ChoiceField(choices=["brief", "detailed"], default="brief")
    sections = serializers.ListField(child=serializers.ChoiceField(choices=SECTIONS), max_length=5, default=list)
    goal = serializers.CharField(max_length=1000, allow_blank=True, default="")
    instrument = serializers.CharField(max_length=50, allow_blank=True, default="")
    trade_id = serializers.IntegerField(min_value=1, required=False)
    screenshots = serializers.BooleanField(default=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Choose a valid IANA timezone.")
        return value

    def validate(self, data):
        if data.get("period") == "custom":
            start, end = data.get("start_date"), data.get("end_date")
            if not start or not end or start > end:
                raise serializers.ValidationError("Choose a valid start and end date.")
            if (end - start).days > 366:
                raise serializers.ValidationError("Choose a period of one year or less.")
        for field in ("start_date", "end_date"):
            if field in data:
                data[field] = data[field].isoformat()
        return data


class MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(max_length=8000)


class ChatSerializer(serializers.Serializer):
    instructions = serializers.CharField(max_length=4000)
    configuration = ConfigurationSerializer(default=dict)
    history = MessageSerializer(many=True, max_length=12, default=list)


class CoachChatView(APIView):
    throttle_classes = [CoachThrottle]

    def get(self, request, journal_id):
        from django.conf import settings
        get_object_or_404(Journal, pk=journal_id, user=request.user)
        return Response({"configured": bool(settings.COACH_API_KEY), "model": settings.COACH_MODEL, "persistent_memory": False})

    def post(self, request, journal_id):
        journal = get_object_or_404(Journal, pk=journal_id, user=request.user)
        serializer = ChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = generate_reply(journal, **serializer.validated_data)
        except CoachUnavailable as error:
            return Response({"detail": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result)


class TaskSerializer(serializers.ModelSerializer):
    configuration = ConfigurationSerializer()
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = CoachTask
        fields = ["id", "title", "instructions", "configuration", "frequency", "local_time", "timezone", "start_date", "enabled", "next_run_at", "created_at", "latest_run"]
        read_only_fields = ["id", "next_run_at", "created_at", "latest_run"]

    def get_latest_run(self, obj):
        run = obj.runs.first()
        return RunSerializer(run).data if run else None

    def validate_timezone(self, value):
        return ConfigurationSerializer().validate_timezone(value)

    def validate(self, data):
        if data.get("configuration", {}).get("period") == "custom":
            raise serializers.ValidationError("Scheduled tasks use a rolling day, week, or month so each run gets fresh data.")
        if self.instance is None and CoachTask.objects.filter(journal=self.context["journal"]).count() >= 20:
            raise serializers.ValidationError("This journal already has 20 tasks. Delete a task before adding another.")
        return data


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoachTaskRun
        fields = ["id", "status", "output", "evidence", "error", "created_at", "completed_at"]


def run_task(task_id, *, scheduled=False, now=None):
    """Claim under a row lock; do provider I/O outside the transaction.

    Advance schedules before I/O, avoiding duplicate billing across workers.
    A killed process is not retried automatically; stale runs are marked failed
    on the next attempt. Failed executions remain visible in task history.
    """
    now = now or timezone.now()
    with transaction.atomic():
        task = CoachTask.objects.select_for_update().select_related("journal").get(pk=task_id)
        if scheduled and (not task.enabled or not task.next_run_at or task.next_run_at > now):
            return None
        active = task.runs.filter(status="running")
        active.filter(created_at__lt=now - timedelta(minutes=10)).update(status="failed", error="The task was interrupted. Run it again manually.", completed_at=now)
        if active.exists():
            return None
        run = CoachTaskRun.objects.create(task=task)
        if scheduled:
            task.next_run_at = next_occurrence(task, now)
            if task.next_run_at is None:
                task.enabled = False
            task.save(update_fields=["next_run_at", "enabled"])
    try:
        config = {**task.configuration, "timezone": task.timezone}
        result = generate_reply(task.journal, task.instructions, config)
        run.output = result["output"]
        run.evidence = result.get("evidence", [])
        run.status = "completed"
    except CoachUnavailable as error:
        run.status, run.error = "failed", str(error)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Coach task execution failed")
        run.status, run.error = "failed", "The task could not finish. Try running it again."
    run.completed_at = timezone.now()
    run.save(update_fields=["output", "evidence", "status", "error", "completed_at"])
    return run


class CoachTaskViewSet(ModelViewSet):
    serializer_class = TaskSerializer
    pagination_class = None
    throttle_classes = [CoachThrottle]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_journal(self):
        return get_object_or_404(Journal, pk=self.kwargs["journal_id"], user=self.request.user)

    def get_queryset(self):
        return CoachTask.objects.filter(journal=self.get_journal()).prefetch_related("runs")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "journal": self.get_journal()}

    def perform_create(self, serializer):
        with transaction.atomic():
            # Lock the journal so concurrent task creation cannot bypass limits.
            Journal.objects.select_for_update().get(pk=self.get_journal().pk)
            if CoachTask.objects.filter(journal=self.get_journal()).count() >= 20:
                raise serializers.ValidationError("Maximum 20 tasks per journal.")
            task = CoachTask(journal=self.get_journal(), **serializer.validated_data)
            task.next_run_at = next_occurrence(task, timezone.now()) if task.enabled else None
            if task.enabled and task.next_run_at is None:
                raise serializers.ValidationError("Choose a future time for a one-time task.")
            task.save()
            serializer.instance = task

    def perform_update(self, serializer):
        with transaction.atomic():
            task = CoachTask.objects.select_for_update().get(pk=serializer.instance.pk)
            for key, value in serializer.validated_data.items():
                setattr(task, key, value)
            task.next_run_at = next_occurrence(task, timezone.now()) if task.enabled else None
            if task.enabled and task.next_run_at is None:
                raise serializers.ValidationError("Choose a future time for a one-time task.")
            task.save()
            serializer.instance = task

    @action(detail=True, methods=["post"])
    def run(self, request, **kwargs):
        task = self.get_object()
        run = run_task(task.pk)
        if run is None:
            return Response({"detail": "This task is already running."}, status=409)
        return Response(RunSerializer(run).data)

    @action(detail=True, methods=["get"])
    def history(self, request, **kwargs):
        return Response(RunSerializer(self.get_object().runs.all()[:20], many=True).data)

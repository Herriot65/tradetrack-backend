from rest_framework import serializers

from .models import Trade, TradeScreenshot, Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ("id", "name", "description", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class TradeScreenshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeScreenshot
        fields = ("id", "image", "uploaded_at")
        read_only_fields = ("id", "uploaded_at")


class TradeSerializer(serializers.ModelSerializer):
    owner = serializers.PrimaryKeyRelatedField(read_only=True)
    screenshots = TradeScreenshotSerializer(many=True, read_only=True)
    workspace = serializers.PrimaryKeyRelatedField(queryset=Workspace.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            self.fields["workspace"].queryset = Workspace.objects.filter(user=request.user)

    class Meta:
        model = Trade
        fields = (
            "id",
            "owner",
            "workspace",
            "asset",
            "trend_direction",
            "opportunity_timeframe",
            "entry_timeframe",
            "setup",
            "session",
            "side",
            "status",
            "entry_datetime",
            "exit_datetime",
            "risk_percent",
            "pnl_r",
            "emotion",
            "notes",
            "screenshots",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "owner", "created_at", "updated_at")

    def validate(self, attrs):
        entry_datetime = attrs.get("entry_datetime", getattr(self.instance, "entry_datetime", None))
        exit_datetime = attrs.get("exit_datetime", getattr(self.instance, "exit_datetime", None))
        risk_percent = attrs.get("risk_percent", getattr(self.instance, "risk_percent", None))

        if entry_datetime and exit_datetime and exit_datetime < entry_datetime:
            raise serializers.ValidationError(
                {"exit_datetime": "Exit datetime must be greater than or equal to entry datetime."}
            )
        if risk_percent is not None and risk_percent <= 0:
            raise serializers.ValidationError({"risk_percent": "Risk percent must be greater than zero."})

        return attrs

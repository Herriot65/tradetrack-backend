from rest_framework import serializers

from .models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade, TradeScreenshot

_UNSET = object()


class JournalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Journal
        fields = (
            "id",
            "name",
            "journal_type",
            "starting_capital",
            "currency",
            "break_even_method",
            "break_even_value",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ("id", "symbol", "name", "is_archived")
        read_only_fields = ("id", "is_archived")


class EmotionTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmotionTag
        fields = ("id", "label", "is_archived")
        read_only_fields = ("id", "is_archived")


class MistakeTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = MistakeTag
        fields = ("id", "label", "is_archived")
        read_only_fields = ("id", "is_archived")


class SetupTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = SetupTag
        fields = ("id", "label", "is_archived")
        read_only_fields = ("id", "is_archived")


class TradeScreenshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeScreenshot
        fields = ("id", "image_url", "section", "uploaded_at")
        read_only_fields = ("id", "image_url", "uploaded_at")


class _AssetBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ("id", "symbol")


class _SetupTagBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = SetupTag
        fields = ("id", "label")


class _EmotionTagBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmotionTag
        fields = ("id", "label")


class _MistakeTagBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = MistakeTag
        fields = ("id", "label")


class TradeSerializer(serializers.ModelSerializer):
    # Read-only nested output
    asset = _AssetBriefSerializer(read_only=True)
    setup = _SetupTagBriefSerializer(read_only=True)
    emotions = _EmotionTagBriefSerializer(many=True, read_only=True)
    mistakes = _MistakeTagBriefSerializer(many=True, read_only=True)
    screenshots = TradeScreenshotSerializer(many=True, read_only=True)

    # Write-only ID input
    asset_id = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.none(), write_only=True)
    setup_id = serializers.PrimaryKeyRelatedField(
        queryset=SetupTag.objects.none(), write_only=True, required=False, allow_null=True
    )
    emotion_ids = serializers.PrimaryKeyRelatedField(
        queryset=EmotionTag.objects.none(), many=True, write_only=True
    )
    mistake_ids = serializers.PrimaryKeyRelatedField(
        queryset=MistakeTag.objects.none(), many=True, write_only=True, required=False
    )

    class Meta:
        model = Trade
        fields = (
            "id",
            "asset",
            "asset_id",
            "side",
            "entry_datetime",
            "exit_datetime",
            "risk_percent",
            "pnl_r",
            "commission",
            "swap",
            "opportunity_timeframe",
            "entry_timeframe",
            "trend_direction",
            "setup",
            "setup_id",
            "session",
            "emotions",
            "emotion_ids",
            "mistakes",
            "mistake_ids",
            "status",
            "notes",
            "screenshots",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        journal = self.context.get("journal")
        if journal:
            self.fields["asset_id"].queryset = Asset.objects.filter(journal=journal)
            self.fields["setup_id"].queryset = SetupTag.objects.filter(journal=journal)
            self.fields["emotion_ids"].child_relation.queryset = EmotionTag.objects.filter(journal=journal)
            self.fields["mistake_ids"].child_relation.queryset = MistakeTag.objects.filter(journal=journal)

    def validate_status(self, value):
        if value == "OPEN":
            raise serializers.ValidationError("OPEN cannot be set manually; it is derived from exit_datetime.")
        return value

    def validate(self, attrs):
        exit_dt = attrs.get("exit_datetime", getattr(self.instance, "exit_datetime", None))
        entry_dt = attrs.get("entry_datetime", getattr(self.instance, "entry_datetime", None))
        if exit_dt and entry_dt and exit_dt <= entry_dt:
            raise serializers.ValidationError(
                {"exit_datetime": "Exit datetime must be after entry datetime."}
            )
        return attrs

    def create(self, validated_data):
        asset = validated_data.pop("asset_id")
        setup = validated_data.pop("setup_id", None)
        emotions = validated_data.pop("emotion_ids", [])
        mistakes = validated_data.pop("mistake_ids", [])
        trade = Trade.objects.create(asset=asset, setup=setup, **validated_data)
        trade.emotions.set(emotions)
        trade.mistakes.set(mistakes)
        return trade

    def update(self, instance, validated_data):
        asset = validated_data.pop("asset_id", None)
        setup = validated_data.pop("setup_id", _UNSET)
        emotions = validated_data.pop("emotion_ids", None)
        mistakes = validated_data.pop("mistake_ids", None)

        if asset is not None:
            instance.asset = asset
        if setup is not _UNSET:
            instance.setup = setup
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if emotions is not None:
            instance.emotions.set(emotions)
        if mistakes is not None:
            instance.mistakes.set(mistakes)
        return instance

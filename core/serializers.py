import math

from rest_framework import serializers

from .models import Asset, EmotionTag, Journal, MistakeTag, SetupTag, Trade, TradeScreenshot, TradeCustomField

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
            "display_unit",
            "break_even_method",
            "break_even_value",
            "synthetic_data_enabled",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "synthetic_data_enabled",
            "created_at",
            "updated_at",
        )


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
        fields = ("id", "image_url", "section", "display_width", "uploaded_at")
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


class TradeCustomFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeCustomField
        fields = ("id", "section", "label", "field_type", "options", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        label = attrs.get("label", "").strip()
        if not label:
            raise serializers.ValidationError({"label": "Enter a field name."})
        journal = self.context["journal"]
        if TradeCustomField.objects.filter(journal=journal, section=attrs["section"], label__iexact=label).exists():
            raise serializers.ValidationError({"label": "A field with this name already exists in this section."})
        options = attrs.get("options", [])
        if not isinstance(options, list) or len(options) > 100 or any(not isinstance(option, str) or not option.strip() or len(option) > 100 for option in options):
            raise serializers.ValidationError({"options": "Use up to 100 non-empty options, each at most 100 characters."})
        options = [option.strip() for option in options]
        if len(set(options)) != len(options):
            raise serializers.ValidationError({"options": "Each option must be unique."})
        if attrs.get("field_type", "text") == "select" and not options:
            raise serializers.ValidationError({"options": "Add at least one dropdown option."})
        if attrs.get("field_type", "text") != "select" and options:
            raise serializers.ValidationError({"options": "Options are only supported for dropdown fields."})
        attrs["label"], attrs["options"] = label, options
        return attrs


class TradeSerializer(serializers.ModelSerializer):
    def validate_notes_document(self, value):
        from .note_documents import validate_notes_document
        return validate_notes_document(value)

    trade_score = serializers.DecimalField(max_digits=4, decimal_places=2, min_value=0, max_value=10, allow_null=True, required=False, coerce_to_string=False)
    effective_status = serializers.SerializerMethodField()
    # Read-only nested output
    asset = _AssetBriefSerializer(read_only=True)
    setup = _SetupTagBriefSerializer(read_only=True)
    emotions = _EmotionTagBriefSerializer(many=True, read_only=True)
    mistakes = _MistakeTagBriefSerializer(many=True, read_only=True)
    screenshots = TradeScreenshotSerializer(many=True, read_only=True)

    # Write-only ID input
    asset_id = serializers.PrimaryKeyRelatedField(
        queryset=Asset.objects.none(), write_only=True, required=False, allow_null=True
    )
    asset_symbol = serializers.CharField(write_only=True, required=False)
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
            "asset_symbol",
            "side",
            "entry_datetime",
            "exit_datetime",
            "risk_percent",
            "capital_basis",
            "risk_amount",
            "pnl_amount",
            "pnl_r",
            "commission",
            "swap",
            "reference_timeframe",
            "trade_score",
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
            "notes_document",
            "custom_fields",
            "effective_status",
            "screenshots",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "capital_basis", "risk_amount", "pnl_amount")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        journal = self.context.get("journal")
        if journal:
            self.fields["asset_id"].queryset = Asset.objects.filter(journal=journal)
            self.fields["setup_id"].queryset = SetupTag.objects.filter(journal=journal)
            self.fields["emotion_ids"].child_relation.queryset = EmotionTag.objects.filter(journal=journal)
            self.fields["mistake_ids"].child_relation.queryset = MistakeTag.objects.filter(journal=journal)

    def get_effective_status(self, trade):
        from .services import effective_trade_status
        return effective_trade_status(trade, self.context.get("journal"))

    def validate_custom_fields(self, values):
        if not isinstance(values, dict):
            raise serializers.ValidationError("Custom fields must be an object.")
        if not values:
            return values
        journal = self.context.get("journal") or getattr(self.instance, "journal", None)
        definitions = {str(field.id): field for field in TradeCustomField.objects.filter(journal=journal)}
        errors = {}
        for key, value in values.items():
            definition = definitions.get(key)
            if definition is None:
                errors[key] = "This field does not belong to this journal."
                continue
            if value is None or value == "":
                continue
            kind = definition.field_type
            valid = (
                (kind == "text" and isinstance(value, str) and len(value) <= 2000)
                or (kind == "number" and type(value) in (int, float) and math.isfinite(value))
                or (kind == "boolean" and isinstance(value, bool))
                or (kind == "select" and isinstance(value, str) and value in definition.options)
            )
            if not valid:
                errors[key] = f"Enter a valid value for {definition.label}."
        if errors:
            raise serializers.ValidationError(errors)
        return values

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
        if not self.instance and not attrs.get("asset_id") and not attrs.get("asset_symbol"):
            raise serializers.ValidationError(
                {"asset_id": "Provide either asset_id or asset_symbol."}
            )
        return attrs

    def _resolve_asset(self, asset_id, asset_symbol, journal):
        if asset_id is not None:
            return asset_id
        if asset_symbol:
            symbol = asset_symbol.strip().upper()
            asset, _ = Asset.objects.get_or_create(
                journal=journal, symbol=symbol, defaults={"name": symbol}
            )
            return asset
        return None

    def create(self, validated_data):
        asset_id = validated_data.pop("asset_id", None)
        asset_symbol = validated_data.pop("asset_symbol", None)
        setup = validated_data.pop("setup_id", None)
        emotions = validated_data.pop("emotion_ids", [])
        mistakes = validated_data.pop("mistake_ids", [])
        journal = validated_data.get("journal")
        asset = self._resolve_asset(asset_id, asset_symbol, journal)
        trade = Trade.objects.create(asset=asset, setup=setup, **validated_data)
        trade.emotions.set(emotions)
        trade.mistakes.set(mistakes)
        return trade

    def update(self, instance, validated_data):
        asset_id = validated_data.pop("asset_id", None)
        asset_symbol = validated_data.pop("asset_symbol", None)
        setup = validated_data.pop("setup_id", _UNSET)
        emotions = validated_data.pop("emotion_ids", None)
        mistakes = validated_data.pop("mistake_ids", None)

        asset = self._resolve_asset(asset_id, asset_symbol, instance.journal)
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


class AnalyticsTradeSerializer(TradeSerializer):
    """Keep history reads small; fetch notes and attachments on opening a trade."""
    analytics_only = serializers.BooleanField(default=True, read_only=True)

    class Meta(TradeSerializer.Meta):
        fields = tuple(field for field in TradeSerializer.Meta.fields
                       if field not in {"notes", "custom_fields", "screenshots"}) + ("analytics_only",)

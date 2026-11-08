from rest_framework import serializers

FIELD_IDS = {
    "asset", "side", "entry_datetime", "exit_datetime", "risk_percent", "pnl_r", "status",
    "commission", "swap", "reference_timeframe", "trade_score", "opportunity_timeframe",
    "entry_timeframe", "trend_direction", "session", "setup", "emotions", "mistakes",
    "notes", "trade_notes",
}
REMOVABLE = {"commission", "swap", "reference_timeframe", "trade_score", "opportunity_timeframe",
             "entry_timeframe", "trend_direction", "session", "setup", "emotions", "mistakes"}


def validate_configuration(value):
    if not isinstance(value, dict) or not set(value).issubset(FIELD_IDS):
        raise serializers.ValidationError("Invalid entry fields.")
    for field, options in value.items():
        if not isinstance(options, dict) or not set(options).issubset({"label", "visible"}):
            raise serializers.ValidationError("Invalid field preferences.")
        if "label" in options and (not isinstance(options["label"], str) or not options["label"].strip() or len(options["label"]) > 60):
            raise serializers.ValidationError("Field names must contain 1–60 characters.")
        if "visible" in options and type(options["visible"]) is not bool:
            raise serializers.ValidationError("Field visibility must be true or false.")
        if field not in REMOVABLE and options.get("visible") is False:
            raise serializers.ValidationError("Core trade fields cannot be removed.")
    return value

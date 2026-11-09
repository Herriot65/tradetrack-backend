from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name")

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
        )
        return user
    
class UserSerializer(serializers.ModelSerializer):
    entry_configuration_update = serializers.JSONField(write_only=True, required=False)

    def validate_entry_configuration_update(self, value):
        from core.models import Journal
        from .entry_configuration import validate_configuration
        if not isinstance(value, dict) or set(value) != {"scope", "journal_id", "fields"}:
            raise serializers.ValidationError("Specify scope, journal_id and fields.")
        if value["scope"] not in ("journal", "future"):
            raise serializers.ValidationError("Select this journal or future journals.")
        if not isinstance(value["journal_id"], int) or isinstance(value["journal_id"], bool) or not Journal.objects.filter(pk=value["journal_id"], user=self.instance).exists():
            raise serializers.ValidationError("Journal not found.")
        value["fields"] = validate_configuration(value["fields"])
        return value

    def update(self, instance, validated_data):
        from django.db import transaction
        from copy import deepcopy
        change = validated_data.pop("entry_configuration_update", None)
        with transaction.atomic():
            instance = User.objects.select_for_update().get(pk=instance.pk)
            if change is not None:
                config = deepcopy(instance.entry_configuration)
                journals = config.setdefault("journals", {})
                if change["scope"] == "future":
                    # Freeze existing journals before replacing the default for new journals.
                    for journal_id in instance.journals.values_list("id", flat=True):
                        journals.setdefault(str(journal_id), deepcopy(config.get("defaults", {})))
                    config["defaults"] = change["fields"]
                journals[str(change["journal_id"])] = change["fields"]
                validated_data["entry_configuration"] = config
            return super().update(instance, validated_data)

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        if value:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise serializers.ValidationError("Select a valid IANA timezone.")
        return value

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "timezone", "rating_style", "theme", "entry_configuration", "entry_configuration_update")
        read_only_fields = ("id", "email", "entry_configuration")

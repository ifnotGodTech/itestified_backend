from rest_framework import serializers

from apps.engagement.choices import HomeEventType

MAX_EVENTS_PER_BATCH = 50
# One item on screen for over an hour is someone who left the phone on.
MAX_DURATION_MS = 60 * 60 * 1000


class HomeEventInputSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=HomeEventType.choices)
    testimony_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    duration_ms = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=MAX_DURATION_MS
    )
    at = serializers.DateTimeField()


class HomeEventBatchSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    session_id = serializers.CharField(max_length=64)
    events = HomeEventInputSerializer(many=True, allow_empty=False, max_length=MAX_EVENTS_PER_BATCH)

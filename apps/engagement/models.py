from django.conf import settings
from django.db import models

from apps.engagement.choices import HomeEventType


class HomeEvent(models.Model):
    """Phase 35 Slice 5 -- one thing a viewer did on the Home feed. Kept
    compact on purpose (no payload blobs) and pruned after
    HOME_EVENT_RETENTION_DAYS, once its day has been rolled up into
    HomeEngagementDay."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # An anonymous per-install id, so guests count too.
    device_id = models.CharField(max_length=64, blank=True)
    # One Home session: from opening the app to leaving it.
    session_id = models.CharField(max_length=64)
    event_type = models.CharField(max_length=20, choices=HomeEventType.choices)
    # A plain id, not a foreign key: a deleted testimony shouldn't erase
    # (or block deleting) the record that someone once watched it.
    testimony_id = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["occurred_at"], name="home_event_occurred_idx"),
            models.Index(fields=["event_type", "occurred_at"], name="home_event_type_occurred_idx"),
        ]

    def __str__(self) -> str:
        return f"HomeEvent<{self.event_type} {self.occurred_at:%Y-%m-%d}>"


class HomeEngagementDay(models.Model):
    """One day's Home engagement, rolled up from HomeEvent so the raw rows
    can be pruned while the history stays."""

    day = models.DateField(unique=True)
    items_viewed = models.PositiveIntegerField(default=0)
    median_view_ms = models.PositiveIntegerField(default=0)
    swipes = models.PositiveIntegerField(default=0)
    sessions = models.PositiveIntegerField(default=0)
    searches = models.PositiveIntegerField(default=0)
    results_opened = models.PositiveIntegerField(default=0)
    responses = models.PositiveIntegerField(default=0)
    rolled_up_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-day"]

    def __str__(self) -> str:
        return f"HomeEngagementDay<{self.day}>"

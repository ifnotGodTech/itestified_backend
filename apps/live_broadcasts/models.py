import secrets

from django.conf import settings
from django.db import models


class LiveBroadcastStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    LIVE = "live", "Live"
    ENDED = "ended", "Ended"
    CANCELED = "canceled", "Canceled"


class LiveBroadcastEndedReason(models.TextChoices):
    CREATOR_ENDED = "creator_ended", "Creator Ended"
    DROPPED = "dropped", "Dropped"
    ADMIN_TERMINATED = "admin_terminated", "Admin Terminated"


class LiveBroadcastRecordingStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    RECORDING = "recording", "Recording"
    STOPPING = "stopping", "Stopping"
    ARCHIVED = "archived", "Archived"
    FAILED = "failed", "Failed"


class LiveBroadcast(models.Model):
    """Phase 27 Slice 1/4/5 -- created in SCHEDULED status whether the
    Ministry is scheduling ahead of time or about to go live immediately;
    `agora_channel_name` stays blank and no vendor resources exist until
    go_live() (services/commands.py) actually succeeds. This mirrors the
    phase's own Background note: scheduling never allocates Agora
    resources by itself."""

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_broadcasts",
    )
    # Required at scheduling time, same as every other testimony type --
    # added here (Slice 5) once archival surfaced that Testimony.category
    # is non-nullable/PROTECT, so an archived recording needs one from the
    # moment it's scheduled, not invented later. Nullable at the DB level
    # only to keep this an additive migration on top of the already-shipped
    # 0001 (no existing rows to backfill a default onto -- the feature has
    # no real broadcasts yet, live-streaming isn't functional until a real
    # Agora project exists); create_live_broadcast() and the mobile
    # serializer both require it unconditionally, so no row created going
    # forward is ever actually null.
    category = models.ForeignKey(
        "testimonies.TestimonyCategory",
        on_delete=models.PROTECT,
        related_name="live_broadcasts",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20, choices=LiveBroadcastStatus.choices, default=LiveBroadcastStatus.SCHEDULED
    )
    scheduled_at = models.DateTimeField(
        null=True, blank=True, help_text="Blank for a 'start now' broadcast, set for one scheduled ahead of time."
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=20, choices=LiveBroadcastEndedReason.choices, blank=True)
    # Phase 27 Slice 8 -- only ever populated alongside
    # ended_reason=ADMIN_TERMINATED; the admin's required, free-text
    # explanation for the kill, surfaced back to the creator so ending a
    # broadcast is never a silent/generic action.
    admin_termination_note = models.TextField(blank=True)

    # Populated only once go_live() succeeds -- never at creation/scheduling
    # time. Unguessable suffix so a channel name can't be reconstructed from
    # the broadcast id alone.
    agora_channel_name = models.CharField(max_length=64, blank=True)
    agora_publisher_uid = models.PositiveIntegerField(null=True, blank=True)

    # Snapshotted from LiveStreamingPolicy at the moment go_live() succeeds,
    # so a later admin policy change never retroactively changes the caps
    # applied to a broadcast already under way.
    max_viewers_applied = models.PositiveIntegerField(null=True, blank=True)
    max_duration_minutes_applied = models.PositiveIntegerField(null=True, blank=True)

    # Phase 27 Slice 5 -- Agora Cloud Recording (composite/mix mode, one
    # publisher). A recording failure never blocks go_live() itself
    # (see commands.py); FAILED here just means there's nothing to
    # archive when the broadcast ends.
    recording_status = models.CharField(
        max_length=20, choices=LiveBroadcastRecordingStatus.choices, default=LiveBroadcastRecordingStatus.NOT_STARTED
    )
    agora_recording_resource_id = models.CharField(max_length=255, blank=True)
    agora_recording_sid = models.CharField(max_length=255, blank=True)
    agora_recording_uid = models.PositiveIntegerField(null=True, blank=True)
    archived_testimony = models.ForeignKey(
        "testimonies.Testimony",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_live_broadcast",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="livebroadcast_status_idx"),
        ]

    def __str__(self) -> str:
        return f"LiveBroadcast<{self.id}:{self.creator_id}:{self.status}>"


class LiveStreamingPolicy(models.Model):
    """Singleton (pk=1), admin-configurable, no-deploy-needed -- mirrors
    `MediaExportBrandingConfig` (Phase 25) and `PremiumPricing` (Phase 21)
    exactly. Defaults are the conservative 2026-08-25 product decision: 50
    viewers / 30 minutes per broadcast, Agora's own 10,000-participant-minute
    free tier as the shared platform-wide monthly ceiling.
    `default_ministry_monthly_allowance_minutes` is a placeholder starting
    point (the product decision didn't pin an exact number), deliberately
    admin-adjustable before launch."""

    is_enabled = models.BooleanField(default=True)
    max_concurrent_viewers = models.PositiveIntegerField(default=50)
    max_duration_minutes = models.PositiveIntegerField(default=30)
    shared_monthly_ceiling_minutes = models.PositiveIntegerField(
        default=10_000, help_text="Participant-minutes (viewers x duration), matching how Agora bills."
    )
    default_ministry_monthly_allowance_minutes = models.PositiveIntegerField(
        default=200, help_text="Participant-minutes. Split from the shared ceiling above, per Ministry."
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="live_streaming_policy_updates",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "live streaming policy"

    def __str__(self) -> str:
        return "LiveStreamingPolicy<singleton>"


class LiveStreamingPolicyHistory(models.Model):
    """One row per changed field per save, not one wide row per save --
    unlike `PremiumPricing`'s single `amount`, this policy has several
    independent knobs, and e.g. a viewer-cap change is a materially
    different event from an allowance change."""

    policy = models.ForeignKey(LiveStreamingPolicy, on_delete=models.CASCADE, related_name="history")
    field_name = models.CharField(max_length=64)
    from_value = models.CharField(max_length=255, blank=True)
    to_value = models.CharField(max_length=255)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="live_streaming_policy_history_actions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LiveStreamingPolicyHistory<{self.field_name}:{self.from_value}->{self.to_value}>"


class LiveMinutePricing(models.Model):
    """One row per currency, mirrors `PremiumPricing` exactly -- the price a
    Ministry pays per 1,000 extra participant-minutes when self-serving past
    its monthly allowance (2026-08-25 pay-to-exceed product decision)."""

    currency = models.CharField(max_length=3, unique=True)
    price_per_1000_minutes = models.PositiveIntegerField(
        help_text="Amount in minor currency units (kobo/cents) per 1,000 participant-minutes.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="live_minute_pricing_updates",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["currency"]
        verbose_name_plural = "live minute pricing"

    def __str__(self) -> str:
        return f"LiveMinutePricing<{self.currency}:{self.price_per_1000_minutes}>"


class LiveMinutePricingHistory(models.Model):
    pricing = models.ForeignKey(LiveMinutePricing, on_delete=models.CASCADE, related_name="history")
    from_amount = models.PositiveIntegerField(null=True, blank=True)
    to_amount = models.PositiveIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="live_minute_pricing_history_actions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LiveMinutePricingHistory<{self.pricing_id}:{self.from_amount}->{self.to_amount}>"


class MinistryStreamingAllowance(models.Model):
    """Per-Ministry, per-calendar-month allowance row (2026-08-25 product
    decision: each Ministry gets its own split of the shared ceiling, never
    a first-come-first-served shared pool). Actual usage this month is
    deliberately NOT stored here -- it's checked live against Agora's own
    Usage API at go-live time (services/agora.py) rather than a locally
    reconstructed estimate that could drift from what Agora actually
    billed. This row only tracks what a local computation can't get from
    Agora: the allowance snapshot itself and any self-service top-up
    purchased this month."""

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_streaming_allowances",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    # Snapshotted from LiveStreamingPolicy the first time this Ministry
    # needs an allowance row in a given month, so a later policy change
    # never retroactively shrinks/grows a month already in progress -- same
    # non-retroactive principle as PremiumPricing (Phase 21).
    base_allowance_minutes = models.PositiveIntegerField()
    purchased_minutes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["creator", "year", "month"], name="uniq_ministry_allowance_creator_month"),
        ]
        ordering = ["-year", "-month"]

    @property
    def total_allowance_minutes(self) -> int:
        return self.base_allowance_minutes + self.purchased_minutes

    def __str__(self) -> str:
        return f"MinistryStreamingAllowance<{self.creator_id}:{self.year}-{self.month:02d}>"


class LiveMinutePurchaseStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    DECLINED = "declined", "Declined"


class LiveMinutePurchase(models.Model):
    """Self-service top-up (2026-08-25 pay-to-exceed decision) -- same
    one-off Flutterwave charge shape as `Donation` (apps.donations)."""

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_minute_purchases",
    )
    minutes = models.PositiveIntegerField()
    amount = models.PositiveIntegerField(help_text="Amount in minor currency units (kobo/cents).")
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(
        max_length=20, choices=LiveMinutePurchaseStatus.choices, default=LiveMinutePurchaseStatus.PENDING
    )
    payment_reference = models.CharField(max_length=80, unique=True)
    checkout_url = models.URLField(blank=True)
    provider_transaction_id = models.CharField(max_length=80, blank=True)
    status_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def generate_reference() -> str:
        return f"LMP-{secrets.token_hex(8).upper()}"

    def __str__(self) -> str:
        return f"LiveMinutePurchase<{self.payment_reference}:{self.status}>"


class LiveBroadcastApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class LiveBroadcastApprovalRequest(models.Model):
    """Fallback path only (2026-08-25 product decision) -- self-service
    purchase (`LiveMinutePurchase`) is the primary way a Ministry covers an
    overage; this exists for the edge case where that's declined or
    unavailable. Approving grants extra minutes onto that Ministry's own
    `MinistryStreamingAllowance` for the broadcast's month, never a change
    to another Ministry's allowance or the shared ceiling."""

    broadcast = models.ForeignKey(
        LiveBroadcast,
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_broadcast_approval_requests",
    )
    requested_minutes = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=LiveBroadcastApprovalStatus.choices, default=LiveBroadcastApprovalStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="live_broadcast_approvals_reviewed",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LiveBroadcastApprovalRequest<{self.broadcast_id}:{self.status}>"

from __future__ import annotations

from django.utils import timezone

from apps.creators.selectors import get_creator_profile
from apps.live_broadcasts.exceptions import LiveMinutePricingNotConfiguredError, NotAVerifiedMinistryError
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastStatus,
    LiveMinutePricing,
    LiveStreamingPolicy,
    MinistryStreamingAllowance,
)
from apps.live_broadcasts.services import agora as agora_service


def require_verified_ministry(user):
    """Phase 27 eligibility gate (2026-08-25 product decision): live
    broadcasting is Ministry-only, not open to Premium individuals. Shared
    by every command and read view that touches a Ministry's own
    broadcast/allowance data."""
    profile = get_creator_profile(user)
    if profile is None or not profile.is_verified:
        raise NotAVerifiedMinistryError("Only a verified Ministry can broadcast live.")
    return profile


def get_live_streaming_policy() -> LiveStreamingPolicy:
    policy, _ = LiveStreamingPolicy.objects.get_or_create(pk=1)
    return policy


def get_live_minute_pricing(*, currency: str) -> LiveMinutePricing:
    pricing = LiveMinutePricing.objects.filter(currency=currency).first()
    if pricing is None:
        raise LiveMinutePricingNotConfiguredError(f"No live-minute pricing configured for {currency}.")
    return pricing


def get_or_create_current_month_allowance(*, creator) -> MinistryStreamingAllowance:
    now = timezone.now()
    return get_or_create_month_allowance(creator=creator, year=now.year, month=now.month)


def get_or_create_month_allowance(*, creator, year: int, month: int) -> MinistryStreamingAllowance:
    allowance, created = MinistryStreamingAllowance.objects.get_or_create(
        creator=creator,
        year=year,
        month=month,
        defaults={"base_allowance_minutes": get_live_streaming_policy().default_ministry_monthly_allowance_minutes},
    )
    return allowance


def get_active_broadcast_for_creator(*, creator) -> LiveBroadcast | None:
    return LiveBroadcast.objects.filter(creator=creator, status="live").first()


def reserved_minutes_this_month(*, creator, year: int, month: int) -> int:
    """Sum of (viewer cap x duration cap) applied to every broadcast this
    Ministry has already gone live on this month -- the same
    worst-case-reservation methodology already used to guarantee the
    shared monthly ceiling is never crossed (see Phase 27's Background
    note), computed locally from our own LiveBroadcast rows rather than a
    per-Ministry breakdown from Agora's Usage API (see services/agora.py's
    note on what could and couldn't be verified there)."""
    broadcasts = LiveBroadcast.objects.filter(
        creator=creator,
        started_at__year=year,
        started_at__month=month,
        max_viewers_applied__isnull=False,
        max_duration_minutes_applied__isnull=False,
    )
    return sum(b.max_viewers_applied * b.max_duration_minutes_applied for b in broadcasts)


def _broadcast_display_queryset():
    return LiveBroadcast.objects.select_related(
        "creator", "creator__creator_profile", "creator__profile"
    )


def list_live_broadcasts():
    """Phase 27 Slice 2 -- viewer discovery, live-now. Public (guests
    included); no viewer-count annotation here -- that comes from Agora's
    own SDK events fired to a client only once it has actually joined the
    channel (see Slice 4's own "no new real-time backend infrastructure"
    note), not something this browse list needs to reconstruct."""
    return _broadcast_display_queryset().filter(status=LiveBroadcastStatus.LIVE).order_by("-started_at")


def list_upcoming_broadcasts():
    """Phase 27 Slice 2 -- viewer discovery, scheduled-upcoming."""
    now = timezone.now()
    return (
        _broadcast_display_queryset()
        .filter(status=LiveBroadcastStatus.SCHEDULED, scheduled_at__gt=now)
        .order_by("scheduled_at")
    )


def list_active_broadcasts_for_admin() -> list[LiveBroadcast]:
    """Phase 27 Slice 7 -- admin monitoring, every Ministry's currently
    live broadcast platform-wide (unlike every other selector in this
    module, not scoped to one creator). Viewer count and this-month
    allowance usage are computed here and attached as plain attributes
    rather than left to the serializer, since both involve an external
    REST call / cross-model aggregation, not simple field access --
    the serializer just reads whatever's attached."""
    broadcasts = list(
        _broadcast_display_queryset().filter(status=LiveBroadcastStatus.LIVE).order_by("-started_at")
    )
    now = timezone.now()
    for broadcast in broadcasts:
        broadcast.elapsed_seconds = int((now - broadcast.started_at).total_seconds()) if broadcast.started_at else 0
        broadcast.viewer_count = (
            agora_service.get_channel_viewer_count(channel_name=broadcast.agora_channel_name)
            if broadcast.agora_channel_name
            else None
        )
        allowance = compute_allowance_summary(creator=broadcast.creator)
        broadcast.reserved_minutes_this_month = allowance["reserved_minutes"]
        broadcast.total_allowance_minutes = allowance["total_allowance_minutes"]
        broadcast.remaining_allowance_minutes = allowance["remaining_minutes"]
    return broadcasts


def list_scheduled_broadcasts_for_admin():
    """Phase 27 Slice 7 -- admin monitoring, every Ministry's scheduled/
    upcoming broadcast platform-wide. Unlike `list_upcoming_broadcasts`
    (public, only ever shows what a viewer could actually still catch),
    this includes a "start now" broadcast that hasn't gone live yet
    (`scheduled_at` blank) -- an admin needs visibility into that too."""
    return _broadcast_display_queryset().filter(status=LiveBroadcastStatus.SCHEDULED).order_by("scheduled_at")


def list_ministry_usage_for_current_month() -> list[dict]:
    """Phase 27 Slice 9 -- per-Ministry cost/usage breakdown for the admin
    view. Reuses the same local worst-case-reservation methodology as
    Slice 4's own allowance check (see reserved_minutes_this_month's own
    docstring) rather than Agora's Usage API, which has no concept of
    "Ministry" to break usage down by -- it only reports every Ministry
    combined (see services/agora.py's get_participant_minutes_used).
    Only Ministries that already have an allowance row this month are
    included -- a Ministry that hasn't gone live at all this month has
    nothing to show."""
    now = timezone.now()
    allowances = MinistryStreamingAllowance.objects.filter(year=now.year, month=now.month).select_related(
        "creator", "creator__creator_profile", "creator__profile"
    )
    rows = []
    for allowance in allowances:
        reserved = reserved_minutes_this_month(creator=allowance.creator, year=now.year, month=now.month)
        rows.append(
            {
                "creator": allowance.creator,
                "base_allowance_minutes": allowance.base_allowance_minutes,
                "purchased_minutes": allowance.purchased_minutes,
                "total_allowance_minutes": allowance.total_allowance_minutes,
                "reserved_minutes": reserved,
                "remaining_minutes": max(allowance.total_allowance_minutes - reserved, 0),
            }
        )
    return rows


def compute_platform_usage_summary() -> dict:
    """Phase 27 Slice 9 -- this month's total Agora usage (best-effort,
    from Agora's own Usage API -- see get_participant_minutes_used's own
    note on what could/couldn't be confirmed) against the shared
    platform-wide monthly ceiling."""
    now = timezone.now()
    policy = get_live_streaming_policy()
    return {
        "year": now.year,
        "month": now.month,
        "used_minutes": agora_service.get_participant_minutes_used(year=now.year, month=now.month),
        "shared_monthly_ceiling_minutes": policy.shared_monthly_ceiling_minutes,
    }


def compute_allowance_summary(*, creator) -> dict:
    now = timezone.now()
    allowance = get_or_create_current_month_allowance(creator=creator)
    reserved = reserved_minutes_this_month(creator=creator, year=now.year, month=now.month)
    remaining = allowance.total_allowance_minutes - reserved
    return {
        "year": allowance.year,
        "month": allowance.month,
        "base_allowance_minutes": allowance.base_allowance_minutes,
        "purchased_minutes": allowance.purchased_minutes,
        "total_allowance_minutes": allowance.total_allowance_minutes,
        "reserved_minutes": reserved,
        "remaining_minutes": max(remaining, 0),
    }

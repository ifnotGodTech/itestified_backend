from __future__ import annotations

from django.utils import timezone

from apps.creators.selectors import get_creator_profile
from apps.live_broadcasts.exceptions import LiveMinutePricingNotConfiguredError, NotAVerifiedMinistryError
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveMinutePricing,
    LiveStreamingPolicy,
    MinistryStreamingAllowance,
)


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

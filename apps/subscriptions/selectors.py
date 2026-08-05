from __future__ import annotations

from apps.subscriptions.models import ENTITLED_STATUSES, NON_TERMINAL_STATUSES, Subscription


def get_current_subscription(user) -> Subscription | None:
    """The single non-terminal subscription for a user, if any -- the
    UniqueConstraint on Subscription guarantees there is at most one.
    Returns None for a user who has never subscribed, or whose subscription
    has reached a terminal state (canceled/expired)."""
    return Subscription.objects.filter(user=user, status__in=NON_TERMINAL_STATUSES).first()


def is_user_premium(user) -> bool:
    """The single reusable entitlement check every later premium-gated
    phase (22, 24, 25) depends on. PAST_DUE still counts as premium --
    grace period, not an instant cutoff -- so this deliberately doesn't
    duplicate that logic at each call site."""
    if not getattr(user, "is_authenticated", False):
        return False
    return Subscription.objects.filter(user=user, status__in=ENTITLED_STATUSES).exists()

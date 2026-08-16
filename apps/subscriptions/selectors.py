from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.subscriptions.models import ENTITLED_STATUSES, NON_TERMINAL_STATUSES, PremiumPricing, Subscription


def current_subscription_queryset(user) -> QuerySet[Subscription]:
    """Non-terminal subscriptions for a user, excluding one that scheduled
    a cancellation whose paid-for period has since passed -- nothing else
    will ever move that row to CANCELED/EXPIRED on its own, since Flutterwave
    stops sending renewal charges (and therefore webhooks) for it the moment
    it's cancelled on their side, so this is computed lazily here rather than
    depending on a scheduled job. Exposed (not module-private) so
    services/commands.py can chain select_for_update() onto it."""
    lapsed_after_cancel = Q(cancel_at_period_end=True, current_period_end__lt=timezone.now())
    return Subscription.objects.filter(user=user, status__in=NON_TERMINAL_STATUSES).exclude(
        lapsed_after_cancel
    )


def get_current_subscription(user) -> Subscription | None:
    """The single non-terminal (and not lapsed-after-cancellation) subscription
    for a user, if any -- the UniqueConstraint on Subscription guarantees at
    most one non-terminal row. Returns None for a user who has never
    subscribed, whose subscription has reached a terminal state
    (canceled/expired), or whose scheduled cancellation has now lapsed."""
    return current_subscription_queryset(user).first()


def is_user_premium(user) -> bool:
    """The single reusable entitlement check every later premium-gated
    phase (22, 24, 25) depends on. PAST_DUE still counts as premium --
    grace period, not an instant cutoff -- so this deliberately doesn't
    duplicate that logic at each call site. A subscription scheduled to
    cancel stays entitled until its current_period_end passes."""
    if not getattr(user, "is_authenticated", False):
        return False
    subscription = (
        Subscription.objects.filter(user=user, status__in=ENTITLED_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if subscription is None:
        return False
    if subscription.cancel_at_period_end and subscription.current_period_end:
        return subscription.current_period_end > timezone.now()
    return True


def list_premium_pricing() -> QuerySet[PremiumPricing]:
    return PremiumPricing.objects.select_related("updated_by").order_by("currency")

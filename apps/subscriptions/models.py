import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q


class SubscriptionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past Due"
    CANCELED = "canceled", "Canceled"
    EXPIRED = "expired", "Expired"


# Statuses that still grant premium access. PAST_DUE deliberately stays
# entitled -- a failed renewal must not be an instant hard cutoff (Phase 21's
# own build note), only PAST_DUE -> EXPIRED (driven by Flutterwave giving up
# its own retry schedule) actually revokes access.
ENTITLED_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)

# A user should only ever have one subscription in a non-terminal state at
# a time -- enforced below via a partial unique constraint, not just
# service-layer discipline.
NON_TERMINAL_STATUSES = (
    SubscriptionStatus.PENDING,
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.PAST_DUE,
)


class Subscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING,
    )
    amount = models.PositiveIntegerField(
        help_text="Amount in minor currency units (kobo/cents), matching Donation's convention.",
    )
    currency = models.CharField(max_length=3, default="NGN")
    payment_reference = models.CharField(
        max_length=80,
        unique=True,
        help_text="Our own reference for the subscription's first charge only -- "
        "Flutterwave generates its own reference for each automatic renewal charge.",
    )
    provider = models.CharField(max_length=40, default="flutterwave")
    provider_plan_id = models.CharField(max_length=40, blank=True)
    provider_subscription_id = models.CharField(max_length=80, blank=True)
    checkout_url = models.URLField(blank=True)
    provider_transaction_id = models.CharField(max_length=80, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status__in=NON_TERMINAL_STATUSES),
                name="one_non_terminal_subscription_per_user",
            ),
        ]

    @staticmethod
    def generate_reference() -> str:
        return f"SUB-{secrets.token_hex(8).upper()}"

    def __str__(self) -> str:
        return f"Subscription<{self.payment_reference}:{self.status}>"


class SubscriptionStatusHistory(models.Model):
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="subscription_status_actions",
        null=True,
        blank=True,
    )
    from_status = models.CharField(max_length=20, choices=SubscriptionStatus.choices)
    to_status = models.CharField(max_length=20, choices=SubscriptionStatus.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"SubscriptionStatusHistory<{self.subscription_id}:{self.from_status}->{self.to_status}>"


class SubscriptionEventLog(models.Model):
    """Captures a Flutterwave webhook event that arrived on the shared
    provider-callback endpoint and could not be confidently matched to a
    Subscription (neither by payment_reference for a first charge, nor by
    customer email for a renewal). Exists so real webhook payloads can be
    inspected and the matching logic tightened with empirical data, rather
    than silently dropping events this code doesn't yet recognize -- see
    Phase 21 Slice 1's own note on this being the one part of the Flutterwave
    Payment Plans integration built without a fully-confirmed payload shape."""

    event = models.CharField(max_length=80, blank=True)
    raw_payload = models.JSONField(default=dict)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"SubscriptionEventLog<{self.event}:{self.created_at}>"

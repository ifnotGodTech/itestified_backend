import secrets

from django.conf import settings
from django.db import models


class DonationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    DECLINED = "declined", "Declined"
    REVERSED = "reversed", "Reversed"
    REFUNDED = "refunded", "Refunded"


class Donation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="donations",
    )
    amount = models.PositiveIntegerField(
        help_text="Amount in minor currency units (kobo/cents).",
    )
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=DonationStatus.choices, default=DonationStatus.PENDING)
    payment_reference = models.CharField(max_length=80, unique=True)
    provider = models.CharField(max_length=40, default="flutterwave")
    checkout_url = models.URLField(blank=True)
    provider_transaction_id = models.CharField(max_length=80, blank=True)
    status_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def generate_reference() -> str:
        return f"DON-{secrets.token_hex(8).upper()}"

    def __str__(self) -> str:
        return f"Donation<{self.payment_reference}:{self.status}>"


class DonationStatusHistory(models.Model):
    donation = models.ForeignKey(
        Donation,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="donation_status_actions",
        null=True,
        blank=True,
    )
    from_status = models.CharField(max_length=20, choices=DonationStatus.choices)
    to_status = models.CharField(max_length=20, choices=DonationStatus.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DonationStatusHistory<{self.donation_id}:{self.from_status}->{self.to_status}>"

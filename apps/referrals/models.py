from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ReferralCommissionRate(models.Model):
    """Phase 24 Slice 1 -- the one current referral commission percentage,
    admin-configurable rather than hardcoded, mirroring Phase 21 Slice 5's
    PremiumPricing pattern exactly: a single row mutated in place (never a
    new row per change, no versioning table of "active" rows), with a
    separate history table for the audit trail. `ReferralCommission`
    (Slice 2) copies this value onto each ledger row at computation
    time rather than referencing it live, so a rate change
    here only ever affects commission computed after the change --
    existing ledger rows keep the rate they were actually computed at,
    same "never claw back/reprice what's already settled" principle as
    Premium pricing and cancellation."""

    percent = models.DecimalField(max_digits=5, decimal_places=2)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referral_commission_rate_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"ReferralCommissionRate<{self.percent}%>"


class ReferralCommissionRateHistory(models.Model):
    rate = models.ForeignKey(ReferralCommissionRate, on_delete=models.CASCADE, related_name="history")
    from_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    to_percent = models.DecimalField(max_digits=5, decimal_places=2)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referral_commission_rate_history_actions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ReferralCommissionRateHistory<{self.from_percent}->{self.to_percent}>"


class ReferralAttribution(models.Model):
    """Phase 24 Slice 6 (not built yet) is what actually creates this row,
    at registration time via a referral code -- but Slice 2's commission
    computation needs the model to exist first, so it's introduced here.
    Permanent and immutable once created: an existing user can never gain
    one retroactively, and it's never reassigned or deleted for as long as
    both users exist."""

    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_attribution",
    )
    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referrals_made",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=~Q(referred_user=F("referrer")),
                name="referral_attribution_no_self_referral",
            ),
        ]

    def __str__(self) -> str:
        return f"ReferralAttribution<{self.referred_user_id}<-{self.referrer_id}>"


class ReferralCommission(models.Model):
    """The commission ledger (Phase 24 Slice 2). One row per successful
    subscription charge (first charge or renewal alike -- a referred
    subscriber's very first payment is exactly the moment the referral
    converts, no reason to treat it differently from any later cycle) where
    both the referred subscriber's charge succeeded and the referrer was,
    at that moment, an active Premium subscriber themselves. `rate_percent`
    is copied from `ReferralCommissionRate` at computation time, not a live
    FK -- a later rate change never touches an already-created row, same
    "never claw back" principle as Premium pricing and cancellation.
    `provider_transaction_id` is unique so a retried webhook delivery for
    the same charge can never double-create a row."""

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_commissions_earned",
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_commissions_generated",
    )
    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.CASCADE,
        related_name="referral_commissions",
    )
    provider_transaction_id = models.CharField(max_length=80, unique=True)
    amount = models.PositiveIntegerField(
        help_text="Commission amount in minor currency units, computed from the charge's own amount and rate_percent."
    )
    currency = models.CharField(max_length=3)
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2)
    billing_period_end = models.DateTimeField(
        help_text="The subscription's current_period_end as of this charge -- identifies which billing cycle this commission was earned for."
    )
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referral_commissions_marked_paid",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ReferralCommission<{self.referrer_id}:{self.amount}{self.currency}>"


class ReferralTermsAcceptance(models.Model):
    """Phase 24 Slice 5. A dedicated row rather than a field bolted onto
    the core `User` model -- keeps this entirely inside apps.referrals'
    own boundary, matching how every other referral concept here already
    gets its own model instead of touching `apps.users`. `accepted_at` is
    set once, at first acceptance; accepting again is a no-op (idempotent,
    same convention as Phase 23 Slice 14's request-verification), so it's
    a plain `auto_now_add` rather than something that gets bumped."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_terms_acceptance",
    )
    accepted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"ReferralTermsAcceptance<{self.user_id}:{self.accepted_at}>"


class ReferralCode(models.Model):
    """Phase 24 Slice 4. Generated lazily the first time an eligible
    subscriber opens "Get my referral link" (see
    services.commands.get_or_create_referral_code) -- not at registration
    or subscription time, so a Free user or a Premium user who never opens
    the screen never gets one. Permanent once created and keeps working
    for new signups even through a later lapse -- only commission
    eligibility (Slice 2) depends on current subscriber status, never the
    code's own existence."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_code",
    )
    code = models.CharField(max_length=8, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"ReferralCode<{self.code}>"

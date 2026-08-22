from __future__ import annotations

import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.referrals.exceptions import (
    ReferralCommissionAlreadyPaidError,
    ReferralCommissionNotFoundError,
    ReferralCommissionRateInvalidPercentError,
)
from apps.referrals.models import (
    ReferralAttribution,
    ReferralCode,
    ReferralCommission,
    ReferralCommissionRate,
    ReferralCommissionRateHistory,
    ReferralTermsAcceptance,
)
from apps.referrals.selectors import get_current_commission_percent
from apps.subscriptions.selectors import is_user_premium

# Mirrors apps.authn.services.commands' temp-password alphabet's own
# ambiguity-avoiding approach, but uppercase-only per this phase's own
# plan text: excludes 0/O/1/I/L so a referral code read aloud or typed
# from memory is never ambiguous.
_REFERRAL_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_REFERRAL_CODE_LENGTH = 8


@transaction.atomic
def set_referral_commission_rate(*, percent: Decimal, actor) -> ReferralCommissionRate:
    """Phase 24 Slice 1: admin sets the referral commission percentage.
    Mirrors Phase 21 Slice 5's set_premium_price exactly -- mutate the one
    current row in place (select_for_update to avoid a race between two
    concurrent admin changes), record a history row alongside it. No
    gateway call needed here (unlike Premium pricing's Flutterwave Payment
    Plan creation) since this is a plain percentage read at commission-
    computation time, not something a payment provider needs to know
    about."""
    if percent < 0 or percent > 100:
        raise ReferralCommissionRateInvalidPercentError("Commission rate must be between 0 and 100.")

    rate = ReferralCommissionRate.objects.select_for_update().order_by("-id").first()
    from_percent = rate.percent if rate else None

    if rate is None:
        rate = ReferralCommissionRate.objects.create(percent=percent, updated_by=actor)
    else:
        rate.percent = percent
        rate.updated_by = actor
        rate.save(update_fields=["percent", "updated_by", "updated_at"])

    ReferralCommissionRateHistory.objects.create(
        rate=rate,
        from_percent=from_percent,
        to_percent=percent,
        actor=actor,
    )
    return rate


@transaction.atomic
def record_commission_for_successful_charge(*, subscription) -> ReferralCommission | None:
    """Phase 24 Slice 2: called from the shared Flutterwave webhook view
    (apps.donations.api.views.DonationProviderCallbackView) right after
    apply_charge_callback matches a successful charge to a Subscription --
    for the first charge and every renewal alike. Returns None (no
    commission row, nothing to reverse later) whenever the subscriber has
    no referral attribution, the referrer isn't currently an active
    Premium subscriber themselves, or no commission rate has ever been
    set (a 0% rate is treated the same as "nothing to pay out" -- the
    ledger stays empty rather than filling with 0-amount rows)."""
    attribution = (
        ReferralAttribution.objects.select_related("referrer")
        .filter(referred_user_id=subscription.user_id)
        .first()
    )
    if attribution is None:
        return None
    if not is_user_premium(attribution.referrer):
        return None
    if not subscription.provider_transaction_id:
        return None

    rate_percent = get_current_commission_percent()
    if rate_percent <= 0:
        return None

    amount = int(
        (Decimal(subscription.amount) * rate_percent / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP)
    )

    commission, _created = ReferralCommission.objects.get_or_create(
        provider_transaction_id=subscription.provider_transaction_id,
        defaults={
            "referrer": attribution.referrer,
            "referred_user": attribution.referred_user,
            "subscription": subscription,
            "amount": amount,
            "currency": subscription.currency,
            "rate_percent": rate_percent,
            "billing_period_end": subscription.current_period_end,
        },
    )
    return commission


@transaction.atomic
def mark_referral_commission_paid(*, commission_id: int, actor) -> ReferralCommission:
    """Phase 24 Slice 3: admin confirms a ledger row was actually paid out
    via the manual, off-system bank transfer this phase deliberately
    stops short of automating. Idempotency is explicit, not silent -- a
    repeat attempt on an already-paid row raises rather than quietly
    no-op'ing, so a confused double-click surfaces as a clear error
    instead of a second, misleading paid_by/paid_at overwrite."""
    commission = (
        ReferralCommission.objects.select_for_update().filter(id=commission_id).first()
    )
    if commission is None:
        raise ReferralCommissionNotFoundError()
    if commission.is_paid:
        raise ReferralCommissionAlreadyPaidError()

    commission.is_paid = True
    commission.paid_at = timezone.now()
    commission.paid_by = actor
    commission.save(update_fields=["is_paid", "paid_at", "paid_by"])
    return commission


def accept_referral_terms(*, user) -> ReferralTermsAcceptance:
    """Phase 24 Slice 5. Idempotent -- a repeat accept (e.g. the mobile
    screen re-submitting) just returns the original acceptance rather than
    erroring or bumping accepted_at, same convention as Phase 23 Slice
    14's request-verification no-op."""
    acceptance, _created = ReferralTermsAcceptance.objects.get_or_create(user=user)
    return acceptance


def _generate_referral_code() -> str:
    return "".join(secrets.choice(_REFERRAL_CODE_ALPHABET) for _ in range(_REFERRAL_CODE_LENGTH))


@transaction.atomic
def get_or_create_referral_code(*, user) -> ReferralCode:
    """Phase 24 Slice 4. Lazily generates on first call, never before --
    a Free user or a Premium user who never opens "Get my referral link"
    never gets one. Retries on a rare code collision, and re-checks for
    an existing row after any IntegrityError so two concurrent requests
    for the same user can't both attempt a create."""
    existing = ReferralCode.objects.filter(user=user).first()
    if existing is not None:
        return existing

    for _ in range(10):
        candidate = _generate_referral_code()
        try:
            with transaction.atomic():
                return ReferralCode.objects.create(user=user, code=candidate)
        except IntegrityError:
            existing = ReferralCode.objects.filter(user=user).first()
            if existing is not None:
                return existing
    raise RuntimeError("Could not generate a unique referral code.")


def attribute_referral_signup(*, referred_user, code: str) -> ReferralAttribution | None:
    """Phase 24 Slice 6. Called from apps.authn.complete_registration
    inside its own transaction, at the exact moment the User row is
    created -- the only point in this codebase attribution can ever be
    decided. Returns None (never raises) for a blank/unrecognized code,
    so an invalid code never blocks registration -- it's just silently
    ignored. `referred_user` was just created moments ago in the same
    transaction, so it cannot already have generated its own ReferralCode
    (Slice 4 only ever creates one for an existing, already-authenticated
    subscriber) -- the self-referral guard below is defensive rather than
    a scenario this flow can actually reach, matching the DB-level
    CheckConstraint on ReferralAttribution itself."""
    code = code.strip().upper()
    if not code:
        return None

    referral_code = ReferralCode.objects.filter(code=code).select_related("user").first()
    if referral_code is None:
        return None
    if referral_code.user_id == referred_user.id:
        return None

    return ReferralAttribution.objects.create(referred_user=referred_user, referrer=referral_code.user)

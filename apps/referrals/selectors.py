from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from django.db.models import QuerySet, Sum

from apps.referrals.models import (
    ReferralCode,
    ReferralCommission,
    ReferralCommissionRate,
    ReferralTermsAcceptance,
)


def get_current_commission_rate() -> ReferralCommissionRate | None:
    """Returns None if an admin has genuinely never set one -- callers
    decide their own fallback rather than this selector silently
    inventing a number. Unlike PremiumPricing, there is no pre-existing
    settings value to seed from, so this app ships with no bootstrap
    migration: the first real value is whatever an admin sets via the
    dashboard."""
    return ReferralCommissionRate.objects.order_by("-id").first()


def get_current_commission_percent() -> Decimal:
    """Slice 2 (commission computation) reads this. Falls back to 0 --
    not the blueprint's 15% example -- if no admin has ever set a rate:
    zero commission is a safe, visible degradation (nothing gets paid
    out and the ledger stays empty), whereas silently assuming 15% would
    hide a missing admin decision behind a number nobody actually chose."""
    rate = get_current_commission_rate()
    return rate.percent if rate is not None else Decimal("0")


def get_referral_commission_totals_by_currency(
    queryset: "QuerySet[ReferralCommission]",
) -> List[Dict[str, Any]]:
    """Mirrors apps.donations.selectors.get_donation_totals_by_currency --
    the admin ledger view (Slice 3) sums whatever filtered queryset it's
    given (e.g. unpaid-only) rather than always totaling the whole table."""
    return list(
        queryset.values("currency").annotate(total_amount=Sum("amount")).order_by("currency")
    )


def has_accepted_referral_terms(user) -> bool:
    return ReferralTermsAcceptance.objects.filter(user=user).exists()


def get_referral_code(user) -> ReferralCode | None:
    return ReferralCode.objects.filter(user=user).first()


def format_referred_user_label(full_name: str) -> str:
    """First name + last initial only, e.g. "David O." -- Slice 7's
    referrer-facing earnings view shows who was referred without exposing
    the referred person's full name or email, mirroring how the public
    `/r/<code>` landing page (Slice 6) never leaks the *referrer's* own
    identity in the other direction."""
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "A referral"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."

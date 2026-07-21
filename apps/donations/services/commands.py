from __future__ import annotations

from django.conf import settings
from django.db import transaction

from apps.donations.exceptions import (
    DonationGatewayNotConfiguredError,
    DonationNotFoundError,
    DonationNotReversibleError,
)
from apps.donations.models import Donation, DonationStatus, DonationStatusHistory
from apps.donations.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError


def _log_status_history(*, donation: Donation, from_status: str, to_status: str, reason: str = "", actor=None) -> None:
    if from_status == to_status:
        return
    DonationStatusHistory.objects.create(
        donation=donation,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
    )


def _gateway() -> FlutterwaveGateway:
    return FlutterwaveGateway(
        secret_key=settings.FLUTTERWAVE_SECRET_KEY,
        base_url=settings.FLUTTERWAVE_BASE_URL,
    )


@transaction.atomic
def create_donation(*, user, amount: int, currency: str) -> Donation:
    reference = Donation.generate_reference()
    donation = Donation.objects.create(
        user=user,
        amount=amount,
        currency=currency,
        payment_reference=reference,
    )
    if not settings.FLUTTERWAVE_SECRET_KEY:
        donation.checkout_url = f"https://checkout.flutterwave.com/pay/{reference.lower()}"
        donation.status_reason = "Flutterwave secret key not configured."
        donation.save(update_fields=["checkout_url", "status_reason", "updated_at"])
        return donation

    redirect_url = settings.FLUTTERWAVE_REDIRECT_URL or "https://www.itestified.app/giving/return"
    try:
        init_result = _gateway().initialize(
            amount=donation.amount,
            currency=donation.currency,
            tx_ref=donation.payment_reference,
            customer_email=user.email,
            customer_name=getattr(user, "full_name", "") or user.email,
            redirect_url=redirect_url,
        )
    except FlutterwaveGatewayError as exc:
        from_status = donation.status
        donation.status = DonationStatus.DECLINED
        donation.status_reason = str(exc)
        donation.save(update_fields=["status", "status_reason", "updated_at"])
        _log_status_history(
            donation=donation,
            from_status=from_status,
            to_status=donation.status,
            reason=donation.status_reason,
            actor=user,
        )
        raise

    donation.checkout_url = init_result.checkout_url
    donation.provider_transaction_id = init_result.provider_transaction_id
    donation.save(update_fields=["checkout_url", "provider_transaction_id", "updated_at"])
    return donation


@transaction.atomic
def verify_donation(*, user, payment_reference: str, transaction_id: str) -> Donation:
    donation = (
        Donation.objects.select_for_update()
        .filter(payment_reference=payment_reference, user=user)
        .first()
    )
    if donation is None:
        raise DonationNotFoundError()
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise DonationGatewayNotConfiguredError()

    verify_result = _gateway().verify(transaction_id)
    from_status = donation.status
    donation.status = verify_result.status
    donation.provider_transaction_id = verify_result.provider_transaction_id
    donation.status_reason = verify_result.status_reason
    donation.save(update_fields=["status", "provider_transaction_id", "status_reason", "updated_at"])
    _log_status_history(
        donation=donation,
        from_status=from_status,
        to_status=donation.status,
        reason=donation.status_reason,
        actor=user,
    )
    return donation


@transaction.atomic
def apply_provider_callback(
    *,
    payment_reference: str,
    status_value: str,
    provider_transaction_id: str,
    status_reason: str,
) -> Donation | None:
    donation = (
        Donation.objects.select_for_update()
        .filter(payment_reference=payment_reference)
        .first()
    )
    if donation is None:
        return None

    from_status = donation.status
    donation.status = status_value
    donation.provider_transaction_id = provider_transaction_id
    donation.status_reason = status_reason
    donation.save(update_fields=["status", "provider_transaction_id", "status_reason", "updated_at"])
    _log_status_history(
        donation=donation,
        from_status=from_status,
        to_status=donation.status,
        reason=donation.status_reason,
    )
    return donation


@transaction.atomic
def reverse_donation(*, donation_id: int, actor, reason: str) -> Donation:
    donation = Donation.objects.select_for_update().filter(pk=donation_id).first()
    if donation is None:
        raise DonationNotFoundError()
    if donation.status != DonationStatus.SUCCESSFUL:
        raise DonationNotReversibleError("Only successful donations can be reversed.")

    from_status = donation.status
    donation.status = DonationStatus.REVERSED
    donation.status_reason = reason
    donation.save(update_fields=["status", "status_reason", "updated_at"])
    _log_status_history(
        donation=donation,
        from_status=from_status,
        to_status=donation.status,
        reason=donation.status_reason,
        actor=actor,
    )
    return donation

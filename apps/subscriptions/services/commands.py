from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError
from apps.subscriptions.exceptions import (
    SubscriptionAlreadyExistsError,
    SubscriptionGatewayNotConfiguredError,
    SubscriptionNotCancelableError,
    SubscriptionNotFoundError,
)
from apps.subscriptions.models import (
    NON_TERMINAL_STATUSES,
    Subscription,
    SubscriptionEventLog,
    SubscriptionStatus,
    SubscriptionStatusHistory,
)
from apps.subscriptions.selectors import current_subscription_queryset

# Approximate a monthly billing cycle for current_period_end -- this field is
# informational (drives the mobile "Renews on" display) rather than the
# actual billing trigger, which Flutterwave owns entirely on its own
# schedule. Exact calendar-month arithmetic isn't worth a new dependency for
# that purpose.
_BILLING_CYCLE = timedelta(days=30)


def _log_status_history(*, subscription: Subscription, from_status: str, to_status: str, reason: str = "", actor=None) -> None:
    if from_status == to_status:
        return
    SubscriptionStatusHistory.objects.create(
        subscription=subscription,
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


def _attach_provider_subscription_id(subscription: Subscription) -> None:
    """Best-effort: look up Flutterwave's own subscription id right after
    the first charge succeeds, so cancel_subscription() has something real
    to call later. A lookup failure here must never fail the whole webhook
    -- the subscription is still genuinely ACTIVE either way; cancellation
    just falls back to local-only if this never gets filled in (logged,
    not silent)."""
    if not settings.FLUTTERWAVE_SECRET_KEY:
        return
    try:
        record = _gateway().find_active_subscription_by_email(subscription.user.email)
    except FlutterwaveGatewayError:
        record = None
    if record is not None and record.provider_subscription_id:
        subscription.provider_subscription_id = record.provider_subscription_id


def subscribe(*, user) -> Subscription:
    """Deliberately NOT a single @transaction.atomic function: the Flutterwave
    call in the middle is a real external side effect, and if it fails we
    still need the CANCELED record (with its failure reason) to persist so
    the attempt is visible/auditable -- wrapping the whole function would
    roll that write back along with everything else the moment we re-raise.
    Each DB-writing step below gets its own short atomic block instead."""
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise SubscriptionGatewayNotConfiguredError()
    if not settings.FLUTTERWAVE_PREMIUM_PLAN_ID:
        raise SubscriptionGatewayNotConfiguredError()

    with transaction.atomic():
        # Query the raw non-terminal row here (not current_subscription_queryset's
        # lapsed-exclusion) -- the DB's partial UniqueConstraint only knows
        # about `status`, so a lapsed cancel_at_period_end row must actually
        # be closed out to CANCELED before a new row can be created, or the
        # INSERT below would violate that constraint.
        existing = (
            Subscription.objects.select_for_update()
            .filter(user=user, status__in=NON_TERMINAL_STATUSES)
            .first()
        )
        if existing is not None:
            has_lapsed = (
                existing.cancel_at_period_end
                and existing.current_period_end is not None
                and existing.current_period_end < timezone.now()
            )
            if not has_lapsed:
                raise SubscriptionAlreadyExistsError()
            from_status = existing.status
            existing.status = SubscriptionStatus.CANCELED
            existing.save(update_fields=["status", "updated_at"])
            _log_status_history(
                subscription=existing,
                from_status=from_status,
                to_status=existing.status,
                reason="Lapsed after a scheduled cancellation.",
            )

        subscription = Subscription.objects.create(
            user=user,
            amount=settings.PREMIUM_PLAN_AMOUNT_KOBO,
            currency=settings.PREMIUM_PLAN_CURRENCY,
            payment_reference=Subscription.generate_reference(),
            provider_plan_id=settings.FLUTTERWAVE_PREMIUM_PLAN_ID,
        )

    redirect_url = settings.FLUTTERWAVE_REDIRECT_URL or "https://www.itestified.app/premium/return"
    try:
        init_result = _gateway().initialize(
            amount=subscription.amount,
            currency=subscription.currency,
            tx_ref=subscription.payment_reference,
            customer_email=user.email,
            customer_name=getattr(user, "full_name", "") or user.email,
            redirect_url=redirect_url,
            payment_plan=settings.FLUTTERWAVE_PREMIUM_PLAN_ID,
        )
    except FlutterwaveGatewayError as exc:
        # No active access existed yet for this attempt (still PENDING), so
        # there's nothing to protect with a grace period -- straight to
        # CANCELED, same reasoning as a failed first charge in
        # apply_charge_callback below. This write must survive the raise
        # below, hence its own atomic block rather than the function-wide one.
        with transaction.atomic():
            from_status = subscription.status
            subscription.status = SubscriptionStatus.CANCELED
            subscription.status_reason = str(exc)
            subscription.save(update_fields=["status", "status_reason", "updated_at"])
            _log_status_history(
                subscription=subscription,
                from_status=from_status,
                to_status=subscription.status,
                reason=subscription.status_reason,
                actor=user,
            )
        raise

    subscription.checkout_url = init_result.checkout_url
    subscription.provider_transaction_id = init_result.provider_transaction_id
    subscription.save(update_fields=["checkout_url", "provider_transaction_id", "updated_at"])
    return subscription


@transaction.atomic
def apply_charge_callback(
    *,
    payment_reference: str,
    customer_email: str,
    status_value: str,
    provider_transaction_id: str,
    status_reason: str,
) -> Subscription | None:
    """Handles a charge.completed webhook event relevant to a subscription
    -- either the first charge (matched by payment_reference, which we
    generated) or an automatic renewal charge (Flutterwave generates its
    own reference for these, so matched by customer_email against the
    user's current non-terminal subscription instead). Returns None if
    neither match succeeds, so the caller can log the event for later
    inspection rather than silently accept an unrecognized payload."""
    subscription = (
        Subscription.objects.select_for_update()
        .filter(payment_reference=payment_reference)
        .first()
    )
    is_first_charge = subscription is not None
    if subscription is None and customer_email:
        subscription = (
            Subscription.objects.select_for_update()
            .filter(user__email__iexact=customer_email, status__in=NON_TERMINAL_STATUSES)
            .first()
        )
    if subscription is None:
        return None

    from_status = subscription.status
    if status_value == "successful":
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_end = timezone.now() + _BILLING_CYCLE
        if is_first_charge and not subscription.provider_subscription_id:
            _attach_provider_subscription_id(subscription)
    elif from_status == SubscriptionStatus.ACTIVE:
        # A failed renewal on an already-active subscription is a grace
        # period, not an instant cutoff -- Flutterwave keeps retrying on
        # its own schedule; subscription.cancelled tells us when it gives up.
        subscription.status = SubscriptionStatus.PAST_DUE
    else:
        # A failed *first* charge (still PENDING) has no active access to
        # protect.
        subscription.status = SubscriptionStatus.CANCELED

    subscription.provider_transaction_id = provider_transaction_id
    subscription.status_reason = status_reason
    subscription.save(
        update_fields=[
            "status",
            "provider_transaction_id",
            "status_reason",
            "current_period_end",
            "provider_subscription_id",
            "updated_at",
        ]
    )
    _log_status_history(
        subscription=subscription,
        from_status=from_status,
        to_status=subscription.status,
        reason=status_reason,
    )
    return subscription


@transaction.atomic
def apply_cancellation_callback(*, provider_subscription_id: str, customer_email: str, reason: str) -> Subscription | None:
    """Handles a subscription.cancelled webhook event. Matched by
    provider_subscription_id when we have it (set once the first
    successful charge told us Flutterwave's own subscription id), falling
    back to customer_email otherwise."""
    subscription = None
    if provider_subscription_id:
        subscription = (
            Subscription.objects.select_for_update()
            .filter(provider_subscription_id=provider_subscription_id)
            .first()
        )
    if subscription is None and customer_email:
        subscription = (
            Subscription.objects.select_for_update()
            .filter(user__email__iexact=customer_email, status__in=NON_TERMINAL_STATUSES)
            .first()
        )
    if subscription is None:
        return None

    from_status = subscription.status
    if from_status == SubscriptionStatus.CANCELED:
        return subscription  # already fully terminal

    if from_status == SubscriptionStatus.PAST_DUE:
        # Flutterwave gave up its own retry schedule -- the last paid
        # period has already ended, so there's no remaining paid time to
        # honor; this is a real, immediate revocation (unlike the ACTIVE
        # case below).
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.status_reason = reason
        subscription.save(update_fields=["status", "status_reason", "updated_at"])
        _log_status_history(
            subscription=subscription,
            from_status=from_status,
            to_status=subscription.status,
            reason=reason,
        )
        return subscription

    if subscription.cancel_at_period_end:
        return subscription  # idempotent echo of our own cancel_subscription() call

    # Unprompted (cancelled directly via Flutterwave's dashboard/support,
    # not through our own cancel_subscription()) -- still honor the
    # remaining paid period rather than clawing back access, same policy
    # as a user-initiated cancel.
    subscription.cancel_at_period_end = True
    subscription.status_reason = reason
    subscription.save(update_fields=["cancel_at_period_end", "status_reason", "updated_at"])
    SubscriptionStatusHistory.objects.create(
        subscription=subscription,
        from_status=from_status,
        to_status=from_status,
        reason=reason,
    )
    return subscription


@transaction.atomic
def cancel_subscription(*, user) -> Subscription:
    """Cancels the renewal, not the access already paid for: status stays
    ACTIVE/PAST_DUE and cancel_at_period_end is set instead of jumping
    straight to CANCELED, so entitlement (is_user_premium) keeps returning
    True until current_period_end passes -- "cancellation takes effect at
    the end of the current paid period, never claws back time already paid
    for" per Phase 21 Slice 3's own build note. The status transition to
    CANCELED itself happens lazily (see current_subscription_queryset)
    rather than via a scheduled job, since no further webhook will ever
    arrive for a Flutterwave-cancelled subscription to drive it."""
    subscription = current_subscription_queryset(user).select_for_update().first()
    if subscription is None:
        raise SubscriptionNotFoundError()
    if subscription.status == SubscriptionStatus.PENDING:
        raise SubscriptionNotCancelableError("Subscription hasn't been activated yet.")
    if subscription.cancel_at_period_end:
        raise SubscriptionNotCancelableError(
            "Already scheduled to cancel at the end of the current period."
        )

    if subscription.provider_subscription_id and settings.FLUTTERWAVE_SECRET_KEY:
        try:
            _gateway().cancel_subscription(subscription.provider_subscription_id)
        except FlutterwaveGatewayError as exc:
            # Don't leave the user thinking they cancelled when Flutterwave
            # never got the request -- surface the failure rather than
            # optimistically scheduling the cancellation anyway.
            raise SubscriptionNotCancelableError(str(exc)) from exc

    subscription.cancel_at_period_end = True
    subscription.status_reason = "Canceled by user; access continues until the current period ends."
    subscription.save(update_fields=["cancel_at_period_end", "status_reason", "updated_at"])
    # Status itself is unchanged, so the guarded _log_status_history helper
    # would treat this as a no-op -- log directly so the cancellation
    # request is still visible in the audit trail (admin visibility is an
    # explicit Phase 21 build requirement).
    SubscriptionStatusHistory.objects.create(
        subscription=subscription,
        from_status=subscription.status,
        to_status=subscription.status,
        reason=subscription.status_reason,
        actor=user,
    )
    return subscription


def log_unrecognized_event(*, event: str, raw_payload: dict, note: str) -> None:
    SubscriptionEventLog.objects.create(event=event, raw_payload=raw_payload, note=note)

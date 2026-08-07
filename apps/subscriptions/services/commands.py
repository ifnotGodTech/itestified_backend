from __future__ import annotations

from calendar import monthrange
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError
from apps.subscriptions.exceptions import (
    SubscriptionAlreadyExistsError,
    SubscriptionGatewayNotConfiguredError,
    SubscriptionNotCancelableError,
    SubscriptionNotFoundError,
    SubscriptionUnsupportedCurrencyError,
)
from apps.subscriptions.models import (
    NON_TERMINAL_STATUSES,
    Subscription,
    SubscriptionEventLog,
    SubscriptionStatus,
    SubscriptionStatusHistory,
)
from apps.subscriptions.selectors import current_subscription_queryset


def _add_one_month(dt: datetime) -> datetime:
    """current_period_end is informational (drives the mobile "Renews on"
    display) rather than the actual billing trigger, which Flutterwave owns
    entirely on its own schedule -- Flutterwave's API exposes no next-billing-
    date field to read back (confirmed against their docs), and doesn't
    document whether "monthly" means +30 days or the same calendar date next
    month. Every payment processor we could confirm behavior for (Stripe,
    PayPal) bills recurring "monthly" plans on the same calendar date each
    month, so this matches that rather than a flat 30-day window, which would
    silently drift against the real charge date by 1-3 days depending on the
    month. Clamps to the last day of the target month when the source day
    doesn't exist there (e.g. Jan 31 -> Feb 28/29), rather than overflowing
    into the following month."""
    year = dt.year + (dt.month // 12)
    month = dt.month % 12 + 1
    last_day_of_target_month = monthrange(year, month)[1]
    day = min(dt.day, last_day_of_target_month)
    return dt.replace(year=year, month=month, day=day)


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


def subscribe(*, user, currency: str = "NGN") -> Subscription:
    """Deliberately NOT a single @transaction.atomic function: the Flutterwave
    call in the middle is a real external side effect, and if it fails we
    still need the CANCELED record (with its failure reason) to persist so
    the attempt is visible/auditable -- wrapping the whole function would
    roll that write back along with everything else the moment we re-raise.
    Each DB-writing step below gets its own short atomic block instead.

    Each supported currency has its own Flutterwave Payment Plan (a plan is
    tied to one currency at creation time on Flutterwave's side), so the
    caller picks which one to subscribe to -- mirrors Giving's existing
    NGN/USD choice (Phase 5) rather than a single hardcoded currency."""
    currency = currency.upper()
    if currency not in settings.PREMIUM_PLAN_PRICING_MINOR_UNITS:
        raise SubscriptionUnsupportedCurrencyError(currency)
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise SubscriptionGatewayNotConfiguredError()
    plan_id = settings.FLUTTERWAVE_PREMIUM_PLAN_IDS.get(currency, "")
    if not plan_id:
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
            amount=settings.PREMIUM_PLAN_PRICING_MINOR_UNITS[currency],
            currency=currency,
            payment_reference=Subscription.generate_reference(),
            provider_plan_id=plan_id,
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
            payment_plan=plan_id,
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
def verify_subscription(*, user, payment_reference: str, transaction_id: str) -> Subscription:
    """Synchronous fallback for the FIRST charge only, mirroring donations'
    verify_donation() exactly. Webhooks stay authoritative for renewals and
    cancellations (there's no "return to app" moment for those to hook
    into), but a webhook-only first charge is fragile: Flutterwave's own
    docs describe webhooks as being for payment methods "not processed in
    real-time" (e.g. bank transfers) -- for a real-time card charge, the
    reliable confirmation path is the client calling this right after the
    checkout redirect, same as donations already does. Real gap found and
    fixed 2026-08-06: a subscription could sit stuck in `pending` -- looking
    identical to a user who never subscribed -- if the webhook was ever
    slow, dropped, or failed to match."""
    subscription = (
        Subscription.objects.select_for_update()
        .filter(payment_reference=payment_reference, user=user)
        .first()
    )
    if subscription is None:
        raise SubscriptionNotFoundError()
    if subscription.status == SubscriptionStatus.ACTIVE:
        return subscription  # webhook already won the race; nothing to do
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise SubscriptionGatewayNotConfiguredError()

    verify_result = _gateway().verify(transaction_id)
    from_status = subscription.status
    if verify_result.status == "successful":
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_end = _add_one_month(timezone.now())
        if not subscription.provider_subscription_id:
            _attach_provider_subscription_id(subscription)
    else:
        # No active access existed yet for this attempt (still PENDING), so
        # there's nothing to protect with a grace period -- same reasoning
        # as a failed first charge in apply_charge_callback below.
        subscription.status = SubscriptionStatus.CANCELED

    subscription.provider_transaction_id = verify_result.provider_transaction_id
    subscription.status_reason = verify_result.status_reason
    subscription.save(
        update_fields=[
            "status",
            "current_period_end",
            "provider_subscription_id",
            "provider_transaction_id",
            "status_reason",
            "updated_at",
        ]
    )
    _log_status_history(
        subscription=subscription,
        from_status=from_status,
        to_status=subscription.status,
        reason=subscription.status_reason,
        actor=user,
    )
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
        subscription.current_period_end = _add_one_month(timezone.now())
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


@transaction.atomic
def admin_cancel_subscription(*, subscription_id: int, actor, reason: str) -> Subscription:
    """Phase 21 Slice 4's "manual override action for support cases" --
    mirrors reverse_donation()'s shape (admin, id-based lookup, required
    reason, actor recorded), but the correct subscription analog to a
    donation reversal is a cancellation, not a refund-style status flip.
    Same non-destructive policy as the user-initiated cancel_subscription()
    for an already-active subscription (schedule the cancellation, never
    claw back time already paid for) -- except a still-PENDING subscription
    (e.g. exactly the stuck-payment support scenario this phase's own
    Status notes describe) has no active access to protect, so that case
    cancels immediately and terminally instead of being scheduled."""
    subscription = Subscription.objects.select_for_update().filter(pk=subscription_id).first()
    if subscription is None:
        raise SubscriptionNotFoundError()
    if subscription.status not in NON_TERMINAL_STATUSES:
        raise SubscriptionNotCancelableError(
            "Only a pending, active, or past-due subscription can be canceled."
        )
    if subscription.cancel_at_period_end:
        raise SubscriptionNotCancelableError(
            "Already scheduled to cancel at the end of the current period."
        )

    if subscription.provider_subscription_id and settings.FLUTTERWAVE_SECRET_KEY:
        try:
            _gateway().cancel_subscription(subscription.provider_subscription_id)
        except FlutterwaveGatewayError as exc:
            raise SubscriptionNotCancelableError(str(exc)) from exc

    from_status = subscription.status
    if from_status == SubscriptionStatus.PENDING:
        subscription.status = SubscriptionStatus.CANCELED
        subscription.status_reason = reason
        subscription.save(update_fields=["status", "status_reason", "updated_at"])
        _log_status_history(
            subscription=subscription,
            from_status=from_status,
            to_status=subscription.status,
            reason=reason,
            actor=actor,
        )
        return subscription

    subscription.cancel_at_period_end = True
    subscription.status_reason = reason
    subscription.save(update_fields=["cancel_at_period_end", "status_reason", "updated_at"])
    SubscriptionStatusHistory.objects.create(
        subscription=subscription,
        from_status=from_status,
        to_status=from_status,
        reason=reason,
        actor=actor,
    )
    return subscription


def log_unrecognized_event(*, event: str, raw_payload: dict, note: str) -> None:
    SubscriptionEventLog.objects.create(event=event, raw_payload=raw_payload, note=note)

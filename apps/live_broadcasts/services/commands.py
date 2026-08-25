from __future__ import annotations

import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError
from apps.live_broadcasts import selectors
from apps.live_broadcasts.exceptions import (
    InsufficientAllowanceError,
    LiveBroadcastApprovalAlreadyDecidedError,
    LiveBroadcastingDisabledError,
    LiveBroadcastWrongStatusError,
    LiveMinutePurchaseNotFoundError,
    NotAVerifiedMinistryError,
)
from apps.live_broadcasts.models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveBroadcastApprovalStatus,
    LiveBroadcastStatus,
    LiveMinutePurchase,
    LiveMinutePurchaseStatus,
)
from apps.live_broadcasts.services import agora
from apps.live_broadcasts.services.notifications import (
    notify_admins_of_approval_request,
    notify_creator_of_approval_decision,
)


def create_live_broadcast(*, creator, title: str, scheduled_at=None) -> LiveBroadcast:
    """Phase 27 Slice 1's backend counterpart -- creates the record only.
    No Agora resources are allocated until go_live() below succeeds, per
    the phase's own Background note."""
    selectors.require_verified_ministry(creator)
    return LiveBroadcast.objects.create(
        creator=creator,
        title=title.strip(),
        scheduled_at=scheduled_at,
    )


@transaction.atomic
def go_live(*, broadcast: LiveBroadcast, actor) -> agora.PublisherCredential:
    """Phase 27 Slice 4 -- the actual credential-issuance moment. Checks
    the attempt against the admin-configurable policy and the Ministry's
    own remaining monthly allowance before ever calling Agora."""
    if broadcast.creator_id != actor.id:
        raise NotAVerifiedMinistryError("Only the broadcast's own Ministry can go live on it.")
    selectors.require_verified_ministry(actor)
    if broadcast.status != LiveBroadcastStatus.SCHEDULED:
        raise LiveBroadcastWrongStatusError(f"Cannot go live on a broadcast in status '{broadcast.status}'.")

    policy = selectors.get_live_streaming_policy()
    if not policy.is_enabled:
        raise LiveBroadcastingDisabledError("Live broadcasting is temporarily unavailable.")

    now = timezone.now()
    worst_case_minutes = policy.max_concurrent_viewers * policy.max_duration_minutes

    allowance = selectors.get_or_create_current_month_allowance(creator=actor)
    already_reserved = selectors.reserved_minutes_this_month(creator=actor, year=now.year, month=now.month)
    remaining = allowance.total_allowance_minutes - already_reserved

    if remaining < worst_case_minutes:
        raise InsufficientAllowanceError(
            shortfall_minutes=worst_case_minutes - remaining,
            remaining_minutes=max(remaining, 0),
        )

    channel_name = f"itestified-live-{broadcast.id}-{secrets.token_hex(4)}"
    credential = agora.issue_publisher_credential(
        channel_name=channel_name,
        uid=broadcast.creator_id,
        expire_seconds=(policy.max_duration_minutes * 60) + 300,
    )

    broadcast.status = LiveBroadcastStatus.LIVE
    broadcast.started_at = now
    broadcast.agora_channel_name = channel_name
    broadcast.agora_publisher_uid = credential.uid
    broadcast.max_viewers_applied = policy.max_concurrent_viewers
    broadcast.max_duration_minutes_applied = policy.max_duration_minutes
    broadcast.save(
        update_fields=[
            "status",
            "started_at",
            "agora_channel_name",
            "agora_publisher_uid",
            "max_viewers_applied",
            "max_duration_minutes_applied",
            "updated_at",
        ]
    )
    return credential


def _gateway() -> FlutterwaveGateway:
    return FlutterwaveGateway(
        secret_key=settings.FLUTTERWAVE_SECRET_KEY,
        base_url=settings.FLUTTERWAVE_BASE_URL,
    )


@transaction.atomic
def initiate_minute_purchase(*, creator, minutes: int, currency: str) -> LiveMinutePurchase:
    """Primary overage path (2026-08-25 pay-to-exceed decision) -- same
    one-off Flutterwave checkout shape as `create_donation`
    (apps.donations)."""
    selectors.require_verified_ministry(creator)
    pricing = selectors.get_live_minute_pricing(currency=currency)
    # Ceil division: a Ministry buying 1 minute over a 1,000-minute pricing
    # unit still pays for the full unit, never a fractional charge.
    amount = -(-minutes * pricing.price_per_1000_minutes // 1000)

    purchase = LiveMinutePurchase.objects.create(
        creator=creator,
        minutes=minutes,
        amount=amount,
        currency=currency,
        payment_reference=LiveMinutePurchase.generate_reference(),
    )
    redirect_url = settings.FLUTTERWAVE_REDIRECT_URL or "https://www.itestified.app/live/minutes/return"
    try:
        init_result = _gateway().initialize(
            amount=purchase.amount,
            currency=purchase.currency,
            tx_ref=purchase.payment_reference,
            customer_email=creator.email,
            customer_name=getattr(creator, "full_name", "") or creator.email,
            redirect_url=redirect_url,
        )
    except FlutterwaveGatewayError as exc:
        purchase.status = LiveMinutePurchaseStatus.DECLINED
        purchase.status_reason = str(exc)
        purchase.save(update_fields=["status", "status_reason", "updated_at"])
        raise

    purchase.checkout_url = init_result.checkout_url
    purchase.provider_transaction_id = init_result.provider_transaction_id
    purchase.save(update_fields=["checkout_url", "provider_transaction_id", "updated_at"])
    return purchase


@transaction.atomic
def verify_minute_purchase(*, creator, payment_reference: str, transaction_id: str) -> LiveMinutePurchase:
    purchase = (
        LiveMinutePurchase.objects.select_for_update()
        .filter(payment_reference=payment_reference, creator=creator)
        .first()
    )
    if purchase is None:
        raise LiveMinutePurchaseNotFoundError()

    was_successful = purchase.status == LiveMinutePurchaseStatus.SUCCESSFUL
    verify_result = _gateway().verify(transaction_id)
    # FlutterwaveVerifyResult.status is exactly "successful"/"declined",
    # matching LiveMinutePurchaseStatus's own values.
    purchase.status = verify_result.status
    purchase.provider_transaction_id = verify_result.provider_transaction_id
    purchase.status_reason = verify_result.status_reason
    purchase.save(update_fields=["status", "provider_transaction_id", "status_reason", "updated_at"])

    if not was_successful and purchase.status == LiveMinutePurchaseStatus.SUCCESSFUL:
        allowance = selectors.get_or_create_current_month_allowance(creator=creator)
        allowance.purchased_minutes += purchase.minutes
        allowance.save(update_fields=["purchased_minutes", "updated_at"])
    return purchase


@transaction.atomic
def request_broadcast_approval(*, broadcast: LiveBroadcast, requested_minutes: int) -> LiveBroadcastApprovalRequest:
    """Fallback only (2026-08-25 product decision) -- called when the
    self-service purchase above was declined or unavailable."""
    approval_request = LiveBroadcastApprovalRequest.objects.create(
        broadcast=broadcast,
        creator=broadcast.creator,
        requested_minutes=requested_minutes,
    )
    transaction.on_commit(lambda: notify_admins_of_approval_request(approval_request))
    return approval_request


@transaction.atomic
def decide_broadcast_approval(
    *, approval_request: LiveBroadcastApprovalRequest, approve: bool, actor, note: str = ""
) -> LiveBroadcastApprovalRequest:
    if approval_request.status != LiveBroadcastApprovalStatus.PENDING:
        raise LiveBroadcastApprovalAlreadyDecidedError()

    approval_request.status = (
        LiveBroadcastApprovalStatus.APPROVED if approve else LiveBroadcastApprovalStatus.REJECTED
    )
    approval_request.reviewed_by = actor
    approval_request.reviewed_at = timezone.now()
    approval_request.review_note = note
    approval_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

    if approve:
        now = timezone.now()
        # Reuses the same purchased_minutes ledger a self-service purchase
        # writes to -- both are "extra minutes added beyond the base
        # allowance", just a different route to getting there.
        allowance = selectors.get_or_create_month_allowance(
            creator=approval_request.creator, year=now.year, month=now.month
        )
        allowance.purchased_minutes += approval_request.requested_minutes
        allowance.save(update_fields=["purchased_minutes", "updated_at"])

    transaction.on_commit(lambda: notify_creator_of_approval_decision(approval_request))
    return approval_request

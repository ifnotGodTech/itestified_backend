from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.services.flutterwave import FlutterwaveGateway, FlutterwaveGatewayError
from apps.live_broadcasts import selectors
from apps.live_broadcasts.exceptions import (
    AgoraNotConfiguredError,
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
    LiveBroadcastEndedReason,
    LiveBroadcastRecordingStatus,
    LiveBroadcastStatus,
    LiveMinutePurchase,
    LiveMinutePurchaseStatus,
)
from apps.live_broadcasts.services import agora
from apps.live_broadcasts.services.notifications import (
    notify_admins_of_approval_request,
    notify_creator_broadcast_recording_ready,
    notify_creator_of_approval_decision,
    notify_followers_of_live_broadcast,
)

logger = logging.getLogger(__name__)

# Offset keeps the Cloud Recording bot's own Agora uid from ever colliding
# with a real publisher uid (which is just the creator's User pk) while
# staying inside Agora's 32-bit unsigned uid range.
RECORDING_UID_OFFSET = 2_000_000_000

# Phase 27 Slice 2 -- each viewer join mints a random uid in its own
# range, disjoint from both real publisher uids (small User pks) and the
# recording bot's range above, so a collision is impossible by
# construction rather than merely unlikely.
VIEWER_UID_RANGE_START = 1_000_000_000
VIEWER_UID_RANGE_SIZE = 500_000_000


def create_live_broadcast(*, creator, title: str, category, scheduled_at=None) -> LiveBroadcast:
    """Phase 27 Slice 1's backend counterpart -- creates the record only.
    No Agora resources are allocated until go_live() below succeeds, per
    the phase's own Background note. `category` is required up front
    (Slice 5): the recording this broadcast eventually produces becomes a
    real Testimony, and Testimony.category is non-nullable."""
    selectors.require_verified_ministry(creator)
    return LiveBroadcast.objects.create(
        creator=creator,
        title=title.strip(),
        category=category,
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

    # Best-effort: a Cloud Recording hiccup should never block the
    # Ministry from actually broadcasting (see Phase 27 Slice 5's own
    # note) -- it just means there's nothing to archive once they end.
    recording_uid = RECORDING_UID_OFFSET + broadcast.id
    try:
        recording_credential = agora.issue_recording_token(
            channel_name=channel_name, uid=recording_uid, expire_seconds=(policy.max_duration_minutes * 60) + 300
        )
        resource_id = agora.acquire_cloud_recording(channel_name=channel_name, recording_uid=recording_uid)
        sid = agora.start_cloud_recording(
            channel_name=channel_name,
            recording_uid=recording_uid,
            resource_id=resource_id,
            recording_token=recording_credential.token,
        )
        broadcast.recording_status = LiveBroadcastRecordingStatus.RECORDING
        broadcast.agora_recording_resource_id = resource_id
        broadcast.agora_recording_sid = sid
        broadcast.agora_recording_uid = recording_uid
    except AgoraNotConfiguredError:
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
    except Exception:  # noqa: BLE001 - a recording-infra failure must never fail go-live itself.
        logger.exception("live_broadcasts.go_live: cloud recording start failed for broadcast %s", broadcast.id)
        broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED

    broadcast.save(
        update_fields=[
            "status",
            "started_at",
            "agora_channel_name",
            "agora_publisher_uid",
            "max_viewers_applied",
            "max_duration_minutes_applied",
            "recording_status",
            "agora_recording_resource_id",
            "agora_recording_sid",
            "agora_recording_uid",
            "updated_at",
        ]
    )
    transaction.on_commit(lambda: notify_followers_of_live_broadcast(broadcast))
    return credential


def join_broadcast_as_viewer(*, broadcast: LiveBroadcast) -> agora.PublisherCredential:
    """Phase 27 Slice 2 -- issues a per-viewer subscribe-only token,
    minted fresh on every join (never persisted or reused across
    viewers). No eligibility check beyond the broadcast actually being
    LIVE -- watching is open to anyone, guests included, per this
    slice's own product decision."""
    if broadcast.status != LiveBroadcastStatus.LIVE:
        raise LiveBroadcastWrongStatusError(f"This broadcast is not currently live (status '{broadcast.status}').")

    viewer_uid = VIEWER_UID_RANGE_START + secrets.randbelow(VIEWER_UID_RANGE_SIZE)
    # Generous fixed window rather than tying it to the broadcast's own
    # remaining duration -- a viewer joining near the end of a long
    # broadcast should still get a usable token, not one that expires in
    # a handful of seconds.
    return agora.issue_viewer_credential(
        channel_name=broadcast.agora_channel_name,
        uid=viewer_uid,
        expire_seconds=4 * 60 * 60,
    )


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


@transaction.atomic
def end_broadcast(*, broadcast: LiveBroadcast, reason: str, actor=None) -> LiveBroadcast:
    """Phase 27 Slice 5 -- the shared ending path regardless of *why* a
    broadcast ends (creator taps "End", a stream drops and
    reconcile_stale_live_broadcasts catches it, or -- once Slice 8 exists
    -- an admin kill). Only ever stops Cloud Recording and kicks off
    archival; it never publishes anything itself (Slice 3 owns that
    decision)."""
    if broadcast.status != LiveBroadcastStatus.LIVE:
        raise LiveBroadcastWrongStatusError(f"Cannot end a broadcast in status '{broadcast.status}'.")

    broadcast.status = LiveBroadcastStatus.ENDED
    broadcast.ended_at = timezone.now()
    broadcast.ended_reason = reason

    if broadcast.recording_status == LiveBroadcastRecordingStatus.RECORDING:
        try:
            agora.stop_cloud_recording(
                channel_name=broadcast.agora_channel_name,
                recording_uid=broadcast.agora_recording_uid,
                resource_id=broadcast.agora_recording_resource_id,
                sid=broadcast.agora_recording_sid,
            )
            broadcast.recording_status = LiveBroadcastRecordingStatus.STOPPING
        except Exception:  # noqa: BLE001 - ending the broadcast must succeed even if the stop call fails.
            logger.exception("live_broadcasts.end_broadcast: stop_cloud_recording failed for broadcast %s", broadcast.id)
            broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED

    broadcast.save(update_fields=["status", "ended_at", "ended_reason", "recording_status", "updated_at"])

    if broadcast.recording_status == LiveBroadcastRecordingStatus.STOPPING:
        from apps.live_broadcasts.tasks import poll_and_archive_recording

        transaction.on_commit(lambda: poll_and_archive_recording.delay(broadcast.id))

    return broadcast


def archive_broadcast_recording(*, broadcast: LiveBroadcast, video_url: str):
    """Phase 27 Slice 5 -- called once poll_and_archive_recording
    (tasks.py) confirms Agora's file is written to storage. Creates the
    DRAFT testimony Slice 3's submit-or-hold decision operates on;
    archiving never publishes anything by itself."""
    from apps.testimonies.models import Testimony, TestimonyStatus, TestimonyType

    with transaction.atomic():
        testimony = Testimony.objects.create(
            author=broadcast.creator,
            category=broadcast.category,
            title=broadcast.title,
            testimony_type=TestimonyType.VIDEO,
            status=TestimonyStatus.DRAFT,
            video_url=video_url,
        )
        broadcast.archived_testimony = testimony
        broadcast.recording_status = LiveBroadcastRecordingStatus.ARCHIVED
        broadcast.save(update_fields=["archived_testimony", "recording_status", "updated_at"])
        transaction.on_commit(lambda: notify_creator_broadcast_recording_ready(broadcast))
    return testimony


def mark_recording_failed(*, broadcast: LiveBroadcast) -> None:
    broadcast.recording_status = LiveBroadcastRecordingStatus.FAILED
    broadcast.save(update_fields=["recording_status", "updated_at"])


# A broadcast's own publish token already expires at
# max_duration_minutes_applied + 300s (go_live's own buffer) -- past that,
# Agora itself has already cut the creator's connection, so anything still
# marked LIVE this far out definitely dropped rather than merely running
# long. The extra 300s here just covers this command's own run cadence
# (see render.yaml's cron schedule) so a broadcast isn't flagged the
# instant its token buffer lapses.
STALE_BROADCAST_GRACE_SECONDS = 300


def reconcile_stale_live_broadcasts() -> int:
    """Phase 27's own Test requirement ("a dropped stream mid-broadcast is
    handled gracefully") -- there's no proactive drop detection via
    Agora's Channel Management API here (its exact channel-presence
    semantics weren't verified while building this); instead, any
    broadcast still LIVE well past when its own publish token must have
    expired is unambiguously stale, purely from data this app already
    has. Run periodically via `manage.py reconcile_stale_live_broadcasts`
    (see render.yaml's cron service), matching this codebase's existing
    cron-command pattern (`publish_scheduled_testimonies` etc.) rather
    than introducing a new Celery beat scheduler."""
    now = timezone.now()
    ended_count = 0
    stale_broadcasts = LiveBroadcast.objects.filter(
        status=LiveBroadcastStatus.LIVE,
        started_at__isnull=False,
        max_duration_minutes_applied__isnull=False,
    )
    for broadcast in stale_broadcasts:
        deadline = broadcast.started_at + timezone.timedelta(
            minutes=broadcast.max_duration_minutes_applied,
            seconds=300 + STALE_BROADCAST_GRACE_SECONDS,
        )
        if now >= deadline:
            end_broadcast(broadcast=broadcast, reason=LiveBroadcastEndedReason.DROPPED)
            ended_count += 1
    return ended_count

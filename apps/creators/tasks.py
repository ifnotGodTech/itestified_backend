from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.creators.models import CreatorFollow, CreatorProfile
from apps.notifications.services import notify_creator_digest
from apps.testimonies.models import Testimony, TestimonyStatus

logger = logging.getLogger(__name__)


@shared_task
def send_creator_follower_digests() -> int:
    """Phase 23 Slice 2 -- intended to run daily via Celery beat (not yet
    wired into a beat schedule/deployed as its own service -- that's a
    deploy-configuration decision, same class of decision as Phase 22's
    Render Blueprint sync, kept separate from this task's own logic).

    For every creator with at least one testimony approved in the prior
    24h, sends exactly ONE digest notification per follower, never one
    per testimony -- so following a prolific creator doesn't spam a
    follower (Phase 23's own test requirement). No new tracking field
    needed: the task's own fixed daily schedule defines the 24h window,
    so a creator with nothing new in that window is silently skipped.

    Returns the number of individual digest notifications sent, for
    observability in Celery logs."""
    since = timezone.now() - timedelta(hours=24)
    # .order_by() clears Testimony's default `ordering = ["-created_at"]" --
    # left in place, Django silently folds created_at into the DISTINCT,
    # so this would return one row per testimony instead of per author.
    creator_ids_with_new_content = (
        Testimony.objects.filter(status=TestimonyStatus.APPROVED, publish_at__gte=since)
        .order_by()
        .values_list("author_id", flat=True)
        .distinct()
    )

    notifications_sent = 0
    for creator_id in creator_ids_with_new_content:
        creator_profile = CreatorProfile.objects.filter(user_id=creator_id).first()
        if creator_profile is None:
            continue  # an ordinary user's approved testimony, not a Ministry account

        follower_ids = list(CreatorFollow.objects.filter(creator_id=creator_id).values_list("follower_id", flat=True))
        if not follower_ids:
            continue

        new_testimony_count = Testimony.objects.filter(
            author_id=creator_id, status=TestimonyStatus.APPROVED, publish_at__gte=since
        ).count()
        notify_creator_digest(
            follower_ids=follower_ids,
            creator_display_name=creator_profile.display_name,
            new_testimony_count=new_testimony_count,
        )
        notifications_sent += len(follower_ids)

    logger.info("creators.digest.sent notifications_sent=%s", notifications_sent)
    return notifications_sent

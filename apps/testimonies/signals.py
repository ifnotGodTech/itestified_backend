"""Counter bookkeeping only (backend/AGENTS.md allows signals for that).

The app's own account deletion is a soft delete and keeps a user's
reactions and comments, so the counters stay right. A user deleted outright
-- from Django admin or a shell -- cascades those rows away without going
through the commands that keep Testimony's counters, so the testimonies
they touched are recounted once the delete is done."""

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.testimonies.models import TestimonyComment, TestimonyReaction
from apps.testimonies.services.commands import recount_testimony_counters


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="testimonies.note_counted_rows")
def note_testimonies_with_counted_rows(sender, instance, **kwargs) -> None:
    # Replies others wrote under this user's comments cascade away too.
    comments = TestimonyComment.objects.filter(Q(author=instance) | Q(parent_comment__author=instance))
    reactions = TestimonyReaction.objects.filter(user=instance)
    instance._testimonies_to_recount = set(comments.values_list("testimony_id", flat=True)) | set(
        reactions.values_list("testimony_id", flat=True)
    )


@receiver(post_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid="testimonies.recount_after_user_delete")
def recount_after_user_delete(sender, instance, **kwargs) -> None:
    testimony_ids = getattr(instance, "_testimonies_to_recount", None)
    if testimony_ids:
        transaction.on_commit(lambda: recount_testimony_counters(testimony_ids=testimony_ids))

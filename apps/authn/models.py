from django.db import models
from django.utils import timezone
from django.conf import settings

from .choices import AccountDeletionReason, ChallengePurpose


class EmailChallenge(models.Model):
    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=30, choices=ChallengePurpose.choices)
    full_name = models.CharField(max_length=255, blank=True)
    code = models.CharField(max_length=12)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "purpose", "-created_at"], name="authn_email_purpose_idx"),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


class UserSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tracked_sessions",
    )
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-updated_at"], name="authn_user_session_user_idx"),
        ]

    def __str__(self) -> str:
        return f"UserSession<{self.user_id}:{self.session_key}>"


class AccountDeletionFeedback(models.Model):
    """Captured at the moment of self-service account deletion, before the
    user row is anonymized -- the account itself is soft-deleted (email/name
    scrubbed, status set to DELETED) rather than hard-deleted, since
    testimonies/comments/donations are shared content and financial records
    other users and the business depend on, so `user` intentionally stays
    set (SET_NULL only if the row is later purged by some future process,
    not by this flow)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reason = models.CharField(max_length=30, choices=AccountDeletionReason.choices)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"AccountDeletionFeedback<{self.user_id}:{self.reason}>"

from django.db import models
from django.utils import timezone
from django.conf import settings

from .choices import ChallengePurpose


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

from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    TESTIMONY_SUBMITTED = "testimony_submitted", "Testimony Submitted"
    TESTIMONY_APPROVED = "testimony_approved", "Testimony Approved"
    TESTIMONY_REJECTED = "testimony_rejected", "Testimony Rejected"
    TESTIMONY_COMMENT = "testimony_comment", "Testimony Comment"
    NEW_VIDEO_TESTIMONY = "new_video_testimony", "New Video Testimony"


class UserNotification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"UserNotification<{self.recipient_id}:{self.notification_type}>"


class UserNotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    allow_email_notifications = models.BooleanField(default=True)
    notify_new_donation_received = models.BooleanField(default=True)
    send_donation_thank_you_email = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"UserNotificationPreference<{self.user_id}>"

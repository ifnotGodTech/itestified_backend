from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    TESTIMONY_SUBMITTED = "testimony_submitted", "Testimony Submitted"
    TESTIMONY_APPROVED = "testimony_approved", "Testimony Approved"
    TESTIMONY_REJECTED = "testimony_rejected", "Testimony Rejected"
    TESTIMONY_COMMENT = "testimony_comment", "Testimony Comment"
    NEW_VIDEO_TESTIMONY = "new_video_testimony", "New Video Testimony"
    DONATION_RECEIVED = "donation_received", "Donation Received"
    APP_UPDATE_AVAILABLE = "app_update_available", "App Update Available"
    SCRIPTURE_PUBLISHED = "scripture_published", "Scripture Published"
    CREATOR_DIGEST = "creator_digest", "Creator Digest"
    PRAYER_RESPONSE = "prayer_response", "Prayer Response"
    LIVE_BROADCAST_APPROVAL_REQUESTED = "live_broadcast_approval_requested", "Live Broadcast Approval Requested"
    LIVE_BROADCAST_APPROVAL_DECIDED = "live_broadcast_approval_decided", "Live Broadcast Approval Decided"
    LIVE_BROADCAST_RECORDING_READY = "live_broadcast_recording_ready", "Live Broadcast Recording Ready"


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
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"], name="notif_recipient_read_idx"),
            models.Index(fields=["notification_type", "is_read", "-created_at"], name="notif_type_read_idx"),
        ]

    def __str__(self) -> str:
        return f"UserNotification<{self.recipient_id}:{self.notification_type}>"


class DevicePlatform(models.TextChoices):
    IOS = "ios", "iOS"
    ANDROID = "android", "Android"
    WEB = "web", "Web"


class DeviceToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    # Unique by the token string itself, not by (user, platform): if this
    # physical device is later used to log into a different account, the OS
    # hands the app the same FCM token, and re-registering it here must
    # reassign ownership -- otherwise the previous account would keep
    # receiving push notifications meant for whoever uses the device next.
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=10, choices=DevicePlatform.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"DeviceToken<{self.user_id}:{self.platform}>"


class UserNotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    allow_email_notifications = models.BooleanField(default=True)
    allow_push_notifications = models.BooleanField(default=True)
    notify_new_donation_received = models.BooleanField(default=True)
    send_donation_thank_you_email = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"UserNotificationPreference<{self.user_id}>"

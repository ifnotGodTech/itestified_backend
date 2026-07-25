from django.contrib import admin

from .models import DeviceToken, UserNotification, UserNotificationPreference


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("recipient__email", "actor__email", "title", "message")


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "platform", "created_at", "last_seen_at")
    list_filter = ("platform",)
    search_fields = ("user__email", "token")


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "allow_email_notifications",
        "notify_new_donation_received",
        "send_donation_thank_you_email",
        "updated_at",
    )
    search_fields = ("user__email",)

from django.contrib import admin

from .models import UserNotification, UserNotificationPreference


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("recipient__email", "actor__email", "title", "message")


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

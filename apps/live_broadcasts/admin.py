from django.contrib import admin

from .models import (
    LiveBroadcast,
    LiveBroadcastApprovalRequest,
    LiveMinutePricing,
    LiveMinutePurchase,
    LiveStreamingPolicy,
    MinistryStreamingAllowance,
)


@admin.register(LiveBroadcast)
class LiveBroadcastAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "creator",
        "title",
        "status",
        "ended_reason",
        "recording_status",
        "started_at",
        "ended_at",
        "archived_testimony",
    )
    list_filter = ("status", "ended_reason", "recording_status")
    search_fields = ("title", "creator__email", "agora_channel_name")


@admin.register(LiveStreamingPolicy)
class LiveStreamingPolicyAdmin(admin.ModelAdmin):
    list_display = ("is_enabled", "max_concurrent_viewers", "max_duration_minutes", "shared_monthly_ceiling_minutes", "updated_at")


@admin.register(LiveMinutePricing)
class LiveMinutePricingAdmin(admin.ModelAdmin):
    list_display = ("currency", "price_per_1000_minutes", "updated_by", "updated_at")


@admin.register(MinistryStreamingAllowance)
class MinistryStreamingAllowanceAdmin(admin.ModelAdmin):
    list_display = ("creator", "year", "month", "base_allowance_minutes", "purchased_minutes")
    search_fields = ("creator__email",)


@admin.register(LiveMinutePurchase)
class LiveMinutePurchaseAdmin(admin.ModelAdmin):
    list_display = ("creator", "minutes", "amount", "currency", "status", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("creator__email", "payment_reference")


@admin.register(LiveBroadcastApprovalRequest)
class LiveBroadcastApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("broadcast", "creator", "requested_minutes", "status", "reviewed_by", "created_at")
    list_filter = ("status",)

from django.contrib import admin

from .models import Subscription, SubscriptionEventLog, SubscriptionStatusHistory


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "amount", "currency", "current_period_end", "created_at")
    list_filter = ("status", "currency")
    search_fields = ("user__email", "payment_reference", "provider_subscription_id")


@admin.register(SubscriptionStatusHistory)
class SubscriptionStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("subscription", "from_status", "to_status", "actor", "created_at")


@admin.register(SubscriptionEventLog)
class SubscriptionEventLogAdmin(admin.ModelAdmin):
    list_display = ("event", "note", "created_at")

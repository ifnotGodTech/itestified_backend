from django.contrib import admin

from .models import (
    ReferralAttribution,
    ReferralCode,
    ReferralCommission,
    ReferralCommissionRate,
    ReferralCommissionRateHistory,
    ReferralTermsAcceptance,
)


@admin.register(ReferralCommissionRate)
class ReferralCommissionRateAdmin(admin.ModelAdmin):
    list_display = ("id", "percent", "updated_by", "updated_at")


@admin.register(ReferralCommissionRateHistory)
class ReferralCommissionRateHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "rate", "from_percent", "to_percent", "actor", "created_at")
    list_filter = ("rate",)


@admin.register(ReferralAttribution)
class ReferralAttributionAdmin(admin.ModelAdmin):
    list_display = ("id", "referred_user", "referrer", "created_at")
    search_fields = ("referred_user__email", "referrer__email")


@admin.register(ReferralCommission)
class ReferralCommissionAdmin(admin.ModelAdmin):
    list_display = ("id", "referrer", "referred_user", "amount", "currency", "is_paid", "created_at")
    list_filter = ("is_paid", "currency")
    search_fields = ("referrer__email", "referred_user__email", "provider_transaction_id")


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "user", "created_at")
    search_fields = ("code", "user__email")


@admin.register(ReferralTermsAcceptance)
class ReferralTermsAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "accepted_at")
    search_fields = ("user__email",)

from django.contrib import admin

from .models import Donation, DonationStatusHistory


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("payment_reference", "user", "amount", "currency", "status", "provider", "created_at")
    list_filter = ("status", "currency", "provider")
    search_fields = ("payment_reference", "user__email", "provider_transaction_id")


@admin.register(DonationStatusHistory)
class DonationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("donation", "from_status", "to_status", "actor", "created_at")
    list_filter = ("from_status", "to_status")
    search_fields = ("donation__payment_reference", "actor__email", "reason")
